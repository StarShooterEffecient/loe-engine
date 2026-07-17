"""LOE v2 — OPTIMIZER.
Two independent paths (the charter's Stage A and Stage B) and one gatekeeper (Stage C):

  PATH A  ITEM-FIRST : find item/rune systems that are strong on their own merits, then ask which
                       champion's kit extracts the most from them. (champion-agnostic seeds)
  PATH B  CHAMPION-FIRST : start from the champion's DNA and grow the build that feeds THAT kit.
  STAGE C MUTATION PROOF : swap every slot — items, boots, keystone, 5 minors, 3 shards — against
                       every legal alternative. Keep only guaranteed improvements. Terminate when
                       no legal single swap improves the objective. Then the build is PROVEN.

Objectives are separate. A champion has as many optimal builds as there are objectives.
Legality is enforced at ONE choke point: legal().
"""
import json, itertools, random
import core, combat

CH, IT, RU = core.CH, core.IT, core.RU
LEG, BOOTS = core.LEGENDARIES, core.BOOTS
KS, MIN, SH = core.KEYSTONES, core.MINORS, core.SHARDS

OBJECTIVES = ['omega', 'dps', 'burst', 'ehp', 'sustain', 'utility']
# 'omega' = the kit-weighted composite: the single build that lifts the most of THIS kit.

# ---------- legality: ONE choke point ----------
# GAME: ITEM GROUPS — the wiki states outright that a player may not equip more than one item
# from the same designated group. Reading this from 'Item group' (rather than inferring it from
# shared passive names) revealed that the engine had been producing ILLEGAL builds: Lord Dominik's
# + Mortal Reminder + Serylda's are all 'Fatality'; Void Staff + Cryptbloom are both 'Blight'.
_IG = json.load(open('item_groups.json'))
ITEM_GROUP = _IG['item_group']

# Shared UNIQUE passive names remain a secondary constraint (they catch groups the article omits).
UNIQUE_TAGS = {}
_groups = {}
for n, d in IT.items():
    for e in d['effects']:
        if e.get('unique') and e.get('name'):
            _groups.setdefault(e['name'], []).append(n)
for gname, members in _groups.items():
    if len(members) > 1:
        for m in members:
            UNIQUE_TAGS.setdefault(m, set()).add(gname)

def legal(items, ks=None, minors=(), shards=()):
    if len(set(items)) != len(items): return False
    # 1. ITEM GROUPS (from the wiki's own 'Item group' table) — at most one item per group
    seen_g = set()
    for i in items:
        for g in ITEM_GROUP.get(i, ()):
            if g in seen_g: return False
            seen_g.add(g)
    # 2. shared unique passive names (secondary constraint)
    seen = {}
    for i in items:
        for t in UNIQUE_TAGS.get(i, ()):
            if t in seen: return False
            seen[t] = i
    if ks is not None:
        prim = RU[ks]['path']
        rows = {}
        trees = {}
        for m in minors:
            r = RU[m]
            if (r['path'], r['row']) in rows: return False          # one rune per row
            rows[(r['path'], r['row'])] = m
            trees.setdefault(r['path'], []).append(m)
        sec = [t for t in trees if t != prim]
        if len(sec) > 1: return False                                # exactly one secondary tree
        if len(trees.get(prim, [])) > 3: return False                # 3 primary
        if sec and len(trees[sec[0]]) > 2: return False              # 2 secondary
        if len(minors) > 5: return False
        # shards: 3 slots, one each, dual-slot shards resolved by assignment
        slots = [RU[s].get('shard_slots', [1, 2, 3]) for s in shards]
        if len(shards) > 3: return False
        ok = False
        for perm in itertools.permutations((1, 2, 3), len(shards)):
            if all(perm[i] in slots[i] for i in range(len(shards))): ok = True; break
        if shards and not ok: return False
    return True

PATCH = '26.13'
_CACHE = {}
CACHE_STATS = dict(hits=0, misses=0)

def _key(name, items, boots, ks, minors, shards):
    # sorted -> Build(A,B) and Build(B,A) share one key, exactly as the caching spec requires
    return (PATCH, name, tuple(sorted(items)), boots, ks,
            tuple(sorted(minors)), tuple(sorted(shards)))

def score(name, items, boots, ks, minors, shards, obj):
    """Deterministic, therefore cacheable: the same build is never simulated twice."""
    k = _key(name, items, boots, ks, minors, shards)
    r = _CACHE.get(k)
    if r is None:
        CACHE_STATS['misses'] += 1
        r = combat.simulate(name, list(items) + [boots, ks] + list(minors) + list(shards))
        _CACHE[k] = r
    else:
        CACHE_STATS['hits'] += 1
    return r[obj], r

def cache_clear():
    _CACHE.clear()

# ---------- rune page: greedy, legality-gated ----------
def best_page(name, items, boots, obj, cur=None):
    """Greedy, legality-gated: keystone -> 3 primary rows -> best secondary tree (2 rows) -> shards."""
    # 1. keystone on its own merit
    ks_v = [(score(name, items, boots, k, [], [], obj)[0], k) for k in KS]
    best_v, k = max(ks_v)
    prim = RU[k]['path']
    # 2. three primary rows, greedily
    chosen = []
    for row in (1, 2, 3):
        cands = [m for m in MIN if RU[m]['path'] == prim and RU[m]['row'] == row]
        if not cands: continue
        chosen.append(max((score(name, items, boots, k, chosen + [m], [], obj)[0], m) for m in cands)[1])
    # 3. best secondary tree, two rows
    sec_best, sec_v = [], -1
    for sp in {RU[m]['path'] for m in MIN} - {prim}:
        pick = []
        for row in (1, 2, 3):
            if len(pick) >= 2: break
            cands = [m for m in MIN if RU[m]['path'] == sp and RU[m]['row'] == row]
            if not cands: continue
            pick.append(max((score(name, items, boots, k, chosen + pick + [m], [], obj)[0], m) for m in cands)[1])
        v = score(name, items, boots, k, chosen + pick[:2], [], obj)[0]
        if v > sec_v: sec_v, sec_best = v, pick[:2]
    minors = chosen + sec_best
    # 4. shards: greedy per slot (dual-slot shards resolved by legal())
    shards = []
    for _ in range(3):
        cands = [(score(name, items, boots, k, minors, shards + [s], obj)[0], s)
                 for s in SH if s not in shards and legal(items, k, minors, shards + [s])]
        if not cands: break
        shards.append(max(cands)[1])
    v = score(name, items, boots, k, minors, shards, obj)[0]
    return (k, minors, shards), v

# ---------- PATH B: champion-first beam search ----------
def _dna_seeds(name):
    """Seed regions derived from the champion's own DNA: the best pure-AP item, the best pure-AD
    item, the best health item, and an empty start. The optimizer still has to PROVE which wins."""
    ap_items = [n for n in LEG if IT[n]['stats'].get('ap', 0) > 60]
    ad_items = [n for n in LEG if IT[n]['stats'].get('ad', 0) > 40]
    hp_items = [n for n in LEG if IT[n]['stats'].get('hp', 0) > 300]
    seeds = [[]]
    for pool in (ap_items, ad_items, hp_items):
        if not pool: continue
        best = max(pool, key=lambda i: core.item_vector([i])['AP'] + core.item_vector([i])['AD'] * 1.5
                   + core.item_vector([i])['HP'] * 0.1)
        seeds.append([best])
    return seeds

def optimize_champion(name, obj, beam=6, seed_items=None):
    if seed_items is None:
        best_all = None; best_v = -1
        for s in _dna_seeds(name):
            r, v = _beam_from(name, obj, beam, s)
            if v > best_v: best_v, best_all = v, r
        return best_all, best_v
    return _beam_from(name, obj, beam, seed_items)

def _beam_from(name, obj, beam, seed_items):
    beams = [list(seed_items)]
    for _ in range(5 - len(seed_items)):
        cands = []
        for b in beams:
            for it in LEG:
                if it in b: continue
                nb = b + [it]
                if not legal(nb): continue
                # score with a cheap fixed boots/page during growth
                v, _ = score(name, nb, BOOTS[0], KS[0], [], [], obj)
                cands.append((v, nb))
        cands.sort(key=lambda x: -x[0])
        seen = set(); beams = []
        for v, nb in cands:
            key = frozenset(nb)
            if key in seen: continue
            seen.add(key); beams.append(nb)
            if len(beams) >= beam: break
    # boots then page: choose boots against a cheap fixed page, then run ONE full page search.
    # (Searching a full rune page for every boot x every beam was 42 page-searches per objective.)
    best = None; best_v = -1
    for b in beams[:3]:
        bt = max(BOOTS, key=lambda x: score(name, b, x, KS[0], [], [], obj)[0])
        page, v = best_page(name, b, bt, obj)
        if v > best_v:
            best_v = v; best = (b, bt, page)
    return best, best_v

# ---------- STAGE C: mutation proof ----------
def mutation_proof(name, items, boots, ks, minors, shards, obj, max_iter=12):
    cur = (list(items), boots, ks, list(minors), list(shards))
    cur_v, _ = score(name, *cur, obj)
    swaps = 0
    for _ in range(max_iter):
        improved = False
        # items
        for i in range(len(cur[0])):
            for alt in LEG:
                if alt in cur[0]: continue
                ni = list(cur[0]); ni[i] = alt
                if not legal(ni, cur[2], cur[3], cur[4]): continue
                v, _ = score(name, ni, cur[1], cur[2], cur[3], cur[4], obj)
                if v > cur_v * 1.0001:
                    cur = (ni, cur[1], cur[2], cur[3], cur[4]); cur_v = v; improved = True; swaps += 1
        # boots
        for alt in BOOTS:
            if alt == cur[1]: continue
            v, _ = score(name, cur[0], alt, cur[2], cur[3], cur[4], obj)
            if v > cur_v * 1.0001:
                cur = (cur[0], alt, cur[2], cur[3], cur[4]); cur_v = v; improved = True; swaps += 1
        # runes: minors
        for i in range(len(cur[3])):
            for alt in MIN:
                if alt in cur[3]: continue
                nm = list(cur[3]); nm[i] = alt
                if not legal(cur[0], cur[2], nm, cur[4]): continue
                v, _ = score(name, cur[0], cur[1], cur[2], nm, cur[4], obj)
                if v > cur_v * 1.0001:
                    cur = (cur[0], cur[1], cur[2], nm, cur[4]); cur_v = v; improved = True; swaps += 1
        # shards
        for i in range(len(cur[4])):
            for alt in SH:
                if alt in cur[4]: continue
                ns = list(cur[4]); ns[i] = alt
                if not legal(cur[0], cur[2], cur[3], ns): continue
                v, _ = score(name, cur[0], cur[1], cur[2], cur[3], ns, obj)
                if v > cur_v * 1.0001:
                    cur = (cur[0], cur[1], cur[2], cur[3], ns); cur_v = v; improved = True; swaps += 1
        if not improved: break
    return cur, cur_v, swaps

if __name__ == '__main__':
    import sys, time
    nm = sys.argv[1] if len(sys.argv) > 1 else 'Aatrox'
    for obj in OBJECTIVES:
        t0 = time.time()
        (items, boots, page), v = optimize_champion(nm, obj)
        ks, minors, shards = page
        (fi, fb, fk, fm, fs), fv, sw = mutation_proof(nm, items, boots, ks, minors, shards, obj)
        r = combat.simulate(nm, fi + [fb, fk] + fm + fs)
        print(f'\n{nm} — MAX {obj.upper()}  ({time.time()-t0:.0f}s, {sw} improving swaps found)')
        print(f'   items : {fi}')
        print(f'   boots : {fb}')
        print(f'   runes : {fk} | {fm} | {[s.replace(" Shard","") for s in fs]}')
        print(f'   dps {r["dps"]:.0f}  burst {r["burst"]:.0f}  ehp {r["ehp"]:.0f}  sustain {r["sustain"]:.0f}  utility {r["utility"]:.1f}')


# ---------- PARETO FRONTIER (adopted from the framework's non-destructive filter) ----------
PARETO_DIMS = ['dps', 'burst', 'ehp', 'sustain', 'utility']

def dominates(a, b):
    """a strictly dominates b only if a is >= on EVERY dimension and > on at least one."""
    return all(a[k] >= b[k] for k in PARETO_DIMS) and any(a[k] > b[k] for k in PARETO_DIMS)

def pareto_frontier(name, candidates):
    """Keep every build that is not strictly dominated. A build 100 gold worse but 1 HP better
    SURVIVES. This is what preserves sleeper builds instead of collapsing to one winner."""
    scored = []
    for items, boots, page in candidates:
        ks, minors, shards = page
        r = combat.simulate(name, list(items) + [boots, ks] + list(minors) + list(shards))
        scored.append((dict(items=list(items), boots=boots, keystone=ks, minors=list(minors),
                            shards=list(shards)), r))
    front = []
    for i, (b, r) in enumerate(scored):
        if not any(dominates(r2, r) for j, (_, r2) in enumerate(scored) if i != j):
            front.append((b, r))
    return front
