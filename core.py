"""LOE v2 — CORE ENGINE.
Everything is a number, every number has a provenance, and every formula is the GAME's formula.

    LEVEL      stat(L) = base + growth * (L-1) * (0.7025 + 0.0175*(L-1))     [GAME: growth curve]
    MITIGATION mult    = 100 / (100 + effective_resist)                       [GAME]
    PEN ORDER  R_eff   = max(0, R * (1 - pct_pen) - flat_pen)                 [GAME: pct before flat]
    HASTE      cdr     = AH / (AH + 100)                                      [GAME]
    EHP        ehp     = HP * (1 + R/100)                                     [GAME]
    CRIT       dmg     = AD * (1 + crit_chance * (0.75 + crit_dmg_bonus))     [GAME: 175% base crit]

No champion is scored on a guess: `coverage` travels with every result.
"""
import json, math

CH = json.load(open('champion_dna.json'))
IT = json.load(open('item_dna.json'))
RU = json.load(open('rune_dna.json'))

GROWTH = lambda base, g, L: base + g * (L - 1) * (0.7025 + 0.0175 * (L - 1))

# ---- stat-name normalisation: the wiki's item keys -> our canonical vector ----
STAT_MAP = {
    'ad': 'AD', 'ap': 'AP', 'as': 'AS', 'crit': 'CRIT', 'critdamage': 'CRIT_DMG',
    'hp': 'HP', 'armor': 'ARMOR', 'mr': 'MR', 'ah': 'AH', 'mana': 'MANA', 'ms': 'MS_PCT',
    'msflat': 'MS', 'lethality': 'PEN', 'armpen': 'PEN_PCT', 'mpen': 'MPEN_PCT', 'mpenflat': 'MPEN',
    'lifesteal': 'LS', 'omnivamp': 'OV', 'physicalvamp': 'PV', 'hp5': 'HP5', 'mp5': 'MP5',
    'hsp': 'HEAL_AMP', 'tenacity': 'TEN', 'goldper10': 'GOLD10', 'adaptive': 'ADAPTIVE',
    'ms_pct': 'MS_PCT',
}
VEC = ['AD','AP','AS','CRIT','CRIT_DMG','HP','ARMOR','MR','AH','MANA','MS','MS_PCT',
       'PEN','PEN_PCT','MPEN','MPEN_PCT','LS','OV','PV','HP5','MP5','HEAL_AMP','TEN','ADAPTIVE']

def zero(): return {k: 0.0 for k in VEC}

# ---- pools ----
def _is_support_quest(d):
    # DATA: support items carry a gold-generation stat and cost 0 (quest-upgraded).
    return 'gp10' in d['stats'] or d.get('buy') == 0.0

LEGENDARIES = [n for n, d in IT.items()
               if d['sr'] and 'Legendary' in d['types'] and not d['removed'] and not _is_support_quest(d)]
SUPPORT_ITEMS = [n for n, d in IT.items()
                 if d['sr'] and 'Legendary' in d['types'] and not d['removed'] and _is_support_quest(d)]
BOOTS = [n for n, d in IT.items() if d['sr'] and 'Boots' in d['types'] and not d['removed'] and d['tier'] >= 2]
KEYSTONES = [n for n, r in RU.items() if r['kind'] == 'KEYSTONE']
MINORS = [n for n, r in RU.items() if r['kind'] == 'MINOR']
SHARDS = [n for n, r in RU.items() if r['kind'] == 'SHARD']

def base_stats(name, L=18):
    s = CH[name]['stats']
    return dict(
        HP=GROWTH(s['hp'], s['hp_lvl'], L), MANA=GROWTH(s['mp'], s['mp_lvl'], L),
        AD=GROWTH(s['ad'], s['ad_lvl'], L), ARMOR=GROWTH(s['armor'], s['armor_lvl'], L),
        MR=GROWTH(s['mr'], s['mr_lvl'], L),
        AS=s['as_base'] * (1 + (s['as_lvl'] / 100.0) * (L - 1) * (0.7025 + 0.0175 * (L - 1))),
        AS_RATIO=s['as_ratio'] or s['as_base'], MS=s['ms'], RANGE=s['range'],
        CAST=s['attack_cast_time'] or 0.3, WINDUP=s['attack_total_time'] or 1.5)

def item_vector(names, L=18):
    """Sum the stat vector. Percentage PENETRATION stacks multiplicatively (GAME), never additively."""
    v = zero()
    pen_mult = 1.0; mpen_mult = 1.0
    for n in names:
        d = IT.get(n)
        if d:
            for k, val in d['stats'].items():
                key = STAT_MAP.get(k)
                if not key: continue
                if key == 'PEN_PCT':   pen_mult *= (1 - val / 100.0); continue
                if key == 'MPEN_PCT':  mpen_mult *= (1 - val / 100.0); continue
                v[key] += val
            continue
        r = RU.get(n)
        if r and r.get('stats'):
            for k, val in r['stats'].items():
                key = STAT_MAP.get(k, k.upper())
                if key in v: v[key] += val
    v['PEN_PCT'] = (1 - pen_mult) * 100.0        # GAME: multiplicative stacking
    v['MPEN_PCT'] = (1 - mpen_mult) * 100.0
    return v

# ---- combat formulas (all GAME) ----
def eff_resist(R, flat, pct):
    return max(0.0, R * (1 - min(0.9, pct / 100.0)) - flat)

def mitig(R): return 100.0 / (100.0 + R)

def ehp(hp, resist): return hp * (1 + resist / 100.0)

def cdr(ah): return ah / (ah + 100.0)

# ---- champion conversion vector: how well does this KIT convert each stat? ----
def conversion(name):
    """Read straight off the kit's own ratios — no roles, no labels, no opinions."""
    c = CH[name]; ab = c['abilities']
    tot = lambda k: sum(a.get(k, 0) or 0 for a in ab.values())
    n_dmg = sum(1 for a in ab.values() if a.get('base') or a.get('ap') or a.get('ad_total') or a.get('ad_bonus'))
    cds = [a['cd'][2] for a in ab.values() if a.get('cd') and a['slot'] in 'QWE']
    onhit = any('on_hit' in (a.get('tags') or []) for a in ab.values())
    amps = {}
    for a in ab.values():
        for stat, rec in (a.get('amps') or {}).items():
            if isinstance(rec, dict):
                amps[stat] = dict(value=rec['values'][4], pct=rec['pct'])   # rank 5
    s = c['stats']
    return dict(
        ap_scaling=round(tot('ap'), 3),
        ad_scaling=round(tot('ad_total') + tot('ad_bonus'), 3),
        hp_scaling=round(tot('max_hp') + tot('missing_hp'), 4),
        ability_count=n_dmg,
        mean_basic_cd=round(sum(cds) / len(cds), 1) if cds else 10.0,
        haste_dependency=round(1.0 / (sum(cds) / len(cds)) * 10, 3) if cds else 1.0,
        auto_dependency=round(1.0 if onhit else 0.4 + (0.3 if s['range'] >= 500 else 0.0), 3),
        resource=c['resource'],
        self_amps=amps,
        range=s['range'],
        durability=round((s['armor'] + s['armor_lvl'] * 17 + s['mr'] + s['mr_lvl'] * 17) / 2, 1),
        coverage=c['coverage'])

if __name__ == '__main__':
    print(f'pools — legendaries {len(LEGENDARIES)} | boots {len(BOOTS)} | keystones {len(KEYSTONES)} '
          f'| minors {len(MINORS)} | shards {len(SHARDS)}')
    for nm in ['Aatrox', "Vel'Koz", 'Ornn', 'Master Yi', 'Jhin']:
        b = base_stats(nm); cv = conversion(nm)
        print(f"\n{nm:10s} L18  HP {b['HP']:.0f}  AD {b['AD']:.0f}  AR {b['ARMOR']:.0f}  MR {b['MR']:.0f}  AS {b['AS']:.2f}")
        print(f"           kit: AP-scaling {cv['ap_scaling']}  AD-scaling {cv['ad_scaling']}  "
              f"HP-scaling {cv['hp_scaling']}  auto-dep {cv['auto_dependency']}  "
              f"mean-CD {cv['mean_basic_cd']}s  amps {cv['self_amps']}")
