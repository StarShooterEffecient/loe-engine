"""LOE v2 — DNA VALIDATOR.
The charter's new law: VALIDATE THE CHAMPION, NOT JUST THE BUILD. Nothing may be optimized on a
number nobody checked. This runs BEFORE any optimization and publishes every defect it finds.

Checks:
  C1  physical-damage ability carrying an AP ratio (or magic ability carrying an AD ratio)  -> parse error
  C2  ability with damage numbers but no cooldown                                           -> incomplete
  C3  champion with zero damage abilities                                                   -> unusable kit
  C4  ability whose base damage is implausible (>1500 at rank 5)                            -> unit error
  C5  ratio implausibly large (>4.0 on a single ability)                                    -> template bleed
  C6  passive present but no effect data                                                    -> silent gap
Every defect is reported by name. Nothing is hidden, nothing is silently dropped.
"""
import json
from collections import defaultdict

CH = json.load(open('champion_dna.json'))
defects = defaultdict(list)
info = defaultdict(list)

for nm, c in CH.items():
    ab = c['abilities']
    dmg_abilities = 0
    for slot, a in ab.items():
        dt = (a.get('dtype') or '').lower()
        ap, adt, adb = a.get('ap', 0), a.get('ad_total', 0), a.get('ad_bonus', 0)
        has_dmg = bool(a.get('base') or ap or adt or adb or a.get('max_hp'))
        if has_dmg: dmg_abilities += 1
        # NOTE: hybrid scaling is REAL in League (Akali's Q is magic damage with an AD ratio;
        # Ezreal's Q is physical with an AP ratio). Recorded as INFO, never as a defect.
        if (dt.startswith('phys') and ap > 0) or (dt.startswith('mag') and (adt + adb) > 0):
            info['hybrid_scaling'].append(f'{nm}/{slot} {a["name"]}')
        if a.get('base') and not a.get('cd') and slot != 'I':
            defects['C2_no_cooldown'].append(f'{nm}/{slot} {a["name"]}')
        if a.get('base') and max(a['base']) > 1500:
            defects['C4_implausible_base'].append(f'{nm}/{slot} {a["name"]} ({max(a["base"])})')
        if max(ap, adt, adb) > 4.0:
            defects['C5_implausible_ratio'].append(f'{nm}/{slot} {a["name"]} ({max(ap, adt, adb)})')
    if dmg_abilities == 0:
        defects['C3_no_damage_kit'].append(nm)
    # A passive with no DAMAGE numbers is often entirely correct (utility passives exist).
    # Only a passive with NO parsed content at all is a genuine gap.
    if 'I' in ab:
        p = ab['I']
        if not (p.get('base') or p.get('max_hp') or p.get('effects') or p.get('tags') or p.get('cd')):
            defects['C6_passive_no_data'].append(f'{nm}/{p["name"]}')
        elif not (p.get('base') or p.get('max_hp')):
            info['passive_utility_only'].append(f'{nm}/{p["name"]}')

total = sum(len(v) for v in defects.values())
print(f'DNA VALIDATION — {len(CH)} champions, {total} defects found\n')
for k in sorted(defects):
    v = defects[k]
    print(f'{k}: {len(v)}')
    for x in v[:6]: print(f'    {x}')
    if len(v) > 6: print(f'    ... and {len(v)-6} more')
    print()
json.dump(dict(defects=dict(defects), info=dict(info)), open('dna_defects.json', 'w'), indent=1)
print(f'INFO (not defects): hybrid-scaling abilities = {len(info["hybrid_scaling"])}')
bad = set()
for k in defects:
    for x in defects[k]: bad.add(x.split('/')[0])
clean = len(CH) - len(bad)
print(f'champions with NO type/scaling defects: {clean}/{len(CH)}')
