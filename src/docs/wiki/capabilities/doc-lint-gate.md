---
capability: doc-lint-gate
pin_algorithm: py3.13.xf75af6/ts5.9.3
pins:
  - cosa.repo.doc_lint.gate.main@f005e4d493
  - cosa.repo.doc_lint.gate.collect@ab8ee7e8f8
  - cosa.repo.doc_lint.gate.is_mechanical@b1c8b96ada
  - cosa.repo.doc_lint.cli.in_scope@2ace35ed53
  - cosa.repo.doc_lint.cli.run_linter@ea4dca0555
  - cosa.repo.doc_lint.changed_ranges.filter_findings@17cdee1728
  - cosa.repo.doc_lint.text_rules.lint_text@b3cd1dcfa1
---
# Doc-lint gate

A pre-commit gate that lints docstrings, `#` comments and markdown on staged files. It warns by default and refuses in the cases listed below.

## What it checks
- `gate.collect` reads each staged `.py` and `.md` file from the index. Python goes through `docstring_lint`, `comment_lint` and ruff; markdown goes through `md_lint` and markdownlint-cli2. Ruff reads the staged text and markdownlint-cli2 reads the working-tree file. A missing tool prints a "SKIPPED" warning.
- `text_rules.lint_text` caps a summary at 90 characters, a sentence at 25 words and a preface at 6 lines. It also flags bare references, dates, banners and text addressed to a model. `docstring_lint` caps a docstring at 40 lines. `md_lint` caps a capability page at 40 lines, front matter included, and other `src/docs/` pages at 1500 words, except the `REFERENCE_SKIP` folders.
- `links.py` flags a relative markdown link whose target file is missing, and a `Design:` path inside the repo that does not exist. It skips web, mail, anchor-only and doc-viewer links, and never judges a `Design:` path outside the repo.

## Scope
- `cli.in_scope` drops a path with a `tests`, `.venv`, `node_modules`, `site-packages`, `__pycache__` or `rnd` directory segment. It also drops `test_*` files and `conftest.py`.
- Warnings print only for lines the staged diff touched (`filter_findings`). Page-level findings (`reference-length`, `capability-length`, `runbook-template`) print when the file has any touched line. Refusals ignore this filter.
- The swept scope (`swept_scope.is_swept`) is every tracked `.py` file that `in_scope` accepts, except paths under `src/lupin_mcp/`. Git lists the files, never a disk walk.

## What makes it refuse
- Warn mode exits 0, including after an internal crash, which prints a loud line. `--blocking` exits 1 when findings remain. Every refusal exits 3 and wins over `--blocking`.
- Rule divergence: a tracked rule file that differs between index and working tree refuses a commit. This applies when the commit stages a Python file or the count table. Rule files are the `doc_lint` package, the word list and `pre-commit-chain.sh`. The swept and counted checks are then skipped.
- Swept scope: a staged swept file is refused when its docstring lint holds any finding on any line, touched or not. A waiver is a same-line marker, `doc-lint: waive <rule> -- <reason>`, that names the rule. Its reason needs a word of three or more letters, or it waives nothing.
- A staged swept file that does not parse, or is not UTF-8, is refused and cannot be waived. The commit gate drops a leading byte-order mark first. Elsewhere a non-UTF-8 file is skipped with a warning, and in the counted scope it counts as one finding.
- Counted scope: every other tracked `.py` file is counted. It is refused when its unwaived finding count exceeds its entry in `src/conf/doc-lint-counts.json`, which records one count per file. A new file starts at zero and a rename inherits its old entry.
- The count table may only fall. A staged table that raises an entry is refused, unless it carries a new rules stamp and equals a census of the index. A table cut under other rules refuses a commit that stages a counted file. With no table, the scope is reported as not checked. `python3 -m cosa.repo.doc_lint.counts --write` regenerates it.
- `BLOCKING_PACKAGES` lists directory prefixes. A staged file inside one is refused for a mechanical finding on any line; the tuple is empty in this tree. Mechanical means `dated-banner`, `iso-date` or `agent-imperative`. It also means an eight-character id, bare or after `row`, `bug`, `task`, `ts`, `decision`, `job`, `pr` or `ticket` (`is_mechanical`).
- `pre-commit-chain.sh` runs the gate after the secret scan and the R&D guard. It stops the commit only on exit 3; any other non-zero exit is allowed with a notice.
- `pre-push-chain.sh` is not installed by default; a person links it into the hooks directory. Once linked, it lints each pushed tip in a throwaway worktree through `src/tests/run-doclint-gate.sh`, which runs `scope_gate`. That gate exits 0 clean, 1 findings, 2 not checked. Any non-zero result refuses the push, but a tip that does not descend from the epoch commit is pushed with a warning.

## Calling it
- Hook: `python3 -m cosa.repo.doc_lint.gate --repo-root <root>`. Whole-corpus or diff reports: `python3 -m cosa.repo.doc_lint.md_lint` (or `docstring_lint`, `comment_lint`) with `--changed BASE`, `--staged`, `--strict` or `--json`, through `cli.run_linter`.
- Related: [[cc-hooks-git-guards]], [[branch-and-directory-loc-analysis]], [[symbol-index]].
