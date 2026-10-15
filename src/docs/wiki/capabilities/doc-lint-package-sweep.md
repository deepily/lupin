---
capability: doc-lint-package-sweep
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.repo.doc_lint.scope_gate.check@af101dc1f0
  - cosa.repo.doc_lint.scope_gate.report@b84598b273
  - cosa.repo.doc_lint.scope_gate.main@811e456565
  - cosa.repo.doc_lint.sweep_packages.split_packages@57f7dd4f89
  - cosa.repo.doc_lint.sweep_packages.measure_file@dfb4a75cd0
  - cosa.repo.doc_lint.sweep_packages.density@bfb8fb8a1e
  - cosa.repo.doc_lint.sweep_packages.sweep@70805e5a87
  - cosa.repo.doc_lint.sweep_packages.format_report@98a5dc221a
  - cosa.repo.doc_lint.sweep_packages.main@cbebec3d35
  - cosa.repo.doc_lint.sweep_lock.slug_of@da23d35e03
  - cosa.repo.doc_lint.sweep_lock.holder_of@b6cb7f02cf
  - cosa.repo.doc_lint.sweep_lock.take@31a5ed8f1a
  - cosa.repo.doc_lint.sweep_lock.release@bbfa9c72da
  - cosa.repo.doc_lint.sweep_lock.takeover@15ac0a42a9
  - cosa.repo.doc_lint.sweep_lock.main@574910fc04
---
# Doc-lint package sweep

The tools behind the docs-rewrite sweep: a whole-scope gate, a package lister and a per-package lock. They sit beside the [[doc-lint-gate]].

## Scope gate (`scope_gate`)
- `check` lints every swept file and returns `files`, `docstrings`, `findings` and `not_checked`. It reads the word list from `words_root`, so the checked tree cannot change the rules.
- `report` prints one line per finding, then the counts, and `main` exits 0 clean, 1 on findings and 2 when it could not check.

## Package lister (`sweep_packages`)
- `split_packages` groups paths into packages, directories with an `__init__.py`, and files in no package. `measure_file` counts one file's docstrings and the findings on them, and `density` is findings per docstring.
- `sweep` measures every package from `git ls-files`, worst density first. `format_report` and `main` print it, as text or with `--json`.

## Package lock (`sweep_lock`)
- The lock is a git ref per package. `slug_of` turns a directory into its ref name, escaping `_` and `-` so two paths never share a slug.
- `holder_of` reads the holder. `take` creates the ref, and of two takers one wins. `release` deletes only the caller's own lock.
- `takeover` replaces a holder of 24 hours or more, or one stamped over five minutes ahead. `main` takes, releases, takes over or shows, exiting 1 on a refusal.

Related: [[doc-lint-package-check]].
