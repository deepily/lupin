---
capability: doc-lint-labelled-set-text-helpers
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.repo.doc_lint.labelled_set_rules.sentences_of@9e810e79ee
  - cosa.repo.doc_lint.labelled_set_rules.sentence_spans@180560c938
  - cosa.repo.doc_lint.labelled_set_rules.words_of@006d7360e5
  - cosa.repo.doc_lint.labelled_set_rules.content_words@b4ae93f7ff
  - cosa.repo.doc_lint.labelled_set_rules.first_sentence_end@9945ff9a3a
  - cosa.repo.doc_lint.labelled_set_rules.sentence_start_before@9d86de3bdf
  - cosa.repo.doc_lint.labelled_set_rules.paragraphs_of@5e7c494149
  - cosa.repo.doc_lint.labelled_set_rules.number_value@44e59e1f6a
  - cosa.repo.doc_lint.labelled_set_rules.lead_words@32198be65a
  - cosa.repo.doc_lint.labelled_set_rules.list_item_starts@e7f6fb7c83
  - cosa.repo.doc_lint.labelled_set_rules.protected_regions@216cc2ad28
  - cosa.repo.doc_lint.labelled_set_rules.in_protected@6f0ac316c1
  - cosa.repo.doc_lint.labelled_set_rules.code_regions@28af2379fa
  - cosa.repo.doc_lint.labelled_set_rules.link_regions@bc3d9f505d
  - cosa.repo.doc_lint.labelled_set_rules.cuts_into@39189a2f67
---
# Doc-lint labelled-set text helpers

Text predicates the labelled-set seeder's selection rules are built from. They use no model and no file. The rules that judge a candidate are in [[doc-lint-labelled-set-rejections]].

## Sentences and words
- `sentences_of` splits a text at terminal punctuation followed by white space. `sentence_spans` returns the offsets of each non-blank sentence, and `first_sentence_end` the offset where the first one ends, or 0.
- `sentence_start_before` says whether a sentence would begin at an index: at text start, after `.`, `!`, `?` or a blank line.
- `words_of` counts words by white space, not counting a leading bullet or list marker, so `- keep the lock` counts 3. `lead_words` returns the lowercase words minus that marker.
- `content_words` returns the lowercase words of three letters or more that are not function words.
- `number_value` returns the integer of a digit token or of a number word from one to six.
- `paragraphs_of` splits a text at blank lines. `list_item_starts` returns the offset where each list item's text begins, just after its bullet or number.

## Regions
- `protected_regions` returns the regions of the old text protected from change: code fences, backtick and double-quoted literals, and example blocks. `in_protected` says whether a span overlaps one.
- `code_regions` returns code fences and backtick spans only. `link_regions` returns each `[reference]` link with its target or label.
- `cuts_into` is true when a span overlaps a region without holding all of it.
