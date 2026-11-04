---
capability: doc-lint-docs-only-diff
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.repo.doc_lint.docs_only_diff.directive_difference@4c79fa4cff
  - cosa.repo.doc_lint.docs_only_diff.first_difference@647af613e9
  - cosa.repo.doc_lint.docs_only_diff.python_directives@6dfb42a951
  - cosa.repo.doc_lint.docs_only_diff.python_difference@c21dece767
  - cosa.repo.doc_lint.docs_only_diff.dart_tokens@fcc7561e72
  - cosa.repo.doc_lint.docs_only_diff.dart_difference@44a4602b05
  - cosa.repo.doc_lint.docs_only_diff.file_difference@c9d821423c
  - cosa.repo.doc_lint.docs_only_diff.changed_files@885399284b
  - cosa.repo.doc_lint.docs_only_diff.path_difference@1afcb01e8c
  - cosa.repo.doc_lint.docs_only_diff.check_diff@ea74866603
  - cosa.repo.doc_lint.docs_only_diff.main@019e348680
  - cosa.repo.doc_lint.ts_docs_only_diff.analyse@84b3f8ef80
  - cosa.repo.doc_lint.ts_docs_only_diff.changed_files@368cc2b6e9
  - cosa.repo.doc_lint.ts_docs_only_diff.description_difference@ee8bbcd779
  - cosa.repo.doc_lint.ts_docs_only_diff.path_difference@7920777588
  - cosa.repo.doc_lint.ts_docs_only_diff.check_diff@f2f86002f5
  - cosa.repo.doc_lint.ts_docs_only_diff.main@fdb2a5b63d
---
# Doc-lint docs-only diff

Proves that a documentation rewrite left the code unchanged, for Python, Dart and script files. `caps_fix` in [[doc-lint-support-modules]] runs it before writing a file.

## Python and Dart (`docs_only_diff`)
- `python_difference` compares two sources with docstrings stripped, and returns `None` when the ASTs are identical. `first_difference` names the path to the first differing node and both sides.
- `python_directives` lists directive comments in order, such as `noqa`, `pragma`, `type:` and the coding line, each with its code line. `directive_difference` names the first one removed, added, moved or changed.
- `dart_tokens` drops whitespace and every comment, nested block comments included, and keeps a comment marker inside a string. `dart_difference` compares the token lists and the directive comments.
- `file_difference` checks one changed file. A file added or deleted is a difference.

## Paths and modes
- `changed_files` lists paths that differ between base and head with their modes, read with `-z`. A rename counts as a delete plus an add.
- `path_difference` fails a file type it does not know as unchecked, and fails a mode change on a file present on both sides. `check_diff` checks every changed file that is not markdown.
- `main` prints a pass or fail line per path and returns 0 when all are docs-only.

## Scripts (`ts_docs_only_diff`)
- `analyse` runs a Node token script over texts in one process and returns a description per id. `description_difference` compares two descriptions, and a parse error is a difference.
- `changed_files`, `path_difference`, `check_diff` and `main` work as above for `.ts`, `.js` and `.mjs`.
