---
capability: doc-lint-labelled-set-rejections
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.repo.doc_lint.labelled_set_rules.restated_elsewhere@91cf3e905a
  - cosa.repo.doc_lint.labelled_set_rules.restated_swap@c2966d5da0
  - cosa.repo.doc_lint.labelled_set_rules.qualifier_rejected@2e84b9e84a
  - cosa.repo.doc_lint.labelled_set_rules.structure_emptied@50a053a742
  - cosa.repo.doc_lint.labelled_set_rules.paragraph_orphan@44c5546a05
  - cosa.repo.doc_lint.labelled_set_rules.delete_rejection@c6b090ba19
  - cosa.repo.doc_lint.labelled_set_rules.markup_rejection@bf7404c77f
  - cosa.repo.doc_lint.labelled_set_rules.lead_in_codes@0282ff508e
  - cosa.repo.doc_lint.labelled_set_rules.lead_in_rejection@3db285ef36
  - cosa.repo.doc_lint.labelled_set_rules.stray_punctuation_rejection@6ffe47e44e
---
# Doc-lint labelled-set rejections

These rules keep a seeded removal from being a bad test. A candidate is refused when its claim stands elsewhere or the cut leaves broken text. Each rule is a heuristic. Helpers are in [[doc-lint-labelled-set-text-helpers]].

## Restated claims
- `restated_elsewhere` is true when another sentence holds at least `RESTATED_SHARE` of the span's content words. A span with no content words gives false.
- `restated_swap` is true when a number swap leaves the same value elsewhere. A quantifier swap is true when the same word occurs again, and any other class is false.
- `qualifier_rejected` refuses a qualifier deletion inside code, quotes or an example block. It also refuses one when another sentence shares two content words with it and carries an exclusion cue or the same qualifier.

## Broken text
- `delete_rejection` returns the first code that fires, in order: `SUMMARY`, `RESTATED`, `PRONOUN`, `LOWERCASE`, `PAREN_START`, `SHORT_SENTENCE`, `EMPTY_FIELD` and `EMPTY_HEADING`.
- `paragraph_orphan` is true when a cut paragraph opens on a pronoun no old paragraph opened on. `structure_emptied` returns `EMPTY_FIELD` or `EMPTY_HEADING`.
- `markup_rejection` returns `CODE` or `LINK` for a span that cuts into one, and `LIST_ITEM` for a delete that leaves a bare list marker. A weaken never gets `LIST_ITEM`.
- `stray_punctuation_rejection` returns `STRAY_PUNCTUATION` when a cut holds more stray marks than the original, counting each kind in both texts.

## Lead-ins
- `lead_in_rejection` returns `HANGING_CONDITION`, `DROPPED_CONDITION`, `JOINED_CONDITIONS` or `UNANSWERED_CONDITION` for a delete that leaves a lead-in hanging. The checks run in that order.
- `lead_in_codes` lists every code that fires. A test holds it to at most one, since no two checks can fire on one span.
- The rule over-rejects: it refuses spans whose result would read fine.
