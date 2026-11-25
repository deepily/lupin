---
capability: principle-extractor-job
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - cosa.agents.principle_learner.enqueue_after_answer.enqueue_after_answer@ab3b706698
  - cosa.agents.principle_learner.enqueue_after_answer.is_enabled@b49876fbb2
  - cosa.agents.principle_learner.enqueue_after_answer.register_job@09d7d1cfa0
  - cosa.agents.principle_learner.extractor_job.PrincipleExtractorJob@db8c5f041c
  - cosa.agents.principle_learner.extractor_job.default_embed@e98982141d
  - cosa.agents.principle_learner.extractor_job.default_session@42b97853f4
  - cosa.agents.principle_learner.extractor_job.encoder_version@226928f982
  - cosa.agents.principle_learner.extractor_rules.owners_own_answer@2634f92fac
---
# Principle extractor job

A queued job that turns one human answer into evidence. It sends the owner nothing: no notification, no progress card, no voice line. Prompt and rules are in [[principle-extractor-prompt-and-rules]], the tables in [[rest-preference-principle-tables]].

## What it does
- `enqueue_after_answer( queue, notification_id, owner_id, owner_email, response_options, ... )` is called once per answered ask by the answer door. It returns `queued`, `reason` and `job_id`.
- `is_enabled` reads the enable key on each call, so a flip needs no restart. A missing key raises `MissingConfigKeyError`. When disabled, nothing is queued or touched.
- When enabled it queues one extractor job now and one review-card sweep after the extractor ends. The sweep is the only job that may send a card ([[principle-review-card-sweep]]).
- A waiting thread queues the sweep once the extractor reaches a terminal state, failed or not. After `give_up_after` seconds it queues the sweep anyway, because the sweep reads only the database.
- `register_job( queue, job, show )` gives the job a user-scoped id when `show` is true, so the owner's queue listing can find it. Otherwise it leaves the job out.
- `PrincipleExtractorJob` has the fixed session id `principle-extractor`. A skipped answer, one not attributed to its owner or with nothing to read, writes nothing and calls no model.
- The run reads the version tags and writes under `current_extractor_version`. The tags pick the system prompt and the rule checks ([[principle-extractor-prompt-and-rules]]). With the `unread` tag on, an unread yes/no text becomes one entry instead of a skip.
- With `principle learner decision stage enabled` on, each checked field keeps the decision stage the model gave, when it is one of the two stages. With `principle learner meaning record input enabled` on, each entry is marked `final` or `draft` by where its text came from. An entry read from the final answer also gets its structure from the newest meaning record of the current schema. The summary then carries `answer_read`, the map of field key to `final` or `draft`.
- `do_all` runs the extraction and returns the summary the queue stores. It raises what the work raises, after marking the job failed. `last_question_asked` shows `[Principle extractor]` and the notification id.
- `encoder_version()` names the embedding model and the text recipe, as `<model name>:<recipe>`, built by `principle_retrieval.encoder_version_of`. The extractor reads the draft with `revealed_draft`. `default_embed` embeds a text with the configured provider.
- The provider must make 768-dimension vectors. Another width fails loudly when a principle is stored.
- `default_session` opens a database session that commits on success and rolls back on error.
- `extractor_rules.owners_own_answer( row )` is True only when the answering user is the recipient and the source is the screen. The extractor and the review cards both gate on it.
- A timeout default, a proxy answer, an answer with no user and another account's answer are all False.
