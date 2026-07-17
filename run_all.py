"""LOE v2 — ONE BUTTON (assumes mirror is already synced; run mirror_fetch.py first for live data). The whole verified pipeline, with every gate."""
import subprocess, sys, time
STAGES = [
    ('mirror_sync.py',    'fold mirror JSON dumps into the store (namespace-filtered)'),
    ('ingest.py',        'canonical wiki page store (dedupe by newest revision)'),
    ('champion_dna.py',  'champion DNA — dual-authority roster gate'),
    ('item_dna.py',      'item DNA — stats, passives, gold, SR legality'),
    ('item_groups.py',   'ITEM GROUPS — the wiki legality rule (one item per group)'),
    ('rune_dna.py',      'rune DNA — trees, rows, shards; ghost runes excluded'),
    ('damage_dna.py',    'damage DNA — types + on-hit/lifesteal properties'),
    ('validate_formulas.py','FORMULA GATE — combat constants vs the wiki rules'),
    ('validate_dna.py',  'VALIDATION GATE — defects published, never hidden'),
    ('wiki_decode.py',   'WIKI MARKUP DECODER — reports unknown templates (future-proofing)'),
    ('named_effects.py',  'Named item effect families — the wiki effect vocabulary'),
    ('item_effects.py',  'item passive compiler — decoder-based, typed values'),
    ('rune_effects.py',  'rune effect DSL'),
    ('kit_profile.py',   'DNA-derived auto-reliance + Omega weights'),
    ('run_all_v2.py',    'optimize every champion x 6 objectives, mutation-proven (resumable)'),
    ('frontier.py',       'R-NSGA-II frontier smoke test'),
    ('build_app.py',     'the Knowledge Output app'),
    ('trust.py',         'TRUST LAYER — item audit, kit coherence, robustness'),
]
t0 = time.time()
for s, why in STAGES:
    print(f'\n===== {s} — {why} =====', flush=True)
    if subprocess.run([sys.executable, '-u', s]).returncode != 0:
        print(f'STAGE FAILED: {s}'); sys.exit(1)
print(f'\nPIPELINE COMPLETE in {(time.time()-t0)/60:.1f} min')
