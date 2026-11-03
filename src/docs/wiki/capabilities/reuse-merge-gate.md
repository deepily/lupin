---
capability: reuse-merge-gate
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_merge_gate.read_names@7b792933ba
  - lupin_mcp.reuse_merge_gate.read_since@504f35523c
  - lupin_mcp.reuse_merge_gate.resolve_base@e7a487a057
  - lupin_mcp.reuse_merge_gate.effective_base@d7bf2a56d9
  - lupin_mcp.reuse_merge_gate.added_text_by_file@9ee8144d1c
  - lupin_mcp.reuse_merge_gate.added_definition_ids@eca08fd03f
  - lupin_mcp.reuse_merge_gate.run@0682ee5040
  - lupin_mcp.reuse_merge_gate.summary@c915c6ed8e
  - lupin_mcp.reuse_merge_gate.main@8dfbeebc88
---
# Reuse merge gate

`lupin_mcp.reuse_merge_gate` is row 4 of the merge pyramid (`src/tests/run-reuse-gate.sh`). It judges the `REUSE-OUTCOME` lines a branch adds to Markdown files. It also checks that each new definition has one. It sends nothing and runs no model. See [[reuse-exit-review-gates-and-verdict-fit]].

## What it does
- `resolve_base( root, names )` returns the merge base with the named branch nearest HEAD, by commits. Names git does not know are passed over. It returns None when none has a merge base.
- `read_names( ini )` reads the key `reuse merge gate base`, split on spaces. It falls back to `main` and `origin/main` when the key is absent, doubled, unreadable or empty.
- `read_since( ini )` reads `reuse merge gate since`, or None when empty. It raises `ValueError` for a value that is not a hexadecimal commit.
- `effective_base( root, sha, since )` moves the base up to `since` only when `since` lies between the base and HEAD. It raises `ValueError` when git does not know the commit.
- `added_text_by_file( root, base_sha )` returns `{ path: text }` for each added or changed `.md` file. Each added line keeps its own line number. It returns None when git cannot diff.
- `added_definition_ids( root, base_sha )` lists the ids of definitions new since the base, by the daily check's window. A renamed file is read under its old path. Its two detached worktrees are always removed.
- `run( root, base, diff_path, data_dir, log_dir, gating, since )` judges every added line and records each once in `refusals.jsonl`. It lists new definitions with no outcome line. A symbol index diff at `diff_path` replaces the definitions found from git.
- `summary( result, gating )` builds the lines the test-suite job reads. The unit is checks: one for the scan, one per outcome line, one per new definition.
- `main( argv, out )` is the command line.

## Exit codes
- 0: nothing refused, or `reuse review gating` is false. With gating false, refusals show as `Report-only` and `Failed` stays 0.
- 1: gating is true and a line is refused or a definition has no outcome line.
- 3: the gate could not check, so no summary block prints. Causes: an unreadable flag, a bad or unknown `since`, no base, or a failed git diff. Also an unwritable data folder, an unreadable call log or diff, or `algorithm_changed`.

## Don't
- Do not turn `reuse review gating` on without `reuse merge gate since` in the same commit. The gate answers 3 rather than check back to the base.
- Do not read exit 3 as a pass. Nothing was checked.
