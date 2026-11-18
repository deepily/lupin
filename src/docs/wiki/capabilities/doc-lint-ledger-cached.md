---
capability: doc-lint-ledger-cached
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - cosa.repo.doc_lint.harness_runner.cached@0c43294747
---
# Doc-lint ledger cache

One helper of the harness runner in [[doc-lint-harness-runner]]: a call made once is read back from the ledger afterwards.

## What it does
- `cached( ledger, key, make )` returns the ledger's value for a key without calling `make`. Otherwise it awaits `make()` and stores the value under the key first.
- A `None` ledger always calls `make` and stores nothing.
