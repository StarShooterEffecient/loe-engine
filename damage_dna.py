"""LOE v2 — DAMAGE DNA (Module:DamageData/data).
The wiki states, for EVERY damage instance in the game (champion abilities, item passives, runes),
its authoritative damage type AND its behavioural properties:

    ApplyLifesteal / ApplyOmnivamp     - does this damage sustain the attacker?
    TriggerOnHitEvents                 - does it proc on-hit items (Kraken, BotRK, Wit's End)?
    CanCrit / RespectDodge/Immunity    - how it resolves
    tags: BasicAttack / ActiveSpell / Proc / AOE / Periodic / Item

v1 guessed all of this from prose. v2 reads it. This is what makes an honest combat model possible:
we no longer have to assume which damage sources proc which items — the wiki tells us.

Also acts as a THIRD authority on damage TYPE, cross-validated against the ability templates.
Output: damage_dna.json + a conflict report (never silently reconciled).
"""
import re, json, sqlite3

cx = sqlite3.connect('wiki.db'); C = cx.cursor()
DD = C.execute("SELECT text FROM pages WHERE title='Module:DamageData/data'").fetchone()[0]

def lua_flags(body):
    return {k: (v == 'true') for k, v in re.findall(r'\["(\w+)"\]\s*=\s*(true|false)', body)}

# 1. resolve PropertyTemplate_* and TagTemplate_* definitions
PROPS, TAGS = {}, {}
for m in re.finditer(r'local (PropertyTemplate_\w+)\s*=\s*\{(.*?)\n\}', DD, re.S):
    PROPS[m.group(1)] = lua_flags(m.group(2))
for m in re.finditer(r'local (TagTemplate_\w+)\s*=\s*\{(.*?)\n\}', DD, re.S):
    TAGS[m.group(1)] = lua_flags(m.group(2))
# some templates are defined by extending another: Prop_X = { ...Prop_Y, extra }
for m in re.finditer(r'local (PropertyTemplate_\w+)\s*=\s*\{[^{}]*?(PropertyTemplate_\w+)', DD, re.S):
    child, parent = m.group(1), m.group(2)
    if parent in PROPS:
        merged = dict(PROPS[parent]); merged.update(PROPS.get(child, {})); PROPS[child] = merged

# 2. DamageTemplate_X -> (properties, tags)
DTPL = {}
for m in re.finditer(r'local (DamageTemplate_\w+)\s*=\s*\{\s*\["properties"\]\s*=\s*(\w+),\s*\["tags"\]\s*=\s*(\w+),?\s*\}', DD, re.S):
    name, p, t = m.group(1), m.group(2), m.group(3)
    DTPL[name] = dict(properties=PROPS.get(p, {}), tags=TAGS.get(t, {}))
print(f'property templates {len(PROPS)} | tag templates {len(TAGS)} | damage templates {len(DTPL)}')

# 3. walk the champions / items / runes sections
def section(name):
    m = re.search(r'\n  \["' + name + r'"\]\s*=\s*\{', DD)
    if not m: return ''
    i = m.end(); dep = 1; j = i
    while dep > 0 and j < len(DD):
        if DD[j] == '{': dep += 1
        elif DD[j] == '}': dep -= 1
        j += 1
    return DD[i:j]

def parse_owner_block(text, ind='    '):
    """owner -> ability/effect -> instance -> {damageType, damageInfo}"""
    out = {}
    for m in re.finditer(r'\n' + ind + r'\["([^"]+)"\]\s*=\s*\{', text):
        owner = m.group(1); i = m.end(); dep = 1; j = i
        while dep > 0 and j < len(text):
            if text[j] == '{': dep += 1
            elif text[j] == '}': dep -= 1
            j += 1
        body = text[i:j]
        abilities = {}
        for am in re.finditer(r'\n' + ind + '  ' + r'\["([^"]+)"\]\s*=\s*\{', body):
            ab = am.group(1); i2 = am.end(); d2 = 1; j2 = i2
            while d2 > 0 and j2 < len(body):
                if body[j2] == '{': d2 += 1
                elif body[j2] == '}': d2 -= 1
                j2 += 1
            abody = body[i2:j2]
            instances = {}
            for im in re.finditer(r'\n' + ind + '    ' + r'\["([^"]+)"\]\s*=\s*\{(.*?)\n' + ind + '    ' + r'\},', abody, re.S):
                inst, ibody = im.group(1), im.group(2)
                dtype = (re.search(r'\["damageType"\]\s*=\s*DamageType_(\w+)', ibody) or [0, None])[1]
                dinfo = (re.search(r'\["damageInfo"\]\s*=\s*(DamageTemplate_\w+)', ibody) or [0, None])[1]
                if not dtype and not dinfo: continue
                tpl = DTPL.get(dinfo, {})
                p, t = tpl.get('properties', {}), tpl.get('tags', {})
                instances[inst] = dict(
                    type=dtype, template=dinfo,
                    lifesteal=p.get('ApplyLifesteal', False), omnivamp=p.get('ApplyOmnivamp', False),
                    triggers_onhit=p.get('TriggerOnHitEvents', False),
                    can_crit=p.get('CanCrit', p.get('RespectCrit', False)),
                    basic_attack=t.get('BasicAttack', False), active_spell=t.get('ActiveSpell', False),
                    proc=t.get('Proc', False), aoe=t.get('AOE', False), periodic=t.get('Periodic', False))
            if instances: abilities[ab] = instances
        if abilities: out[owner] = abilities
    return out

def parse_flat(text):
    """items/runes: owner -> instance -> {damageType, damageInfo} (one level shallower)."""
    out = {}
    for m in re.finditer(r'\n    \["([^"]+)"\]\s*=\s*\{', text):
        owner = m.group(1); i = m.end(); dep = 1; j = i
        while dep > 0 and j < len(text):
            if text[j] == '{': dep += 1
            elif text[j] == '}': dep -= 1
            j += 1
        body = text[i:j]
        inst = {}
        for im in re.finditer(r'\["([^"]+)"\]\s*=\s*\{([^{}]*?\["damage(?:Type|Info)"\][^{}]*?)\}', body, re.S):
            nm2, ib = im.group(1), im.group(2)
            dtype = (re.search(r'\["damageType"\]\s*=\s*DamageType_(\w+)', ib) or [0, None])[1]
            dinfo = (re.search(r'\["damageInfo"\]\s*=\s*(DamageTemplate_\w+)', ib) or [0, None])[1]
            if not (dtype or dinfo): continue
            tpl = DTPL.get(dinfo, {}); p = tpl.get('properties', {}); t = tpl.get('tags', {})
            inst[nm2] = dict(type=dtype, template=dinfo,
                             lifesteal=p.get('ApplyLifesteal', False), omnivamp=p.get('ApplyOmnivamp', False),
                             triggers_onhit=p.get('TriggerOnHitEvents', False),
                             can_crit=p.get('CanCrit', p.get('RespectCrit', False)),
                             basic_attack=t.get('BasicAttack', False), active_spell=t.get('ActiveSpell', False),
                             proc=t.get('Proc', False), aoe=t.get('AOE', False), periodic=t.get('Periodic', False))
        if inst: out[owner] = inst
    return out

CHAMP_DMG = parse_owner_block(section('champions'))
ITEM_DMG = parse_owner_block(section('items')) or parse_flat(section('items'))
RUNE_DMG = parse_owner_block(section('runes')) or parse_flat(section('runes'))
json.dump(dict(champions=CHAMP_DMG, items=ITEM_DMG, runes=RUNE_DMG, templates=DTPL),
          open('damage_dna.json', 'w'), indent=0)
n_inst = sum(len(v) for a in CHAMP_DMG.values() for v in a.values())
print(f'champions with damage data: {len(CHAMP_DMG)} ({n_inst} damage instances)')
print(f'items with damage data: {len(ITEM_DMG)} | runes: {len(RUNE_DMG)}')

# 4. CROSS-VALIDATE damage types against the ability-template parse (third authority)
CH = json.load(open('champion_dna.json'))
agree = conflict = 0; conflicts = []
for nm, c in CH.items():
    dmap = CHAMP_DMG.get(nm, {})
    for slot, a in c['abilities'].items():
        inst = dmap.get(a['name'])
        if not inst or not a.get('dtype'): continue
        auth = {i['type'] for i in inst.values() if i['type']}
        mine = a['dtype'].split('/')[0].strip().capitalize()
        if not auth: continue
        if mine in auth: agree += 1
        else:
            conflict += 1
            conflicts.append((nm, slot, a['name'], mine, sorted(auth)))
print(f'\nDAMAGE-TYPE CROSS-VALIDATION vs ability templates: AGREE {agree} | CONFLICT {conflict}')
for c in conflicts[:10]:
    print(f'   {c[0]}/{c[1]} {c[2]}: templates said {c[3]}, DamageData says {c[4]}')
json.dump(conflicts, open('damage_conflicts.json', 'w'), indent=1)

# 5. what triggers on-hit? (the question v1 could never answer)
onhit_ab = [(nm, ab) for nm, m in CHAMP_DMG.items() for ab, ins in m.items()
            if any(i['triggers_onhit'] for i in ins.values())]
print(f'\nability damage instances that TRIGGER ON-HIT EVENTS: {len(onhit_ab)}')
print('   e.g.', onhit_ab[:6])
