---
capability: doc-lint-gate-staged-input
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.repo.doc_lint.gate.git_toplevel@b5ba72423f
  - cosa.repo.doc_lint.gate.staged_entries@5c4fd4e89b
  - cosa.repo.doc_lint.gate.staged_changes@fc0dc27f85
  - cosa.repo.doc_lint.gate.staged_paths@5d9f3c8510
  - cosa.repo.doc_lint.gate.staged_binary@ad040db7aa
  - cosa.repo.doc_lint.gate.staged_deleted@ae77437671
  - cosa.repo.doc_lint.gate.staged_counted@887350e223
  - cosa.repo.doc_lint.gate.staged_ts_counted@8b9ac69fe2
  - cosa.repo.doc_lint.gate.staged_exports_counted@e88cd85fae
  - cosa.repo.doc_lint.gate.staged_source@0abd3a5b9b
  - cosa.repo.doc_lint.gate.staged_bytes@a746296982
  - cosa.repo.doc_lint.gate.head_table_text@c428d83787
  - cosa.repo.doc_lint.gate.incoming_commits@a3f2bb88c8
  - cosa.repo.doc_lint.gate.incoming_commit@48c806cde4
  - cosa.repo.doc_lint.gate.merged_in@24719de3c1
---
# Doc-lint gate staged input

How the [[doc-lint-gate]] reads what a commit stages: the file lists, the staged text, and the commit a merge or cherry-pick brings in. Every listing is anchored at the root and reads names apart at the NUL byte.

## File lists
- `git_toplevel` returns the working-tree root that holds a directory. `staged_entries` lists additions, copies, modifications, renames and type changes, with gitlinks and symlinks apart and a `changed` set that leaves out moves and mode-only changes.
- `staged_changes` is its names and `renamed_from` map with no gitlink or symlink. `staged_paths` keeps the in-scope paths. `staged_deleted` lists staged deletions.
- `staged_binary` lists files whose change git counts as binary, by git's own verdict.
- `staged_counted`, `staged_ts_counted` and `staged_exports_counted` return paths, renames and whether the matching count table is staged, for the Python, script and exports scopes.

## Text
- `staged_source` reads a file from the index and drops a leading byte-order mark, so findings match the diff's line numbers. `staged_bytes` reads from the index, or the working tree when the index has none.
- `head_table_text` reads a file as the last commit has it, or `None` when HEAD lacks it.

## Merge and cherry-pick
- `incoming_commits` names the commits an in-progress merge or cherry-pick brings in, one per octopus parent. An unreadable record gives a loud warning and lets no finding off. `incoming_commit` is the first.
- `merged_in` returns the findings on lines identical to an incoming commit's copy. A page-level finding qualifies only when the whole file matches. A line changed in a conflict is enforced.
