from PIL import Image, ImageDraw
imgs = ["coeur", "smiley", "logo", "pjw"]
cols = [("long", 8), ("court", 8), ("court", 10)]
W = 540
sheet = Image.new("L", (W * len(cols), W * len(imgs) + 40), 255)
d = ImageDraw.Draw(sheet)
for j, (u, v) in enumerate(cols):
    d.text((j * W + 10, 10), f"URL {u} - version {v}", fill=0)
    for i, n in enumerate(imgs):
        im = Image.open(f"out/{n}_{u}_v{v}.png")
        im.thumbnail((W - 20, W - 20))
        sheet.paste(im, (j * W + 10, 40 + i * W))
sheet.save("out/planche.png")
