---
capability: prediction-episode-view
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - cosa.agents.prediction_engine.episode_view.episode_view@17e927ce2c
  - cosa.agents.prediction_engine.episode_view.fields_of@d7c3d7eb59
  - cosa.agents.prediction_engine.episode_view.history_of@4282b44471
  - cosa.agents.prediction_engine.episode_view.link_kind@8589923965
  - cosa.agents.prediction_engine.episode_view.links_of@1b4339d5fb
  - cosa.agents.prediction_engine.episode_view.load_pool@ad9fe91035
  - cosa.agents.prediction_engine.episode_view.pool_limit@7dd31094df
  - cosa.agents.prediction_engine.episode_view.revealed_at@2f2fb0bf4b
  - cosa.agents.prediction_engine.history_context_rebuild.notification_dict@d299ca5ddb
  - cosa.agents.prediction_engine.history_context_rebuild.answer_known_at_ask@9b8a4af9d2
  - cosa.agents.prediction_engine.episode_view.revealed_draft@21d8e909e3
---
# Prediction episode view

The ask-time record the principle learner reads: what was knowable about one ask at a moment, and nothing later. It builds no as-of logic itself. `rebuild_context` withholds a later answer ([[prediction-history-recovery]]).

## What it does
- `episode_view( session, notification_id, as_of, limit )` returns the owner, project, asker, asked time, title, message, response type, default, timeout and abstract. It also returns links, fields, history, exposure and pool. With `as_of` None it reads as of the ask's own time.
- An `as_of` before the ask raises `ValueError`. A missing notification raises `LookupError`. The ask's own answer is never read.
- `load_pool` reads five indexed queries, one per tier of `rebuild_context`. Each keeps rows sent to the ask's recipient and created strictly before the ask. It returns the pool and the tiers that hit the limit.
- `pool_limit` reads the INI key for the per-tier limit. A missing, blank or non-positive value raises, so a limit never becomes unbounded.
- `history_of` keeps the first three attachments that are questions, plus any informational messages. A question answered after `as_of` reads pending.
- `fields_of` reads the card's fields: prompt, mode (single, multi or text), options with ids, and the default. With the full-answer switch on (`episode_view` reads it) each option also carries a `stable_id`, the position id plus a label hash, which survives a reordering. `links_of` lists the abstract's markdown links, and `link_kind` names each one.
- `revealed_at` reads when the reader first opened the forecast fold, as known at a moment. A reveal after the cutoff reads None.
- The exposure block holds `revealed_at` and `draft_at_reveal`. `draft_at_reveal` comes from `revealed_draft`: the draft stored with the reveal, None when there is none or the reveal came after the cutoff. With no cutoff it is the raw stored draft, never prompt input.
- `notification_dict( row )` turns a notification row into the dict `rebuild_context` reads. `answer_known_at_ask( answered_at, asked_at )` applies the one as-of rule: an answer at or before the ask is known.
