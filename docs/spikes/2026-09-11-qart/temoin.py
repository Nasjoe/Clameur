from essai import *
import segno
for uk, url in URLS.items():
    q = segno.make(url, error="l", micro=False, boost_error=False)
    m = np.array([[bool(v) for v in row] for row in q.matrix])
    im = render(m, 8)
    print("temoin", uk, "v", q.version, "natif", decode(im)[0] == url, decode(im)[1] == url,
          "| degrade zxing", decode(degrade(im))[0] == url, "cv", decode(degrade(im))[1] == url)
# qart : degradation plus douce pour situer le seuil opencv
g, c, payload, st = qart(URLS["court"], "img/coeur.png", version=8)
im = render(g, 8)
for px in (6, 4, 3):
    for blur in (0, 0.8):
        w = int(im.width * px / 8)
        d = im.resize((w, w), Image.BILINEAR).filter(ImageFilter.GaussianBlur(blur)) if blur else im.resize((w, w), Image.BILINEAR)
        print(f"qart coeur v8 {px}px/module flou={blur}:", ["zx", "cv"], [s == payload for s in decode(d)])
