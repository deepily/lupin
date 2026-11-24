---
capability: principle-extractor-job
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - cosa.agents.principle_learner.enqueue_after_answer.enqueue_after_answer@ab3b706698
  - cosa.agents.principle_learner.enqueue_after_answer.is_enabled@b49876fbb2
  - cosa.agents.principle_learner.enqueue_after_answer.register_job@09d7d1cfa0
  - cosa.agents.principle_learner.extractor_job.PrincipleExtractorJob@4cc1e0e7f0
  - cosa.agents.principle_learner.extractor_job.default_embed@e98982141d
  - cosa.agents.principle_learner.extractor_job.default_session@42b97853f4
  - cosa.agents.principle_learner.extractor_job.encoder_version@226928f982
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
- `do_all` runs the extraction and returns the summary the queue stores. It raises what the work raises, after marking the job failed. `last_question_asked` shows `[Principle extractor]` and the notification id.
- `encoder_version()` names the embedding model and the text recipe, as `<model name>:<recipe>`, built by `principle_retrieval.encoder_version_of`. The extractor reads the draft with `revealed_draft`. `default_embed` embeds a text with the configured provider.
- The provider must make 768-dimension vectors. Another width fails loudly when a principle is stored.
- `default_session` opens a database session that commits on success and rolls back on error.
