"""LOE v2 — ITEM GROUPS (the legality rule we were missing).
The wiki states it plainly: certain items belong to designated ITEM GROUPS, and a player may not
equip more than one item from the same group. Without this the engine was producing ILLEGAL builds
— Void Staff + Cryptbloom + Terminus (all 'Blight'), or three Last Whisper items at once.

v1 and v2-until-now inferred uniqueness from shared passive NAMES, which only caught a fraction.
This reads the rule from the source.
"""
import re, json, sqlite3

cx = sqlite3.connect('wiki.db'); C = cx.cursor()
TXT = C.execute("SELECT text FROM pages WHERE title='Item group'").fetchone()[0]

GROUPS = {}
# table rows: |'''GroupName'''  \n |{{ii|Item}}<br />{{ii|Item}}...
for m in re.finditer(r"\|\s*(?:\{\{anchor\|[^}]*\}\})?'''([^']+)'''\s*\n\|((?:\s*\{\{ii\|[^}]+\}\}(?:<br\s*/?>)?)+)", TXT):
    name = m.group(1).strip()
    items = re.findall(r'\{\{ii\|([^}|]+)', m.group(2))
    items = [i.strip() for i in items]
    if items:
        GROUPS[name] = items

# invert: item -> its groups
ITEM_GROUP = {}
for g, items in GROUPS.items():
    for it in items:
        ITEM_GROUP.setdefault(it, []).append(g)

json.dump(dict(groups=GROUPS, item_group=ITEM_GROUP), open('item_groups.json', 'w'), indent=1)

if __name__ == '__main__':
    print(f'ITEM GROUPS from the wiki: {len(GROUPS)}')
    for g, items in sorted(GROUPS.items(), key=lambda x: -len(x[1])):
        print(f'   {g:16s} ({len(items):2d}) {", ".join(items[:6])}{"…" if len(items) > 6 else ""}')
    import core
    leg = set(core.LEGENDARIES)
    affected = {g: [i for i in items if i in leg] for g, items in GROUPS.items()}
    affected = {g: v for g, v in affected.items() if len(v) > 1}
    print(f'\ngroups that constrain the LEGENDARY pool: {len(affected)}')
    for g, v in affected.items():
        print(f'   {g:16s} only ONE of: {", ".join(v)}')
