---
capability: principle-extractor-prompt-and-rules
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - cosa.agents.principle_learner.extractor_prompt.build_user_prompt@f911ff3570
  - cosa.agents.principle_learner.extractor_prompt.parse_reply@f4219a655e
  - cosa.agents.principle_learner.extractor_rules.card_text@8ca4e0d9df
  - cosa.agents.principle_learner.extractor_rules.check_field@3e2f56447e
  - cosa.agents.principle_learner.extractor_rules.check_hypothesis@5e43ffdc68
  - cosa.agents.principle_learner.extractor_rules.drafted_text@81cdace015
  - cosa.agents.principle_learner.extractor_rules.field_answers@c68629b988
  - cosa.agents.principle_learner.extractor_rules.ground_condition@b959b4a594
  - cosa.agents.principle_learner.extractor_rules.project_names@8b5564e300
  - cosa.agents.principle_learner.extractor_rules.unaided_answer@d5ccca2591
  - cosa.agents.principle_learner.extractor_store.apply_field@062f1181d4
  - cosa.agents.principle_learner.extractor_store.fetch_neighbours@f13f230063
---
# Principle extractor prompt, rules and store

One model call covers every field of one answered ask. The model proposes. The rules decide what is kept, so they hold with a live model and a recorded double alike. The job is in [[principle-extractor-job]].

## Prompt
- `build_user_prompt( episode, entries, neighbours )` writes the card, the history, the answers and the nearest principles as JSON blocks. No notification, owner or sender id is written into it.
- A principle's dimension is shown as its approved heading when it has one ([[principle-vocabulary]]).
- `parse_reply( text )` returns the list of field results when the reply is an object with a `fields` list. It returns None for anything else and never repairs a reply.

## Rules
- A field holds at most three hypotheses, each under 240 characters. More than three rejects the whole field.
- `field_answers` splits a decoded answer into one entry per field. `bare_yes` is True only for a yes with no qualifier, and a bare yes creates no principle.
- `drafted_text` reads the draft text for one field. `unaided_answer` chooses the text the extractor reads. A draft for the field wins. With no draft, the answer is marked possibly influenced only when `revealed_before_answer` says so.
- `card_text` gathers the title, abstract, field prompts and option labels a condition may be grounded in; it is `episode_view.card_text` with `include_options=True`. `owners_own_answer( row )` is the one test that an answer is the owner's own word from their own screen. `ground_condition` keeps a condition only when its words occur there or in the answer.
- `project_names` lists the projects named in some sender ids. A global statement may name none of them.
- `check_hypothesis` returns the cleaned hypothesis or the reason it was rejected. `check_field` returns the kind, dimension, hypotheses, relations and rejections.
- `check_field` drops a relation to a principle the model was not shown. A kind outside the two allowed, or a blank dimension, rejects the field.

## Store
- `fetch_neighbours` finds an owner's principles nearest the query vectors within one encoder version. A principle of another version is never read.
- `apply_field` writes new principles and evidence for one checked field. Evidence is append-only, so a second run adds nothing.
- A new principle takes `continues_principle_id` from the lowest named principle of another extractor version.
