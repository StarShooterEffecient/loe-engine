"""LOE v2 — R-NSGA-II FRONTIER (from the Dynamic Theorycrafting blueprint).
The single-beam search commits early: it picks the item with the best SINGLE-objective score first,
so an AP kit that looks marginally better in raw AD for one step gets locked onto the wrong axis and
never recovers. That is the source of the remaining max-DPS / max-burst coherence violations.

R-NSGA-II fixes this structurally by optimizing ALL objectives at once and keeping a whole frontier:

  1. POPULATION      a diverse set of legal builds, seeded from every scaling axis the kit can use
  2. EVALUATE        each build scored on all 5 objectives (dps, burst, ehp, sustain, utility)
  3. NON-DOM SORT    rank builds into Pareto fronts; a build survives if nothing beats it on
                     everything (the blueprint's "discard dominated solutions")
  4. REFERENCE POINT steer toward the champion's IDENTITY — the objective mix its own kit implies
                     (the Omega weights), so Aatrox is pulled toward high-damage-high-survival, not
                     hard-locked into a role
  5. EVOLVE          crossover + mutation on the survivors, always legality-gated, for N generations

The champion is never forced onto an axis. If a non-traditional combination matches the reference
point, it survives on the frontier — the blueprint's "allowing the exceptions".
"""
import json, random, itertools
import core, combat
import optimizer as O

CH, IT = core.CH, core.IT
LEG, BOOTS = core.LEGENDARIES, core.BOOTS
OBJS = ['dps', 'burst', 'ehp', 'sustain', 'utility']
REF = dict(dps=450.0, burst=1800.0, ehp=9000.0, sustain=120.0, utility=6.0)


def _seed_pools(name):
    """The blueprint's dynamic scaling: seed from every axis the kit — or an item — can unlock."""
    ap = [n for n in LEG if IT[n]['stats'].get('ap', 0) > 55]
    ad = [n for n in LEG if IT[n]['stats'].get('ad', 0) > 35]
    hp = [n for n in LEG if IT[n]['stats'].get('hp', 0) > 300]
    tank = [n for n in LEG if IT[n]['stats'].get('armor', 0) + IT[n]['stats'].get('mr', 0) > 40]
    return [p for p in (ap, ad, hp, tank) if len(p) >= 5]


def _random_build(name, pools, rng):
    pool = rng.choice(pools) + rng.sample(LEG, 8)
    items = []
    for it in rng.sample(pool, len(pool)):
        if it in items: continue
        if O.legal(items + [it]):
            items.append(it)
        if len(items) == 5: break
    boots = rng.choice(BOOTS)
    return (tuple(items), boots)


def _evaluate(name, genome, page_cache):
    items, boots = genome
    if items not in page_cache:
        # a fast fixed page during frontier search; the winner gets a full page + mutation proof later
        page_cache[items] = (O.KS[0], [], [])
    ks, minors, shards = page_cache[items]
    r = combat.simulate(name, list(items) + [boots, ks] + list(minors) + list(shards))
    return {o: r[o] for o in OBJS}, r


def _dominates(a, b):
    return all(a[o] >= b[o] for o in OBJS) and any(a[o] > b[o] for o in OBJS)


def _fronts(pop_scores):
    """Fast non-dominated sort -> list of fronts (each a list of indices)."""
    n = len(pop_scores)
    S = [[] for _ in range(n)]; nd = [0] * n; rank = [0] * n; fronts = [[]]
    for p in range(n):
        for q in range(n):
            if p == q: continue
            if _dominates(pop_scores[p], pop_scores[q]): S[p].append(q)
            elif _dominates(pop_scores[q], pop_scores[p]): nd[p] += 1
        if nd[p] == 0: rank[p] = 0; fronts[0].append(p)
    i = 0
    while fronts[i]:
        nxt = []
        for p in fronts[i]:
            for q in S[p]:
                nd[q] -= 1
                if nd[q] == 0: rank[q] = i + 1; nxt.append(q)
        i += 1; fronts.append(nxt)
    return fronts[:-1]


def _ref_distance(score, weights):
    """Distance to the champion's identity reference point, in weighted normalized objective space."""
    return sum(weights[o] * abs(score[o] / REF[o] - 1.0) for o in OBJS)


def optimize_frontier(name, pop_size=40, generations=6, seed=7):
    rng = random.Random(seed)
    weights = combat.KP.omega_weights(name)
    pools = _seed_pools(name)
    if not pools: pools = [LEG]
    page_cache = {}

    pop = []
    seen = set()
    while len(pop) < pop_size:
        g = _random_build(name, pools, rng)
        if len(g[0]) == 5 and g not in seen:
            seen.add(g); pop.append(g)

    for gen in range(generations):
        scores = [_evaluate(name, g, page_cache)[0] for g in pop]
        fronts = _fronts(scores)
        # selection: fill the next generation front by front, ref-distance within a front
        nextpop = []
        for front in fronts:
            front_sorted = sorted(front, key=lambda i: _ref_distance(scores[i], weights))
            for i in front_sorted:
                if len(nextpop) < pop_size // 2: nextpop.append(pop[i])
            if len(nextpop) >= pop_size // 2: break
        # breed: crossover two parents' items + mutate one slot, always legal
        children = []
        while len(children) < pop_size - len(nextpop):
            pa, pb = rng.choice(nextpop), rng.choice(nextpop)
            mix = list(dict.fromkeys(list(pa[0]) + list(pb[0])))
            rng.shuffle(mix)
            items = []
            for it in mix:
                if O.legal(items + [it]) and it not in items: items.append(it)
                if len(items) == 5: break
            if len(items) < 5: continue
            if rng.random() < 0.6:                       # mutation
                j = rng.randrange(5); alt = rng.choice(LEG)
                trial = items[:j] + [alt] + items[j + 1:]
                if len(set(trial)) == 5 and O.legal(trial): items = trial
            boots = pa[1] if rng.random() < 0.5 else pb[1]
            g = (tuple(items), boots)
            if g not in seen: seen.add(g); children.append(g)
        pop = nextpop + children

    # final frontier
    scores = [_evaluate(name, g, page_cache)[0] for g in pop]
    fronts = _fronts(scores)
    frontier = [(pop[i], scores[i]) for i in fronts[0]]
    # the identity pick: frontier build closest to the reference point
    best = min(frontier, key=lambda x: _ref_distance(x[1], weights))
    return frontier, best, weights


def prove_from_frontier(name, genome):
    """Give the chosen frontier build a full rune page, then mutation-prove it (Stage C)."""
    items, boots = genome
    page, _ = O.best_page(name, list(items), boots, 'omega')
    ks, minors, shards = page
    (fi, fb, fk, fm, fs), fv, sw = O.mutation_proof(name, list(items), boots, ks, minors, shards, 'omega')
    return dict(items=fi, boots=fb, keystone=fk, minors=fm, shards=fs, swaps=sw)


if __name__ == '__main__':
    import time
    for nm in ['Aatrox', 'Ahri', 'Master Yi', "Vel'Koz"]:
        t = time.time()
        frontier, (best_g, best_s), w = optimize_frontier(nm)
        print(f'\n{nm} — frontier of {len(frontier)} non-dominated builds ({time.time()-t:.1f}s)')
        print(f'   identity weights: {dict((k, round(v,2)) for k,v in w.items())}')
        print(f'   identity pick: {list(best_g[0])} + {best_g[1]}')
        print(f'   scores: dps {best_s["dps"]:.0f} burst {best_s["burst"]:.0f} ehp {best_s["ehp"]:.0f} '
              f'sustain {best_s["sustain"]:.0f}')
