---
capability: doc-lint-package-check
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.repo.doc_lint.package_check.keyed_docstrings@cc6219cf86
  - cosa.repo.doc_lint.package_check.match_docstrings@0ecc28f231
  - cosa.repo.doc_lint.package_check.check_package@b10891dd4c
  - cosa.repo.doc_lint.package_check.refusal_result@c81d2e71c2
  - cosa.repo.doc_lint.package_check.main@237dffa530
---
# Doc-lint package check

Runs the docs-rewrite checks on one rewritten package against a base revision and writes the claim check's input. It is the per-package step of the [[doc-lint-package-sweep]].

## What it does
- `keyed_docstrings` keys each docstring of a source by kind, name and occurrence. `match_docstrings` pairs the old and new texts of one file and returns the pairs that changed.
- A file whose key set differs between the two sides is refused with the keys added or removed. A side that does not parse is refused too.
- `check_package` runs the four checks on the package's own in-scope `.py` files and returns `result` and `pairs`. `pass` is true only when every check ran and passed. No key set may differ.
- `refusal_result` builds a `result.json` body with every normal key for a run that could not start, with `pass` false and `refused` holding the message.

## Calling it
- `main` writes `result.json` and `pairs.json` into `--out` and prints one line per check. It exits 0 only when every check passed and 1 on a failure. It exits 2 when the base does not resolve or the package holds no in-scope file.
- A check that raises is recorded as not run, so one bug never costs the whole report.
