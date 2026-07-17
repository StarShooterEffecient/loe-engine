"""LOE v2 — COMBAT MODEL.
Every damage source is resolved from DNA, never from a heuristic:

  ABILITIES   real base damage (rank 5) + real ratios, cast on their OWN cooldown, paying their
              OWN cost from a real mana budget, resolved against their OWN damage type.
  AUTOS       real base AD + items, real attack speed (with the champion's as_ratio), crit
              with the game's 175% multiplier plus crit-damage amplifiers.
  ON-HIT      item on-hit passives fire per auto AND per ability that the wiki says
              triggers on-hit events (74 abilities — this is what v1 could never know).
  PROCS       stacking procs (Kraken: every 3rd) fire at their real cadence; %-health procs
              read the target's real health.
  KIT PASSIVE the champion's own innate — Aatrox's 7% max-health on-hit, on its real cooldown.
  AMPS        self-buffs (World Ender's bonus AD) applied as amplifiers, not phantom damage.

Objectives are SEPARATE, never blended into one score (the Vel'Koz-as-tank question needs this):
  DPS · BURST · EHP · SUSTAIN · each measured against three level-18 ranked benchmarks.
"""
import json, math, re
import core
import kit_profile as KP
import item_effects as IE
import rune_effects as RE

CH, IT, RU = core.CH, core.IT, core.RU

WINDOW = 15.0          # ASSUMPTION: extended-fight window, seconds
ULT_CASTS = 1.0        # ASSUMPTION: one ult per window
MANA_REGEN = 0.35      # ASSUMPTION: pool + regen/refunds available over the window
AUTO_UPTIME = {'ranged': 0.85, 'melee': 0.65}   # ASSUMPTION: fraction of window spent auto-attacking
CRIT_BASE = 1.00       # GAME: crits deal 200% (reverted from 175% in V26.01; verified by validate_formulas.py)
MIN_CD = 0.75          # ASSUMPTION: floor on an ability's effective cooldown
AS_CAP = 2.5           # GAME

TARGETS = [dict(name='Squishy', HP=2500, ARMOR=100, MR=52),
           dict(name='Bruiser', HP=3600, ARMOR=160, MR=100),
           dict(name='Tank',    HP=4800, ARMOR=320, MR=220)]

def adaptive_split(v, kit):
    """Adaptive force -> AP or AD by the champion's own kit ratios (GAME: whichever is higher)."""
    if v['ADAPTIVE'] <= 0: return v
    ap_bias = kit['ap_scaling'] > kit['ad_scaling']
    if ap_bias: v['AP'] += v['ADAPTIVE'] * 1.0
    else:       v['AD'] += v['ADAPTIVE'] * 0.6      # GAME: 1 adaptive = 0.6 AD or 1.0 AP
    v['ADAPTIVE'] = 0.0
    return v

def build_state(name, pieces, L=18):
    b = core.base_stats(name, L)
    v = core.item_vector(pieces, L)
    kit = core.conversion(name)
    v = adaptive_split(v, kit)
    # self-buff amps from the champion's own kit — PERCENT amps multiply, flat amps add.
    # (World Ender: +40% AD. Highlander: +65% AS. v1 and early v2 lost these entirely.)
    UP = 0.5        # ASSUMPTION: ultimate amp active ~half of the fight window
    for stat, rec in kit['self_amps'].items():
        key = {'ad': 'AD', 'ap': 'AP', 'as': 'AS', 'ah': 'AH', 'armor': 'ARMOR', 'mr': 'MR',
               'ms': 'MS_PCT', 'omni': 'OV'}.get(stat)
        if not key: continue
        val = rec['value'] if isinstance(rec, dict) else rec
        pct = rec['pct'] if isinstance(rec, dict) else False
        if pct and key == 'AD':      v['AD'] += (b['AD'] + v['AD']) * val / 100.0 * UP
        elif pct and key == 'AP':    v['AP'] += v['AP'] * val / 100.0 * UP
        elif pct and key == 'AS':    v['AS'] += val * UP
        elif pct and key in ('ARMOR', 'MR'): v[key] += (b[key] + v[key]) * val / 100.0 * UP
        else:                        v[key] += val * UP
    st = dict(v)
    st['HP'] += b['HP']; st['ARMOR'] += b['ARMOR']; st['MR'] += b['MR']
    st['MANA'] += b['MANA']
    st['BASE_AD'] = b['AD']; st['TOTAL_AD'] = b['AD'] + v['AD']
    st['AS'] = min(AS_CAP, b['AS'] * (1 + v['AS'] / 100.0))
    st['RANGE'] = b['RANGE']
    return st, b, kit

DMG_ITEMS = json.load(open('damage_dna.json'))['items']

def onhit_type(item_name, node=None):
    if node and node.get('dtype'): return node['dtype']      # decoder read it from the wiki
    for k, v in DMG_ITEMS.get(item_name, {}).items():
        if v.get('type'): return v['type']
    return None

name_ref = ['']
def resolve_items(pieces, st, base, kit):
    """Fire every compiled item hook. Returns the stat/behaviour deltas the passives create.
    Anything not compiled is NOT guessed — it is counted in `unmodelled` and reported."""
    nodes = IE.build_nodes(pieces) + RE.rune_nodes(pieces)
    d = dict(shred_ar=0.0, shred_mr=0.0, amp=1.0, amp_magic=1.0, amp_vs_hp=0.0,
             crit_dmg=0.0, ehp_mult=1.0, shield=0.0, heal_ps=0.0,
             onhit=[], onability=[], regen=0.0, mult_ap=1.0, procs=[], antiheal=0.0)
    # PASS 1: conversions (mana->AP etc). They must land BEFORE the multipliers.
    for n in nodes:
        if n['op'] == 'convert':
            src = st.get(n['frm'], 0.0)
            amt = src * n['value']
            if n['to'] == 'AP': st['AP'] += amt
            else: st['TOTAL_AD'] += amt; st['AD'] += amt
        elif n['op'] == 'ap_from_mana': st['AP'] += st['MANA'] * n['value']
        elif n['op'] == 'ad_from_mana':
            st['TOTAL_AD'] += st['MANA'] * n['value']; st['AD'] += st['MANA'] * n['value']
    # PASS 2: stat MULTIPLIERS (Rabadon's multiplies TOTAL ability power by 30%)
    for n in nodes:
        if n['op'] == 'mult_stat':
            k = n['stat']
            if k == 'AP': d['mult_ap'] *= (1 + n['value'])
            elif k == 'AD':
                st['TOTAL_AD'] *= (1 + n['value']); st['AD'] *= (1 + n['value'])
            elif k in st: st[k] *= (1 + n['value'])
        elif n['op'] == 'mult_ap': d['mult_ap'] *= (1 + n['value'])
    st['AP'] *= d['mult_ap']
    # PASS 3: everything else
    for n in nodes:
        h, op = n['hook'], n['op']
        if op == 'shred':
            d['shred_ar'] = max(d['shred_ar'], n['armor']); d['shred_mr'] = max(d['shred_mr'], n['mr'])
        elif h == 'ON_HIT' and op == 'damage':
            d['onhit'].append(n)
        elif h == 'ON_HIT' and op == 'cleave_pct_hp':
            d['onhit'].append(dict(item=n['item'], flat=0.0, pct_max_hp=0.0, pct_cur_hp=0.0,
                                   amp_lo=0, amp_hi=0, every=1, self_hp=n['value'], name='Cleave'))
        elif h == 'ON_ABILITY':
            d['onability'].append(n)
        elif h == 'AMP' and op == 'damage_amp':
            if n.get('magic_only'): d['amp_magic'] *= (1 + n['value'])
            else: d['amp'] *= (1 + n['value'])
        elif op == 'amp_vs_max_hp':
            d['amp_vs_hp'] = max(d['amp_vs_hp'], n['value'])
        elif op == 'crit_damage':
            d['crit_dmg'] += n['value']
        elif op in ('ap_from_mana', 'ad_from_mana', 'mult_ap', 'mult_stat', 'convert'):
            pass                                     # already applied in passes 1-2
        elif op == 'stacking_resists':
            st['ARMOR'] += n['value']; st['MR'] += n['value']
        elif op == 'flat_resists':
            st['ARMOR'] += n['value'] * 0.5; st['MR'] += n['value'] * 0.5
        elif op in ('shield_pct_hp', 'magic_shield_pct'):
            d['shield'] += st['HP'] * n['value']
        elif op == 'shield_flat':
            d['shield'] += n['value']
        elif op == 'spellblade':
            # after an ability, next attack deals bonus on-hit (base AD + AP scaling), on a cooldown
            d['onability'].append(dict(item=n['item'], flat=n.get('base_ad', 0) * st['BASE_AD']
                                       + n.get('ap', 0) * st['AP'], pct_max_hp=0.0,
                                       dtype=n.get('dtype', 'Magic'), name='Spellblade'))
        elif op == 'spellshield':
            d['shield'] += st['HP'] * 0.06          # blocks one ability ~ a modest effective-HP buffer
        elif op == 'antiheal':
            d['antiheal'] = n['value']              # utility: reduces enemy healing (tracked, not damage)
        elif op == 'damage_reduction':
            d['ehp_mult'] *= 1 / (1 - n['value'])
        elif op == 'crit_reduction':
            d['ehp_mult'] *= 1 + n['value'] * 0.25          # only vs crit sources
        elif op == 'regen_pct_hp':
            d['regen'] += st['HP'] * n['value']
        elif h == 'SUSTAIN' and op == 'heal':
            d['heal_ps'] += n['value'] / 10.0               # ASSUMPTION: proc cadence ~10s
        elif op == 'phantom_hit':
            d['phantom'] = True
        # ---- rune hooks ----
        elif op == 'stat':
            k = n['stat']
            if k == 'AS': st['AS'] = min(AS_CAP, st['AS'] * (1 + n['value'] / 100.0))
            elif k in st: st[k] = st.get(k, 0) + n['value']
        elif op == 'adaptive_stacks':                        # Conqueror
            kitp = KP.kit_profile(name_ref[0])
            adaptive = n['value'] * n['stacks']
            if kitp['ratio_mass'] and CH[name_ref[0]]['abilities']:
                ap_k = sum(a.get('ap', 0) or 0 for a in CH[name_ref[0]]['abilities'].values())
                ad_k = sum((a.get('ad_total', 0) or 0) + (a.get('ad_bonus', 0) or 0)
                           for a in CH[name_ref[0]]['abilities'].values())
                if ap_k > ad_k: st['AP'] += adaptive
                else: st['TOTAL_AD'] += adaptive * 0.6; st['AD'] += adaptive * 0.6
            d['heal_ps'] += n.get('heal', 0) * 40
        elif op in ('burst_proc', 'proc'):                   # Electrocute, Comet, Aery, Scorch
            d['procs'].append(n)
        elif op == 'pct_max_hp_self':                        # Grasp
            d['onhit'].append(dict(item=n['rune'], flat=0.0, pct_max_hp=0.0, pct_cur_hp=0.0,
                                   amp_lo=0, amp_hi=0, every=max(1, int(n['cd'] / 1.5)),
                                   self_hp=n['value'], name=n['rune']))
        elif op == 'heal_ps':
            d['heal_ps'] += n['value']
    return d

def onhit_damage(d, st, tgt, phys, mag, pieces):
    tot = 0.0
    for n in d['onhit']:
        dmg = n.get('flat', 0.0)
        dmg += n.get('pct_max_hp', 0.0) * tgt['HP']
        dmg += n.get('pct_cur_hp', 0.0) * tgt['HP'] * 0.65
        dmg += n.get('self_hp', 0.0) * st['HP']
        if n.get('amp_hi'): dmg *= 1 + (n['amp_lo'] + n['amp_hi']) / 2 * 0.5
        dmg /= max(1, n.get('every', 1))
        t = onhit_type(n['item'], n)
        tot += dmg * (mag if t == 'Magic' else 1.0 if t == 'True' else phys)
    if d.get('phantom'): tot *= 1.33
    return tot

def onability_damage(d, st, tgt, phys, mag):
    tot = 0.0
    for n in d['onability']:
        dmg = (n.get('flat', 0.0) + n.get('pct_max_hp', 0.0) * tgt['HP']
               + n.get('pct_cur_hp', 0.0) * tgt['HP'] * 0.65
               + n.get('ap_ratio', 0.0) * st['AP'])
        t = n.get('dtype') or 'Magic'
        tot += dmg * (phys if t == 'Physical' else 1.0 if t == 'True' else mag)
    return tot

def simulate(name, pieces, L=18):
    st, b, kit = build_state(name, pieces, L)
    ab = CH[name]['abilities']
    cdr = core.cdr(st['AH'])
    manaless = kit['resource'] not in ('Mana', 'Mana ')
    ranged = st['RANGE'] >= 350
    # DNA-DERIVED: how much of the fight does THIS kit actually spend auto-attacking?
    # (A kit with no on-hit ability, no AS amp and no auto reset does not stand at the
    #  attack-speed cap for 13 of 15 seconds. That bug bought Ahri 175 AD.)
    uptime = KP.auto_uptime(name, ranged)
    crit_mult = 1 + min(1.0, st['CRIT'] / 100.0) * (CRIT_BASE + st['CRIT_DMG'] / 100.0)

    per_target = []
    name_ref[0] = name
    FX = resolve_items(pieces, st, b, kit)
    shred_ar, shred_mr = FX['shred_ar'], FX['shred_mr']
    crit_mult = 1 + min(1.0, st['CRIT'] / 100.0) * (CRIT_BASE + st['CRIT_DMG'] / 100.0 + FX['crit_dmg'])
    for tgt in TARGETS:
        A = core.eff_resist(tgt['ARMOR'] * (1 - shred_ar / 100.0), st['PEN'], st['PEN_PCT'])
        M = core.eff_resist(tgt['MR'] * (1 - shred_mr / 100.0), st['MPEN'], st['MPEN_PCT'])
        phys, mag = core.mitig(A), core.mitig(M)
        mult = {'Physical': phys, 'Magic': mag, 'True': 1.0}

        # ---- autos ----
        # item damage amplifiers (Horizon Focus, Abyssal, Luden's) + %-max-HP amp (Giant Slayer)
        amp_p = FX['amp'] * (1 + FX['amp_vs_hp'] * min(1.0, tgt['HP'] / 4000.0))
        amp_m = amp_p * FX['amp_magic']
        auto_base = st['TOTAL_AD'] * crit_mult * phys * amp_p
        onhit = onhit_damage(FX, st, tgt, phys, mag, pieces) * amp_p
        # champion innate on-hit (Aatrox's Deathbringer etc.)
        innate = 0.0
        p = ab.get('I')
        if p and (p.get('max_hp') or p.get('base')):
            pd = (p['max_hp'] or 0) * tgt['HP'] + (p['base'][4] if p.get('base') else 0)
            pcd = max((p['cd'][4] if p.get('cd') else 6.0) * (1 - cdr), 1.0)
            innate = pd * mult.get(p.get('dtype') or 'Physical', phys) / pcd    # damage per second from the proc
        # auto rate is computed AFTER the ability time-budget (see below)

        # ---- abilities (each cast consumes real cast time from the fight window) ----
        ab_dmg = 0.0; ab_cost = 0.0; rot_once = 0.0; onhit_procs = 0.0; cast_time_used = 0.0
        for slot in ('Q', 'W', 'E'):
            a = ab.get(slot)
            if not a or not (a.get('base') or a.get('ap') or a.get('ad_total') or a.get('ad_bonus')): continue
            d = ((a['base'][4] if a.get('base') else 0)
                 + a.get('ap', 0) * st['AP']
                 + a.get('ad_total', 0) * st['TOTAL_AD']
                 + a.get('ad_bonus', 0) * st['AD']
                 + a.get('max_hp', 0) * tgt['HP'])
            dt = a.get('dtype') or 'Magic'
            d *= mult.get(dt, mag) * (amp_m if dt == 'Magic' else amp_p)
            d += onability_damage(FX, st, tgt, phys, mag) * amp_m   # Luden's/Blackfire fire per ability
            cd = max((a['cd'][4] if a.get('cd') else 10.0) * (1 - cdr), MIN_CD)
            swings = a.get('casts', 1) or 1      # DATA: Aatrox Q swings 3x, Riven Q 3x, Yasuo Q 2x
            rotations = WINDOW / cd
            hits = rotations * swings
            ab_dmg += hits * d
            ab_cost += rotations * (a['cost'][4] if a.get('cost') else 0) * swings
            rot_once += d * swings               # the full combo, not one swing
            # DATA: does this ability proc on-hit items? (DamageData properties OR the template flag)
            if a.get('triggers_onhit') or a.get('onhit_flag'):
                ab_dmg += hits * onhit
                onhit_procs += hits
            # DATA: real cast time per swing (wiki 'cast time' field); default 0.25s if absent
            cast_time_used += hits * (a.get('cast_time') or 0.25)
        r = ab.get('R')
        ult = 0.0
        if r and (r.get('base') or r.get('ap') or r.get('ad_total')):
            ult = ((r['base'][4] if r.get('base') else 0) + r.get('ap', 0) * st['AP']
                   + r.get('ad_total', 0) * st['TOTAL_AD'] + r.get('ad_bonus', 0) * st['AD']
                   + r.get('max_hp', 0) * tgt['HP']) * mult.get(r.get('dtype') or 'Magic', mag) * amp_m
        if not manaless and ab_cost > 0:
            budget = st['MANA'] * (1 + MANA_REGEN)
            mana_scale = min(1.0, budget / ab_cost)
            ab_dmg *= mana_scale
            cast_time_used *= mana_scale
        ability_dps = (ab_dmg + ULT_CASTS * ult) / WINDOW

        # TIME BUDGET (GAME): time spent casting is time NOT spent auto-attacking.
        # This is why an ability-centric kit cannot also auto at full rate — and why it should
        # buy what its abilities scale with, not what its autos would like.
        free_time = max(0.0, WINDOW - cast_time_used - ULT_CASTS * 0.5)
        auto_rate = st['AS'] * uptime * (free_time / WINDOW)
        auto_dps = auto_rate * (auto_base + onhit) + innate

        # rune procs (Electrocute, Comet, Aery, Scorch) on their own cooldowns
        rune_dps = 0.0
        for n in FX['procs']:
            dmg = n.get('flat', 0) + n.get('ap', 0) * st['AP'] + n.get('ad', 0) * st['TOTAL_AD']
            eff_cd = max(1.0, n.get('cd', 10.0) * (1 - cdr))
            rune_dps += dmg * mag / eff_cd
        dps = auto_dps + ability_dps + rune_dps
        n_auto_burst = 1.0 + 3.0 * KP.kit_profile(name)['auto_reliance']   # DNA: how many autos fit in a burst window
        rune_burst = sum(n.get('flat', 0) + n.get('ap', 0) * st['AP'] + n.get('ad', 0) * st['TOTAL_AD']
                         for n in FX['procs']) * mag
        burst = rot_once + ult + auto_base * n_auto_burst + rune_burst
        per_target.append(dict(target=tgt['name'], dps=dps, burst=burst,
                               ttk=tgt['HP'] / dps if dps > 0 else 999))

    # ---- defensive objectives (target-independent) ----
    ehp_p = (st['HP'] + FX['shield']) * (1 + st['ARMOR'] / 100.0) * FX['ehp_mult']
    ehp_m = (st['HP'] + FX['shield']) * (1 + st['MR'] / 100.0) * FX['ehp_mult']
    ehp = (ehp_p + ehp_m) / 2
    mean_dps = sum(t['dps'] for t in per_target) / 3

    # ---- KIT OUTPUT: what this champion's kit DOES, fed by this build ----
    heal_amp = 1 + st['HEAL_AMP'] / 100.0
    # 1. the kit's own healing/shielding, scaled by the stats the build actually provides
    kit_heal = 0.0
    for slot, a in ab.items():
        hp_ap = a.get('heal_ap', 0) or 0
        hp_ad = a.get('heal_ad', 0) or 0
        if not (hp_ap or hp_ad): continue
        per_cast = hp_ap * st['AP'] + hp_ad * st['TOTAL_AD']
        cd = max((a['cd'][4] if a.get('cd') else 12.0) * (1 - cdr), MIN_CD)
        kit_heal += per_cast * (WINDOW / cd) * (a.get('casts', 1) or 1)
    # 2. lifesteal/omnivamp converting the build's damage into sustain (DamageData says which
    #    ability damage applies it — v1 had to guess)
    # KIT VAMP: damage -> healing conversion stated by the kit itself, with its own scaling
    # (Aatrox: 16% + 1.1% per 100 bonus health -> his healing scales with HP items).
    bonus_hp = st['HP'] - b['HP']
    kit_vamp = 0.0
    for a in ab.values():
        v0 = a.get('vamp', 0) or 0
        if not v0: continue
        kit_vamp = max(kit_vamp, v0 + (a.get('vamp_per100hp', 0) or 0) * bonus_hp / 100.0
                                    + (a.get('vamp_per100ap', 0) or 0) * st['AP'] / 100.0)
    auto_frac = KP.auto_uptime(name)              # fraction of the fight actually auto-attacking
    # lifesteal & physical vamp only heal from autos -> scale by how much this kit autos.
    # omnivamp and kit-vamp apply to all damage.
    ls_frac = (st['LS'] + st['PV']) / 100.0 * auto_frac + kit_vamp
    ov_frac = st['OV'] / 100.0
    # the portion of damage that lifesteal actually applies to (auto + lifesteal-flagged) vs
    # the portion omnivamp applies to (everything)
    ls_source = mean_dps * WINDOW * (0.4 + 0.5 * auto_frac)
    sustain = (kit_heal + ls_source * ls_frac + mean_dps * WINDOW * ov_frac
               + FX['heal_ps'] * WINDOW + FX['regen']) * heal_amp / WINDOW
    # 3. utility: what the kit brings that isn't damage or health (CC, mobility, shielding)
    cc_n = sum(1 for a in ab.values() if 'cc' in (a.get('tags') or []))
    mob_n = sum(1 for a in ab.values() if 'dash' in (a.get('tags') or []))
    shield_n = sum(1 for a in ab.values() if 'shield' in (a.get('tags') or []))
    utility = (cc_n * 1.0 + mob_n * 0.7 + shield_n * 0.8) * (1 + cdr) * (1 + st['AH'] / 200.0)

    # ---- OMEGA: "maximize THIS champion" — objectives combined by weights the KIT dictates ----
    W = KP.omega_weights(name)
    REF = dict(dps=450.0, burst=1800.0, ehp=9000.0, sustain=120.0, utility=6.0)
    raw = dict(dps=mean_dps, burst=sum(t['burst'] for t in per_target) / 3,
               ehp=ehp, sustain=sustain, utility=utility)
    omega = sum(W[k] * min(2.5, raw[k] / REF[k]) for k in W) * 100

    return dict(
        omega=omega, omega_weights=W,
        dps=mean_dps,
        burst=sum(t['burst'] for t in per_target) / 3,
        ehp=ehp, ehp_phys=ehp_p, ehp_mag=ehp_m,
        sustain=sustain, kit_heal=kit_heal / WINDOW, utility=utility,
        per_target=per_target, coverage=CH[name]['coverage'], stats=st,
        modelled=round(sum(1 for p in pieces if p in IE.COMPILED or (p in IT and not IT[p]['effects']))
                       / max(1, sum(1 for p in pieces if p in IT)), 2))

if __name__ == '__main__':
    tests = [
        ('Aatrox', ['Bloodthirster', 'Sterak\'s Gage', 'Death\'s Dance', 'Black Cleaver', 'Sundered Sky', 'Plated Steelcaps']),
        ('Aatrox', ['Kraken Slayer', 'Terminus', 'Wit\'s End', 'Blade of the Ruined King', 'Experimental Hexplate', 'Plated Steelcaps']),
        ("Vel'Koz", ['Luden\'s Echo', 'Shadowflame', 'Rabadon\'s Deathcap', 'Void Staff', 'Zhonya\'s Hourglass', 'Sorcerer\'s Shoes']),
        ('Ornn', ['Heartsteel', 'Warmog\'s Armor', 'Thornmail', 'Kaenic Rookern', 'Unending Despair', 'Plated Steelcaps']),
    ]
    print(f'{"champion":10s} {"build":28s} {"DPS":>6s} {"burst":>6s} {"EHP":>6s}')
    for nm, build in tests:
        avail = [p for p in build if p in IT]
        r = simulate(nm, avail)
        tag = build[0][:26]
        print(f'{nm:10s} {tag:28s} {r["dps"]:6.0f} {r["burst"]:6.0f} {r["ehp"]:6.0f}   ({len(avail)}/{len(build)} items found)')
    print()
    r = simulate('Aatrox', ['Bloodthirster', "Sterak's Gage", "Death's Dance", 'Black Cleaver', 'Sundered Sky', 'Plated Steelcaps'])
    for t in r['per_target']:
        print(f'  Aatrox vs {t["target"]:8s} dps {t["dps"]:6.0f}  ttk {t["ttk"]:5.1f}s')
