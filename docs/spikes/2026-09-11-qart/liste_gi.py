import json, urllib.request, re
def get(u): return json.load(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "spike"}), timeout=30))
MOTS = r"bicycl|bike|mountain|hik|climb|tree|forest|pine|tent|camp|backpack|boot|cap\b|cap$|beanie|hat|leaf|flower|compass|summit|peak|rope|carabiner|axe|pick|helmet|glove|mitten|lantern|lamp|trail|path|footprint|ski|sled|kayak|canoe|deer|bear|wolf|fox|rabbit|squirrel|owl|goat|ibex|chamois|eagle|marmot|mushroom|acorn|pinecone|fern|oak|birch|river|lake|waterfall|sun|snow|cloud|binocular|map|signpost|flask|thermos|canteen|wool|scarf|sock|cliff|rock|stone|hill|valley|cabin|hut|chalet|campfire|fire|sleeping|hammock|bird|butterfly|bee|beetle|snail|feather|paw"
gi = get("https://api.iconify.design/collection?prefix=game-icons")
noms = set(gi.get("uncategorized", [])) | {i for v in (gi.get("categories") or {}).values() for i in v}
print(" ".join(sorted(n for n in noms if re.search(MOTS, n))))
