---
capability: principle-vocabulary
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - cosa.agents.principle_learner.vocabulary.heading_for@b152c8df9e
  - cosa.agents.principle_learner.vocabulary.headings_block@dff0bfcd39
  - cosa.agents.principle_learner.vocabulary.is_heading@1d3d579dfc
  - cosa.agents.principle_learner.vocabulary.same_heading@121861db78
  - cosa.agents.principle_learner.vocabulary.shown_dimension@9afe5bb4a8
---
# Principle vocabulary

The 14 dimension headings the owner approved on 19 November 2026, and the map from 60 old dimension names to them. The extractor prompt reads the headings from here ([[principle-extractor-prompt-and-rules]]).

## What it does
- `is_heading( dimension )` is True only when the dimension equals an approved heading character for character.
- `heading_for( dimension )` returns the mapped heading for one of the 60 old names. It returns None for anything else, so an unknown name is never filed under a guessed heading.
- `shown_dimension( dimension )` gives the name a stored dimension is shown and compared under. An old name reads as its heading, and an unknown name is shown as stored.
- `same_heading( first, second )` is True when both dimensions show as the same name. An old name and its heading agree.
- `headings_block()` writes the headings as a numbered list in the approved order, for the extractor prompt.

## Don't
- Don't edit the headings of an old vocabulary in place. A new vocabulary gets a new `VOCABULARY_VERSION` date.
