---
capability: doc-lint-marker-counts
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.repo.doc_lint.marker_counts.blank_code@e2ddc46198
  - cosa.repo.doc_lint.marker_counts.strip_markdown@91d84ac20f
  - cosa.repo.doc_lint.marker_counts.link_target_of_label@35a7ac216e
  - cosa.repo.doc_lint.marker_counts.is_section_ref_resolved@9e648668f6
  - cosa.repo.doc_lint.marker_counts.bare_section_refs@65162ec5ae
  - cosa.repo.doc_lint.marker_counts.caps_words@457e832782
  - cosa.repo.doc_lint.marker_counts.count_markers@15d6adc538
  - cosa.repo.doc_lint.marker_counts.rates_per_thousand@65862d90bc
  - cosa.repo.doc_lint.marker_counts.add_counts@a8b7284b8c
  - cosa.repo.doc_lint.marker_counts.empty_counts@a4fcbacde2
---
# Doc-lint marker counts

Counts the writing markers in docstrings and markdown pages, which the [[doc-lint-metrics-measure]] turns into rates. A marker is a pattern the style rules discourage.

## Preparing the text
- `blank_code` reduces fenced and doctest blocks to their newlines, so line numbers hold. `strip_markdown` removes front matter, fenced code and HTML comments, and keeps inline code spans.

## Section marks
- `bare_section_refs` lists section marks with no path beside them. `is_section_ref_resolved` is true when a path sits within the look-back or look-ahead distance in the same paragraph.
- A mark in a markdown link label resolves when the link target holds a path. `link_target_of_label` returns that target in full, however long.

## Capitals and rates
- `caps_words` lists all-caps words that are emphasis. A word counts only when its lowercase form is in the word list and not in the exceptions. Words in quotes or backticks are skipped.
- `count_markers` returns the word count and one count per marker column. `rates_per_thousand` converts to rates per 1,000 words, one decimal, and gives zero for an empty corpus.
- `empty_counts` returns a zeroed result and `add_counts` adds one result into a running total in place. Rates are computed once from the summed counts, never summed.
