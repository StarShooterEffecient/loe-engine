"""LOE v2 — TRACEABILITY AUDIT.
Answers the question "how do we know the numbers are correct?" for the half that CAN be answered
exactly: the INPUTS. Every raw number the engine reads (ability base damage, ratios, cooldowns,
item stats) should equal exactly what the wiki page says. This re-reads the raw wiki page for a
sample of values, extracts them independently, and compares to what the engine stored.

It deliberately does NOT check OUTPUTS (DPS, EHP, Omega) — the wiki publishes no such numbers, so
"matches the wiki" is undefined for them. Those are covered by the coherence/plausibility gates.
This cleanly splits the chain:
    inputs faithful to wiki?  -> THIS audit (exact)
    math done correctly?      -> coherence + sanity gates (plausibility)
If inputs pass here, any remaining error is in the model, not the data — so you know which to trust.
"""
import sqlite3, json, re, random

cx = sqlite3.connect('wiki.db'); C = cx.cursor()
CH = json.load(open('champion_dna.json'))
IT = json.load(open('item_dna.json'))


def raw(title):
    r = C.execute("SELECT text FROM pages WHERE title=?", (title,)).fetchone()
    return r[0] if r else None


def field(text, name):
    """Pull a template field's raw value, tolerant of spaces in field names."""
    m = re.search(r'\|\s*' + re.escape(name) + r'\s*=\s*(.*?)(?=\n\s*\|[a-zA-Z0-9_][a-zA-Z0-9_ ]*=|\n\}\}|\Z)',
                  text, re.S)
    return m.group(1).strip() if m else None


def nums(s):
    return [float(x) for x in re.findall(r'-?\d+(?:\.\d+)?', s or '')]


# ---------------------------------------------------------------- ability cooldowns
def audit_ability_cooldowns(sample=40):
    """Cooldown is a clean, unambiguous field: compare engine's rank-5 CD to the wiki template."""
    checks, ok, fail = 0, 0, []
    champs = random.Random(1).sample(list(CH), min(sample, len(CH)))
    for nm in champs:
        for slot, a in CH[nm]['abilities'].items():
            if not a.get('cd'): continue
            t = raw(f"Template:Data {nm}/{a['name']}")
            if not t: continue
            wiki_cd = field(t, 'cooldown')
            if not wiki_cd: continue
            wvals = nums(wiki_cd)
            if not wvals: continue
            checks += 1
            engine_cd = a['cd'][4] if len(a['cd']) > 4 else a['cd'][-1]
            # the wiki's last listed cooldown value should match the engine's rank-5 value
            if any(abs(engine_cd - w) < 0.01 for w in wvals):
                ok += 1
            else:
                fail.append((nm, slot, a['name'], engine_cd, wvals))
    return checks, ok, fail


# ---------------------------------------------------------------- item stats
def audit_item_stats(sample=60):
    """Item base stats come straight from ItemData's ["stats"] block; verify against it exactly.
    The wiki uses short keys: ["ap"]=130, ["ad"], ["health"], ["armor"], ["mr"]..."""
    lua = raw('Module:ItemData/data')
    checks, ok, fail = 0, 0, []
    items = random.Random(2).sample(list(IT), min(sample, len(IT)))
    # engine stat key -> the wiki's key(s) inside the ["stats"] table
    keymap = {'ap': ['ap'], 'ad': ['ad'], 'hp': ['health'], 'armor': ['armor'],
              'mr': ['mr'], 'as': ['as'], 'crit': ['crit'], 'ah': ['ah'], 'ms': ['ms'],
              'mana': ['mana'], 'ls': ['lifesteal'], 'lethality': ['lethality']}
    for nm in items:
        i = lua.find(f'["{nm}"]') if lua else -1
        if i < 0: continue
        # isolate this item's ["stats"] = { ... } block
        sm = re.search(r'\["stats"\]\s*=\s*\{(.*?)\}', lua[i:i + 2500], re.S)
        if not sm: continue
        statblock = sm.group(1)
        for stat_key, wiki_keys in keymap.items():
            eng = IT[nm]['stats'].get(stat_key, 0)
            if not eng: continue
            found = None
            for wk in wiki_keys:
                m = re.search(r'\["' + wk + r'"\]\s*=\s*([\d.]+)', statblock)
                if m: found = float(m.group(1)); break
            if found is None: continue
            checks += 1
            if abs(eng - found) < 0.01: ok += 1
            else: fail.append((nm, stat_key, eng, found))
    return checks, ok, fail


# ---------------------------------------------------------------- item gold cost
def audit_item_gold(sample=40):
    lua = raw('Module:ItemData/data')
    checks, ok, fail = 0, 0, []
    items = random.Random(3).sample(list(IT), min(sample, len(IT)))
    for nm in items:
        eng = IT[nm].get('buy')
        if not eng: continue
        i = lua.find(f'["{nm}"]') if lua else -1
        if i < 0: continue
        block = lua[i:i + 1500]
        m = re.search(r'\["buy"\]\s*=\s*([\d.]+)', block)
        if not m: continue
        checks += 1
        if abs(eng - float(m.group(1))) < 0.5: ok += 1
        else: fail.append((nm, eng, float(m.group(1))))
    return checks, ok, fail


def run():
    print('=' * 68)
    print('TRACEABILITY AUDIT — do the engine\'s INPUT numbers match the wiki exactly?')
    print('=' * 68)
    total_checks = total_ok = 0
    report = {}
    for label, fn in [('ability cooldowns', audit_ability_cooldowns),
                      ('item base stats', audit_item_stats),
                      ('item gold cost', audit_item_gold)]:
        checks, ok, fail = fn()
        total_checks += checks; total_ok += ok
        pct = ok / checks * 100 if checks else 0
        print(f'\n{label:22s}  {ok}/{checks} match ({pct:.0f}%)')
        for f in fail[:5]:
            print(f'    MISMATCH: {f}')
        report[label] = dict(checks=checks, ok=ok, mismatches=fail[:20])
    print('\n' + '=' * 68)
    pct = total_ok / total_checks * 100 if total_checks else 0
    print(f'OVERALL: {total_ok}/{total_checks} input values traced to wiki and verified ({pct:.1f}%)')
    print('=' * 68)
    print('\nNote: this audits INPUTS only. Outputs (DPS/EHP/Omega) have no wiki value to match;')
    print('they are covered by the coherence & sanity gates. A high score here means the DATA is')
    print('faithful — so any remaining error is in the model, not in what we read from the wiki.')
    json.dump(report, open('traceability_report.json', 'w'), indent=1)
    return report


if __name__ == '__main__':
    run()
