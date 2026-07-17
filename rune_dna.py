"""LOE v2 — RUNE DNA.
v1's rune tree (path membership + row assignment) was HAND-CURATED by me from memory — the single
weakest link in the whole engine. The wiki states it explicitly: every 'Template:Rune data <Name>'
page carries |path= (the tree) and |slot= (Keystone or which row). No more guessing.
Output: rune_dna.json — {name: {path, slot, row, kind, trigger, effects, adaptive, text}}
"""
import re, json, sqlite3
from collections import defaultdict

cx = sqlite3.connect('wiki.db'); C = cx.cursor()

def field(t, name):
    m = re.search(r'\|\s*' + re.escape(name) + r'\s*=\s*(.*?)(?=\n\s*\|[a-zA-Z0-9_][a-zA-Z0-9_ ]*=|\n\}\}|\Z)', t, re.S)
    return m.group(1).strip() if m else ''

TRIGGERS = [
 ('ON_HIT',        r'\bon-hit\b'),
 ('ON_ABILITY',    r'\babilit(?:y|ies)\b.{0,30}\b(?:hit|damage)|damaging (?:ability|spell)'),
 ('ON_TAKEDOWN',   r'takedown|champion kill'),
 ('ON_IMMOBILIZE', r'immobilis|immobiliz'),
 ('ON_CC',         r'crowd control'),
 ('PERIODIC',      r'every \d+|per second|periodically'),
 ('ON_LOW_HEALTH', r'below \d+%'),
 ('ALWAYS',        r'.'),
]
EFFECTS = [
 ('DAMAGE',      r'\bdamage\b'),
 ('HEAL',        r'\bheal|life ?steal|omnivamp'),
 ('SHIELD',      r'\bshield'),
 ('AD',          r'attack damage'),
 ('AP',          r'ability power'),
 ('AS',          r'attack speed'),
 ('AH',          r'ability haste|cooldown'),
 ('MS',          r'movement speed'),
 ('RESIST',      r'\barmor\b|magic resist'),
 ('HP',          r'\bhealth\b'),
 ('MANA',        r'\bmana\b'),
 ('PEN',         r'penetrat|lethality'),
 ('ADAPTIVE',    r'adaptive force'),
 ('SLOW_RESIST', r'tenacity'),
 ('GOLD',        r'\bgold\b'),
 ('EXECUTE',     r'execute'),
]
ROW_OF = {'Keystone': 0, '1': 1, '2': 2, '3': 3, 'Slot 1': 1, 'Slot 2': 2, 'Slot 3': 3,
          'Offense': 1, 'Flex': 2, 'Defense': 3}

# ---- SHARDS: exact values from the wiki Rune article's shard matrix (3 slots x 3 options) ----
# Health-scaling shard is 10->180 by level (level 18 => 10 + 170/17*17 = 180); listed at its L18 value.
SHARDS = {
 'Adaptive Force':  dict(slots=[1, 2], stats={'adaptive': 9},  text='+9 adaptive force'),
 'Attack Speed':    dict(slots=[1],    stats={'as': 10},       text='+10% attack speed'),
 'Ability Haste':   dict(slots=[1],    stats={'ah': 8},        text='+8 ability haste'),
 'Move Speed':      dict(slots=[2],    stats={'ms_pct': 2.5},  text='+2.5% movement speed'),
 'Health Scaling':  dict(slots=[2, 3], stats={'hp': 180},      text='+10-180 health by level (180 at 18)'),
 'Health':          dict(slots=[3],    stats={'hp': 65},       text='+65 health'),
 'Tenacity':        dict(slots=[3],    stats={'tenacity': 15}, text='+15% tenacity and slow resist'),
}

RUNES = {}
removed_n = [0]
rows = C.execute("SELECT title, text FROM pages WHERE title LIKE 'Template:Rune data %'").fetchall()
for title, raw in rows:
    name = title.replace('Template:Rune data ', '').strip()
    path = field(raw, 'path')
    slot = field(raw, 'slot')
    desc = field(raw, 'description') + ' ' + field(raw, 'description2')
    if not path: continue
    if re.search(r'\|\s*removed\s*=\s*true', raw): removed_n[0] += 1; continue   # ghost-rune gate
    d = desc.lower()
    trig = next(t for t, rx in TRIGGERS if re.search(rx, d))
    effs = [e for e, rx in EFFECTS if re.search(rx, d)]
    RUNES[name] = dict(
        path=path, slot=slot, row=ROW_OF.get(slot, None),
        kind=('KEYSTONE' if slot == 'Keystone' else 'SHARD' if path == 'Stat' or 'shard' in slot.lower() else 'MINOR'),
        trigger=trig, effects=effs,
        adaptive=bool(re.search(r'adaptive force', d)),
        text=re.sub(r'\{\{[^{}]*\}\}|\[\[|\]\]|\'{2,}', '', desc).strip()[:260])

for n, s in SHARDS.items():
    RUNES[n + ' Shard'] = dict(path='Stat', slot='Shard', row=None, kind='SHARD',
                               trigger='ALWAYS', effects=list(s['stats']), adaptive=(n == 'Adaptive Force'),
                               shard_slots=s['slots'], stats=s['stats'], text=s['text'])
json.dump(RUNES, open('rune_dna.json', 'w'), indent=0)
print(f'GHOST-RUNE GATE: excluded {removed_n[0]} removed runes')

trees = defaultdict(lambda: defaultdict(list))
for n, r in RUNES.items():
    trees[r['path']][r['slot']].append(n)
print(f'runes parsed: {len(RUNES)}')
for path in sorted(trees):
    slots = trees[path]
    ks = slots.get('Keystone', [])
    print(f'\n{path}:')
    if ks: print(f'   KEYSTONES ({len(ks)}): {", ".join(sorted(ks))}')
    for s in sorted(k for k in slots if k != 'Keystone'):
        print(f'   {s:10s} ({len(slots[s])}): {", ".join(sorted(slots[s]))}')
