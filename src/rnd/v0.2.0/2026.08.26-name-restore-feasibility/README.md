# Reproduction kit — 2026.08.26 name-restore feasibility

Run from this directory. `drops.py` reads the live corpus at
`projects-data/lupin/dm-corpus/dm_traffic.jsonl`.

| file | what it is |
|---|---|
| `drops.py` | reproduces §1 — the rewritten / dropped / single-drop counts |
| `classes.py` | §1a — splits the 1,560 into sender-signature / identifier / third-party |
| `sample.py` | §2 — draws the stratified 60 (seed 20260826) |
| `pronoun.py` | §5 — finds the 18 strict and 77 loose pronoun cases |
| `roles.py` | §5d — draws and prints the 20 role-noun cases (seed 7) |
| `dump.py` / `dump18.py` | print cases for reading |
| `labels.py` | **the hand labels** — all 60, all 18, all 20, each with a reason |

⚠️ **`sample.json` and `role_sample.json` are COMMITTED ON PURPOSE.** The corpus is live and
grows, so re-running the draws on a later snapshot returns *different* cases — and `labels.py`
indexes by position. Without these two pins the labels would silently describe the wrong
messages. The large intermediates (`single_drops.json`, `classC.json`, `role_hits.json`) are
gitignored; rebuild them with `python3 drops.py && python3 classes.py`.
