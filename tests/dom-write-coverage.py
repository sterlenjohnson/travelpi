#!/usr/bin/env python3
"""Render-code -> page DOM contract: every write target in travelpi.ts
(setText/setState/setBadge/setHidden/setSwitch/setClass/setProgress/setHtml)
must exist as an element id in at least one registered app page.
Guards against phantom writes into DOM ids removed by page redesigns."""
import json
import re
import pathlib

root = pathlib.Path(__file__).parents[1]
src = (root / "travelpi.ts").read_text(encoding="utf-8")
ids = set(re.findall(
    r'\b(?:setText|setState|setBadge|setHidden|setSwitch|setClass|setProgress|setHtml)\("([^"]+)"', src))
# Sparklines write through renderSparkline, not a setter: include them.
ids |= set(re.findall(r'\brenderSparkline\("([^"]+)"', src))
assert ids, "render code must have write targets to check (empty set means the scan broke)"

manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
pages = [root / spec["path"] for spec in manifest.get("pages", {}).values()]
assert pages, "manifest registers pages"
html = {p.read_text(encoding="utf-8") for p in pages}

dead = sorted(i for i in ids if all(('id="%s"' % i) not in h for h in html))
assert not dead, f"render code writes to ids absent from every page: {dead}"
print("dom write coverage checks passed")
