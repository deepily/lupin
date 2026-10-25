---
capability: doc-lint-gate-refusals
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.repo.doc_lint.gate.swept_refusal_line@0d0a268b83
  - cosa.repo.doc_lint.gate.refusal_line@b7ebfa4deb
  - cosa.repo.doc_lint.gate.counted_refusal@12b2a1cc13
  - cosa.repo.doc_lint.gate.is_warn_only@26cdbfbc48
  - cosa.repo.doc_lint.gate.is_record_exempt@5e73b498ee
  - cosa.repo.doc_lint.gate.page_condition@ca42ebf5f0
  - cosa.repo.doc_lint.gate.predating@fa2d8b8936
  - cosa.repo.doc_lint.gate.in_blocking_package@08514d8bd2
  - cosa.repo.doc_lint.gate.link_stands_for_source@7b10c95b40
  - cosa.repo.doc_lint.gate.rule_divergence@9af9a12ac4
  - cosa.repo.doc_lint.gate.scope_check@cf6204b9f6
  - cosa.repo.doc_lint.gate.counted_check@28a7c7040d
  - cosa.repo.doc_lint.gate.ts_counted_check@e850b589a6
  - cosa.repo.doc_lint.gate.exports_counted_check@d5610929b3
---
# Doc-lint gate refusals

How the [[doc-lint-gate]] decides what refuses a commit and words each refusal. Staged input comes from [[doc-lint-gate-staged-input]].

## Which findings refuse
- `is_warn_only` is true for a path in `WARN_ONLY_PATHS` or under `WARN_ONLY_PREFIXES`, which `--blocking` leaves in warn mode. `in_blocking_package` is true under a listed package prefix.
- `is_record_exempt` says whether rule set B drops a finding in a root record file. It is false for any file outside `RECORD_PATHS`.
- `page_condition` names a page-level condition apart from its size. `predating` returns the findings whose condition the last commit's copy already had with a measure that did not rise. A moved page has no earlier condition at a path that brings a limit.
- `link_stands_for_source` follows a staged symlink chain up to `MAX_LINK_HOPS`. It answers true when the end is unknown, such as a loop, and false only for a folder with no such file.

## Counted scopes
- `scope_check` holds one scope's staged files to its table and returns refusals, warnings and stats. With no table at HEAD and none staged, nothing is refused and the scope is reported as not checked.
- A staged table that raises an entry is refused unless it carries a new stamp and equals a census of the index. A table with another stamp refuses a commit that stages a counted file.
- `counted_check`, `ts_counted_check` and `exports_counted_check` run it for the Python, script and exports scopes.
- `rule_divergence` refuses a commit whose staged rule files differ from the working copies.

## Wording
- `refusal_line` gives the file, line, kind and where the history belongs, for a mechanical finding. `swept_refusal_line` adds the matched text and how to waive, and says so when a marker gives no reason.
- `counted_refusal` gives a header and up to `SHOWN_FINDINGS` findings for a file whose count rose.
