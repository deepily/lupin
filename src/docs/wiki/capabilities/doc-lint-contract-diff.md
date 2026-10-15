---
capability: doc-lint-contract-diff
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.repo.doc_lint.contract_diff.tokens@ecb8e3593b
  - cosa.repo.doc_lint.contract_diff.overlap@5b5793c035
  - cosa.repo.doc_lint.contract_diff.guards@237c7d18b2
  - cosa.repo.doc_lint.contract_diff.changed_items@8992955408
  - cosa.repo.doc_lint.contract_diff.likely_lost@3b7c6164a3
  - cosa.repo.doc_lint.contract_diff.stand_in@c8f95130b3
  - cosa.repo.doc_lint.contract_diff.parse_sections@52bfa09450
  - cosa.repo.doc_lint.contract_diff.definition_sections@9aa581336b
  - cosa.repo.doc_lint.contract_diff.diff_contracts@bc37b5df67
  - cosa.repo.doc_lint.contract_diff.findings@e798e2a1e1
  - cosa.repo.doc_lint.contract_diff.check_diff@ca74b49adb
  - cosa.repo.doc_lint.contract_diff.render_table@54af1e2ce8
  - cosa.repo.doc_lint.contract_diff.main@564b433cc7
---
# Doc-lint contract diff

Compares the `Requires`, `Ensures` and `Raises` items of every definition before and after a change. A rewrite that drops or weakens an item shows up in the count or in the guards.

## Reading contracts
- `parse_sections` reads each heading and its bulleted items from one docstring. An indented continuation line joins the item above it.
- `definition_sections` maps each function and class to its sections. A class is named `K (class)`, and a repeated name gets `#2`, `#3` and so on.

## Comparing items
- `tokens` reduces an item to its meaning-carrying words, ignoring order, case and punctuation. `overlap` is the share of the old item's words the new item keeps.
- `guards` lists the negations, quantifiers, limits and comparison operators in an item. Dropping a `never` or turning `>=` into `>` changes the list, and rewording around them does not.
- `changed_items` finds old items whose best new match says the same thing with a guard missing, matched one to one.
- `likely_lost` picks the old items with the lowest best overlap. `stand_in` finds the new heading that now holds a vanished heading's items.

## Reporting
- `diff_contracts` returns one row per definition and heading. A row holds the before and after items, a missing-heading flag, its stand-in, and the lost and changed items.
- `findings` lists a vanished heading, a fallen item count and a weakened clause. `check_diff` runs it over every changed `.py` file, and a rename counts as a delete plus an add.
- `render_table` renders `HEADING MISSING`, `COUNT FELL` or a dash per row. `main` prints the table or JSON and returns 1 under `--strict` when there are findings.
