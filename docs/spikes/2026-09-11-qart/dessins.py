from PIL import Image, ImageDraw
import math
S = 400
# coeur
im = Image.new("L", (S, S), 255); d = ImageDraw.Draw(im)
pts = []
for k in range(360):
    t = math.radians(k)
    x = 16 * math.sin(t) ** 3
    y = 13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)
    pts.append((S / 2 + x * 11, S / 2 - y * 11 - 10))
d.polygon(pts, fill=0); im.save("img/coeur.png")
# smiley
im = Image.new("L", (S, S), 255); d = ImageDraw.Draw(im)
d.ellipse((20, 20, S - 20, S - 20), fill=0)
d.ellipse((120, 110, 170, 190), fill=255); d.ellipse((230, 110, 280, 190), fill=255)
d.arc((100, 150, 300, 320), 20, 160, fill=255, width=30)
im.save("img/smiley.png")
