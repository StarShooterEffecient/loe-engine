"""LOE v2 — KIT PROFILE.
The bug that produced 152 coherence violations (Ahri, an AP mage, being bought 175 AD):
the combat model let EVERY champion auto-attack for 85% of the fight at capped attack speed.
Nothing in it knew that Ahri's kit has no on-hit ability, no attack-speed amp, no auto reset —
that her autos are incidental and her abilities ARE her damage.

The fix cannot be a fudge factor. It must be DERIVED FROM THE KIT — from the champion's own DNA,
never from roles, meta, or opinion. Every signal below is read from the wiki:

  AUTO RELIANCE   does the kit REWARD auto-attacking?
    + an ability that triggers on-hit events        (DamageData)
    + an ability that amplifies attack speed        (parsed amps)
    + an auto-attack reset                          (ability tags)
    + an on-hit innate passive                      (passive tags)
    + high attack-speed growth per level            (ChampionData as_lvl)
    + a kit whose damage scales with total AD       (ratios)

  ABILITY RELIANCE  does the kit reward casting?
    + total damage ratios across Q/W/E/R
    + short mean cooldown (more casts per fight)
    + multi-cast abilities
    + a resource pool sized for casting

A champion sits somewhere on that line, and the fight window is spent accordingly.
Master Yi is nearly all autos. Ahri is nearly all abilities. Aatrox is genuinely both.
The model must reflect that, or it will hand a mage a Kraken Slayer and call it optimal.
"""
import json, math

CH = json.load(open('champion_dna.json'))


def kit_profile(name):
    c = CH[name]
    ab = c['abilities']
    s = c['stats']

    # ---------- signals that the kit REWARDS auto-attacking ----------
    auto_sig = 0.0
    onhit_abilities = sum(1 for a in ab.values() if a.get('triggers_onhit') or a.get('onhit_flag'))
    if onhit_abilities: auto_sig += 2.0 + 0.5 * (onhit_abilities - 1)
    passive = ab.get('I')
    if passive and 'on_hit' in (passive.get('tags') or []): auto_sig += 2.0
    as_amp = 0.0
    for a in ab.values():
        rec = (a.get('amps') or {}).get('as')
        if rec:
            v = rec['values'][4] if isinstance(rec, dict) else rec
            as_amp = max(as_amp, v)
    if as_amp: auto_sig += 1.5 + min(1.5, as_amp / 40.0)
    # An attack RESET only counts if the ability actually involves attacking (Riven Q, Nasus Q).
    # Seraphine's passive/ult carry a 'reset' tag for ability echoes, not auto-attack resets —
    # crediting those made a support mage look ~40% auto-reliant and bought her AS/crit items.
    def real_attack_reset(a):
        tags = a.get('tags') or []
        if 'reset' not in tags: return False
        return bool(a.get('triggers_onhit') or a.get('onhit_flag')
                    or (a.get('ad_total') or 0) or (a.get('ad_bonus') or 0)
                    or 'on_hit' in tags)
    if any(real_attack_reset(a) for a in ab.values()): auto_sig += 1.5
    # ChampionData: a kit built to auto-attack grows attack speed
    auto_sig += min(1.5, s['as_lvl'] / 3.0)
    # total-AD scaling means items bought for autos also feed the kit
    ad_total = sum(a.get('ad_total', 0) or 0 for a in ab.values())
    auto_sig += min(1.5, ad_total * 0.6)

    # ---------- signals that the kit REWARDS casting ----------
    ability_sig = 0.0
    ratio_mass = sum((a.get('ap', 0) or 0) + (a.get('ad_total', 0) or 0) + (a.get('ad_bonus', 0) or 0)
                     + 6.0 * (a.get('max_hp', 0) or 0) for k, a in ab.items() if k != 'I')
    # Heal and shield AP scaling is ability power the kit genuinely uses. Ignoring it made enchanters
    # and support mages (Seraphine, Soraka, Lulu) look far less ability-reliant than they are.
    for k, a in ab.items():
        if k == 'I': continue
        ratio_mass += (a.get('heal_ap', 0) or 0) + (a.get('heal_ad', 0) or 0)
        for e in (a.get('effects') or []):
            if e.get('kind') in ('SHIELD', 'SUSTAIN'):
                ratio_mass += (e.get('ap', 0) or 0) + (e.get('ad_total', 0) or 0)
    ability_sig += min(4.0, ratio_mass * 1.1)
    cds = [a['cd'][4] for k, a in ab.items() if k in 'QWE' and a.get('cd')]
    if cds:
        mean_cd = sum(cds) / len(cds)
        ability_sig += max(0.0, min(2.5, (14.0 - mean_cd) / 4.0))     # short cooldowns -> cast-centric
    ability_sig += 0.4 * sum((a.get('casts', 1) or 1) - 1 for a in ab.values())
    n_dmg = sum(1 for k, a in ab.items() if k != 'I' and (a.get('base') or a.get('ap')
                or a.get('ad_total') or a.get('ad_bonus')))
    ability_sig += 0.35 * n_dmg

    total = auto_sig + ability_sig
    auto_reliance = auto_sig / total if total else 0.5

    return dict(auto_signal=round(auto_sig, 2), ability_signal=round(ability_sig, 2),
                auto_reliance=round(auto_reliance, 3),
                onhit_abilities=onhit_abilities, as_amp=as_amp,
                ratio_mass=round(ratio_mass, 2))


# ---------- the fight window is SPENT according to the kit ----------
def auto_uptime(name, ranged=None):
    """Fraction of the fight this kit actually spends auto-attacking.
    A kit with zero auto-synergy still throws some autos between casts — but it does not stand
    at the attack-speed cap for 13 of 15 seconds, which is what produced the Ahri-buys-AD bug."""
    p = kit_profile(name)
    r = p['auto_reliance']
    base = 0.90 if (CH[name]['stats']['range'] >= 350 if ranged is None else ranged) else 0.75
    # floor 0.06 (a caster throws the odd auto, no more), ceiling `base` (a true auto-attacker).
    # The exponent 1.7 makes the curve steep: only genuinely auto-reliant kits get meaningful auto
    # value. The old 0.18 floor / 1.35 exponent had Ahri "auto-attacking" 22% of a fight, which made
    # 35 AD + 25% crit items score well on pure mages and converged half the roster onto them.
    return round(0.06 + (base - 0.06) * (r ** 1.7), 3)


# ---------- OMEGA: the kit-weighted composite ("maximize THIS champion") ----------
# Objectives stay separate and are all reported. Omega is an ADDITIONAL answer to the question
# "which single build lifts the most of what THIS kit does?" — with weights read from the kit,
# never chosen by hand.
def omega_weights(name):
    c = CH[name]; ab = c['abilities']
    p = kit_profile(name)
    ap = sum(a.get('ap', 0) or 0 for a in ab.values())
    ad = sum((a.get('ad_total', 0) or 0) + (a.get('ad_bonus', 0) or 0) for a in ab.values())
    heal = sum((a.get('heal_ap', 0) or 0) + (a.get('heal_ad', 0) or 0) for a in ab.values())
    vamp = max([a.get('vamp', 0) or 0 for a in ab.values()] + [0])
    hp_scale = sum(a.get('max_hp', 0) or 0 for a in ab.values())
    cc = sum(1 for a in ab.values() if 'cc' in (a.get('tags') or []))
    shield = sum(1 for a in ab.values() if 'shield' in (a.get('tags') or []))

    w = dict(
        # sustained damage matters more to a kit that keeps hitting
        dps=1.0 + 0.6 * p['auto_reliance'],
        # burst matters more to a kit with big ratios and long cooldowns
        burst=0.6 + 0.5 * min(2.0, (ap + ad)) / 2.0,
        # durability matters to a kit that scales WITH health or must survive to keep casting
        ehp=0.35 + 2.5 * hp_scale + (0.35 if vamp else 0),
        # sustain matters to a kit that heals or converts damage to health
        sustain=0.25 + 1.6 * min(1.5, heal) + 2.2 * vamp,
        # utility matters to a kit that brings CC and shields
        utility=0.2 + 0.14 * cc + 0.16 * shield,
    )
    tot = sum(w.values())
    return {k: round(v / tot, 4) for k, v in w.items()}


if __name__ == '__main__':
    print(f'{"champion":14s} {"auto":>6s} {"abil":>6s} {"reliance":>9s} {"uptime":>7s}   omega weights')
    for nm in ['Master Yi', 'Aatrox', 'Ahri', "Vel'Koz", 'Ornn', 'Jhin', 'Soraka', 'Vladimir', 'Garen', 'Kai\'Sa']:
        if nm not in CH: continue
        p = kit_profile(nm); u = auto_uptime(nm); w = omega_weights(nm)
        ws = ' '.join(f'{k[:3]}{v:.2f}' for k, v in w.items())
        print(f'{nm:14s} {p["auto_signal"]:6.2f} {p["ability_signal"]:6.2f} {p["auto_reliance"]:9.2f} {u:7.2f}   {ws}')


# ---------------------------------------------------------------------------
# STAT AFFINITY — how much of a stat this champion's KIT can actually convert
# into output, derived entirely from DNA (no meta, no hand-authored per-champion lists).
#
# Used as a SOFT modifier on the Omega (identity-fit) score only. Raw dps/burst/ehp stay
# pure math, so a genuinely strong off-kit build still shows up on those objectives and on
# the frontier. Nothing is ever removed from the pool — off-kit items are simply worth less
# to a kit that cannot cash them in, and on-kit items are worth a little more.
# ---------------------------------------------------------------------------
FLOOR = 0.15          # even a "useless" stat keeps this much value — never zero, never banned


def _clamp(v, lo=FLOOR, hi=1.0):
    return max(lo, min(hi, v))


def stat_affinity(name):
    c = CH[name]; ab = c['abilities']; s = c['stats']
    p = kit_profile(name)
    up = auto_uptime(name)

    # --- how much the kit scales with each damage source ---
    ap_mass = sum(a.get('ap', 0) or 0 for a in ab.values())
    ap_mass += sum((a.get('heal_ap', 0) or 0) for a in ab.values())
    for a in ab.values():
        for e in (a.get('effects') or []):
            if e.get('kind') in ('SHIELD', 'SUSTAIN'):
                ap_mass += e.get('ap', 0) or 0
    ad_mass = sum((a.get('ad_total', 0) or 0) + (a.get('ad_bonus', 0) or 0) for a in ab.values())
    hp_mass = sum(a.get('max_hp', 0) or 0 for a in ab.values())
    onhit = p.get('onhit_abilities', 0)

    # --- ability haste: worth more to short-cooldown kits and ult-centric kits ---
    cds = [a['cd'][4] for k, a in ab.items() if k in 'QWE' and a.get('cd')]
    mean_cd = (sum(cds) / len(cds)) if cds else 12.0
    r_cd = ((ab.get('R') or {}).get('cd') or [100.0])[-1] or 100.0
    ult_centric = _clamp((140.0 - r_cd) / 100.0, 0.2, 1.0)

    # --- mana: only matters if the kit actually spends it ---
    costs = [max(a.get('cost') or [0]) for a in ab.values() if a.get('cost')]
    mana_use = _clamp((sum(costs) / max(len(costs), 1)) / 90.0, 0.2, 1.0) if costs else 0.2

    aff = {
        # AP is worth what the kit's ability/heal/shield ratios can convert
        'ap':        _clamp(0.25 + 0.75 * min(1.0, ap_mass / 2.0)),
        # AD serves both ability AD-scaling and auto-attacks
        'ad':        _clamp(0.20 + 0.55 * min(1.0, ad_mass / 2.0) + 0.45 * up),
        # attack speed only pays out through attacking (and on-hit ability kits love it)
        'as':        _clamp(0.10 + 0.75 * up + 0.25 * min(1.0, onhit / 2.0)),
        # crit ONLY applies to basic attacks — a caster cannot use it at all
        'crit':      _clamp(0.06 + 0.94 * up),
        'lifesteal': _clamp(0.06 + 0.94 * up),
        # penetration follows the damage type the kit actually deals
        'armpen':    _clamp(0.15 + 0.50 * min(1.0, ad_mass / 2.0) + 0.40 * up),
        'lethality': _clamp(0.15 + 0.50 * min(1.0, ad_mass / 2.0) + 0.40 * up),
        'mpen':      _clamp(0.20 + 0.80 * min(1.0, ap_mass / 2.0)),
        # durability is useful to everyone, more so to HP-scaling kits
        'hp':        _clamp(0.45 + 0.55 * min(1.0, hp_mass * 4.0)),
        'armor':     _clamp(0.50 + 0.30 * min(1.0, hp_mass * 4.0)),
        'mr':        _clamp(0.50 + 0.30 * min(1.0, hp_mass * 4.0)),
        # haste: short cooldowns and big ultimates both want it
        'ah':        _clamp(0.35 + 0.40 * _clamp((16.0 - mean_cd) / 10.0, 0.0, 1.0) + 0.35 * ult_centric),
        'mana':      _clamp(0.15 + 0.85 * mana_use),
        'ms':        0.55,
        'hsp':       _clamp(0.15 + 0.85 * min(1.0, sum((a.get('heal_ap', 0) or 0) for a in ab.values()) * 3)),
    }
    return {k: round(v, 3) for k, v in aff.items()}


def build_affinity(name, item_stats):
    """Gold-weighted average affinity of a build's stat allocation: 0..1.
    item_stats is a dict of stat -> total amount across the build."""
    aff = stat_affinity(name)
    # rough gold-per-point so big-ticket stats dominate the average sensibly
    GOLD = dict(ap=20.0, ad=35.0, **{'as': 25.0}, crit=40.0, hp=2.7, armor=20.0, mr=20.0,
                ah=26.7, mana=4.0, ms=30.0, lifesteal=40.0, armpen=41.7, lethality=35.0,
                mpen=35.0, hsp=20.0)
    num = den = 0.0
    for stat, amount in (item_stats or {}).items():
        if not amount:
            continue
        g = GOLD.get(stat, 15.0) * abs(amount)
        num += g * aff.get(stat, 0.5)
        den += g
    return (num / den) if den else 1.0
