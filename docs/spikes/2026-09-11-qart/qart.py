"""PROTOTYPE JETABLE — portage Python de rsc.io/qr (qart, coding, gf256).
Spike du 2026-09-11 : faisabilite d'un QR « image » pour le ticket Sunmi.

Code derive : Copyright (c) 2009 The Go Authors, licence BSD 3 clauses,
reproduite dans LICENSE-rsc-qr. / Derived from rsc.io/qr, BSD licence.
"""

import random

import numpy as np
from PIL import Image

# ---------------------------------------------------------------- GF(256) / RS

EXP = [0] * 512
LOG = [0] * 256
_x = 1
for _i in range(255):
    EXP[_i] = _x
    LOG[_x] = _i
    _x <<= 1
    if _x & 0x100:
        _x ^= 0x11D
for _i in range(255, 512):
    EXP[_i] = EXP[_i - 255]


def gf_mul(a, b):
    if a == 0 or b == 0:
        return 0
    return EXP[LOG[a] + LOG[b]]


_gen_cache = {}


def rs_generator(nc):
    if nc not in _gen_cache:
        g = [1]
        for i in range(nc):
            # g *= (x + alpha^i), coefficients poids fort d'abord
            ng = g + [0]
            for j in range(len(g)):
                ng[j + 1] ^= gf_mul(g[j], EXP[i])
            g = ng
        _gen_cache[nc] = g
    return _gen_cache[nc]


def rs_ecc(data, nc):
    gen = rs_generator(nc)
    p = list(data) + [0] * nc
    for i in range(len(data)):
        c = p[i]
        if c:
            for j in range(1, nc + 1):
                p[i + j] ^= gf_mul(gen[j], c)
    return p[len(data):]


# ---------------------------------------------------------------- flux de bits


class Bits:
    def __init__(self):
        self.b = []

    def write(self, v, n):
        for i in range(n - 1, -1, -1):
            self.b.append((v >> i) & 1)

    def __len__(self):
        return len(self.b)

    def pad(self, n):
        if n <= 4:
            self.write(0, n)
            return
        self.write(0, 4)
        n -= 4
        k = -len(self) & 7
        n -= k
        self.write(0, k)
        pad = n // 8
        i = 0
        while i < pad:
            self.write(0xEC, 8)
            if i + 1 >= pad:
                break
            self.write(0x11, 8)
            i += 2

    def to_bytes(self):
        assert len(self.b) % 8 == 0
        return [int("".join(map(str, self.b[i:i + 8])), 2) for i in range(0, len(self.b), 8)]


def size_class(v):
    return 0 if v <= 9 else (1 if v <= 26 else 2)


def encode_string(bits, s, v):
    bits.write(4, 4)
    bits.write(len(s), [8, 16, 16][size_class(v)])
    for c in s.encode("latin-1"):
        bits.write(c, 8)


def encode_num(bits, s, v):
    bits.write(1, 4)
    bits.write(len(s), [10, 12, 14][size_class(v)])
    i = 0
    while i + 3 <= len(s):
        bits.write(int(s[i:i + 3]), 10)
        i += 3
    if len(s) - i == 1:
        bits.write(int(s[i]), 4)
    elif len(s) - i == 2:
        bits.write(int(s[i:i + 2]), 7)


# ---------------------------------------------------------------- plan du QR

# version: (apos, astride, bytes, pattern, [(nblock, check) pour L, M, Q, H])
VTAB = [
    None,
    (100, 100, 26, 0x0, [(1, 7), (1, 10), (1, 13), (1, 17)]),
    (16, 100, 44, 0x0, [(1, 10), (1, 16), (1, 22), (1, 28)]),
    (20, 100, 70, 0x0, [(1, 15), (1, 26), (2, 18), (2, 22)]),
    (24, 100, 100, 0x0, [(1, 20), (2, 18), (2, 26), (4, 16)]),
    (28, 100, 134, 0x0, [(1, 26), (2, 24), (4, 18), (4, 22)]),
    (32, 100, 172, 0x0, [(2, 18), (4, 16), (4, 24), (4, 28)]),
    (20, 16, 196, 0x7C94, [(2, 20), (4, 18), (6, 18), (5, 26)]),
    (22, 18, 242, 0x85BC, [(2, 24), (4, 22), (6, 22), (6, 26)]),
    (24, 20, 292, 0x9A99, [(2, 30), (5, 22), (8, 20), (8, 24)]),
    (26, 22, 346, 0xA4D3, [(4, 18), (5, 26), (8, 24), (8, 28)]),
    (28, 24, 404, 0xBBF6, [(4, 20), (5, 30), (8, 28), (11, 24)]),
    (30, 26, 466, 0xC762, [(4, 24), (8, 22), (10, 26), (11, 28)]),
    (32, 28, 532, 0xD847, [(4, 26), (9, 22), (12, 24), (16, 22)]),
    (24, 20, 581, 0xE60D, [(4, 30), (9, 24), (16, 20), (16, 24)]),
]

BLACK, INVERT = 1, 2
POSITION, ALIGNMENT, TIMING, FORMAT, PVERSION, UNUSED, DATA, CHECK, EXTRA = range(1, 10)


def role(p):
    return (p >> 2) & 15


def offset(p):
    return p >> 6


def mkpix(r, off=0):
    return (r << 2) | (off << 6)


MASKS = [
    lambda i, j: (i + j) % 2 == 0,
    lambda i, j: i % 2 == 0,
    lambda i, j: j % 3 == 0,
    lambda i, j: (i + j) % 3 == 0,
    lambda i, j: (i // 2 + j // 3) % 2 == 0,
    lambda i, j: i * j % 2 + i * j % 3 == 0,
    lambda i, j: (i * j % 2 + i * j % 3) % 2 == 0,
    lambda i, j: (i * j % 3 + (i + j) % 2) % 2 == 0,
]


class Plan:
    pass


def pos_box(m, x, y):
    pos = mkpix(POSITION)
    n = len(m)
    for dy in range(7):
        for dx in range(7):
            p = pos
            if dx in (0, 6) or dy in (0, 6) or (2 <= dx <= 4 and 2 <= dy <= 4):
                p |= BLACK
            m[y + dy][x + dx] = p
    for dy in range(-1, 8):
        if 0 <= y + dy < n:
            if x > 0:
                m[y + dy][x - 1] = pos
            if x + 7 < n:
                m[y + dy][x + 7] = pos
    for dx in range(-1, 8):
        if 0 <= x + dx < n:
            if y > 0:
                m[y - 1][x + dx] = pos
            if y + 7 < n:
                m[y + 7][x + dx] = pos


def align_box(m, x, y):
    a = mkpix(ALIGNMENT)
    for dy in range(5):
        for dx in range(5):
            p = a
            if dx in (0, 4) or dy in (0, 4) or (dx == 2 and dy == 2):
                p |= BLACK
            m[y + dy][x + dx] = p


def new_plan(version, level, mask):
    p = Plan()
    p.version, p.level, p.mask = version, level, mask
    siz = 17 + 4 * version
    m = [[0] * siz for _ in range(siz)]
    p.pixel = m
    apos, astride, nbytes, pattern, levels = VTAB[version]

    # timing
    for i in range(siz):
        t = mkpix(TIMING) | (BLACK if i & 1 == 0 else 0)
        m[i][6] = t
        m[6][i] = t
    pos_box(m, 0, 0)
    pos_box(m, siz - 7, 0)
    pos_box(m, 0, siz - 7)
    x = 4
    while x + 5 < siz:
        y = 4
        while y + 5 < siz:
            if not ((x < 7 and y < 7) or (x < 7 and y + 5 >= siz - 7) or (x + 5 >= siz - 7 and y < 7)):
                align_box(m, x, y)
            y = apos if y == 4 else y + astride
        x = apos if x == 4 else x + astride
    if pattern:
        v = pattern
        for x in range(6):
            for y in range(3):
                q = mkpix(PVERSION) | (BLACK if v & 1 else 0)
                m[siz - 11 + y][x] = q
                m[x][siz - 11 + y] = q
                v >>= 1
    m[siz - 8][8] = mkpix(UNUSED) | BLACK

    # format
    fb = (level ^ 1) << 13
    fb |= mask << 10
    rem = fb
    for i in range(14, 9, -1):
        if rem & (1 << i):
            rem ^= 0x537 << (i - 10)
    fb |= rem
    inv = 0x5412
    for i in range(15):
        q = mkpix(FORMAT, i) | (BLACK if (fb >> i) & 1 else 0)
        if (inv >> i) & 1:
            q ^= INVERT | BLACK
        if i < 6:
            m[i][8] = q
        elif i < 8:
            m[i + 1][8] = q
        elif i < 9:
            m[8][7] = q
        else:
            m[8][14 - i] = q
        if i < 8:
            m[8][siz - 1 - i] = q
        else:
            m[siz - 1 - (14 - i)][8] = q

    # donnees + controle
    nblock, ne = levels[level]
    nde = (nbytes - ne * nblock) // nblock
    extra = (nbytes - ne * nblock) % nblock
    data_bits = (nde * nblock + extra) * 8
    check_bits = ne * nblock * 8
    p.data_bytes = nbytes - ne * nblock
    p.check_bytes = ne * nblock
    p.blocks = nblock
    data = [mkpix(DATA, i) for i in range(data_bits)]
    check = [mkpix(CHECK, i + data_bits) for i in range(check_bits)]
    dlist, clist = [], []
    for i in range(nblock):
        nd = nde + (1 if i >= nblock - extra else 0)
        dlist.append(data[:nd * 8])
        data = data[nd * 8:]
        clist.append(check[:ne * 8])
        check = check[ne * 8:]
    seq = []
    for i in range(nde + 1):
        for b in dlist:
            if i * 8 < len(b):
                seq += b[i * 8:(i + 1) * 8]
    for i in range(ne):
        for b in clist:
            if i * 8 < len(b):
                seq += b[i * 8:(i + 1) * 8]
    seq += [mkpix(EXTRA)] * 7
    k = 0
    x = siz
    while x > 0:
        for y in range(siz - 1, -1, -1):
            for xx in (x - 1, x - 2):
                if role(m[y][xx]) == 0:
                    m[y][xx] = seq[k]
                    k += 1
        x -= 2
        if x == 7:
            x -= 1
        for y in range(siz):
            for xx in (x - 1, x - 2):
                if role(m[y][xx]) == 0:
                    m[y][xx] = seq[k]
                    k += 1
        x -= 2

    # masque
    for y in range(siz):
        for x in range(siz):
            if role(m[y][x]) in (DATA, CHECK, EXTRA) and MASKS[mask](y, x):
                m[y][x] ^= BLACK | INVERT
    return p


def rotate(p, rot):
    n = len(p.pixel)
    src = p.pixel
    for _ in range(rot % 4):
        src = [[src[x][n - 1 - y] for x in range(n)] for y in range(n)]
    p.pixel = src


def add_check_bytes(bits, version, level):
    apos, astride, nbytes, pattern, levels = VTAB[version]
    nblock, ne = levels[level]
    nd = nbytes - nblock * ne
    if len(bits) < nd * 8:
        bits.pad(nd * 8 - len(bits))
    assert len(bits) == nd * 8, "trop de donnees"
    dat = bits.to_bytes()
    db = nd // nblock
    extra = nd % nblock
    out = list(dat)
    for i in range(nblock):
        if i == nblock - extra:
            db += 1
        out += rs_ecc(dat[:db], ne)
        dat = dat[db:]
    return out


# ---------------------------------------------------------------- bloc de bits


def bit_of(byts, bi):
    return (byts[bi // 8] >> (7 - bi % 8)) & 1


def to_vec(byts):
    v = 0
    for i, c in enumerate(byts):
        for k in range(8):
            if (c >> (7 - k)) & 1:
                v |= 1 << (8 * i + k)
    return v


def from_vec(v, n):
    out = []
    for i in range(n):
        c = 0
        for k in range(8):
            c = (c << 1) | ((v >> (8 * i + k)) & 1)
        out.append(c)
    return out


class BitBlock:
    """Elimination de Gauss sur GF(2). Chaque ligne est un mot RS valide
    (donnees + controle), stocke comme un entier ; le XOR de deux lignes
    reste un mot valide. / Gaussian elimination over GF(2)."""

    def __init__(self, nd, nc, bdata):
        self.nd, self.nc = nd, nc
        self.B = to_vec(list(bdata) + rs_ecc(bdata, nc))
        self.M = []
        for i in range(nd * 8):
            row = [0] * nd
            row[i // 8] = 1 << (7 - i % 8)
            self.M.append(to_vec(row + rs_ecc(row, nc)))
        self.saved = []

    def can_set(self, bi, bval):
        mask = 1 << bi
        for j, row in enumerate(self.M):
            if row & mask:
                targ = self.M.pop(j)
                break
        else:
            return False
        self.M = [r ^ targ if r & mask else r for r in self.M]
        self.saved = [r ^ targ if r & mask else r for r in self.saved]
        if (self.B >> bi) & 1 != bval:
            self.B ^= targ
        self.saved.append(targ)
        return True

    def out(self):
        byts = from_vec(self.B, self.nd + self.nc)
        assert rs_ecc(byts[:self.nd], self.nc) == byts[self.nd:], "ecc casse"
        return byts


# ---------------------------------------------------------------- cible image


def make_target(path, n, invert=False, margin=0):
    """Image -> grille n x n de gris 0..255, -1 hors image / transparent."""
    img = Image.open(path).convert("RGBA")
    inner = n - 2 * margin
    w, h = img.size
    if w > h:
        nw, nh = inner, max(1, round(h * inner / w))
    else:
        nw, nh = max(1, round(w * inner / h)), inner
    img = img.resize((nw, nh), Image.LANCZOS)
    a = np.asarray(img).astype(int)
    lum = (299 * a[..., 0] + 587 * a[..., 1] + 114 * a[..., 2] + 500) // 1000
    if invert:
        lum = 255 - lum
    lum[a[..., 3] == 0] = -1
    t = -np.ones((n, n), dtype=int)
    ox, oy = (n - nw) // 2, (n - nh) // 2
    t[oy:oy + nh, ox:ox + nw] = lum
    return t


def contrast_map(t):
    n = t.shape[0]
    s = np.zeros_like(t)
    s2 = np.zeros_like(t)
    cnt = np.zeros_like(t)
    d = 5
    for dy in range(-d, d + 1):
        for dx in range(-d, d + 1):
            ys0, ys1 = max(0, dy), min(n, n + dy)
            xs0, xs1 = max(0, dx), min(n, n + dx)
            sub = t[ys0:ys1, xs0:xs1]
            s[ys0 - dy:ys1 - dy, xs0 - dx:xs1 - dx] += sub
            s2[ys0 - dy:ys1 - dy, xs0 - dx:xs1 - dx] += sub * sub
            cnt[ys0 - dy:ys1 - dy, xs0 - dx:xs1 - dx] += 1
    avg = s // cnt
    c = s2 // cnt - avg * avg
    c[t < 0] = -1
    return c


# ---------------------------------------------------------------- QArt


def qart(url, target_path, version=8, mask=2, rotation=0, rand=False,
         seed=1, only_data=False, invert=False, margin=0, level=0):
    rng = random.Random(seed)
    p = new_plan(version, level, mask)
    rotate(p, rotation)
    n = len(p.pixel)
    targ = make_target(target_path, n, invert=invert, margin=margin)
    contr = contrast_map(targ)

    nblocks = p.blocks
    nd0 = p.data_bytes // nblocks
    nc = p.check_bytes // nblocks
    extra = p.data_bytes - nd0 * nblocks

    total = (p.data_bytes + p.check_bytes) * 8
    info = [None] * total  # off -> dict
    for y in range(n):
        for x in range(n):
            pix = p.pixel[y][x]
            if role(pix) in (DATA, CHECK):
                tv = targ[y, x]
                c = int(contr[y, x])
                if rand and c >= 0:
                    c = rng.randrange(128) + 64 * ((x + y) % 2) + 64 * ((x + y) % 3 % 2)
                info[offset(pix)] = {"x": x, "y": y, "pix": pix,
                                     "targ": 255 if tv < 0 else int(tv),
                                     "contrast": c, "hard_zero": False, "ctrl": False}

    prefix = url + "#"
    hb = Bits()
    encode_string(hb, prefix, version)
    encode_num(hb, "", version)
    bbit = len(hb)
    dbit = p.data_bytes * 8 - bbit
    if dbit < 0:
        raise ValueError("URL trop longue pour cette version")
    ndig = dbit // 10 * 3
    mbit = bbit + dbit // 10 * 10

    for _attempt in range(50):
        num = "0" * ndig
        b = Bits()
        encode_string(b, prefix, version)
        encode_num(b, num, version)
        data = add_check_bytes(b, version, level)

        for d in info:
            d["ctrl"] = False
        doff = coff = 0
        nd = nd0
        for blocknum in range(nblocks):
            if blocknum == nblocks - extra:
                nd += 1
            bdata = data[doff // 8: doff // 8 + nd]
            bb = BitBlock(nd, nc, bdata)
            lo, hi = 0, nd * 8
            if lo < bbit - doff:
                lo = min(bbit - doff, hi)
            if hi > mbit - doff:
                hi = max(mbit - doff, lo)
            for i in list(range(0, lo)) + list(range(hi, nd * 8)):
                assert bb.can_set(i, bit_of(bdata, i))
            order = [doff + i for i in range(lo, hi)]
            if not only_data:
                order += [p.data_bytes * 8 + coff + i for i in range(nc * 8)]
            prio = {o: (info[o]["contrast"] << 8) | rng.randrange(256) for o in order}
            order.sort(key=lambda o: -prio[o])
            for o in order:
                d = info[o]
                bval = 1 if d["targ"] < 128 else 0
                if d["pix"] & INVERT:
                    bval ^= 1
                if d["hard_zero"]:
                    bval = 0
                if role(d["pix"]) == DATA:
                    bi = o - doff
                else:
                    bi = o - p.data_bytes * 8 - coff + nd * 8
                if bb.can_set(bi, bval):
                    d["ctrl"] = True
            blk = bb.out()
            data[doff // 8: doff // 8 + nd] = blk[:nd]
            data[p.data_bytes + coff // 8: p.data_bytes + coff // 8 + nc] = blk[nd:]
            doff += nd * 8
            coff += nc * 8

        # Relit les groupes de 10 bits ; >= 1000 n'est pas un nombre valide.
        noops = 0
        digits = []
        for i in range(dbit // 10):
            v = 0
            for j in range(10):
                v = (v << 1) | bit_of(data, bbit + 10 * i + j)
            if v >= 1000:
                d = info[bbit + 10 * i + 3]
                d["contrast"] = 10 ** 9 >> 8
                d["hard_zero"] = True
                noops += 1
            digits.append(f"{v:03d}")
        if noops == 0:
            break
    else:
        raise RuntimeError("pas de convergence")

    num = "".join(digits)
    b1 = Bits()
    encode_string(b1, prefix, version)
    encode_num(b1, num, version)
    assert add_check_bytes(b1, version, level) == data, "incoherence octets"

    grid = np.zeros((n, n), dtype=bool)
    ctrl = np.zeros((n, n), dtype=bool)
    for y in range(n):
        for x in range(n):
            pix = p.pixel[y][x]
            blk = bool(pix & BLACK)
            if role(pix) in (DATA, CHECK):
                if bit_of(data, offset(pix)):
                    blk = not blk
                ctrl[y, x] = info[offset(pix)]["ctrl"]
            grid[y, x] = blk
    stats = {
        "version": version, "taille": n, "url": url, "chiffres": len(num),
        "bits_libres": dbit // 10 * 10, "bits_total": total,
        "controles": int(ctrl.sum()),
    }
    return grid, ctrl, prefix + num, stats


def render(grid, scale=8, quiet=4):
    n = grid.shape[0]
    img = np.full((n + 2 * quiet, n + 2 * quiet), 255, dtype=np.uint8)
    img[quiet:quiet + n, quiet:quiet + n] = np.where(grid, 0, 255)
    return Image.fromarray(img).resize(((n + 2 * quiet) * scale,) * 2, Image.NEAREST)
