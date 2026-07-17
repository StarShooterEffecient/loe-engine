# LOE Synergy Engine v2 — patch 26.13

Pure mathematical build discovery for League of Legends.
**No meta. No win rates. No pick rates. No tier lists. Ever.**

## The objective that answers "maximize the champion"
**Ω (omega)** is a kit-weighted composite. Its weights are read from the champion's OWN kit —
how much they scale with AP vs AD, whether they heal, whether they convert damage to health,
whether they bring CC — never chosen by hand and never taken from the meta. Ω answers "which
single build lifts the most of what THIS champion does?"

The five component objectives stay separate and are all reported:
**Max DPS · Max Burst · Max Effective HP · Max Sustain · Max Utility**
A champion has as many optimal builds as they have things they do.

Every build is **mutation-proven**: no legal single swap of any item, boot, keystone, rune or
shard improves its objective.

## The laws
- Blind to the meta, permanently.
- The data is the referee — never memory, never taste.
- Wiki-only sourcing (`wiki.leagueoflegends.com`).
- **Validate the champion, not just the build.** (Dual-authority roster gate.)
- **A parser that lies loudly is safer than one that lies quietly.** (Sanity gate.)
- Honest limits, published — see the app's "What we do NOT model" tab.

## Data source: the mirror
Ingestion is source-format-agnostic. It reads Special:Export XML **and** the leaguewikimirror's
native {title:{content,revid}} JSON, deduping by newest revision — so a mirror that re-downloads only
changed pages folds in with no code change. A namespace filter drops Legends of Runeterra, TFT and
Wild Rift pages (a full mirror is ~75% other-game noise). A FORMULA GATE validates the engine's combat
constants against the wiki's own mechanics articles: it caught the V26.01 revert of critical strikes
to 200% (the engine was on 175%), which memory alone would never have surfaced.

## The frontier optimizer (Ω)
The Ω build comes from an **R-NSGA-II multi-objective frontier**: all five objectives are optimized
at once, builds are ranked by Pareto non-domination, and the survivor set is steered toward each
champion's **identity reference point** (the objective mix their own kit implies). This replaced the
single-objective beam for Ω, which committed to one axis too early. A champion is never forced onto a
role — a non-traditional build that matches the identity point survives on the frontier.

## The wiki decoder
Item and rune effects are read by a real recursive **template decoder**, not regex. Every value
carries the wiki's own type ({{as|VALUE|TYPE}}), so a CONDITION ("at or below 50% of max health")
is never again read as a PAYLOAD. Any template the decoder does not recognise is REPORTED — a future
patch that adds markup surfaces loudly instead of silently corrupting builds. Current unknown
templates: 0.

## Legality
Builds obey the wiki's **item group** rule (one item per group: Fatality, Blight, Lifeline,
Spellblade, Hydra, Annul, Immolate, Manaflow). Before this rule was read from the source,
**37% of every build the engine produced was illegal** — Lord Dominik's + Mortal Reminder +
Serylda's are all one group; Void Staff + Cryptbloom are another.

## Honest state
- 53/106 SR legendary passives computed; the rest are valued on raw stats and **flagged in the app**.
- 16/17 keystones computed. Unmodelled runes contribute ZERO so they cannot win by default.
- 8 parser claims rejected by the sanity gate (a condition read as a payload).
- 61 champion data defects published in `dna_defects.json`.
- 4 dual-form champions (Aphelios, Jayce, Udyr, Mega Gnar) excluded pending a two-form model.
- Ability cast/channel times: the wiki's ChannelData module has ONE entry. A true tick simulator
  remains impossible without inventing numbers. We don't.

## Run it
```
python3 run_all.py     # ingest -> DNA -> validate -> effects -> optimize -> app -> trust
```
`run_all_v2.py` is resumable and checkpoints every 10 champions.
Patch day: drop new wiki exports into the uploads folder and re-run.
