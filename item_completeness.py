"""LOE v2 — ITEM COMPLETENESS AUDIT.
Answers "are we missing any items?" against the wiki's own authority, so nothing is ever silently
dropped — and when a patch adds a new item, this flags it loudly instead of the engine just not
knowing it exists.

The wiki flags every item's availability per mode (["classic sr 5v5"] = true) and its tier
(Legendary/Mythic/Boots/etc). This audit lists every SR-legal legendary the wiki knows and checks
the engine has each one. Anything missing is either a KNOWN deliberate exclusion (support/quest
items, listed below) or a NEW gap that needs attention — and it says which.
"""
import sqlite3, re, json
import core

cx = sqlite3.connect('wiki.db'); C = cx.cursor()
IT = json.load(open('item_dna.json'))

# Deliberate, documented exclusions — support/quest items are gold-generators, mutually exclusive,
# and don't fit the standard 5-legendary build slot. Excluding them is correct, not a gap.
KNOWN_EXCLUSIONS = {
    'Bloodsong', 'Bounty of Worlds', 'Celestial Opposition', 'Dream Maker',
    'Solstice Sleigh', "Zaz'Zak's Realmspike", 'Runic Compass', 'Zaz\'Zak\'s Realmspike',
}


def item_blocks(lua):
    for m in re.finditer(r'\n    \["([^"]+)"\]\s*=\s*\{', lua):
        name = m.group(1); start = m.end(); depth = 1; i = start
        while depth > 0 and i < len(lua):
            if lua[i] == '{': depth += 1
            elif lua[i] == '}': depth -= 1
            i += 1
        yield name, lua[start:i]


def audit():
    lua = C.execute("SELECT text FROM pages WHERE title='Module:ItemData/data'").fetchone()[0]
    sr_legendary, sr_boots, sr_other = [], [], []
    for name, block in item_blocks(lua):
        if not re.search(r'\["classic sr 5v5"\]\s*=\s*true', block):
            continue
        types = re.search(r'\["type"\]\s*=\s*\{([^}]*)\}', block)
        typestr = types.group(1) if types else ''
        removed = re.search(r'\["removed"\]\s*=\s*true', block)
        if removed: continue
        if 'Legendary' in typestr or 'Mythic' in typestr:
            sr_legendary.append(name)
        elif 'Boots' in typestr:
            sr_boots.append(name)

    engine = set(core.LEGENDARIES)
    missing = [n for n in sr_legendary if n not in engine]
    unexpected_missing = [n for n in missing if n not in KNOWN_EXCLUSIONS]
    known_missing = [n for n in missing if n in KNOWN_EXCLUSIONS]

    print('=' * 66)
    print('ITEM COMPLETENESS AUDIT — vs the wiki\'s own SR-legal flag')
    print('=' * 66)
    print(f'wiki SR-legal legendaries: {len(sr_legendary)}')
    print(f'engine has:                {len(engine & set(sr_legendary))}')
    print(f'deliberately excluded:     {len(known_missing)} (support/quest items — correct)')
    print(f'UNEXPECTEDLY missing:      {len(unexpected_missing)}')
    if unexpected_missing:
        print('\n*** THESE NEED ATTENTION (new items? renamed? a patch added them?) ***')
        for n in unexpected_missing:
            print(f'    {n}')
    else:
        print('\n  -> every SR-legal legendary is accounted for (present or deliberately excluded).')

    json.dump(dict(wiki_sr_legendary=sr_legendary, engine_count=len(engine & set(sr_legendary)),
                   deliberately_excluded=known_missing, unexpectedly_missing=unexpected_missing),
              open('item_completeness_report.json', 'w'), indent=1)
    return unexpected_missing


if __name__ == '__main__':
    missing = audit()
    # a NEW missing item is worth failing loudly on, so a patch can't silently drop coverage
    if missing:
        print(f'\nWARNING: {len(missing)} SR-legal item(s) missing from the engine and not in the '
              f'known-exclusion list. Review Module:ItemData/data for new/renamed items.')
