---
capability: doc-lint-claim-extractor
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.repo.doc_lint.claim_extractor.ExtractionParseError@120cfe250c
  - cosa.repo.doc_lint.claim_extractor.normalize@7959404295
  - cosa.repo.doc_lint.claim_extractor.classify_quote@ec7c8dc8a6
  - cosa.repo.doc_lint.claim_extractor.locate_quote@e71e6d0823
  - cosa.repo.doc_lint.claim_extractor.spans_overlap@2a47f18891
  - cosa.repo.doc_lint.claim_extractor.uncovered_fraction@bc84eb8f22
  - cosa.repo.doc_lint.claim_extractor.parse_claims@a33e51e1a0
  - cosa.repo.doc_lint.claim_extractor.verify_claims@8cafb78103
  - cosa.repo.doc_lint.claim_extractor.discard_rows@6b30f41607
  - cosa.repo.doc_lint.claim_extractor.uncovered_runs@a7b12d01aa
  - cosa.repo.doc_lint.claim_extractor.enclosing_sentences@9af6c1eaab
  - cosa.repo.doc_lint.claim_extractor.claim_tail@265a4fae8e
  - cosa.repo.doc_lint.claim_extractor.clause_stems@191a4d988c
  - cosa.repo.doc_lint.claim_extractor.says_more_than_quote@713a97712b
  - cosa.repo.doc_lint.claim_extractor.unsupported_claim_indexes@31f47af534
  - cosa.repo.doc_lint.claim_extractor.loose_qualifiers@e30a8a7044
  - cosa.repo.doc_lint.claim_extractor.extract_claims@74ad0c4062
---
# Doc-lint claim extractor

The first stage of the judge harness. A model lists the claims in old text, each with a verbatim quote. Python keeps only the claims whose quote verifies. [[doc-lint-claim-judge]] takes the claims next.

## Verifying quotes
- `normalize` folds white space and drops backticks and asterisks, keeping a map back to the original offsets. `classify_quote` returns no code and a span for a verified quote, else one of the discard codes.
- A bounded quote is discarded as too few words or characters, ambiguous, too long, or over the share cap. `locate_quote` returns the span exactly when the quote verifies.
- `parse_claims` parses the reply strictly as one JSON object and raises `ExtractionParseError` on a bad shape. `verify_claims` splits pairs into claims and discards, and `discard_rows` makes ledger rows with no quote text.

## Catching what the model missed
- `spans_overlap` and `uncovered_fraction` give the share of old text no span covers, with no model call. `uncovered_runs` keeps runs of enough words, and `enclosing_sentences` joins the sentences holding them.
- `claim_tail` returns the last clause of a claim and `clause_stems` its content stems. `says_more_than_quote` is true when that clause shares no stem with the quote. `unsupported_claim_indexes` lists such claims.
- `loose_qualifiers` returns limiting words that no tight quote covers.

## Extracting
- `extract_claims` asks the model, verifies, and puts uncovered runs and loose qualifiers to the model once more in one extra call. A run still uncovered is flagged for a person.
- An unreadable first reply is asked again once. If the retry is unreadable, the result has `parse_failed` set and no claims.
