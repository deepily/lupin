---
capability: prediction-checkpoint-cohort-and-fixture-scripts
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - scripts.filter_stop_hook_cards.stop_hook_ids@2b1a6318e3
  - scripts.filter_stop_hook_cards.split_cohort@857029fe35
  - scripts.filter_stop_hook_cards.build@7219b0eb68
  - scripts.filter_stop_hook_cards.main@7ec00621ae
  - scripts.capture_proxy_decisions_fixture.capture@d5892daf0e
  - scripts.capture_proxy_decisions_fixture.main@ab397b3ad4
---
# Cohort filter and proxy-decision fixture scripts

Two operator scripts under `src/scripts/` that read the database in a read-only transaction and prepare test or checkpoint data.

## Cohort without Stop-hook cards
- `filter_stop_hook_cards.py` builds a second checkpoint cohort without the cards titled exactly "Stop hook: Anything else?". The committed cohort file is only read.
- `stop_hook_ids( session )` returns those ids in lower case and rolls the transaction back. `split_cohort` returns the kept and dropped ids, both in cohort order.
- `build` writes the filtered cohort, its manifest and the dropped ids, then checks the cohort against the manifest with `verify_snapshot`. It raises `RuntimeError` when no id would be dropped, before writing, or when the check fails, after writing.
- `main` takes `--cohort`, `--out`, `--manifest` and `--dropped`, each with a default under `src/conf/`, prints the receipt as JSON and returns 0. Nothing checks that the output files are new.

## Proxy-decision fixture
- `capture_proxy_decisions_fixture.py` needs `--day`. `capture( day )` returns that UTC day's `proxy_decisions` rows tagged `organic`, oldest first, with `user_answer` taken from the row's metadata and no notification id.
- `main` prints the rows as JSON on standard output and returns 0. It needs `LUPIN_ROOT` set.
