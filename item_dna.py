"""LOE v2 — ITEM DNA.
Everything v1 had to guess at is stated explicitly in Module:ItemData:
  - modes["classic sr 5v5"]  -> SR legality, from the source (v1 reverse-engineered this)
  - tags                     -> HasOnHit / Lifeline / SpellBlade... mechanical identity, free
  - type/tier                -> Legendary vs Boots vs Consumable
  - buy + recipe             -> gold cost and build path (v1 had NO gold data at all)
  - effects.pass/act         -> named passives and actives with full description text
Each passive is classified into a TRIGGER (what fires it) and an EFFECT (what it does), so the
optimizer can reason about item behaviour instead of only raw stats.
Output: item_dna.json
"""
import re, json, sqlite3

cx = sqlite3.connect('wiki.db'); C = cx.cursor()
LUA = C.execute("SELECT text FROM pages WHERE title='Module:ItemData/data'").fetchone()[0]
try:
    GOLD = C.execute("SELECT text FROM pages WHERE title='Module:Gold value/data'").fetchone()[0]
except Exception:
    GOLD = ''

# ---- gold value per stat point (the wiki's own reference table) ----
gold_per = {}
for k, v in re.findall(r'\["(\w+)"\]\s*=\s*\{\s*\["val"\]\s*=\s*([\d.]+)', GOLD):
    gold_per[k] = float(v)

def blocks(lua):
    """Yield (name, body) for every top-level item entry."""
    for m in re.finditer(r'\n\s*\["([^"]+)"\]\s*=\s*\{', lua):
        if lua[:m.start()].count('{') - lua[:m.start()].count('}') != 1: continue
        nm = m.group(1); i = m.end(); dep = 1; j = i
        while dep > 0 and j < len(lua):
            if lua[j] == '{': dep += 1
            elif lua[j] == '}': dep -= 1
            j += 1
        yield nm, lua[i:j]

# ---- trigger / effect classification for passives ----
TRIGGERS = [
 ('ON_HIT',        r'\bon-hit\b|basic attacks?\b.{0,40}\bdeal'),
 ('ON_ABILITY',    r'dealing\s*(?:\[\[)?ability damage|damaging (?:ability|spell)|after (?:using|casting) an ability|'
                   r'ability hit|with a champion ability|ability damage to'),
 ('ON_CRIT',       r'critical strike'),
 ('ON_TAKEDOWN',   r'takedown|kill(?:s|ing)? (?:an )?enem'),
 ('ON_IMMOBILIZE', r'immobilis|immobiliz'),
 ('ON_LOW_HEALTH', r'(?:below|under) \d+%.{0,20}health|lifeline'),
 ('PERIODIC',      r'every \d+|periodically|per second'),
 ('AURA',          r'nearby (?:allies|enemies)|aura'),
 ('ALWAYS',        r'.'),
]
EFFECTS = [
 ('PCT_MAX_HP_DMG', r'%[^.]{0,40}(?:maximum|max)[^a-z]{0,8}health', 'damage'),
 ('PCT_CUR_HP_DMG', r'%[^.]{0,40}current[^a-z]{0,8}health', 'damage'),
 ('MISSING_HP_AMP', r'missing[^a-z]{0,8}health'),
 ('FLAT_DAMAGE',    r'bonus (?:physical|magic|true) damage'),
 ('BURN',           r'burn|over \d+ seconds'),
 ('SHIELD',         r'\bshield'),
 ('HEAL',           r'\bheal|life ?steal|omnivamp'),
 ('SHRED',          r'reduc\w+ (?:their |the )?(?:armor|magic resist)|armor reduction'),
 ('PEN',            r'penetrat'),
 ('STAT_GAIN',      r'gain\w*\s+(?:\{\{[^}]*\}\}\s*)?\d|grants?\s+\d'),
 ('SLOW',           r'\bslow'),
 ('CDR_REFUND',     r'cooldown.{0,30}(?:reduc|refund)|refund\w*.{0,20}cooldown'),
]
def classify(desc):
    d = desc.lower()
    trig = next(t for t, rx in TRIGGERS if re.search(rx, d))
    effs = [e for e, rx, *_ in EFFECTS if re.search(rx, d)]
    return trig, effs

RD = re.compile(r'\{\{rd\|\s*([\d.]+)\s*\+\s*\(\s*([\d.]+)\s*-\s*[\d.]+\s*\)')   # {{rd|150 + (200-150)/10*(x-1)...}}
PP = re.compile(r'\{\{pp\|([\d.]+)\s*to\s*([\d.]+)')                                      # {{pp|0 to 75 by 5|...}}
AP = re.compile(r'\{\{ap\|([\d.]+)(?:\s*to\s*([\d.]+))?')

def numeric(desc):
    """Mine the wiki's own formula templates for the passive's real numbers (level-scaled ranges)."""
    out = dict(dmg_lo=0.0, dmg_hi=0.0, amp_lo=0.0, amp_hi=0.0)
    m = RD.search(desc)
    if m:
        out['dmg_lo'] = float(m.group(1)); out['dmg_hi'] = float(m.group(2))
    else:
        m = AP.search(desc)
        if m and re.search(r'damage', desc, re.I):
            out['dmg_lo'] = float(m.group(1)); out['dmg_hi'] = float(m.group(2) or m.group(1))
    p = PP.search(desc)
    if p:
        out['amp_lo'] = float(p.group(1)) / 100.0; out['amp_hi'] = float(p.group(2)) / 100.0
    return out

COND = re.compile(r'(?:at or (?:below|above)|below|above|less than|greater than|under|over|'
                  r'if|when|while|reaching|drops? to|health is)\s*$', re.I)

def pct_first(desc, rx):
    """Return a %-health DAMAGE ratio — never a CONDITION threshold."""
    for m in re.finditer(rx, desc, re.I):
        pre = desc[max(0, m.start() - 40):m.start()]
        pre_clean = re.sub(r'\{\{[^}]*\||\}\}|\[\[|\]\]|\'{2,}', ' ', pre).strip()
        if COND.search(pre_clean):
            continue                                    # threshold, not damage
        if not re.search(r'deal|damage|dealt|inflict|strike', desc[:m.start()], re.I):
            continue                                    # no damage verb -> not a payload
        return float(m.group(1)) / 100.0
    return 0.0

ITEMS = {}
for nm, b in blocks(LUA):
    if '["stats"]' not in b and '["effects"]' not in b: continue
    g = lambda k: (re.search(r'\["' + k + r'"\]\s*=\s*(-?[\d.]+)', b) or [0, None])[1]
    stats = {}
    sm = re.search(r'\["stats"\]\s*=\s*\{(.*?)\n\s*\}', b, re.S)
    if sm:
        stats = {k: float(v) for k, v in re.findall(r'\["(\w+)"\]\s*=\s*(-?[\d.]+)', sm.group(1))}
    modes = {k: (v == 'true') for k, v in re.findall(r'\["([^"]+)"\]\s*=\s*(true|false)',
             (re.search(r'\["modes"\]\s*=\s*\{(.*?)\n\s*\}', b, re.S) or [0, ''])[1])}
    types = re.findall(r'"([^"]+)"', (re.search(r'\["type"\]\s*=\s*\{([^}]*)\}', b) or [0, ''])[1])
    tags = re.findall(r'"([^"]+)"', (re.search(r'\["tags"\]\s*=\s*\{([^}]*)\}', b) or [0, ''])[1])
    menu = list(re.findall(r'\["(\w+)"\]\s*=\s*true', (re.search(r'\["menu"\]\s*=\s*\{(.*?)\n\s*\}', b, re.S) or [0, ''])[1]))
    recipe = re.findall(r'"([^"]+)"', (re.search(r'\["recipe"\]\s*=\s*\{([^}]*)\}', b) or [0, ''])[1])
    buy = float(g('buy') or 0)
    removed = bool(re.search(r'\["removed"\]\s*=\s*true', b))
    effs = []
    for kind in ('pass', 'pass2', 'pass3', 'act', 'act2'):
        em = re.search(r'\["' + kind + r'"\]\s*=\s*\{(.*?)\n\s*\},', b, re.S)
        if not em: continue
        body = em.group(1)
        name = (re.search(r'\["name"\]\s*=\s*"([^"]*)"', body) or [0, ''])[1]
        desc = (re.search(r'\["description"\]\s*=\s*"(.*)"', body, re.S) or [0, ''])[1]
        if not desc: continue
        trig, elist = classify(desc)
        effs.append(dict(slot=kind, name=name, kind='ACTIVE' if kind.startswith('act') else 'PASSIVE',
                         unique=bool(re.search(r'\["unique"\]\s*=\s*true', body)),
                         trigger=trig, effects=elist,
                         pct_max_hp=pct_first(desc, r'([\d.]+)\s*%[^.]{0,40}(?:maximum|max)[^a-z]{0,8}health'),
                         pct_cur_hp=pct_first(desc, r'([\d.]+)\s*%[^.]{0,40}current[^a-z]{0,8}health'),
                         icd=float((re.search(r'(\d+(?:\.\d+)?)\s*second cooldown', desc) or [0, 0])[1]),
                         **numeric(desc),
                         raw=desc,
                         text=re.sub(r'\{\{[^{}]*\}\}|\[\[|\]\]|\'{2,}', '', desc)[:300]))
    # gold efficiency from the wiki's own stat-gold table
    gold_worth = sum(stats.get(k, 0) * v for k, v in gold_per.items() if k in stats)
    ITEMS[nm] = dict(id=int(float(g('id') or 0)), tier=int(float(g('tier') or 0)), types=types, tags=tags,
                     menu=menu, stats=stats, modes=modes, sr=modes.get('classic sr 5v5'),
                     buy=buy, recipe=recipe, removed=removed, effects=effs,
                     gold_stat_value=round(gold_worth, 1),
                     gold_efficiency=round(gold_worth / buy, 3) if buy else None)

json.dump(ITEMS, open('item_dna.json', 'w'), indent=0)

sr_leg = [n for n, d in ITEMS.items() if d['sr'] and 'Legendary' in d['types'] and not d['removed']]
boots = [n for n, d in ITEMS.items() if d['sr'] and 'Boots' in d['types'] and not d['removed'] and d['tier'] >= 2]
withpass = [n for n in sr_leg if ITEMS[n]['effects']]
print(f'items parsed: {len(ITEMS)}')
print(f'SR-legal LEGENDARIES: {len(sr_leg)}  |  SR boots (tier>=2): {len(boots)}')
print(f'  ...of which carry a passive/active: {len(withpass)}')
print(f'gold data: {sum(1 for n in sr_leg if ITEMS[n]["buy"])} items priced | stat-gold table entries: {len(gold_per)}')
from collections import Counter
print('trigger distribution:', Counter(e["trigger"] for n in sr_leg for e in ITEMS[n]["effects"]).most_common(6))
k = ITEMS['Kraken Slayer']
print('\nKraken Slayer DNA:', {kk: k[kk] for kk in ('stats','tags','buy','gold_efficiency')})
print('  effects:', k['effects'][:1])
