---
capability: doc-lint-seeder-candidates
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.repo.doc_lint.labelled_set_seeder.phrase_units@553a6194ec
  - cosa.repo.doc_lint.labelled_set_seeder.repair@74e9d818f8
  - cosa.repo.doc_lint.labelled_set_seeder.cut_text@a2ad747976
  - cosa.repo.doc_lint.labelled_set_seeder.bad_cut@87042b42ff
  - cosa.repo.doc_lint.labelled_set_seeder.quotable_once@c5b9a7b923
  - cosa.repo.doc_lint.labelled_set_seeder.span_ok@9a5af265d4
  - cosa.repo.doc_lint.labelled_set_seeder.delete_candidates@7a89f99459
  - cosa.repo.doc_lint.labelled_set_seeder.weaken_edits@d7b49c7f55
  - cosa.repo.doc_lint.labelled_set_seeder.apply_edit@70e29781a3
  - cosa.repo.doc_lint.labelled_set_seeder.edit_confined_to_token@49048bd341
  - cosa.repo.doc_lint.labelled_set_seeder.weaken_candidates@3eb7e9d909
  - cosa.repo.doc_lint.labelled_set_seeder.relocate_candidates@cf42dc2b96
  - cosa.repo.doc_lint.labelled_set_seeder.candidates_for@7a7b6df6c3
  - cosa.repo.doc_lint.labelled_set_seeder.candidate_span@0260d3f563
---
# Doc-lint seeder candidates

How the labelled-set seeding script finds what it may change in a docstring. A candidate is a delete, a weaken, a relocate or a paraphrase. The selection rules are in [[doc-lint-labelled-set-rejections]].

## Spans and cuts
- `phrase_units` returns clauses, parentheticals and list items of the old text as offsets. It never cuts mid-phrase, and two adjacent units in one sentence also give their joined stretch.
- `cut_text` returns the old text with a span removed and the join repaired. `repair` fixes spacing and stray punctuation after a cut, and edits nothing else.
- `bad_cut` returns `EMPTY`, `NO_VERB`, `DANGLING` or `ORPHAN` when a cut leaves broken text. Reasons are counted by code.
- `quotable_once` passes a span only when it passes the harness quote test and occurs once. `span_ok` also needs 2 or more words that are not all stoplist words.

## Candidate kinds
- `delete_candidates` returns each seedable deletion as `{ span, span_text, cut }`. Cuts refused by `bad_cut` or by rules 4, 5, 8, 9 and 10 are left out and counted by reason.
- `weaken_edits` returns every single-word coded edit. A number edit adds one to an integer under 100 or steps a number word up one. A qualifier deletion takes the word and one following space.
- `apply_edit` returns the old text with one edit applied. `edit_confined_to_token` says whether the weak text differs only at the changed token.
- `weaken_candidates` returns weakenings that pass `span_ok` and stay on the changed token. A swap whose value occurs again, or a refused qualifier or markup span, is left out.
- `relocate_candidates` returns each sentence of a text of 2 or more sentences, with the rest as the cut.
- `candidates_for` returns a docstring's candidates for a kind. A paraphrase has exactly one, the docstring itself.
- `candidate_span` returns the text a candidate removes or moves, as `x_span_in_old` records it. It is empty for a paraphrase.
