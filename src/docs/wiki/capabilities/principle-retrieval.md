---
capability: principle-retrieval
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - cosa.agents.prediction_engine.principle_retrieval.PrincipleBoundExceeded@0853c3b241
  - cosa.agents.prediction_engine.principle_retrieval.embedding_text@f007a01873
  - cosa.agents.prediction_engine.principle_retrieval.encoder_version_of@21bd5692f2
  - cosa.agents.prediction_engine.principle_retrieval.load_owner_ledger@f1ebcb9d08
  - cosa.agents.prediction_engine.principle_retrieval.principle_block@670a623320
  - cosa.agents.prediction_engine.principle_retrieval.reembed_principles@bd20e20746
  - cosa.agents.prediction_engine.principle_retrieval.retrieve_principles@75d5dc404c
  - cosa.agents.prediction_engine.principle_retrieval.select_principles@534a882f93
  - cosa.agents.prediction_engine.principle_retrieval.session_lookup@8f3af8c197
  - cosa.agents.prediction_engine.principle_features.card_features@db9c0264e8
  - cosa.agents.prediction_engine.principle_features.feature_lookup@eb0253643c
---
# Principle retrieval and card features

Fetches the principles that apply to one ask and shapes them as a prompt block. Tables are in [[rest-preference-principle-tables]]. The forecast that uses the block is in [[principles-forecast-arm]].

## What it does
- `retrieve_principles` filters in SQL by owner, an embedding, the same `encoder_version` and scope global or `project:<name>`. It fetches every match in cosine order and derives each status as of the ask.
- It returns `principles`, `available` and `short`. Nothing is written. More than `bound` matches raise `PrincipleBoundExceeded`.
- `select_principles( scored, statuses, k )` drops principles with no usable evidence, contested ones and retracted ones. Then it keeps the first `k`, so a dropped principle never takes a slot.
- `principle_block( selected, suffix )` writes the lines the prompt carries: id, status, scope, dimension, statement and conditions. The lines sit between tags with a random suffix, so a statement cannot close the block.
- No raw answer, rationale or evidence row enters the block.
- `embedding_text` is the statement, then the rationale on a new line. `encoder_version_of( model )` names an encoder as `<model>|<recipe>`.
- `reembed_principles` re-embeds an owner's principles that another encoder made. It flushes without committing, and a wrong vector count raises with nothing changed.
- `load_owner_ledger` reads an owner's principles and evidence of every extractor version, because a ruling may name an older principle.
- `session_lookup` names the session of an evidence row's notification, in one query.
- `card_features( row )` returns the response type, notification type and the sender's project, or `none`. `feature_lookup` builds the lookup status uses, in one query. A title or message is never a feature.
