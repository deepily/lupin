---
capability: doc-lint-claim-history
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.repo.doc_lint.history_class.history_kinds@409763c7fe
  - cosa.repo.doc_lint.history_class.is_history@dedf36f829
  - cosa.repo.doc_lint.history_class.tag_absent@27827d4c9d
  - cosa.repo.doc_lint.history_destination.normalize@3a8f0d8dd5
  - cosa.repo.doc_lint.history_destination.quote_found@b96cd79095
  - cosa.repo.doc_lint.history_destination.load_sort@712854b313
  - cosa.repo.doc_lint.history_destination.load_worksheet@d2001a6b7f
  - cosa.repo.doc_lint.history_destination.read_destinations@e33e4d08e4
  - cosa.repo.doc_lint.history_destination.design_lines_check@76fa29de35
  - cosa.repo.doc_lint.history_destination.empty_result@601d118088
  - cosa.repo.doc_lint.history_destination.check_history@f212740bd0
  - cosa.repo.doc_lint.history_destination.main@b2eb06af71
---
# Doc-lint claim history

Two parts of the claim check handle a claim a rewrite dropped. `history_class` tags a dropped claim as history. `history_destination` checks that each such claim's text is kept elsewhere. The claims come from [[doc-lint-claim-extractor]].

## Tagging (`history_class`)
- `history_kinds` returns the history kinds a claim matches, searched in the claim text and never in the quote. A reason or behaviour marker in the text or quote returns none.
- `is_history` says whether a claim is tagged. The tag excuses nothing. `tag_absent` lists the claims judged dropped and which of them are tagged.

## Destination (`history_destination`)
- `normalize` lowercases, removes backticks and folds white space. `quote_found` is true only when the normalized quote appears whole. A quote edge on a word character must not touch another there.
- `load_sort` reads a reviewer's sort file and `load_worksheet` reads the worksheet that numbers claims. Both raise `ValueError` for a malformed row.
- `read_destinations` reads design documents and commit bodies, labelled `design:<path>` and `commit:<full sha>`. `design_lines_check` reports `Design:` lines whose target does not exist.
- `check_history` checks that every history-labelled claim has its quote at a destination. `empty_result` builds a refusal body with every normal key and `pass` false.
- `main` writes `history-destination.json`. It exits 0 only on a pass and 1 for a missing claim or a dead `Design:` line. A refusal exits 2.
