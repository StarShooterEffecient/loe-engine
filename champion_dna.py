"""LOE v2 — CHAMPION DNA.
Two things v1 could not do, both fixed here:

1. ROSTER GATE (the Aatrox fix). A champion's ability slots may ONLY be filled by templates whose
   names appear in Module:ChampionData's CURRENT skill roster (skill_i/q/w/e/r). Dead pre-rework
   templates are structurally excluded — not heuristically avoided.

2. WIKI VARIABLE RESOLUTION (the accuracy fix). Ability templates define values as
   {{#vardefine:b1|10}} and reference them as {{#var:b1}}, sometimes inside {{#expr:}} arithmetic.
   v1 discarded every such ability as "unparseable" (Garen's Judgment, Aatrox's Q...). v2 resolves
   the variables and evaluates the expressions, so the numbers are read exactly as the wiki states them.

Output: champion_dna.json — base stats + growth + resource + range + per-slot abilities, each with
base damage (rank 1..5), AP / total-AD / bonus-AD / max-HP / missing-HP ratios, damage type,
cooldown, cost, cast time, and mechanical tags. Coverage is recorded per champion and never hidden.
"""
import re, json, sqlite3, math

cx = sqlite3.connect('wiki.db'); C = cx.cursor()
CD = C.execute("SELECT text FROM pages WHERE title='Module:ChampionData/data'").fetchone()[0]

# ---------------------------------------------------------------- wiki markup evaluator
def resolve_vars(text):
    """Resolve {{#vardefine:k|v}} -> {{#var:k}} references, then evaluate {{#expr:...}}."""
    vars_ = {}
    for k, v in re.findall(r'\{\{#vardefine:\s*([^|]+?)\s*\|\s*([^}]*?)\s*\}\}', text):
        vars_[k.strip()] = v.strip()
    # iterative substitution (vars can reference vars)
    for _ in range(4):
        changed = False
        def sub_var(m):
            nonlocal changed
            k = m.group(1).strip()
            if k in vars_: changed = True; return vars_[k]
            return m.group(0)
        text = re.sub(r'\{\{#var:\s*([^}|]+?)\s*\}\}', sub_var, text)
        for k in list(vars_):
            new = re.sub(r'\{\{#var:\s*([^}|]+?)\s*\}\}',
                         lambda m: vars_.get(m.group(1).strip(), m.group(0)), vars_[k])
            if new != vars_[k]: vars_[k] = new; changed = True
        if not changed: break
    # evaluate {{#expr: ... }} (innermost first)
    def eval_expr(m):
        e = m.group(1).strip()
        e = e.replace('&#42;', '*').replace('&minus;', '-')
        if not re.fullmatch(r'[\d\s+\-*/().,round]*', e): return m.group(0)
        try:
            e2 = re.sub(r'round\s*(\d+)', r'', e)
            v = eval(e2, {'__builtins__': {}}, {})
            return str(round(v, 4)) if isinstance(v, float) else str(v)
        except Exception:
            return m.group(0)
    for _ in range(3):
        new = re.sub(r'\{\{#expr:([^{}]*?)\}\}', eval_expr, text)
        if new == text: break
        text = new
    return text

def field(t, name):
    m = re.search(r'\|\s*' + re.escape(name) + r'\s*=\s*(.*?)(?=\n\s*\|[a-zA-Z0-9_][a-zA-Z0-9_ ]*=|\n\}\}|\Z)', t, re.S)
    return m.group(1).strip() if m else ''

def rank_values(s):
    """5 rank values from {{ap|...}}, {{pplevel|...}} or a bare 'a to b' span (linear interp)."""
    m = re.search(r'\{\{(?:ap|pplevel|fd)\|([^}]+)\}\}', s)
    body = m.group(1) if m else s
    body = re.sub(r'key\s*=\s*[^|]*\|?', '', body)   # pplevel carries key=% metadata
    to = re.match(r'\s*([\d.]+)\s*to\s*([\d.]+)\s*$', body)
    if to:
        a, b = float(to.group(1)), float(to.group(2))
        return [round(a + (b - a) * i / 4, 2) for i in range(5)]
    parts = [p.strip().rstrip('%') for p in body.split('|')]
    vals = [float(p) for p in parts if re.fullmatch(r'[\d.]+', p)]
    if not vals: return None
    if len(vals) == 1: return [vals[0]] * 5
    return (vals + [vals[-1]] * 5)[:5]

R_AP  = re.compile(r'\+\s*(?:\{\{ap\|)?([\d.]+)(?:\s*to\s*([\d.]+))?[^)]{0,25}?%\s*\}*\s*(?:AP\b|ability power)', re.I)
R_ADB = re.compile(r'\+\s*(?:\{\{ap\|)?([\d.]+)(?:\s*to\s*([\d.]+))?[^)]{0,10}?%\s*\}*\s*(?:\'{2,3})?bonus(?:\'{2,3})?\s*AD', re.I)
R_ADT = re.compile(r'\+\s*(?:\{\{ap\|)?([\d.]+)(?:\s*to\s*([\d.]+))?[^)]{0,10}?%\s*\}*\s*(?:(?:\'{2,3})?total(?:\'{2,3})?\s*)?AD\b', re.I)
R_HP_A  = re.compile(r'\{\{(?:pplevel|ap)\|(?:key=%\|)?([\d.]+)(?:\s*to\s*([\d.]+))?\}\}[^.]{0,70}?(?:maximum|max)[^a-zA-Z]{0,10}health', re.I)
R_HP_B  = re.compile(r'([\d.]+)(?:\s*to\s*([\d.]+))?\s*%[^.)]{0,50}?(?:maximum|max)[^a-zA-Z]{0,10}health', re.I)
R_MHP_A = re.compile(r'\{\{(?:pplevel|ap)\|(?:key=%\|)?([\d.]+)(?:\s*to\s*([\d.]+))?\}\}[^.]{0,70}?missing[^a-zA-Z]{0,10}health', re.I)
R_MHP_B = re.compile(r'([\d.]+)(?:\s*to\s*([\d.]+))?\s*%[^.)]{0,50}?missing[^a-zA-Z]{0,10}health', re.I)

def pct_health(s, missing=False, rank=5):
    """Percent-health ratio at the given ability rank (default 5), under either wiki encoding."""
    tot = 0.0
    for rx in ((R_MHP_A, R_MHP_B) if missing else (R_HP_A, R_HP_B)):
        for m in rx.finditer(s):
            a = float(m.group(1)); b = float(m.group(2)) if m.group(2) else a
            tot += (a + (b - a) * (rank - 1) / 4.0) / 100.0
        if tot: break          # encoding A wins if present; never double-count
    return round(tot, 4)

def ratio_sum(rx, s, rank=5):
    """Ratios scale by ability rank ('{{ap|60 to 100}}% total AD'). v1/earlier-v2 averaged the
    span and silently understated every kit's late-game scaling. We evaluate at the given rank
    (default 5 = maxed) — the same convention as base damage, so the two are consistent."""
    tot = 0.0
    for m in rx.finditer(s):
        a = float(m.group(1)); b = float(m.group(2)) if m.lastindex >= 2 and m.group(2) else a
        v = a + (b - a) * (rank - 1) / 4.0
        tot += v / 100.0
    return round(tot, 4)

AMP_RX = {
 'ad':    re.compile(r'\b(?:bonus\s+)?attack damage\b', re.I),
 'ap':    re.compile(r'\babilit(?:y|ies) power\b', re.I),
 'as':    re.compile(r'\battack speed\b', re.I),
 'ah':    re.compile(r'\babilit(?:y|ies) haste\b', re.I),
 'ms':    re.compile(r'\bmovement speed\b', re.I),
 'armor': re.compile(r'\barmor\b', re.I),
 'mr':    re.compile(r'\bmagic resist', re.I),
 'omni':  re.compile(r'\bomnivamp|life ?steal|physical vamp', re.I),
 'heal_amp': re.compile(r'\bheal(?:ing)? (?:and shield )?power|increased healing', re.I),
}

def st_pairs(lev):
    """Split every {{st|Label|Values|Label2|Values2...}} into (label, values) PAIRS.
    The wiki packs alternative forms as extra pipe-args inside ONE template; naive regex
    capture merged them and double-counted every ratio (Pantheon Q read 6.9x bonus AD)."""
    out = []
    for m in re.finditer(r'\{\{st\|', lev):
        i = m.end(); dep = 2; j = i          # we are inside {{ }}
        while j < len(lev) and dep > 0:
            if lev.startswith('{{', j): dep += 2; j += 2; continue
            if lev.startswith('}}', j):
                dep -= 2; j += 2
                if dep == 0: break
                continue
            j += 1
        body = lev[i:j-2]
        # split on TOP-LEVEL pipes only
        parts, depth, cur = [], 0, ''
        for ch in body:
            if ch == '{': depth += 1
            elif ch == '}': depth -= 1
            if ch == '|' and depth == 0:
                parts.append(cur); cur = ''
            else:
                cur += ch
        parts.append(cur)
        for k in range(0, len(parts) - 1, 2):
            out.append((parts[k].strip(), parts[k + 1].strip()))
    return out

ALT_RX = re.compile(r'\s*(increased|empowered|total|max|maximum|sweetspot|critical|enhanced)\b', re.I)
def _agg(effects, key):
    """Sum genuine components; take MAX across alternative forms (they cannot co-occur)."""
    dmg = [e for e in effects if e['kind'] == 'DAMAGE']
    base = sum(e[key] for e in dmg if not ALT_RX.match(e['label']))
    alts = [e[key] for e in dmg if ALT_RX.match(e['label'])]
    return max([base] + alts) if alts else base

AMP_LABEL = re.compile(r'(?:total|bonus)?\s*(?:attack damage|ability power|attack speed|ability haste|'
                       r'armor|magic resist(?:ance)?|resistances|adaptive force|movement speed|'
                       r'lethality|armor penetration|magic penetration|omnivamp|life ?steal|'
                       r'critical strike|heal(?:ing)? (?:and shield )?power)\s*$', re.I)
def classify(label, body):
    l = label.strip().lower()
    # A label naming a STAT is a self-buff (amp), even though 'Attack Damage' contains 'damage'.
    if AMP_LABEL.match(l): return 'AMP'
    if 'damage' in l: return 'DAMAGE'
    if 'heal' in l or 'lifesteal' in l or 'omnivamp' in l: return 'SUSTAIN'
    if 'shield' in l: return 'SHIELD'
    if any(k in l for k in ('movement speed','dash','range')): return 'MOBILITY'
    if any(k in l for k in ('attack damage','ability power','attack speed','ability haste','armor','magic resist','resistances')): return 'AMP'
    if any(k in l for k in ('duration','slow','stun','root')): return 'CC'
    return 'OTHER'

TAGS = [('on_hit', r'on-hit'), ('execute', r'\bexecute'), ('reset', r'reset|refresh'),
        ('dash', r'\bdash|\bblink|leap'), ('shield', r'\bshield'), ('heal', r'heal'),
        ('cc', r'stun|root|snare|slow|knock|charm|fear|taunt|airborne|suppress'),
        ('dot', r'per second|every \d+\.?\d* seconds|damage over time|burn')]

# ---------------------------------------------------------------- champion registry
def parse_champions(lua):
    out = {}
    for m in re.finditer(r'\n\s*\["([^"]+)"\]\s*=\s*\{', lua):
        if lua[:m.start()].count('{') - lua[:m.start()].count('}') != 1: continue
        nm = m.group(1); i = m.end(); dep = 1; j = i
        while dep > 0 and j < len(lua):
            if lua[j] == '{': dep += 1
            elif lua[j] == '}': dep -= 1
            j += 1
        body = lua[i:j]
        g = lambda k, d=0.0: float((re.search(r'\["' + k + r'"\]\s*=\s*(-?[\d.]+)', body) or [0, d])[1])
        gs = lambda k, d='': (re.search(r'\["' + k + r'"\]\s*=\s*"([^"]*)"', body) or [0, d])[1]
        if not g('hp_base'): continue
        roster = {}
        for slot in ('i', 'q', 'w', 'e', 'r'):
            mm = re.search(r'\["skill_' + slot + r'"\]\s*=\s*\{([^}]*)\}', body)
            if mm: roster[slot.upper()] = re.findall(r'"([^"]+)"', mm.group(1))
        out[nm] = dict(
            id=int(g('id')), apiname=gs('apiname'), resource=gs('resource') or 'None',
            herotype=gs('herotype'), alttype=gs('alttype'), rangetype=gs('rangetype'),
            roles=re.findall(r'"([^"]+)"', (re.search(r'\["role"\]\s*=\s*\{([^}]*)\}', body) or [0, ''])[1]),
            stats=dict(
                hp=g('hp_base'), hp_lvl=g('hp_lvl'), mp=g('mp_base'), mp_lvl=g('mp_lvl'),
                armor=g('arm_base'), armor_lvl=g('arm_lvl'), mr=g('mr_base'), mr_lvl=g('mr_lvl'),
                ad=g('dam_base'), ad_lvl=g('dam_lvl'), as_base=g('as_base'), as_lvl=g('as_lvl'),
                as_ratio=g('as_ratio') or g('as_base'), hp5=g('hp5_base'), hp5_lvl=g('hp5_lvl'),
                mp5=g('mp5_base'), mp5_lvl=g('mp5_lvl'), ms=g('ms'), range=g('range'),
                attack_cast_time=g('attack_cast_time'), attack_total_time=g('attack_total_time')),
            ratings=dict(damage=g('damage'), toughness=g('toughness'),
                         control=g('control'), mobility=g('mobility')),
            roster=roster)
    return out

CHAMPS = parse_champions(CD)

# --- second authority: the wiki's own slot redirects (Template:Data X/Q -> the current ability) ---
REDIR = {}
for title, body in C.execute("SELECT title, text FROM pages WHERE title LIKE 'Template:Data %/_'"):
    m = re.search(r'#REDIRECT\s*\[\[Template:Data ([^/]+)/([^\]]+)\]\]', body, re.I)
    if m:
        champ, slot = title.replace('Template:Data ', '').rsplit('/', 1)
        REDIR[(champ, slot.upper())] = m.group(2).strip().replace('_', ' ')
print(f'champions in ChampionData: {len(CHAMPS)} | slot redirects: {len(REDIR)}')

confirm = dict(agree=0, added=0, conflict=0)
for nm, ch in CHAMPS.items():
    for pre in (nm, nm.split(' & ')[0], ch.get('apiname', '')):
        if any(k[0] == pre for k in REDIR): break
    for slot in ('I', 'Q', 'W', 'E', 'R'):
        r = REDIR.get((pre, slot))
        if not r: continue
        roster = ch['roster'].get(slot, [])
        if r in roster: confirm['agree'] += 1
        elif any(r in x or x in r for x in roster): confirm['agree'] += 1     # formatting variance only
        elif roster: confirm['conflict'] += 1
        else:
            ch['roster'][slot] = [r]; confirm['added'] += 1                    # redirect fills a gap
print(f"ROSTER CROSS-CHECK (two independent wiki authorities): confirmed {confirm['agree']} | "
      f"filled by redirect {confirm['added']} | conflicts {confirm['conflict']}")

# ---------------------------------------------------------------- ability ingestion (ROSTER-GATED)
pages = {t: x for t, x in C.execute("SELECT title, text FROM pages WHERE kind='ability'")}
stats_cov = dict(gated_out=0, parsed=0, no_template=0)
def tpl_prefixes(nm, apiname):
    """The wiki files ability templates under a SHORT name; ChampionData uses the display name.
    ('Nunu & Willump' -> 'Nunu', 'Kled & Skaarl' -> 'Kled', 'Renata Glasc' -> 'Renata Glasc'...)"""
    cands = [nm, nm.split(' & ')[0], apiname]
    if nm == 'Wukong': cands.append('Wukong')
    return [c for c in dict.fromkeys(cands) if c]

for nm, ch in CHAMPS.items():
    abils = {}
    prefixes = tpl_prefixes(nm, ch.get('apiname', ''))
    for slot, names in ch['roster'].items():
        best = None
        for aname in names:                      # ONLY names the current roster authorizes
            raw = None
            for pre in prefixes:
                raw = pages.get(f'Template:Data {pre}/{aname}')
                if raw: break
            if not raw: continue
            t = resolve_vars(raw)
            lev = ' '.join(re.findall(r'\|\s*leveling\d*\s*=\s*(.*?)(?=\n\s*\|[a-zA-Z]|\n\}\})', t, re.S))
            dmg_lines = ' '.join(seg for seg in re.findall(r'\{\{st\|([^|]*)\|(.*?)(?=\{\{st\||$)', lev, re.S)
                                 for seg in [seg[1]] if 'damage' in seg[0].lower() or True) if lev else ''
            desc_all = field(t, 'description') + ' ' + field(t, 'description2')
            base = None; effects = []; amps = {}
            for label, body in st_pairs(lev):
                kind = classify(label, body); rv = rank_values(body)
                if rv: effects.append(dict(kind=kind, label=label.strip(), values=rv,
                                           ap=ratio_sum(R_AP, body), ad_bonus=ratio_sum(R_ADB, body),
                                           ad_total=max(0.0, ratio_sum(R_ADT, body) - ratio_sum(R_ADB, body)),
                                           max_hp=pct_health(body), missing_hp=pct_health(body, True)))
                if kind == 'DAMAGE' and rv:
                    # 'Increased/Empowered/Total/Max/Sweetspot' lines are ALTERNATIVE forms of the same
                    # application, not extra damage — summing them invents damage that cannot co-occur.
                    alt = re.match(r'\s*(increased|empowered|total|max|maximum|sweetspot|critical|enhanced)\b',
                                   label, re.I)
                    if alt or base is None:
                        base = rv if base is None else [max(x, y) for x, y in zip(base, rv)]
                    else:
                        base = [x + y for x, y in zip(base, rv)]
                if kind == 'AMP' and rv:
                    is_pct = '%' in body
                    for stat, rx in AMP_RX.items():
                        if rx.search(label):
                            amps[stat] = dict(values=rv, pct=is_pct); break
            # innate/passive damage is stated in the DESCRIPTION, not a leveling block
            if slot == 'I' and base is None:
                # innate damage lives in prose: '{{ap|X to Y}} ... damage' or a %-health scaling
                dm = re.search(r'\{\{(?:ap|pplevel)\|(?:key=[^|]*\|)?([\d.]+)\s*to\s*([\d.]+)\}\}[^.]{0,60}?damage', desc_all, re.I)
                if dm:
                    a1, b1 = float(dm.group(1)), float(dm.group(2))
                    base = [round(a1 + (b1 - a1) * i / 4, 1) for i in range(5)]
                    effects.append(dict(kind='DAMAGE', label='innate damage', values=base,
                                        ap=ratio_sum(R_AP, desc_all), ad_bonus=ratio_sum(R_ADB, desc_all),
                                        ad_total=0.0, max_hp=0.0, missing_hp=0.0))
            if base is None and slot == 'I':
                mh = R_HP_A.search(desc_all) or R_HP_B.search(desc_all)
                if mh:
                    a = float(mh.group(1)); b = float(mh.group(2)) if mh.group(2) else a
                    ratio_ranks = [round(a + (b - a) * i / 4, 2) for i in range(5)]
                    if ratio_ranks: effects.append(dict(kind='DAMAGE', label='% max health (innate on-hit)', values=ratio_ranks, ap=0.0, ad_bonus=0.0, ad_total=0.0, max_hp=round(sum(ratio_ranks)/len(ratio_ranks)/100,4), missing_hp=0.0))
            cast_t = rank_values(field(t, 'cast time'))
            onhit_flag = 'true' in field(t, 'onhiteffects').lower()
            # multi-cast abilities (Aatrox Q swings 3x, Riven Q 3x): the wiki states it in prose
            dsc = field(t, 'description') + ' ' + field(t, 'description2')
            casts = 1
            m3 = re.search(r'(?i)\b(?:up to\s+)?(two|three|twice|thrice|2|3)\s+times|recast(?:\s+\w+){0,3}\s+(?:up to\s+)?(twice|two|three|3|2)', dsc)
            if m3:
                w = (m3.group(1) or m3.group(2) or '').lower()
                casts = {'two': 2, 'twice': 2, '2': 2, 'three': 3, 'thrice': 3, '3': 3}.get(w, 1)
            cd = rank_values(field(t, 'cooldown')) or rank_values(field(t, 'static')) or rank_values(field(t, 'recharge'))
            cost = rank_values(field(t, 'cost'))
            blob = lev + ' ' + field(t, 'description') + ' ' + field(t, 'description2')
            vamp = 0.0; vamp_per100hp = 0.0; vamp_per100ap = 0.0
            vm = re.search(r'(?i)heal(?:s|ing)?[^0-9%]{0,30}?for\s+(?:\{\{[^}]*\|)?([\d.]+)\s*%[\s\S]{0,140}?damage', desc_all)
            if vm:
                vamp = float(vm.group(1)) / 100.0
                sc = re.search(r'(?i)\+\s*(?:\{\{fd\|)?([\d.]+)\}*\s*%\s*per\s*100[^a-zA-Z]{0,12}(?:bonus)?[^a-zA-Z]{0,12}health', desc_all)
                if sc: vamp_per100hp = float(sc.group(1)) / 100.0
                sc2 = re.search(r'(?i)\+\s*(?:\{\{fd\|)?([\d.]+)\}?\}?\s*%\s*per\s*100\s*(?:ability power|AP)', desc_all)
                if sc2: vamp_per100ap = float(sc2.group(1)) / 100.0
            rec = dict(name=aname, slot=slot, vamp=vamp, vamp_per100hp=vamp_per100hp, vamp_per100ap=vamp_per100ap,
                       base=base, cd=cd, cost=cost if 'mana' in field(t, 'costtype').lower() or not field(t, 'costtype') else None,
                       dtype=(field(t, 'damagetype').split('/')[0].strip() or None),
                       ap=round(_agg(effects, 'ap'), 4) or ratio_sum(R_AP, desc_all if slot=='I' else ''),
                       ad_bonus=round(_agg(effects, 'ad_bonus'), 4),
                       ad_total=round(_agg(effects, 'ad_total'), 4),
                       heal_ap=round(sum(e['ap'] for e in effects if e['kind'] in ('SUSTAIN','SHIELD')), 4),
                       heal_ad=round(sum(e['ad_bonus'] + e['ad_total'] for e in effects if e['kind'] in ('SUSTAIN','SHIELD')), 4),
                       max_hp=round(sum(e['max_hp'] for e in effects if e['kind']=='DAMAGE'), 4) or pct_health(desc_all),
                       missing_hp=round(sum(e['missing_hp'] for e in effects if e['kind']=='DAMAGE'), 4) or pct_health(desc_all, True),
                       effects=effects, amps=amps, cast_time=(cast_t[0] if cast_t else None),
                       casts=casts, onhit_flag=onhit_flag,
                       targeting=field(t, 'targeting'), affects=field(t, 'affects'),
                       tags=[k for k, rx in TAGS if re.search(rx, blob, re.I)])
            score = (rec['base'] is not None, bool(cd), len(lev))
            if best is None or score > best[0]: best = (score, rec)
        if best: abils[slot] = best[1]; stats_cov['parsed'] += 1
    ch['abilities'] = abils
    ch['coverage'] = ''.join(s for s in 'QWER' if s in abils) + ('+P' if 'I' in abils else '')

# how many dead templates did the gate exclude?
all_tpl = set(t.split('/')[-1] for t in pages)
for nm, ch in CHAMPS.items():
    live = set(sum(ch['roster'].values(), []))
    for pre in tpl_prefixes(nm, ch.get('apiname', '')):
        dead = [t for t in pages if t.startswith(f'Template:Data {pre}/') and t.split('/', 1)[1] not in live]
        stats_cov['gated_out'] += len(dead)
        if dead or any(t.startswith(f'Template:Data {pre}/') for t in pages): break

json.dump(CHAMPS, open('champion_dna.json', 'w'), indent=0)
full = sum(1 for c in CHAMPS.values() if len(c['abilities']) >= 4)
p_ok = sum(1 for c in CHAMPS.values() if 'I' in c['abilities'])
dmg = sum(1 for c in CHAMPS.values() if any(a['base'] for a in c['abilities'].values()))
print(f"ROSTER GATE: excluded {stats_cov['gated_out']} dead/off-roster templates")
print(f'ability slots parsed: {stats_cov["parsed"]} | champs with 4+ slots: {full} | with passive: {p_ok} | with any damage numbers: {dmg}')
a = CHAMPS['Aatrox']
print('\n=== AATROX (the test case) ===')
for s in ('I', 'Q', 'W', 'E', 'R'):
    if s in a['abilities']:
        x = a['abilities'][s]
        print(f"  {s}: {x['name']:22s} base={x['base']} cd={x['cd']} ap={x['ap']} adT={x['ad_total']} adB={x['ad_bonus']} hp={x['max_hp']} tags={x['tags'][:4]}")
