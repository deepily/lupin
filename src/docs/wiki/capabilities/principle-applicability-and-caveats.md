---
capability: principle-applicability-and-caveats
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - cosa.agents.prediction_engine.principle_retrieval.supporting_rows@4799fd492a
  - cosa.agents.prediction_engine.principle_retrieval.latest_caveat@fa94a2363f
  - cosa.agents.prediction_engine.principle_retrieval.clean_caveat@3d050322f2
  - cosa.agents.prediction_engine.principle_retrieval.applicability_rules@42d7ad6241
  - cosa.agents.prediction_engine.card_stage.card_stage_of@81efdf6c81
  - cosa.agents.prediction_engine.card_stage.question_text@37a21e9fa7
---
# Principle applicability checks and caveats

The parts of principle retrieval that drop a principle that does not fit the card, and that attach a stored caveat. Both sit behind switches that are off. Retrieval itself is in [[principle-retrieval]]. None of these calls a model or writes anything.

## Rows that count
- `supporting_rows( principle_id, evidence, asked_at, extractor_version, relations )` lists one principle's extractor rows of the current version that are usable at the ask.
- By default it keeps the relations status counts as support. `relations=None` keeps every relation.

## Caveats
- `latest_caveat` picks the caveat of the most recently answered supporting row that has one, or None.
- `clean_caveat` turns every run of whitespace into one space and cuts the text at `CAVEAT_MAX` (200). So a caveat can never start a line of its own.

## Applicability
- `applicability_rules( principles, evidence, asked_at, extractor_version, card, card_stage )` returns the failing principles only, each with its rule.
- The `antecedent` rule fails a principle when a row of any relation quotes an antecedent and no quote appears in the card. It is tried first.
- The `stage` rule fails a principle when its supporting rows name a stage and none is the card's.
- A principle whose rows quote no antecedent, or name no stage, passes that rule.

## The card's stage
- `card_stage_of( episode )` names the decision stage from the card's own words, never from an answer.
- A question holding a delegation phrase such as "ask me before" or "you decide" is `who_decides`.
- Otherwise a yes/no, a multiple choice or a card with an option list is `what_to_do_once_asked`. Anything else is None, and the stage rule is skipped.
- `question_text( episode )` is the title, message and field prompts, case-folded. Option labels and the abstract are left out, because they can mention delegation in passing.
