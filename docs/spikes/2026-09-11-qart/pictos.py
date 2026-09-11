import urllib.request, io, cairosvg
from PIL import Image, ImageDraw
from essai import *
PICTOS = ["ph:bicycle-fill", "ph:mountains-fill", "ph:baseball-cap-fill", "ph:beanie-fill",
          "ph:tent-fill", "ph:tree-evergreen-fill", "game-icons:mountain-climbing", "game-icons:hiking",
          "mdi:rock-climbing", "ph:bicycle", "ph:beanie", "tabler:mountain"]
res = []
for p in PICTOS:
    s, n = p.split(":")
    svg = urllib.request.urlopen(urllib.request.Request(f"https://api.iconify.design/{s}/{n}.svg?height=400", headers={"User-Agent": "spike"}), timeout=30).read()
    png = cairosvg.svg2png(bytestring=svg, output_width=400, output_height=400, background_color="white")
    chemin = f"img/picto_{s}_{n}.png"
    open(chemin, "wb").write(png)
    g, c, payload, st = qart(URLS["court"], chemin, version=8, margin=3)
    im = render(g, 7)
    ok = decode(im)[0] == payload
    res.append((p, im, ok))
    print(f"{p:32} lisible={ok}")
W = 420
sheet = Image.new("L", (W * 4, (W + 30) * 3), 255); d = ImageDraw.Draw(sheet)
for k, (p, im, ok) in enumerate(res):
    x, y = (k % 4) * W, (k // 4) * (W + 30)
    im = im.resize((W - 20, W - 20), Image.NEAREST)
    sheet.paste(im, (x + 10, y + 25)); d.text((x + 10, y + 5), p, fill=0)
sheet.save("out/pictos.png")
