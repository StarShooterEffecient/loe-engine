"""LOE v2 — NAMED ITEM EFFECTS.
The wiki's 'Named item effect' article describes every named passive in the game — including the 60
legendaries whose in-item text the decoder couldn't fully compile. This parses that article into a
lookup {effect_name: description} and classifies the recurring EFFECT FAMILIES (spell shield,
grievous wounds, heal->shield, spellblade, execute...) that are behaviours rather than raw numbers.

This is how we 'get better at decoding everything': not by hand-writing each item, but by teaching
the engine the wiki's own effect vocabulary once, so every item that shares an effect inherits it.
"""
import re, json, sqlite3
import wiki_decode as W

cx = sqlite3.connect('wiki.db'); C = cx.cursor()
ART = C.execute("SELECT text FROM pages WHERE title='Named item effect'").fetchone()
ART = ART[0] if ART else ''

# ---- parse the article's tables into {name: (description, [items])} ----
NAMED = {}
for m in re.finditer(r"\|\s*\{\{anchor\|[^}]*\}\}'''([^']+)'''\s*\n\|(.*?)\n\|((?:\s*\{\{ii\|[^}]+\}\}(?:<br\s*/?>)?)*)",
                     ART, re.S):
    name = m.group(1).strip()
    desc = W.decode(m.group(2).strip())['text']
    items = re.findall(r'\{\{ii\|([^}|]+)', m.group(3))
    NAMED[name] = dict(desc=desc, items=[i.strip() for i in items])

json.dump(NAMED, open('named_effects.json', 'w'), indent=1)

# ---- effect-family classifier: behaviours the combat model can honor ----
FAMILIES = [
    ('SPELLSHIELD',  r'spell ?shield|blocks the next (?:hostile |enemy )?ability', dict(hook='DEFENSE', op='spellshield', ehp_bonus=0.06)),
    ('GRIEVOUS',     r'grievous wounds', dict(hook='AMP', op='antiheal', value=0.0)),
    ('HEAL_TO_SHIELD', r'excess healing.*shield|convert.*healing.*shield', dict(hook='DEFENSE', op='overheal_shield', value=0.10)),
    ('SPELLBLADE',   r'after casting an ability.*next basic attack.*bonus damage', dict(hook='ON_ABILITY', op='spellblade', value=1.0)),
    ('EXECUTE',      r'execute|true damage.*missing health|if.*would kill', dict(hook='ON_ABILITY', op='execute', value=0.10)),
    ('ENERGIZED',    r'energized|moving and attacking build', dict(hook='ON_HIT', op='energized', value=40.0)),
    ('SHRED_AURA',   r'reduc\w+ (?:the )?(?:armor|magic resist).*nearby|curse.*resist', dict(hook='ALWAYS', op='shred_aura', value=0.0)),
    ('DErive_SHIELD', r'grant.*shield.*(?:ally|allies)|shield.*nearby', dict(hook='DEFENSE', op='ally_shield', value=0.05)),
    ('SLOW',         r'\bslow(?:s|ing)?\b', dict(hook='AMP', op='slow_amp', value=0.02)),
    ('BURN',         r'burn|damage over \d|per second for', dict(hook='ON_ABILITY', op='burn', value=0.0)),
]


def classify_named(effect_name):
    """Return an effect-family node for a named effect, or None if it's not a family we honor."""
    rec = NAMED.get(effect_name)
    if not rec: return None
    d = rec['desc'].lower()
    for fam, rx, node in FAMILIES:
        if re.search(rx, d):
            out = dict(node); out['family'] = fam; out['from'] = effect_name
            return out
    return None


if __name__ == '__main__':
    print(f'named effects parsed from the wiki article: {len(NAMED)}')
    from collections import Counter
    fam = Counter()
    for name in NAMED:
        c = classify_named(name)
        if c: fam[c['family']] += 1
    print(f'effects classified into families: {sum(fam.values())}')
    print(f'family distribution: {dict(fam)}')
    print('\nunclassified named effects (still just numbers or unique mechanics):')
    un = [n for n in NAMED if not classify_named(n)]
    print(f'  {len(un)} of {len(NAMED)}')
    for n in un[:12]:
        print(f'   {n:22s} {NAMED[n]["desc"][:70]}')
