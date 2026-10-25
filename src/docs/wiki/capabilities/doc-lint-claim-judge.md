---
capability: doc-lint-claim-judge
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.repo.doc_lint.claim_judge.JudgeParseError@63d3593f90
  - cosa.repo.doc_lint.claim_judge.build_prompt@16c37fa75c
  - cosa.repo.doc_lint.claim_judge.parse_verdicts@45592fa3dd
  - cosa.repo.doc_lint.claim_judge.judge_claims@cf776d805e
  - cosa.repo.doc_lint.claim_judge.finish_judgements@8b515b8ea0
  - cosa.repo.doc_lint.claim_judge.history_report@e970fa218e
  - cosa.repo.doc_lint.claim_judge.unlabelled_drops@d514241779
  - cosa.repo.doc_lint.claim_judge.load_destination@8babbedd68
  - cosa.repo.doc_lint.claim_judge.refuse_stand_in@58bfecccfc
  - cosa.repo.doc_lint.claim_judge.history_destinations_missing@7f8ad99ef0
  - cosa.repo.doc_lint.claim_judge.restored_still_dropped@840a7f9ae4
  - cosa.repo.doc_lint.claim_judge.close_history_gate@57073e68ba
---
# Doc-lint claim judge

The second stage of the judge harness. It decides for each extracted claim whether the new text still states it, and closes the history labels. Claims come from [[doc-lint-claim-extractor]].

## Judging
- `build_prompt` lays out the numbered claims, the new text and an optional design document as tagged data. One random tag suffix is used, and it occurs in none of them.
- `parse_verdicts` reads one verdict per claim from one JSON object and raises `JudgeParseError` for extra keys, a bad word or wrong ids.
- `judge_claims` judges every claim, escalates the uncertain ones and fails closed. A claim uncertain after escalation is `absent` with a reason. No claims make no model call.
- `finish_judgements` does the same from first-pass verdicts. Only the uncertain claims go to the escalation model.

## History labels
- `history_report` lists every claim judged dropped as a row for the author to label `history` or `restored`. `unlabelled_drops` returns rows still without a valid label.
- `load_destination` reads the document a label says the claim moved to, and `refuse_stand_in` refuses one that holds the whole old or new text.
- `history_destinations_missing` returns history rows whose quote is absent from the destination.
- `restored_still_dropped` judges each restored row again and returns those the new text still does not state.
- `close_history_gate` runs all three checks together and returns `unlabelled`, `destination_missing`, `restored_failed` and `ok`.
