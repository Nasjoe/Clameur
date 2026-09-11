import sys
sys.path.insert(0, "/home/jonas/Gits/Clameur")
from impression.sunmi_cloud_printer import SunmiCloudPrinter, ALIGN_CENTER, THRESHOLD_DITHER
from essai import *

t = SunmiCloudPrinter(dots_per_line=576, app_id="x", app_key="x", printer_sn="x")
t.restoreDefaultSettings()
t.setAlignment(ALIGN_CENTER)
essais = [("coeur", 8, 7), ("smiley", 10, 8), ("logo", 8, 10), ("pjw", 10, 8)]
for nom, v, dots in essais:
    g, c, payload, st = qart(URLS["court"], f"img/{nom}.png", version=v)
    im = render(g, dots)
    chemin = f"out/ticket_{nom}.png"
    im.save(chemin)
    assert decode(im)[0] == payload
    t.appendText(f"{nom} v{v} {dots} pts/module ({im.width} pts)\n")
    t.appendImage(chemin, mode=THRESHOLD_DITHER)
    t.lineFeed(2)
t.lineFeed(3)
t.cutPaper(full_cut=False)
open("out/ticket_qart.bin", "wb").write(t.orderData)
print(len(t.orderData), "octets")
