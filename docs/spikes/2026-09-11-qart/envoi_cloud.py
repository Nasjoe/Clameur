import os, sys, time
sys.path.insert(0, "/home/jonas/Gits/Clameur")
from impression.sunmi_cloud_printer import SunmiCloudPrinter, ALIGN_CENTER, THRESHOLD_DITHER  # charge le .env
from essai import *

sn = os.environ["SUNMI_PRINTER_SN"]
def pilote():
    return SunmiCloudPrinter(dots_per_line=576, app_id=os.environ["SUNMI_APP_ID"],
                             app_key=os.environ["SUNMI_APP_KEY"], printer_sn=sn)

etat = pilote().onlineStatus(sn)
print("en ligne :", [(a.get("is_online")) for a in (etat.get("data") or {}).get("list", []) if a.get("sn") == sn])

essais = [("smiley", 10, 8), ("logo", 8, 10), ("pjw", 10, 8)]
stamp = int(time.time())
for nom, v, dots in essais:
    g, c, payload, st = qart(URLS["court"], f"img/{nom}.png", version=v)
    im = render(g, dots)
    chemin = f"out/ticket_{nom}.png"
    im.save(chemin)
    assert decode(im)[0] == payload
    t = pilote()
    t.restoreDefaultSettings()
    t.setAlignment(ALIGN_CENTER)
    t.appendText(f"QArt {nom} - v{v} - {dots} pts/module ({im.width} pts)\n")
    t.appendImage(chemin, mode=THRESHOLD_DITHER)
    t.lineFeed(4)
    t.cutPaper(full_cut=False)
    rep = t.pushContent(trade_no=f"qa{nom[:3]}{stamp}", sn=sn, count=1, media_text="QArt")
    print(nom, len(t.orderData), "octets ->", rep.get("code"), rep.get("msg"))
    time.sleep(2)
