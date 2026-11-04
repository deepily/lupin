---
capability: doc-lint-ts-dart-linters
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.repo.doc_lint.tsdoc_lint.in_scope@0aea8eff92
  - cosa.repo.doc_lint.tsdoc_lint.tracked_files@a7ced7bcbf
  - cosa.repo.doc_lint.tsdoc_lint.mask_jsdoc@829e9606c6
  - cosa.repo.doc_lint.tsdoc_lint.lint_comment@8f4af6673c
  - cosa.repo.doc_lint.tsdoc_lint.lint_comments@a149a877c8
  - cosa.repo.doc_lint.tsdoc_lint.run_extractor@cea2c69364
  - cosa.repo.doc_lint.tsdoc_lint.main@2e5746f4fd
  - cosa.repo.doc_lint.dartdoc_lint.doc_comment_lines@64cbf3718d
  - cosa.repo.doc_lint.dartdoc_lint.doc_blocks@9e37dd2edf
  - cosa.repo.doc_lint.dartdoc_lint.lint_source@0bc05491f8
  - cosa.repo.doc_lint.dartdoc_lint.main@c78f7a09b8
---
# Doc-lint TypeScript and Dart linters

The comment linters for TypeScript, JavaScript and Dart, for the [[doc-lint-gate]]. They apply the [[doc-lint-text-rules]].

## TypeScript and JavaScript (`tsdoc_lint`)
- `in_scope` accepts `.ts`, `.js` and `.mjs`, tests included, and refuses `node_modules`, `.venv`, `dist` and minified files. `tracked_files` lists them from git.
- `run_extractor` sends files to a Node extractor in batches and returns records per file. It refuses a run where a file comes back with no record.
- `lint_comment` skips directive comments and commented-out code. A JSDoc block gets the full rule set and other comments a reduced one. `mask_jsdoc` blanks tags and `{@link}` spans first.
- `lint_comments` lints one file's records and adds a parse-error finding when the compiler failed. `main` takes `--changed`, `--staged`, `--strict` and `--json`.

## Dart (`dartdoc_lint`)
- `doc_comment_lines` returns the `///` and `/** */` lines and skips string literals. `doc_blocks` groups consecutive lines into blocks.
- `lint_source` lints each block, and a block over the line cap gives one `dartdoc-length` finding. `main` runs it through `cli.run_linter`.

Related: [[doc-lint-ts-count-tables]].
