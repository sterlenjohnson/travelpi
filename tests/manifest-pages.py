#!/usr/bin/env python3
"""Cockpit registration contract: every menu group and page registered in
manifest.json must exist as a complete app page (shared chrome + scripts)."""
import json
import pathlib

root = pathlib.Path(__file__).parents[1]
manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))

menus = manifest.get("menu", {})
pages = manifest.get("pages", {})
assert menus, "manifest registers a menu group"
assert pages, "manifest registers pages"
assert "content-security-policy" in manifest, "manifest keeps the app CSP"

for pid, spec in pages.items():
    path = root / spec.get("path", "")
    assert path.exists(), f"{pid}: missing page file {spec.get('path')!r}"
    assert spec.get("label"), f"{pid}: missing label"
    assert spec.get("menu") in menus, f"{pid}: refers to undeclared menu {spec.get('menu')!r}"
    assert spec.get("position") is not None, f"{pid}: missing position"
    html = path.read_text(encoding="utf-8")
    for needle in ('id="travelpi-app"', 'id="confirm-dialog"', 'id="pending-bar"',
                   'class="vitals-strip"', 'src="travelpi.js"', 'src="../base1/cockpit.js"'):
        assert needle in html, f"{pid}: page missing {needle}"

# The app registers no Cockpit tools. If that ever changes, every tool path
# must be a real file, so the loop is asserted non-vacuous when tools exist.
tools = manifest.get("tools", {})
for tid, spec in tools.items():
    assert (root / spec.get("path", "")).exists(), f"tool {tid}: missing {spec.get('path')!r}"

# Menu groups must be complete: every declared group needs a label, and a group
# that no page references is dead registration (Cockpit builds the sidebar from
# `menu`, pages attach through their own `menu` key).
for group, entry in menus.items():
    assert entry.get("label"), f"menu group {group}: missing display label"
    members = [pid for pid, spec in pages.items() if spec.get("menu") == group]
    assert members, f"menu group {group}: declared but no page is registered under it"

# URL file-mapping twin: /travelpi/travelpi is served as travelpi.html by cockpit's
# static file resolver, so it must stay byte-identical to index.html.
index_html = (root / "index.html").read_text(encoding="utf-8")
twin_html = (root / "travelpi.html").read_text(encoding="utf-8")
assert index_html == twin_html, "travelpi.html must stay byte-identical to index.html (re-copy after edits)"

print("manifest page checks passed")
