"""LOE v2 — KNOWLEDGE LAYER.
Turns proven builds into knowledge that accumulates:

  EXTRACTION %   champion's value with a core / the best any champion gets from that core
                 ("can this build be played to its max by this champion?")
  REALIZATION %  champion's value with a core / that champion's own proven ceiling
                 ("can this champion play to their max because of this build?")
  PERFECT PAIR   both >= 95% -> a checkable definition of "these two max each other"
  DNA REALIZATION  how much of the CHAMPION'S OWN KIT this build actually feeds — measured as the
                 fraction of their objective ceilings the build reaches, across ALL objectives.
                 A build that maxes DPS but wastes the kit's healing scores lower than one that
                 lifts the whole kit. This is "maximize the champion", not "maximize one number".
  ENGINES        recurring item/rune systems the optimizer independently converges on.
"""
import json
from collections import defaultdict, Counter
import combat, core

OPT = json.load(open('optimized_v2.json'))
OBJ = ['dps', 'burst', 'ehp', 'sustain', 'utility']

# ---------- 1. each champion's ceiling per objective (their own proven max) ----------
ceiling = {nm: {o: r['objectives'][o]['value'] for o in OBJ if o in r['objectives'] and 'value' in r['objectives'][o]}
           for nm, r in OPT.items()}

# ---------- 2. DNA REALIZATION: does this build lift the WHOLE kit? ----------
def dna_realization(nm, build_key):
    """Fraction of the champion's own ceilings that this ONE build reaches, across every objective.
    1.0 would mean a single build simultaneously maxes everything the kit can do."""
    b = OPT[nm]['objectives'].get(build_key)
    if not b or 'error' in b: return None
    cl = ceiling[nm]
    got = dict(dps=b['dps'], burst=b['burst'], ehp=b['ehp'], sustain=b['sustain'], utility=b['utility'])
    fr = [min(1.0, got[o] / cl[o]) for o in OBJ if cl.get(o)]
    return round(sum(fr) / len(fr), 3) if fr else None

for nm in OPT:
    OPT[nm]['dna_realization'] = {o: dna_realization(nm, o) for o in OBJ}
    best = max((v, o) for o, v in OPT[nm]['dna_realization'].items() if v)
    OPT[nm]['most_complete_build'] = dict(objective=best[1], score=best[0])

# ---------- 3. distinct cores + extraction matrix (per objective) ----------
cores = defaultdict(Counter)
for nm, r in OPT.items():
    for o in OBJ:
        b = r['objectives'].get(o)
        if b and 'items' in b:
            cores[o][frozenset(b['items'])] += 1

pairs = []
for o in OBJ:
    top_cores = [list(c) for c, _ in cores[o].most_common(24)]
    for core_items in top_cores:
        vals = []
        for nm in OPT:
            b = OPT[nm]['objectives'].get(o)
            if not b or 'boots' not in b: continue
            tail = [b['boots'], b['keystone']] + b['minors'] + b['shards']
            try:
                s = combat.simulate(nm, core_items + tail)[o]
            except Exception:
                continue
            vals.append((s, nm))
        if not vals: continue
        ceil_v, ceil_champ = max(vals)
        for v, nm in vals:
            ext = v / ceil_v if ceil_v else 0
            own = ceiling[nm].get(o, 0)
            real = v / own if own else 0
            if ext >= 0.95 and real >= 0.95:
                pairs.append(dict(champ=nm, objective=o, items=sorted(core_items),
                                  extraction=round(100 * ext), realization=round(100 * real),
                                  is_own=set(core_items) == set(OPT[nm]['objectives'][o]['items'])))

# ---------- 4. engines: item systems the optimizer independently converges on ----------
engines = []
for o in OBJ:
    for c, n in cores[o].most_common(8):
        if n < 3: continue
        users = [nm for nm in OPT if OPT[nm]['objectives'].get(o, {}).get('items') and
                 frozenset(OPT[nm]['objectives'][o]['items']) == c]
        engines.append(dict(objective=o, items=sorted(c), champions=n, examples=users[:6]))

json.dump(dict(champions=OPT, perfect_pairs=pairs, engines=engines,
               cores={o: len(cores[o]) for o in OBJ}), open('knowledge_v2.json', 'w'), indent=0)

print(f'champions: {len(OPT)}')
print(f'distinct cores per objective: {dict((o, len(cores[o])) for o in OBJ)}')
print(f'perfect pairs: {len(pairs)} ({sum(1 for p in pairs if p["is_own"])} are the champion\'s own proven build)')
print(f'engines (3+ champions converge): {len(engines)}')
print()
print('MOST COMPLETE BUILDS (a single build that lifts the most of the kit):')
top = sorted(OPT.items(), key=lambda x: -(x[1]['most_complete_build']['score'] or 0))[:6]
for nm, r in top:
    m = r['most_complete_build']
    print(f'   {nm:14s} max-{m["objective"]:8s} realizes {m["score"]:.0%} of the kit\'s total ceilings')
