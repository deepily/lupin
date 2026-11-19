---
capability: reuse-merge-gate-foreign-receipts
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - lupin_mcp.reuse_merge_gate.sibling_data_dirs@3a551af2db
  - lupin_mcp.reuse_merge_gate.foreign_receipts@c8073ceb17
  - lupin_mcp.reuse_merge_gate.name_foreign_receipts@161e944f94
---
# Reuse merge gate, receipts from another repo

A seat in another registered repo logs its reuse-tool calls under that repo's own data folder. Such a receipt is a search of another codebase. The gate reads those folders only to name where a refused receipt was logged. It never lets a line pass for it ([[reuse-merge-gate]]).

## What it does
- `sibling_data_dirs( root, names )` returns the existing `<fleet data root>/<name>/<data subdir>` folders that hold a `call-log` folder, in registry order. `names` is None to read the `external repos` registry. This repo's own folder is never listed.
- `foreign_receipts( sibling_dirs )` maps each receipt id in those call logs to the repo name. A receipt logged in two repos keeps the first of the list.
- `name_foreign_receipts( verdicts, receipts, foreign, root )` adds one reason to each refused line whose receipt is absent here and present in `foreign`. The reason names the other repo and says to re-run `check_exists` with root set to this one.

## How it is used
- `run` takes `sibling_dirs` and `main` builds them, except when `--log-dir` is given.
