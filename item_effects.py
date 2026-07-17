"""LOE v2 — ITEM EFFECT COMPILER (decoder-based).
Rebuilt on wiki_decode. The difference is structural, not cosmetic:

  OLD (regex):  hunt for '50%' near the word 'health' -> Serylda's Grudge appeared to deal 50% of
                the target's max health per ability, and topped all 171 builds.
  NEW (typed):  the wiki writes every real payload as {{as|VALUE|TYPE}}. A value carrying a TYPE
                ('physical damage', 'magic damage', 'shield', 'heal') is a payload. A value with
                NO type is a condition, a duration or a threshold — never damage.

That discriminator is what regex could not see, and it is why this was worth rebuilding.
Trigger detection reads the DECODED plain text, so tooltip wrappers can no longer hide a keyword.
Any template the decoder does not know is REPORTED — a future patch adding markup shows up loudly.
"""
import json, re
import wiki_decode as W

IT = json.load(open('item_dna.json'))
DMG_ITEMS = json.load(open('damage_dna.json'))['items']

TEXT_TYPE = re.compile(r'\b(physical|magic|true)\s+damage\b', re.I)
# A percentage is a HEALTH payload only when the prose binds it to health. "reduces armor by 30%"
# is not "30% of max health as damage" — that conflation made Black Cleaver a nuke.
HEALTH_PCT = re.compile(
    r"([\d.]+)\s*%\s*of\s+(?:the\s+)?(?:target'?s?|their|its|your|enemy'?s?)?\s*"
    r"(maximum|max|current|bonus)?\s*health", re.I)

def declared_type(dec_text, item):
    """The damage type, from three authorities in order of reliability:
       1. an {{as|VALUE|TYPE}} span   2. the plain prose   3. Module:DamageData"""
    m = TEXT_TYPE.search(dec_text)
    if m: return m.group(1).capitalize()
    for v in DMG_ITEMS.get(item, {}).values():
        if v.get('type'): return v['type']
    return None

DAMAGE_TYPES = ('physical damage', 'magic damage', 'true damage', 'adaptive damage')


def payload_type(vtype):
    v = (vtype or '').lower()
    if any(t in v for t in DAMAGE_TYPES):
        return ('Physical' if 'physical' in v else 'Magic' if 'magic' in v
                else 'True' if 'true' in v else 'Adaptive')
    if 'shield' in v: return 'SHIELD'
    if 'heal' in v: return 'HEAL'
    return None


TRIGGERS = [
    ('ON_HIT',        r'on-hit|basic attacks?[^.]{0,40}(?:deal|appl|grant)'),
    ('ON_ABILITY',    r'dealing\s+ability damage|damaging (?:ability|spell)|ability (?:hit|damage) to|'
                      r'after (?:using|casting)|abilities? (?:deal|apply)'),
    ('ON_CRIT',       r'critical strikes?'),
    ('ON_TAKEDOWN',   r'takedowns?|killing an enemy|champion kills?'),
    ('ON_IMMOBILIZE', r'immobilis|immobiliz'),
    ('PERIODIC',      r'every \d+|each second|periodically|per second'),
    ('ON_LOW_HEALTH', r'(?:below|under) \d+%[^.]{0,20}health|lifeline'),
    ('AURA',          r'nearby (?:allies|enemies)'),
    ('ALWAYS',        r'.'),
]


def detect_trigger(text):
    t = text.lower()
    return next(name for name, rx in TRIGGERS if re.search(rx, t))


MULT_RX = re.compile(r'increase[sd]?\s+(?:your\s+)?(ability power|attack damage|armor|magic resist|'
                     r'health|attack speed)\s+by\s+([\d.]+)\s*%', re.I)
# two phrasings occur: "X% of your bonus mana as ability power" and
# "Grants ability power equal to X% bonus mana"
CONV_RX = re.compile(r'([\d.]+)\s*%\s*(?:of\s+)?(?:your\s+)?(?:bonus\s+)?(?:maximum\s+)?(mana|health)'
                     r'[^.]{0,60}?as\s+(?:bonus\s+)?(ability power|attack damage)', re.I)
CONV_RX_B = re.compile(r'grants?\s+(ability power|attack damage)\s+equal to\s+([\d.]+)\s*%'
                       r'[^.]{0,30}?(mana|health)', re.I)
AMP_RX = re.compile(r'([\d.]+)\s*%\s*(?:increased|more|amplified|bonus)\s+'
                    r'(magic |physical |true |all )?damage', re.I)
SHRED_RX = re.compile(r'(?:reduce[sd]?[^.]{0,50}?(armor|magic resist)[^.]{0,30}?by\s*([\d.]+)\s*%)|'
                      r'(?:([\d.]+)\s*%[^.]{0,30}?(armor|magic resist)\s+reduction)', re.I)
STAT_KEY = {'ability power': 'AP', 'attack damage': 'AD', 'armor': 'ARMOR',
            'magic resist': 'MR', 'health': 'HP', 'attack speed': 'AS'}


def compile_item(name):
    d = IT.get(name)
    if not d: return [], []
    nodes, unmodelled = [], []
    for e in d['effects']:
        dec = W.decode(e.get('raw', ''))
        text = dec['text']
        trig = detect_trigger(text)
        made = False

        # --- collect typed values ---
        payloads, untyped = [], []
        for v in dec['values']:
            if v['kind'] != 'typed': continue
            pt = payload_type(v.get('vtype'))
            if pt and v.get('value') is not None:
                payloads.append((pt, v['value'], bool(v.get('pct'))))
            elif v.get('value') is not None:
                untyped.append((v['value'], bool(v.get('pct'))))
        # The effect declares its damage type ONCE; the number may live in a different span.
        # (BotRK: one span says 'physical damage', another says '9% of current health'.)
        declared = next((pt for pt, _, _ in payloads if pt in ('Physical', 'Magic', 'True', 'Adaptive')), None)
        if declared is None:
            declared = declared_type(text, name)

        # --- 1. AMPLIFIER first: "take 12% increased magic damage" is NOT a payload ---
        is_amp = bool(re.search(r'(?:increased|more|amplified)\s+(?:magic |physical |true |all )?damage|'
                                r'take[^.]{0,20}(?:increased|more)\s+damage', text, re.I))
        if is_amp:
            am = AMP_RX.search(text)
            if am:
                v = float(am.group(1)) / 100.0
                if 0 < v <= 0.35:
                    nodes.append(dict(item=name, name=e['name'], source='decoded', hook='AMP',
                                      op='damage_amp', value=v,
                                      magic_only=bool(am.group(2) and 'magic' in am.group(2).lower())))
                    made = True

        # --- 2. damage payload (typed, or untyped number under a declared type) ---
        if not made and declared:
            dmg = [(t, val, p) for t, val, p in payloads
                   if t in ('Physical', 'Magic', 'True', 'Adaptive')]
            flat = max((v for t, v, p in dmg if not p), default=0.0)
            if not flat:
                flat = max((v for v, p in untyped if not p), default=0.0)
            # a %-health payload must be BOUND to health in the prose
            hm = HEALTH_PCT.search(text)
            pct = float(hm.group(1)) / 100.0 if hm else 0.0
            which = (hm.group(2) or 'maximum').lower() if hm else ''
            self_hp = bool(hm) and bool(re.search(r'your\s+(?:bonus\s+)?(?:maximum\s+)?health|wielder',
                                                  text, re.I))
            cur_hp = which == 'current'
            if flat or pct:
                stacking = bool(re.search(r'up to \d+ stacks?[^.]{0,90}next basic attack|at \d+ stacks',
                                          text, re.I))
                nodes.append(dict(item=name, name=e['name'], source='decoded', op='damage',
                                  hook=('ON_HIT' if trig == 'ON_HIT' else
                                        'ON_ABILITY' if trig == 'ON_ABILITY' else trig),
                                  dtype=declared, flat=flat,
                                  pct_max_hp=(pct if (pct and not self_hp and not cur_hp) else 0.0),
                                  pct_cur_hp=(pct if cur_hp else 0.0),
                                  self_hp=(pct if self_hp else 0.0),
                                  every=3 if stacking else 1, icd=e.get('icd', 0.0) or 0.0))
                made = True

        # --- 3. shields / heals ---
        shields = [(val, p) for t, val, p in payloads if t == 'SHIELD']
        heals = [(val, p) for t, val, p in payloads if t == 'HEAL']
        if shields and not made:
            val, p = max(shields)
            nodes.append(dict(item=name, name=e['name'], source='decoded', hook='DEFENSE',
                              op='shield_pct_hp' if p else 'shield_flat',
                              value=(val / 100.0 if p else val)))
            made = True
        if heals and not made:
            val, p = max(heals)
            nodes.append(dict(item=name, name=e['name'], source='decoded', hook='SUSTAIN',
                              op='heal', value=(val * 20 if p else val)))
            made = True

        m = MULT_RX.search(text)
        if m:
            st = STAT_KEY.get(m.group(1).lower())
            if st:
                nodes.append(dict(item=name, name=e['name'], source='decoded', hook='ALWAYS',
                                  op='mult_stat', stat=st, value=float(m.group(2)) / 100.0))
                made = True
        cm = CONV_RX.search(text)
        cb = CONV_RX_B.search(text) if not cm else None
        if cm:
            nodes.append(dict(item=name, name=e['name'], source='decoded', hook='ALWAYS', op='convert',
                              frm=('MANA' if 'mana' in cm.group(2).lower() else 'HP'),
                              to=('AP' if 'ability' in cm.group(3).lower() else 'AD'),
                              value=float(cm.group(1)) / 100.0))
            made = True
        elif cb:
            nodes.append(dict(item=name, name=e['name'], source='decoded', hook='ALWAYS', op='convert',
                              frm=('MANA' if 'mana' in cb.group(3).lower() else 'HP'),
                              to=('AP' if 'ability' in cb.group(1).lower() else 'AD'),
                              value=float(cb.group(2)) / 100.0))
            made = True
        sm = SHRED_RX.search(text)
        if sm and not made:
            g = [x for x in sm.groups() if x]
            num = next((float(x) for x in g if x.replace('.', '').isdigit()), None)
            which = next((x.lower() for x in g if not x.replace('.', '').isdigit()), '')
            if num:
                nodes.append(dict(item=name, name=e['name'], source='decoded', hook='ALWAYS', op='shred',
                                  armor=num * 0.8 if 'armor' in which else 0.0,
                                  mr=num * 0.8 if 'magic' in which else 0.0))
                made = True
        # ---- effect FAMILIES: recurring named passives whose numbers are in the decoded text ----
        # Modeling the family once benefits every item that shares it (Lich Bane/Iceborn/Dusk = Spellblade).
        ename = (e.get('name') or '').lower()
        if not made:
            # SPELLBLADE: after an ability, next attack deals bonus on-hit (base-AD + AP scaling)
            if 'spellblade' in ename or ('next basic attack' in text.lower() and 'ability' in text.lower()):
                base_ad = re.search(r'([\d.]+)\s*%\s*base\s*AD', text, re.I)
                ap = re.search(r'\+\s*([\d.]+)\s*%\s*AP', text, re.I)
                if base_ad or ap:
                    nodes.append(dict(item=name, name=e['name'], source='family:spellblade',
                                      hook='ON_ABILITY', op='spellblade',
                                      base_ad=float(base_ad.group(1))/100 if base_ad else 0.0,
                                      ap=float(ap.group(1))/100 if ap else 0.0,
                                      dtype='Magic')); made = True
            # GRIEVOUS WOUNDS: applies healing reduction to enemies (an anti-heal debuff)
            elif 'grievous' in ename or 'grievous wounds' in text.lower():
                nodes.append(dict(item=name, name=e['name'], source='family:grievous',
                                  hook='ALWAYS', op='antiheal', value=0.40)); made = True
            # LIFELINE: a shield when you take damage that would drop you low (effective health)
            elif 'lifeline' in ename or ('shield' in text.lower() and 'below' in text.lower()):
                sh = re.search(r'shield[^.]{0,80}?([\d.]{2,4})', text, re.I)
                nodes.append(dict(item=name, name=e['name'], source='family:lifeline',
                                  hook='DEFENSE', op='shield_flat',
                                  value=float(sh.group(1)) if sh else 300.0)); made = True
            # CLEAVE: on-hit AoE damage scaling with the WIELDER'S own attack/health
            elif 'cleave' in ename:
                pct = re.search(r'([\d.]+)\s*%[^.]{0,30}?(?:total\s+)?attack damage', text, re.I)
                nodes.append(dict(item=name, name=e['name'], source='family:cleave',
                                  hook='ON_HIT', op='damage', dtype='Physical',
                                  flat=0.0, pct_max_hp=0.0, pct_cur_hp=0.0,
                                  ad_ratio=float(pct.group(1))/100 if pct else 0.4, every=1)); made = True
            # ANNUL: spell shield that blocks the next enemy ability (small effective magic EHP)
            elif 'annul' in ename or 'spell shield' in text.lower() or 'spellshield' in text.lower():
                nodes.append(dict(item=name, name=e['name'], source='family:spellshield',
                                  hook='DEFENSE', op='spellshield', value=0.0)); made = True

        if not made and e.get('name'):
            unmodelled.append(e['name'])
    return nodes, unmodelled


LIMITS = dict(pct_max_hp=0.10, pct_cur_hp=0.12, flat=400.0, value=0.60, heal=600.0, shield_pct=0.40)


def sane(n):
    if n.get('pct_max_hp', 0) > LIMITS['pct_max_hp']:
        return False, f"{n['item']}/{n.get('name')}: {n['pct_max_hp']:.0%} max-HP per proc"
    if n.get('pct_cur_hp', 0) > LIMITS['pct_cur_hp']:
        return False, f"{n['item']}/{n.get('name')}: {n['pct_cur_hp']:.0%} current-HP per proc"
    if n.get('flat', 0) > LIMITS['flat']:
        return False, f"{n['item']}/{n.get('name')}: {n['flat']:.0f} flat damage per proc"
    if n['op'] == 'heal' and n.get('value', 0) > LIMITS['heal']:
        return False, f"{n['item']}/{n.get('name')}: {n['value']:.0f} heal per proc"
    if n['op'] == 'damage_amp' and n.get('value', 0) > LIMITS['value']:
        return False, f"{n['item']}/{n.get('name')}: {n['value']:.0%} damage amp"
    if n['op'] == 'shield_pct_hp' and n.get('value', 0) > LIMITS['shield_pct']:
        return False, f"{n['item']}/{n.get('name')}: {n['value']:.0%} shield"
    return True, None


# Overrides: ONLY mechanics the wiki does not state in decodable form. Now a short list.
OVERRIDES = {
    "Guinsoo's Rageblade": [dict(hook='ON_HIT', op='phantom_hit', value=0.5,
        why='Every third attack applies on-hit effects TWICE — a proc-on-proc the generic path cannot express.')],
    'Infinity Edge': [dict(hook='ON_CRIT', op='crit_damage', value=0.40,
        why='Increases critical strike DAMAGE — must multiply the crit term, not add damage.')],
    "Jak'Sho, The Protean": [dict(hook='ALWAYS', op='stacking_resists', value=30.0,
        why='Resists stack over a fight to a plateau.')],
    "Death's Dance": [dict(hook='DEFENSE', op='damage_reduction', value=0.30,
        why='Defers a share of post-mitigation damage as a bleed.')],
    "Randuin's Omen": [dict(hook='DEFENSE', op='crit_reduction', value=0.30,
        why='Reduces incoming critical damage.')],
    "Warmog's Armor": [dict(hook='PERIODIC', op='regen_pct_hp', value=0.025,
        why='Percentage max-health regeneration.')],
    'Titanic Hydra': [dict(hook='ON_HIT', op='damage', dtype='Physical', flat=0.0, name='Cleave',
        pct_max_hp=0.0, pct_cur_hp=0.0, self_hp=0.015, every=1, icd=0.0,
        why="Cleave scales with the WIELDER'S max health; the prose is ambiguous and the decoder "
            "defaults %-health payloads to the target.")],
}

COMPILED, UNMODELLED, REJECTED = {}, {}, []
for _n in IT:
    if _n in OVERRIDES:
        _nodes = [dict(o, item=_n, source='override') for o in OVERRIDES[_n]]
        _un = []
    else:
        _nodes, _un = compile_item(_n)
    _keep = []
    for _nd in _nodes:
        _ok, _why = sane(_nd)
        if _ok: _keep.append(_nd)
        else:
            REJECTED.append(_why)
            _un.append(_nd.get('name') or _nd['op'])
    if _keep: COMPILED[_n] = _keep
    if _un: UNMODELLED[_n] = _un


def build_nodes(pieces):
    out = []
    for p in pieces:
        out.extend(COMPILED.get(p, []))
    return out


if __name__ == '__main__':
    import core
    from collections import Counter
    leg = core.LEGENDARIES
    modelled = sum(1 for n in leg if n in COMPILED or not IT[n]['effects'])
    print(f'SR legendaries modelled: {modelled}/{len(leg)} ({modelled/len(leg):.0%})')
    print(f'hooks: {dict(Counter(n["hook"] for nn in COMPILED.values() for n in nn))}')
    print(f'sources: {dict(Counter(n["source"] for nn in COMPILED.values() for n in nn))}')
    print(f'sanity gate rejected: {len(REJECTED)}')
    for r in REJECTED[:5]: print(f'   {r}')
    print(f'unknown wiki templates: {W.coverage_report()["unknown_total"]}')
    print('\n--- the items that used to be wrong ---')
    for n in ["Serylda's Grudge", "Rabadon's Deathcap", 'Kraken Slayer', 'Blackfire Torch',
              "Archangel's Staff", 'Blade of the Ruined King']:
        c = COMPILED.get(n)
        if not c: print(f'   {n:24s} — no passive modelled'); continue
        for x in c:
            keys = {k: v for k, v in x.items() if k not in ('item', 'why', 'source', 'name') and v}
            print(f'   {n:24s} {x["op"]:12s} {keys}')
