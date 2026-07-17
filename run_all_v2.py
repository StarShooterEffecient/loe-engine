"""Full roster optimization: every champion x every objective, mutation-proven."""
import json, time, sys, hashlib
import optimizer as O, combat, core
import frontier as F

import os
# A resume is only valid if the DATA hasn't changed. We stamp each result file with a fingerprint
# of the champion+item+rune DNA. If the wiki (mirror) changed, the fingerprint changes, and we
# recompute from scratch instead of trusting a stale cache. This is what makes the GitHub run
# actually reflect fresh wiki data rather than a shipped file.
def data_fingerprint():
    h = hashlib.sha256()
    for f in ('champion_dna.json', 'item_dna.json', 'rune_dna.json', 'damage_dna.json'):
        if os.path.exists(f):
            h.update(open(f, 'rb').read())
    return h.hexdigest()[:16]

FP = data_fingerprint()
prev = json.load(open('optimized_v2.json')) if os.path.exists('optimized_v2.json') else {}
if prev.get('_fingerprint') == FP:
    OUT = prev
    print(f'resuming: same data fingerprint {FP} — reusing valid results', flush=True)
else:
    OUT = {'_fingerprint': FP}
    if prev:
        print(f'data changed (fingerprint {prev.get("_fingerprint")} -> {FP}) — recomputing all', flush=True)
DONE = {k for k, v in OUT.items() if k != '_fingerprint'
        and len(v.get('objectives', {})) == len(O.OBJECTIVES)
        and all('items' in b for b in v['objectives'].values())}
print(f'{len(DONE)} champions already proven for this data version', flush=True)
t0 = time.time()
names = sorted(core.CH)
for i, nm in enumerate(names, 1):
    c = core.CH[nm]
    if not any(a.get('base') or a.get('ap') or a.get('ad_total') or a.get('ad_bonus')
               for a in c['abilities'].values()):
        continue                                   # unusable kit — disclosed, never faked
    if nm in DONE: continue
    rec = {}
    O.cache_clear()          # bound memory: the cache pays off WITHIN a champion, not across
    for obj in O.OBJECTIVES:
        try:
            if obj == 'omega':
                # R-NSGA-II frontier: optimize all objectives at once, steer to kit identity
                frontier, (best_g, _), _ = F.optimize_frontier(nm)
                pv = F.prove_from_frontier(nm, best_g)
                fi, fb, fk, fm, fs, sw = (pv['items'], pv['boots'], pv['keystone'],
                                          pv['minors'], pv['shards'], pv['swaps'])
                r = combat.simulate(nm, fi + [fb, fk] + fm + fs)
                fv = r['omega']
            else:
                (items, boots, page), _ = O.optimize_champion(nm, obj)
                ks, minors, shards = page
                (fi, fb, fk, fm, fs), fv, sw = O.mutation_proof(nm, items, boots, ks, minors, shards, obj)
                r = combat.simulate(nm, fi + [fb, fk] + fm + fs)
            rec[obj] = dict(items=fi, boots=fb, keystone=fk, minors=fm, shards=fs,
                            value=round(fv, 2), swaps=sw, proven=True,
                            omega=round(r['omega'], 1), modelled=r['modelled'],
                            dps=round(r['dps']), burst=round(r['burst']), ehp=round(r['ehp']),
                            sustain=round(r['sustain']), utility=round(r['utility'], 1),
                            per_target=[dict(t=t['target'], dps=round(t['dps']), ttk=round(t['ttk'], 1))
                                        for t in r['per_target']])
        except Exception as e:
            rec[obj] = dict(error=str(e)[:80])
    OUT[nm] = dict(objectives=rec, coverage=c['coverage'],
                   conversion=core.conversion(nm))
    if i % 10 == 0:
        json.dump(OUT, open('optimized_v2.json', 'w'), indent=0)      # checkpoint
        el = time.time() - t0
        print(f'{i}/{len(names)}  {el/60:.1f}min elapsed, ~{el/i*(len(names)-i)/60:.0f}min left', flush=True)
json.dump(OUT, open('optimized_v2.json', 'w'), indent=0)
print(f'DONE: {len(OUT)} champions x {len(O.OBJECTIVES)} objectives in {(time.time()-t0)/60:.1f} min')
