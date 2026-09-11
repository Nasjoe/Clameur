from essai import *
rows = []
for img in ["coeur", "smiley", "logo", "pjw"]:
    for uk, url in URLS.items():
        for v in (6, 8, 10):
            t = time.time()
            try:
                g, c, payload, st = qart(url, f"img/{img}.png", version=v, mask=2)
            except Exception as e:
                print(img, uk, v, "ERREUR", e); continue
            dt = time.time() - t
            im = render(g, 8)
            im.save(f"out/{img}_{uk}_v{v}.png")
            z, cv = decode(im)
            zd, cvd = decode(degrade(im))
            ok = lambda s: "OK" if s == payload else ("--" if s is None else "FAUX")
            print(f"{img:7} {uk:5} v{v:<2} {st['taille']}mod {im.width}pts ctrl={st['controles']}/{st['bits_total']} "
                  f"({100*st['controles']/st['bits_total']:.0f}%)  zxing={ok(z)} cv={ok(cv)} | degrade zxing={ok(zd)} cv={ok(cvd)}  {dt:.1f}s")
print("exemple payload:", payload[:90], "...")
