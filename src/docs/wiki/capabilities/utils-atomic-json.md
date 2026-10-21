---
capability: utils-atomic-json
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.utils.atomic_json.load_json_section@2f34252d1b
  - cosa.utils.atomic_json.write_json_atomic@eceb325e91
---
# Atomic JSON files

Two helpers the arbiter and the worktree ledgers share to write a JSON file whole and read one section back. The hook library keeps its own copies, because a hook must not import `cosa`.

## What it does
- `write_json_atomic( path, data )` writes `data` to a temp file in the same folder, then renames it over the target. A reader sees the old file or the new one.
- The temp name carries the writer's pid and a uuid, so two writers never share one.
- It creates the parent folder when missing. A value that JSON cannot encode is written as its `str()`.
- `load_json_section( path, key )` returns the dict stored under a top-level key.

## Don't
- Don't use `load_json_section` to tell a missing file from an empty section. Both give `{}`.

## Invariants
- `load_json_section` never raises. A missing or unreadable file, bad JSON, a non-object file or a non-dict value gives `{}`.
- `write_json_atomic` never swallows an `OSError`.
