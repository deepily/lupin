---
capability: reuse-merge-gate
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - lupin_mcp.reuse_merge_gate.read_names@7b792933ba
  - lupin_mcp.reuse_merge_gate.read_since@3dca802f66
  - lupin_mcp.reuse_merge_gate.resolve_base@e7a487a057
  - lupin_mcp.reuse_merge_gate.effective_base@4be5903d55
  - lupin_mcp.reuse_merge_gate.added_text_by_file@9ee8144d1c
  - lupin_mcp.reuse_merge_gate.added_definition_ids@6ba288dc97
  - lupin_mcp.reuse_merge_gate.run@c4e9795f10
  - lupin_mcp.reuse_merge_gate.summary@c915c6ed8e
  - lupin_mcp.reuse_merge_gate.main@f451060514
---
# Reuse merge gate

`lupin_mcp.reuse_merge_gate` is row 4 of the merge pyramid (`src/tests/run-reuse-gate.sh`). It judges the `REUSE-OUTCOME` lines a branch adds to Markdown files. It also checks that each new definition has one. It sends nothing and runs no model. See [[reuse-exit-review-gates-and-verdict-fit]].

## What it does
- `resolve_base( root, names )` returns the merge base with the named branch nearest HEAD, by commits. Names git does not know are passed over. It returns None when none has a merge base.
- `read_names( ini )` reads the key `reuse merge gate base`, split on spaces. It falls back to `main` and `origin/main` when the key is absent, doubled, unreadable or empty.
- `read_since( ini, key )` reads `reuse merge gate since`, or with `key` set to `SEARCHED_SINCE_KEY` the key `reuse searched since`. It returns None when empty. It raises `ValueError` for a value that is not a hexadecimal commit.
- `effective_base( root, sha, since, key )` moves the base up to `since` only when `since` lies between the base and HEAD. It raises `ValueError` when git does not know the commit.
- `added_text_by_file( root, base_sha )` returns `{ path: text }` for each added or changed `.md` file. Each added line keeps its own line number. It returns None when git cannot diff.
- `added_definition_ids( root, base_sha )` lists the ids of definitions new since the base, by the daily check's window. A renamed file is read under its old path, through the daily check's `definitions_held_at_start`. A definition whose qualified name holds `<locals>` (a function nested in a function) is not listed, since no other file can reuse it. Nor is a script definition that the symbol index does not report, such as a member of an object literal. No lookup can name one, so no outcome line could cover it. Its two detached worktrees are always removed.
- `run( root, base, diff_path, data_dir, log_dir, gating, since, searched_since )` judges every added line and records each once in `refusals.jsonl`. It lists new definitions with no outcome line. It also lists each ruled definition with no `SEARCHED` line (`missing_searched_refusals`). A line before `since` is not read, so it is exempt. The `SEARCHED` check reads only rulings added after `reuse searched since`, a key of its own so `since` need not move. A symbol index diff at `diff_path` replaces the definitions found from git.
- `summary( result, gating )` builds the lines the test-suite job reads. The unit is checks: one for the scan, one per outcome line, one per new definition.
- `main( argv, out )` is the command line.

## Exit codes
- 0: nothing refused, or `reuse review gating` is false. With gating false, refusals show as `Report-only` and `Failed` stays 0.
- 1: gating is true and a line is refused or a definition has no outcome line.
- 3: the gate could not check, so no summary block prints. Causes: an unreadable flag, a bad or unknown `since` or `reuse searched since`, or no base. Another is gating true with `reuse searched since` empty, or a failed git diff. Also an unwritable data folder, an unreadable call log or diff, or `algorithm_changed`.

## Don't
- Do not turn `reuse review gating` on without `reuse merge gate since` and `reuse searched since` in the same commit. The gate answers 3 rather than check back to the base.
- Do not read exit 3 as a pass. Nothing was checked.
