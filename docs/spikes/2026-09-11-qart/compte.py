import json, urllib.request, re
def get(u): return json.load(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "spike"}), timeout=30))
MOTS = r"bicycle|bike|mountain|hik|climb|tree|forest|pine|tent|camp|fire|backpack|boot|sneaker|cap\b|cap-|beanie|hat|leaf|plant|flower|compass|map|sun|snow|cloud|rain|bird|butterfly|fish|mushroom|acorn|cactus|park|path|signpost|binocular|lantern|flashlight|rope|axe|carabiner|helmet|glove|mitten|sock|jacket|water|wave|river|lake|drop|bottle|flask|mug|coffee|feather|paw|deer|bear|wolf|fox|rabbit|squirrel|owl|bee|bug|snail|moon|star|rock|stone|hill|valley|peak|trail|footprint|ski|sled|kayak|canoe|horse|goat|cow|sheep|campfire|hammock|cabin|house|barn|windmill|wheat|grain|seedling|sprout|clover|daisy|tulip|rose|cherry|apple|pear|grape|berry"
ph = get("https://api.iconify.design/collection?prefix=ph")
noms = set(ph.get("uncategorized", [])) | {i for v in (ph.get("categories") or {}).values() for i in v}
fill = sorted(n[:-5] for n in noms if n.endswith("-fill") and re.search(MOTS, n))
print(f"Phosphor fill pertinents : {len(fill)}"); print(", ".join(fill))
gi = get("https://api.iconify.design/collection?prefix=game-icons")
gnoms = set(gi.get("uncategorized", [])) | {i for v in (gi.get("categories") or {}).values() for i in v}
g = sorted(n for n in gnoms if re.search(MOTS, n))
print(f"\ngame-icons pertinents (brut, avant tri) : {len(g)}")
