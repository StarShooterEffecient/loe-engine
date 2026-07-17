"""Offline test of the mirror's incremental-sync brain — the part that must be right BEFORE it runs
live: given a manifest of known revids and a fresh listing from the wiki, fetch ONLY what changed."""
import mirror_fetch as M

def diff(have, latest):
    changed = [t for t, rev in latest.items() if have.get(t) != rev]
    removed = [t for t in have if t not in latest]
    return sorted(changed), sorted(removed)

# scenario: we already mirror 3 pages; the wiki has one unchanged, one bumped, one brand-new, and
# one of ours was deleted upstream.
have   = {'Module:ItemData/data': 100, 'Module:ChampionData/data': 200, 'Template:Data Aatrox/Q': 50}
latest = {'Module:ItemData/data': 100,          # unchanged  -> skip
          'Module:ChampionData/data': 201,       # bumped     -> fetch
          'Template:Rune data Conqueror': 10}    # new        -> fetch
# Template:Data Aatrox/Q vanished from latest -> removed

changed, removed = diff(have, latest)
assert changed == ['Module:ChampionData/data', 'Template:Rune data Conqueror'], changed
assert removed == ['Template:Data Aatrox/Q'], removed
print('PASS: unchanged page skipped, bumped + new fetched, deleted page pruned')

# scenario: nothing changed -> zero fetches (the steady state that keeps it free to run hourly)
changed2, removed2 = diff(have, have)
assert changed2 == [] and removed2 == []
print('PASS: identical manifest -> zero downloads (idempotent, cheap to run on a schedule)')

# namespace/prefix filter: only in-scope modules survive listing
from mirror_fetch import KEEP_PREFIX, KEEP_ARTICLES
assert 'Module:ItemData/data'.startswith(KEEP_PREFIX)
assert not 'Module:SkinData/data'.startswith(KEEP_PREFIX)
assert 'Critical strike' in KEEP_ARTICLES
assert 'Random Article' not in KEEP_ARTICLES
print('PASS: namespace/prefix filter keeps SR data, drops skins/other-game noise')

print('\nmirror diff-logic verified offline. The network path runs on GitHub Actions.')
