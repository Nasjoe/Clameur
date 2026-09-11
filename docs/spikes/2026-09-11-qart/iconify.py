import json, urllib.request, collections
def get(u):
    return json.load(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "spike"}), timeout=30))
cols = get("https://api.iconify.design/collections")
sets = ["game-icons", "mdi", "material-symbols", "ph", "tabler", "fa6-solid", "maki", "temaki", "openmoji", "fluent-emoji-high-contrast", "mingcute", "ri", "streamline"]
for s in sets:
    c = cols.get(s)
    if c: print(f"{s:28} {c['total']:>6} icones  licence={c['license']['title']}")
mots = ["bicycle", "bike", "mountain", "hiking", "climbing", "tree", "forest", "tent", "campfire", "backpack", "boot", "cap", "beanie", "hat", "leaf", "compass"]
par_set = collections.defaultdict(dict)
for m in mots:
    r = get(f"https://api.iconify.design/search?query={m}&limit=999")
    for ic in r.get("icons", []):
        p, n = ic.split(":", 1)
        par_set[p].setdefault(m, []).append(n)
print()
for s in sets:
    d = par_set.get(s, {})
    print(f"{s:28}", " ".join(f"{m}={len(d.get(m, []))}" for m in mots))
print()
for s in ["game-icons", "ph", "mdi", "fa6-solid", "temaki"]:
    d = par_set.get(s, {})
    print(s, {m: d.get(m, [])[:8] for m in ["climbing", "cap", "beanie", "hat", "hiking", "mountain"]})
