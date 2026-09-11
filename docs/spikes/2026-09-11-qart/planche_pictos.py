import io, os, urllib.request
import cairosvg
from PIL import Image, ImageDraw, ImageFont
from essai import *

PH = """acorn axe backpack barn baseball-cap beanie bicycle binoculars bird boot bug-beetle butterfly
cactus campfire cloud cloud-fog cloud-lightning cloud-rain cloud-snow cloud-sun clover coffee compass
compass-rose cow drop feather fire fish flashlight flower flower-tulip footprints grains horse leaf
map-trifold moon-stars mountains park path paw-print person-simple-bike person-simple-hike
person-simple-ski person-simple-snowboard plant rabbit rainbow signpost sneaker snowflake sock sun
sun-horizon sunglasses tent tree tree-evergreen waves windmill""".split()
GI = """hiking mountains mountaintop mountain-road peaks summits hills valley mountain-climbing
cliff-crossing rope-bridge carabiner rope-coil walking-boot boots boot-prints light-backpack
camping-tent forest-camp sleeping-bag water-flask treasure-map lantern pine-tree oak forest fern
maple-leaf oak-leaf mushroom spotted-mushroom deer fox squirrel owl goat snail sunrise skier
winter-hat billed-cap propeller-beanie dutch-bike wood-cabin waterfall river trail hatchet
winter-gloves""".split()
PICTOS = [("ph", n + "-fill", "MIT") for n in PH] + [("game-icons", n, "CC BY 3.0") for n in GI]

os.makedirs("pictos/svg", exist_ok=True); os.makedirs("pictos/png", exist_ok=True)
POLICE = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 15)
GRAS = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 22)

cellules, index = [], []
for k, (s, n, lic) in enumerate(PICTOS, 1):
    svg_path = f"pictos/svg/{s}__{n}.svg"
    if not os.path.exists(svg_path):
        svg = urllib.request.urlopen(urllib.request.Request(
            f"https://api.iconify.design/{s}/{n}.svg?height=400", headers={"User-Agent": "spike"}), timeout=30).read()
        open(svg_path, "wb").write(svg)
    png_path = f"pictos/png/{s}__{n}.png"
    cairosvg.svg2png(url=svg_path, write_to=png_path, output_width=400, output_height=400, background_color="white")
    g, c, payload, st = qart(URLS["court"], png_path, version=8, margin=3)
    qr = render(g, 7)
    ok = decode(qr)[0] == payload
    index.append(f"{k:3d}  {'OK ' if ok else 'ILLISIBLE'}  {s}:{n}  ({lic})")
    cellules.append((k, f"{s}:{n}", ok, qr, Image.open(png_path)))
    print(index[-1])

CW, CH, COLS, ROWS = 300, 380, 8, 5
par_page = COLS * ROWS
for p in range(0, len(cellules), par_page):
    page = Image.new("L", (CW * COLS, CH * ROWS), 255); d = ImageDraw.Draw(page)
    for i, (k, nom, ok, qr, orig) in enumerate(cellules[p:p + par_page]):
        x, y = (i % COLS) * CW, (i // COLS) * CH
        d.rectangle((x, y, x + CW - 1, y + CH - 1), outline=200)
        d.text((x + 10, y + 6), str(k), font=GRAS, fill=0)
        d.text((x + 60, y + 12), nom.replace("-fill", ""), font=POLICE, fill=0)
        page.paste(qr.resize((270, 270), Image.NEAREST), (x + 15, y + 38))
        page.paste(orig.convert("L").resize((60, 60), Image.LANCZOS), (x + 15, y + 312))
        d.text((x + 90, y + 332), "lisible" if ok else "ILLISIBLE", font=POLICE, fill=0)
    page.save(f"out/pictos_page{p // par_page + 1}.png")
open("out/pictos_index.txt", "w").write("\n".join(index) + "\n")
print(len(cellules), "pictos,", sum(1 for c in cellules if c[2]), "lisibles")
