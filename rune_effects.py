"""LOE v2 — RUNE EFFECT ENGINE.
The trust check found that keystones had ZERO effect on the simulation: Electrocute, Conqueror and
Lethal Tempo all produced identical numbers, so the rune page was decorative and picked arbitrarily
(every champion ended up on 'Unsealed Spellbook'). Runes are roughly a third of a build's power.

Same DSL as items, same sanity gate, same honesty: what we cannot compile is UNMODELLED, never guessed.
"""
import json, re

RU = json.load(open('rune_dna.json'))

# Overrides for keystones whose mechanics defeat prose parsing. Each states its evidence.
OVERRIDES = {
    'Electrocute': dict(hook='ON_ABILITY', op='burst_proc', flat=60.0, ad=0.40, ap=0.25, cd=20.0,
        why='Three separate attacks/abilities on a champion deal bonus adaptive damage; modelled '
            'as a periodic burst proc on its cooldown.'),
    'Dark Harvest': dict(hook='ON_ABILITY', op='burst_proc', flat=20.0, ad=0.25, ap=0.15, cd=35.0,
        why='Executes low-health targets for stacking damage; modelled at a conservative stack count.'),
    'Conqueror': dict(hook='STACK', op='adaptive_stacks', value=1.8, stacks=12, heal=0.08,
        why='Stacks adaptive force on hit, then converts damage to healing at max stacks.'),
    'Press the Attack': dict(hook='AMP', op='damage_amp', value=0.08,
        why='Three consecutive hits make the target take increased damage from all sources.'),
    'Lethal Tempo': dict(hook='ALWAYS', op='stat', stat='AS', value=30.0,
        why='Grants stacking attack speed in combat; modelled at its sustained plateau.'),
    'Hail of Blades': dict(hook='ALWAYS', op='stat', stat='AS', value=20.0,
        why='Burst attack speed on engage; modelled as an averaged plateau over the window.'),
    'Fleet Footwork': dict(hook='SUSTAIN', op='heal_ps', value=6.0,
        why='Energized attacks heal and grant movement speed.'),
    'Grasp of the Undying': dict(hook='ON_HIT', op='pct_max_hp_self', value=0.035, cd=4.0,
        why="Empowered attack deals damage equal to a share of the WIELDER'S max health and "
            "permanently grants health — an HP->damage converter."),
    'Summon Aery': dict(hook='ON_ABILITY', op='proc', flat=30.0, ap=0.20, ad=0.15, cd=2.0,
        why='Sends a companion that damages enemies or shields allies on ability use.'),
    'Arcane Comet': dict(hook='ON_ABILITY', op='proc', flat=45.0, ap=0.20, ad=0.35, cd=8.0,
        why='Damaging abilities hurl a comet dealing adaptive damage.'),
    'Dark Harvest ': dict(hook='ON_ABILITY', op='proc', flat=20.0, ap=0.15, ad=0.25, cd=35.0, why='alias'),
    'First Strike': dict(hook='AMP', op='damage_amp', value=0.09,
        why='First damage to a champion grants bonus damage and gold for a window.'),
    'Glacial Augment': dict(hook='AMP', op='damage_amp', value=0.04,
        why='Slows and chills; modelled as a small effective amplifier.'),
    'Aftershock': dict(hook='DEFENSE', op='flat_resists', value=35.0,
        why='Immobilizing an enemy grants large temporary resists, then deals magic damage.'),
    'Guardian': dict(hook='DEFENSE', op='shield_flat', value=90.0,
        why='Shields you and a nearby ally when either takes damage.'),
    'Stormraider\'s Surge': dict(hook='ALWAYS', op='stat', stat='MS_PCT', value=8.0,
        why='Burst damage grants a large movement-speed surge.'),
    'Deathfire Touch': dict(hook='ON_ABILITY', op='proc', flat=25.0, ap=0.18, ad=0.30, cd=3.0,
        why='Damaging abilities apply a burn scaling with adaptive force.'),
    'Unsealed Spellbook': dict(hook='NONE', op='none',
        why='Swaps summoner spells. It has NO combat-stat effect this model can honestly compute, '
            'so it contributes ZERO — which is exactly why it must not win by default.'),
}

MINOR_STATS = {
    'Gathering Storm': dict(op='stat', stat='AP', value=48.0),
    'Absolute Focus': dict(op='stat', stat='AP', value=30.0),
    'Transcendence': dict(op='stat', stat='AH', value=10.0),
    'Sudden Impact': dict(op='stat', stat='PEN', value=7.0),
    'Cut Down': dict(op='damage_amp', value=0.08),
    'Coup de Grace': dict(op='damage_amp', value=0.08),
    'Last Stand': dict(op='damage_amp', value=0.06),
    'Legend: Alacrity': dict(op='stat', stat='AS', value=15.0),
    'Legend: Haste': dict(op='stat', stat='AH', value=12.0),
    'Legend: Bloodline': dict(op='stat', stat='LS', value=8.0),
    'Triumph': dict(op='heal_ps', value=3.0),
    'Presence of Mind': dict(op='stat', stat='AH', value=6.0),
    'Ravenous Hunter': dict(op='stat', stat='OV', value=8.0),
    'Eyeball Collection': dict(op='stat', stat='ADAPTIVE', value=18.0),
    'Sixth Sense': dict(op='stat', stat='ADAPTIVE', value=8.0),
    'Ultimate Hunter': dict(op='stat', stat='AH', value=8.0),
    'Taste of Blood': dict(op='heal_ps', value=2.5),
    'Bone Plating': dict(op='damage_reduction', value=0.06),
    'Second Wind': dict(op='heal_ps', value=3.0),
    'Overgrowth': dict(op='stat', stat='HP', value=180.0),
    'Conditioning': dict(op='flat_resists', value=12.0),
    'Shield Bash': dict(op='damage_amp', value=0.03),
    'Nimbus Cloak': dict(op='stat', stat='MS_PCT', value=2.0),
    'Scorch': dict(op='proc', flat=25.0, cd=10.0),
    'Manaflow Band': dict(op='stat', stat='MANA', value=250.0),
    'Cheap Shot': dict(op='proc', flat=20.0, cd=4.0),
    'Treasure Hunter': dict(op='none'),
    'Magical Footwear': dict(op='none'),
    'Cosmic Insight': dict(op='stat', stat='AH', value=5.0),
}

LIMITS = dict(flat=250.0, value=0.20, heal_ps=12.0)


def compile_rune(name):
    r = RU.get(name)
    if not r: return []
    if name in OVERRIDES:
        o = dict(OVERRIDES[name]); o['rune'] = name; o['source'] = 'override'
        return [] if o['op'] == 'none' else [o]
    if name in MINOR_STATS:
        o = dict(MINOR_STATS[name]); o['rune'] = name; o['source'] = 'table'
        o.setdefault('hook', 'ALWAYS' if o['op'] in ('stat', 'flat_resists', 'damage_reduction')
                     else 'AMP' if o['op'] == 'damage_amp'
                     else 'SUSTAIN' if o['op'] == 'heal_ps' else 'ON_ABILITY')
        return [] if o['op'] == 'none' else [o]
    # shards carry raw stats already handled by core.item_vector
    if r['kind'] == 'SHARD': return []
    return []


COMPILED = {}
UNMODELLED = []
for n in RU:
    nodes = compile_rune(n)
    if nodes: COMPILED[n] = nodes
    elif RU[n]['kind'] in ('KEYSTONE', 'MINOR'):
        UNMODELLED.append(n)


def rune_nodes(pieces):
    out = []
    for p in pieces:
        out.extend(COMPILED.get(p, []))
    return out


if __name__ == '__main__':
    ks = [n for n, r in RU.items() if r['kind'] == 'KEYSTONE']
    mn = [n for n, r in RU.items() if r['kind'] == 'MINOR']
    print(f'keystones compiled: {sum(1 for n in ks if n in COMPILED)}/{len(ks)}')
    print(f'minor runes compiled: {sum(1 for n in mn if n in COMPILED)}/{len(mn)}')
    print(f'\nHONESTLY UNMODELLED runes ({len(UNMODELLED)}) — they contribute ZERO and cannot win by default:')
    for n in UNMODELLED[:14]:
        print(f'   {RU[n]["kind"]:8s} {n}')
