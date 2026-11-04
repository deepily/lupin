---
capability: dm-rewrite-study-freeze
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.research.phi4_flash_lite_study.freeze_corpus.EmptyReplaySet@21a4eeb0bd
  - cosa.research.phi4_flash_lite_study.freeze_corpus.LivePathRefused@4f144667ff
  - cosa.research.phi4_flash_lite_study.freeze_corpus.SourceChangedDuringRead@3e210eabd9
  - cosa.research.phi4_flash_lite_study.freeze_corpus.assert_dir_is_not_live_corpus_dir@c0d19bcacb
  - cosa.research.phi4_flash_lite_study.freeze_corpus.build_manifest@fd3ad3d582
  - cosa.research.phi4_flash_lite_study.freeze_corpus.count_claims@5b462331a9
  - cosa.research.phi4_flash_lite_study.freeze_corpus.current_git_sha@55ba3132b3
  - cosa.research.phi4_flash_lite_study.freeze_corpus.main@c88724659b
  - cosa.research.phi4_flash_lite_study.freeze_corpus.read_corpus_rows@568b95e37d
  - cosa.research.phi4_flash_lite_study.freeze_corpus.resolve_live_corpus_path@12f35d4889
  - cosa.research.phi4_flash_lite_study.freeze_corpus.sample_rows@7b107deac0
  - cosa.research.phi4_flash_lite_study.freeze_corpus.select_eligible@b31ae2109f
  - cosa.research.phi4_flash_lite_study.freeze_corpus.sha256_of_file@b4a8bcd899
  - cosa.research.phi4_flash_lite_study.freeze_corpus.sha256_of_rows@a59d4255a5
  - cosa.research.phi4_flash_lite_study.freeze_corpus.verify_snapshot@e8f8f864be
  - cosa.research.phi4_flash_lite_study.freeze_corpus.write_snapshot@b8134d1542
---
# DM rewrite study: freezing the corpus

The helpers behind `freeze` in [[dm-rewrite-model-study]]. Replay and statistics are in [[dm-rewrite-study-replay]] and [[dm-rewrite-study-checks]].

## What it does
- `resolve_live_corpus_path` asks the DM router for its corpus directory and appends `dm_traffic.jsonl`, so the study and the writer cannot disagree.
- `assert_dir_is_not_live_corpus_dir` refuses the live directory by real path and by device and inode. A bind mount defeats a path check alone.
- `read_corpus_rows` returns the rows and a count of unparseable lines. A truncated last line is counted, not fatal.
- `count_claims` is the router's own claim counter. `select_eligible` keeps non-blank bodies with strictly more claims than the trigger, in input order.
- `sample_rows` keeps the original order and is repeatable for a seed. `write_snapshot` writes sorted-key JSON, one row per line to `dm_replay_frozen.jsonl`, and the manifest is `manifest.json` beside it. `sha256_of_file` and `sha256_of_rows` give the source and snapshot checksums, and the row checksum covers the exact bytes `write_snapshot` emits.
- `build_manifest` records source and snapshot paths, counts and checksums, the selection settings and the git sha from `current_git_sha`. That sha is `None` when git fails, and a freeze goes on.
- `verify_snapshot` returns `( ok, detail )`. It fails on an unparseable line, too few rows, a row count that differs, or a checksum that differs.
- `main` is the command line: `--out-dir`, `--trigger-claims` (default 4), `--all-rows`, `--sample`, `--seed`, `--minimum-rows` and `--verify`. It returns 1 only for a failed verify.

## Don't
- Don't trust a zero-row freeze. The claim counter fails open to 0, so a broken counter makes every row ineligible. `EmptyReplaySet` stops it.
- Don't keep a manifest from a freeze that raised `SourceChangedDuringRead`. The source is checksummed before and after the read, and the corpus grew in between.
- Don't aim the freeze at the live directory. `LivePathRefused` is a hard stop.
