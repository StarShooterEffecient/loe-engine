"""LOE v2 — THE TRUST LAYER.
"How do we know the builds aren't crap?" is answerable, and it is not answered by running more.
Determinism means re-running changes nothing. Builds improve when DATA improves or the MODEL
improves. This file is how we find where both are still wrong.

Three tests, each capable of failing loudly:

  T1  ITEM MODELLING AUDIT — for every item the optimizer picks, how much of that item does the
      combat model actually COMPUTE? An item whose passive we ignore is being bought (or skipped)
      on partial information. This is the single biggest source of bad builds.

  T2  KIT COHERENCE ORACLE — derived from the champion's own DNA, never from the meta:
      a kit with AP scaling and no AD scaling must not be handed an AD build. If it is, either
      the kit parse is wrong or the model is. Violations are printed by name.

  T3  ROBUSTNESS SWEEP — re-optimize under changed assumptions (fight length, auto uptime, target
      mix). A build that only wins at exactly 15 seconds is an artifact, not a discovery.
      Builds that survive every assumption are the ones you can trust.
"""
import json, copy
from collections import Counter, defaultdict
import core, combat, optimizer as O

IT, CH = core.IT, core.CH
# trust reads the knowledge/optimization results; tolerate a missing file and skip the fingerprint
# stamp so iterating champions never hits the '_fingerprint' string key.
import os
if os.path.exists('knowledge_v2.json'):
    K = json.load(open('knowledge_v2.json'))
    OPT = K.get('champions', K)
elif os.path.exists('optimized_v2.json'):
    OPT = json.load(open('optimized_v2.json'))
else:
    OPT = {}
OPT = {n: v for n, v in OPT.items() if n != '_fingerprint'}

# ============ T1: ITEM MODELLING AUDIT ============
# What the combat model actually reads today:
#   - every raw stat (AD/AP/AS/HP/armor/MR/AH/crit/pen/lifesteal/omnivamp/heal-amp...)
#   - ON_HIT passives with damage numbers
#   - SHRED passives (armor/MR reduction)
# What it does NOT read: everything else (actives, on-ability procs, shields, conditional damage,
# stacking mechanics, movement effects). Those items are valued on stats alone.
MODELLED_TRIGGERS = {'ON_HIT'}
MODELLED_EFFECTS = {'SHRED'}

def item_modelled_fraction(name):
    d = IT.get(name)
    if not d: return None
    if not d['effects']: return 1.0                      # stat-only item: fully modelled
    modelled = 0; total = 0
    for e in d['effects']:
        total += 1
        has_numbers = e['dmg_hi'] or e['pct_max_hp'] or e['pct_cur_hp']
        if e['trigger'] in MODELLED_TRIGGERS and has_numbers: modelled += 1
        elif set(e['effects']) & MODELLED_EFFECTS: modelled += 1
    return round(modelled / total, 2) if total else 1.0

def t1_audit():
    picks = Counter()
    for nm, r in OPT.items():
        for o, b in r['objectives'].items():
            for i in b.get('items', []): picks[i] += 1
    rows = []
    for item, n in picks.most_common():
        f = item_modelled_fraction(item)
        d = IT[item]
        unmod = [e['name'] for e in d['effects']
                 if not ((e['trigger'] in MODELLED_TRIGGERS and (e['dmg_hi'] or e['pct_max_hp'] or e['pct_cur_hp']))
                         or set(e['effects']) & MODELLED_EFFECTS)]
        rows.append(dict(item=item, picks=n, modelled=f, unmodelled_passives=unmod))
    fully = sum(1 for r in rows if r['modelled'] == 1.0)
    partial = [r for r in rows if r['modelled'] is not None and r['modelled'] < 1.0]
    print('=== T1  ITEM MODELLING AUDIT ===')
    print(f'items the optimizer picks: {len(rows)} | fully modelled: {fully} | partially modelled: {len(partial)}')
    print('\nMOST-PICKED items whose passives we DO NOT compute (these builds rest on stats alone):')
    for r in sorted(partial, key=lambda x: -x['picks'])[:12]:
        print(f"   {r['item']:26s} picked {r['picks']:4d}x  modelled {r['modelled']:.0%}  ignoring: {', '.join(r['unmodelled_passives'][:2])}")
    # the inverse risk: strong items we may be UNDER-valuing and never picking
    never = [n for n in core.LEGENDARIES if n not in picks]
    print(f'\nSR legendaries the optimizer NEVER picks: {len(never)}/{len(core.LEGENDARIES)}')
    unmod_never = [n for n in never if (item_modelled_fraction(n) or 1) < 1.0]
    print(f'   ...of which have passives we do not model: {len(unmod_never)}')
    for n in unmod_never[:10]:
        e = IT[n]['effects'][0]['name'] if IT[n]['effects'] else ''
        print(f'      {n:26s} (passive: {e})')
    return rows, never

# ============ T2: KIT COHERENCE ORACLE ============
def t2_coherence():
    """Derived from the champion's OWN kit. No meta, no roles, no opinions."""
    print('\n=== T2  KIT COHERENCE ORACLE ===')
    viol = []
    for nm, r in OPT.items():
        cv = r['conversion']
        ap_kit, ad_kit = cv['ap_scaling'], cv['ad_scaling']
        ab = CH[nm]['abilities']
        has_heal = any((a.get('heal_ap') or a.get('heal_ad') or a.get('vamp')) for a in ab.values())
        for o, b in r['objectives'].items():
            if o in ('ehp', 'utility'): continue        # defensive objectives need no offense
            if o == 'sustain' and not has_heal: continue # no native heal -> item sustain is fine
            if 'items' not in b: continue
            v = core.item_vector(b['items'] + [b['boots']])
            ap_buy, ad_buy = v['AP'], v['AD']
            # a kit that scales ONLY with AP must not be bought AD (and vice versa)
            if ap_kit >= 1.0 and ad_kit < 0.2 and ad_buy > ap_buy * 0.8:
                viol.append((nm, o, 'AP kit bought AD', round(ap_kit, 2), round(ad_kit, 2), round(ap_buy), round(ad_buy)))
            if ad_kit >= 1.0 and ap_kit < 0.2 and ap_buy > ad_buy * 0.8:
                viol.append((nm, o, 'AD kit bought AP', round(ap_kit, 2), round(ad_kit, 2), round(ap_buy), round(ad_buy)))
    print(f'coherence violations: {len(viol)}')
    for v in viol[:12]:
        print(f'   {v[0]:14s} {v[1]:8s} {v[2]:18s} kit(AP {v[3]} / AD {v[4]})  bought(AP {v[5]} / AD {v[6]})')
    if not viol:
        print('   none — every offensive build feeds the scaling its kit actually has')
    return viol

# ============ T3: ROBUSTNESS SWEEP ============
def t3_robustness(sample=14):
    """A build that only wins under one set of assumptions is an artifact."""
    print('\n=== T3  ROBUSTNESS SWEEP (do builds survive changed assumptions?) ===')
    import random
    random.seed(11)
    names = random.sample(list(OPT), min(sample, len(OPT)))
    scenarios = [
        ('baseline',          dict()),
        ('short fight  8s',   dict(WINDOW=8.0)),
        ('long fight  30s',   dict(WINDOW=30.0)),
        ('low auto uptime',   dict(AUTO_UPTIME={'ranged': 0.6, 'melee': 0.4})),
        ('tank-heavy targets', dict(TARGETS=[dict(name='Bruiser', HP=3600, ARMOR=160, MR=100),
                                             dict(name='Tank', HP=4800, ARMOR=320, MR=220),
                                             dict(name='Tank2', HP=5600, ARMOR=380, MR=260)])),
    ]
    orig = {k: getattr(combat, k) for k in ('WINDOW', 'AUTO_UPTIME', 'TARGETS')}
    results = defaultdict(dict)
    for label, patch in scenarios:
        for k, v in patch.items(): setattr(combat, k, v)
        for nm in names:
            b = OPT[nm]['objectives'].get('dps')
            if not b or 'items' not in b: continue
            (items, boots, page), _ = O.optimize_champion(nm, 'dps', beam=4)
            results[nm][label] = frozenset(items)
        for k, v in orig.items(): setattr(combat, k, v)
    stable = 0
    for nm in names:
        r = results[nm]
        if 'baseline' not in r: continue
        base = r['baseline']
        agree = sum(1 for lab, s in r.items() if lab != 'baseline' and len(s & base) >= 4)
        if agree == len(r) - 1: stable += 1
        overlap = {lab: len(s & base) for lab, s in r.items() if lab != 'baseline'}
        print(f'   {nm:14s} items shared with baseline: {overlap}')
    print(f'\nbuilds stable under EVERY assumption change (>=4/5 items shared): {stable}/{len(names)}')
    return results

if __name__ == '__main__':
    rows, never = t1_audit()
    viol = t2_coherence()
    rob = t3_robustness()
    json.dump(dict(item_audit=rows, never_picked=never, coherence_violations=viol),
              open('trust_report.json', 'w'), indent=1)
    print('\nsaved trust_report.json')
