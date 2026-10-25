---
capability: doc-lint-support-modules
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.repo.doc_lint.caps_fix.code_identifiers@8f22aa6efc
  - cosa.repo.doc_lint.caps_fix.lower_line@dac385db5a
  - cosa.repo.doc_lint.caps_fix.fix_source@4bb3798cf1
  - cosa.repo.doc_lint.caps_fix.fix_files@08b4c2184c
  - cosa.repo.doc_lint.caps_fix.format_report@3da1ddc8b3
  - cosa.repo.doc_lint.caps_fix.main@fbbb71b968
  - cosa.repo.doc_lint.changed_ranges.unquote_path@15988b2ea5
  - cosa.repo.doc_lint.changed_ranges.parse_diff_ranges@69094f15a4
  - cosa.repo.doc_lint.changed_ranges.changed_line_ranges@b022ef7423
  - cosa.repo.doc_lint.changed_ranges.in_ranges@dc49804a58
  - cosa.repo.doc_lint.links.markdown_link_findings@e7d1f55ecb
  - cosa.repo.doc_lint.links.is_outside_root@519e60a957
  - cosa.repo.doc_lint.links.design_path_findings@91b3575cbd
  - cosa.repo.doc_lint.waivers.waiver_state@cbff90e81d
  - cosa.repo.doc_lint.swept_scope.is_swept@142461ab96
  - cosa.repo.doc_lint.swept_scope.swept_files@2aa338dd52
  - cosa.repo.doc_lint.word_list.configure_root@237df3584b
  - cosa.repo.doc_lint.word_list.load_words@06e082a2cf
  - cosa.repo.doc_lint.word_list.default_words@a7d8effccd
---
# Doc-lint support modules

Small helpers the [[doc-lint-gate]] and the linters share: a capitals fixer, git diff ranges, link checks, waivers, the swept scope and the word list.

## Capitals fixer (`caps_fix`)
- `fix_source` lowers the words the `caps` rule flags, only inside docstring text. `code_identifiers` lists the names the source uses, so `lower_line` leaves an identifier alone and returns what it lowered and what stayed.
- `fix_files` fixes tracked files. A real run writes a file only when its edit passes `docs_only_diff`; otherwise the file is refused untouched. `format_report` renders the result, and `main` takes `--dry-run` and `--packages-only`.

## Touched lines (`changed_ranges`)
- `changed_line_ranges` asks git for a zero-context diff and `parse_diff_ranges` turns it into `{ path: [ ( first, last ) ] }`, one-based and inclusive. A pure deletion adds no range. `unquote_path` undoes git's quoting of a name, and `in_ranges` tests a line against the ranges.

## Links, waivers and scope
- `markdown_link_findings` reports relative links to missing files and skips web, anchor and doc-viewer links. `design_path_findings` reports a `Design:` path that does not exist.
- `is_outside_root` decides by shape alone, so an absolute path is never judged. `waiver_state` reads the same-line marker and returns `honoured`, `no-reason` or `none`.
- `is_swept` is true for a Python file `in_scope` accepts outside the held prefixes. `swept_files` lists them from git, never from a disk walk.
- `configure_root`, `load_words` and `default_words` read the word list behind the `caps` rule. An unreadable list raises, so the rule never turns off silently.
