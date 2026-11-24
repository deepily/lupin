---
capability: principle-retrieval
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - cosa.agents.prediction_engine.principle_retrieval.PrincipleBoundExceeded@0853c3b241
  - cosa.agents.prediction_engine.principle_retrieval.embedding_text@f007a01873
  - cosa.agents.prediction_engine.principle_retrieval.encoder_version_of@bbd0bdb649
  - cosa.agents.prediction_engine.principle_retrieval.load_owner_ledger@f1ebcb9d08
  - cosa.agents.prediction_engine.principle_retrieval.principle_block@670a623320
  - cosa.agents.prediction_engine.principle_retrieval.retrieval_limits@5fc23ecaa0
  - cosa.agents.prediction_engine.principle_retrieval.reembed_principles@bd20e20746
  - cosa.agents.prediction_engine.principle_retrieval.retrieve_principles@e37ee0c827
  - cosa.agents.prediction_engine.principle_retrieval.select_principles@534a882f93
  - cosa.agents.prediction_engine.principle_retrieval.session_lookup@8f3af8c197
  - cosa.agents.prediction_engine.principle_features.card_features@db9c0264e8
  - cosa.agents.prediction_engine.principle_features.feature_lookup@eb0253643c
---
# Principle retrieval and card features

Fetches the principles that apply to one ask and shapes them as a prompt block. Tables are in [[rest-preference-principle-tables]]. The forecast that uses the block is in [[principles-forecast-arm]].

## What it does
- `retrieve_principles` filters in SQL by owner, an embedding, the same `encoder_version` and scope global or `project:<name>`. At or below the limit it fetches every match in cosine order. Above it, a positive multiplier M fetches only the `k` x M nearest. Each status is derived as of the ask.
- It returns `principles`, `available` and `short`. Nothing is written. More than `bound` matches raise `PrincipleBoundExceeded` when the multiplier is 0.
- `retrieval_limits()` reads the limit and multiplier from the INI file, shipped at 5000 and 0. A missing key raises, a limit under 1 raises, and a negative multiplier raises.
- `select_principles( scored, statuses, k )` drops principles with no usable evidence, contested ones and retracted ones. Then it keeps the first `k`, so a dropped principle never takes a slot.
- `principle_block( selected, suffix )` writes the lines the prompt carries: id, status, scope, dimension, statement and conditions. The lines sit between tags with a random suffix, so a statement cannot close the block.
- No raw answer, rationale or evidence row enters the block.
- One exception: a stored caveat, behind the switch `principle learner caveats enabled` (off).
- With it on, `retrieve_principles( caveats=True )` adds the latest supporting row's caveat to each entry.
- `principle_block( caveats=True )` then ends that principle's line with `caveat:` and the text. The text is one line, cut at 200 characters, inside the same tags.
- The switch `principle learner applicability checks enabled` (off) adds two drops to `retrieve_principles( applicability={ card, card_stage } )`.
- Rule `antecedent`: a row of the principle, of any relation, quotes an antecedent the card lacks. Rule `stage`: the rows name a stage and none is the card's.
- Neither rule calls a model. The result gains `applicability`, a list of `{ principle_id, rule }`.
- `principles_forecast` does not yet know the card's stage, so it passes none.
- `embedding_text` is the statement, then the rationale on a new line. `encoder_version_of( model )` names an encoder as `<model>:<recipe>`. The extractor job stores rows through it, so storing and filtering agree.
- `reembed_principles` re-embeds an owner's principles that another encoder made. It flushes without committing, and a wrong vector count raises with nothing changed.
- `load_owner_ledger` reads an owner's principles and evidence of every extractor version, because a ruling may name an older principle.
- `session_lookup` names the session of an evidence row's notification, in one query.
- `card_features( row )` returns the response type, notification type and the sender's project, or `none`. `feature_lookup` builds the lookup status uses, in one query. A title or message is never a feature.
