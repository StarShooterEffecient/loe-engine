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
    if any('reset' in (a.get('tags') or []) for a in ab.values()): auto_sig += 1.5
    # ChampionData: a kit built to auto-attack grows attack speed
    auto_sig += min(1.5, s['as_lvl'] / 3.0)
    # total-AD scaling means items bought for autos also feed the kit
    ad_total = sum(a.get('ad_total', 0) or 0 for a in ab.values())
    auto_sig += min(1.5, ad_total * 0.6)

    # ---------- signals that the kit REWARDS casting ----------
    ability_sig = 0.0
    ratio_mass = sum((a.get('ap', 0) or 0) + (a.get('ad_total', 0) or 0) + (a.get('ad_bonus', 0) or 0)
                     + 6.0 * (a.get('max_hp', 0) or 0) for k, a in ab.items() if k != 'I')
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
    # floor 0.18 (you auto between casts), ceiling `base` (a true auto-attacker)
    return round(0.18 + (base - 0.18) * (r ** 1.35), 3)


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
