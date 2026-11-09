---
capability: doc-lint-comment-rules
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.repo.doc_lint.comment_lint.lint_source@246629f4d1
  - cosa.repo.doc_lint.comment_lint.main@b67cbc1960
  - cosa.repo.doc_lint.comment_lint.line_pointer_findings@c52e302db2
  - cosa.repo.doc_lint.comment_lint.dangling_path_findings@d00d0a28d2
  - cosa.repo.doc_lint.comment_lint.commented_out_code_findings@fe24574f73
  - cosa.repo.doc_lint.comment_lint.is_commented_out_code@214584af37
  - cosa.repo.doc_lint.comment_lint.tracked_paths@5f52346c0a
  - cosa.repo.doc_lint.comment_lint.ignored_paths@ae5442232e
  - cosa.repo.doc_lint.comment_lint.take_path_failure@3532a03de0
---
# Doc-lint comment rules

The linter for `#` comments in Python files, called by the [[doc-lint-gate]]. Its sibling pages are [[doc-lint-markdown-comments-and-tools]] and [[doc-lint-text-rules]].

## What it does
- `lint_source` checks every `#` comment for banners, shouting and emphasis glyphs. It skips the shebang and reports one parse-error finding for a file that cannot be tokenized. `main` is the command line, and warns once when the dangling-path check was skipped.
- `line_pointer_findings` flags each `file.ext:NNN` citation, for the extensions in `POINTER_EXTENSIONS`, so `host:port` and version strings pass.
- `dangling_path_findings` flags a cited repo path (a slash, a known extension, a tracked top-level folder) that git does not track. It skips wildcards, URLs, `...`, placeholders such as `foo` and ignored paths.
- `commented_out_code_findings` flags a comment that `is_commented_out_code` finds to be a Python statement. Prose such as `return early`, pragmas and bare names pass.
- `tracked_paths` lists the files git tracks, from the index, cached per root during a whole-corpus run. `ignored_paths` returns the named paths that `git check-ignore` matches.

## Invariants
- The three rules above accept a same-line `doc-lint: waive` marker, which is cut off before the statement parse. No other comment rule can be waived.
- A git failure turns off the dangling-path rule alone for the rest of the run. `take_path_failure` hands over the reason once and clears it.
