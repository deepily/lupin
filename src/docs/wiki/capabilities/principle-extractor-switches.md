---
capability: principle-extractor-switches
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - cosa.agents.principle_learner.extractor_prompt.switch_on@467bb3b876
  - cosa.agents.principle_learner.extractor_prompt.active_tags@09fa7acf52
  - cosa.agents.principle_learner.extractor_prompt.active_prompt_version@1bdc2c1c10
  - cosa.agents.principle_learner.extractor_prompt.current_extractor_version@9db5565a62
  - cosa.agents.principle_learner.extractor_prompt.system_prompt_for@f93f996488
  - cosa.agents.principle_learner.extractor_rules.unread_entries@db877f93b1
  - cosa.agents.principle_learner.extractor_store.evidence_keys@6a519b4998
  - cosa.agents.principle_learner.extractor_store.source_key_for@567c862433
---
# Principle extractor switches

Off-by-default INI switches that change what the principle extractor asks, keeps and stores. All off is the behaviour before they existed. The prompt and rules they change are in [[principle-extractor-prompt-and-rules]], and the job that reads them is in [[principle-extractor-job]].

## Versions
- Five switches each add a tag to the extractor version. Each key starts `principle learner`.
- They are `bare yes relations enabled` (`bareyes`), `uninformative relation enabled` (`uninformative`) and `unread answers enabled` (`unread`). The other two are `source dedup enabled` (`dedup`) and `decision stage enabled` (`stage`).
- `switch_on( key )` reads one switch. An absent key is off, and an unreadable one is off and prints a line. `active_tags( reader )` lists the tags whose switch is on, in that fixed order.
- `active_prompt_version()` is the prompt version with `+<tag>` for each active tag.
- `current_extractor_version( model )` is `extractor_version_of( model, active_tags() )`. The job writes its rows under it, and every reader of those rows must ask for it.
- `system_prompt_for( tags )` builds the system prompt. The stage tag swaps in the stage prompt, and each other tag with an addendum appends it. No tags give the plain prompt.

## Rules
- A bare yes keeps only `supports` relations. With `bare_yes_relations` on it may also keep `contradicts` and `refines`.
- With `uninformative` on, a bare yes may name a principle `uninformative`. The relation is kept only with the quoted antecedent, which goes into `antecedents`.
- With `source_dedup` on, a hypothesis marked a standing instruction must carry a `standing_quote` found in the grounding text, or it is rejected. The cleaned hypothesis keeps the quote.
- `unread_entries( answer, response_type )` turns a yes/no text the answer reader could not read into one whole-answer entry marked `unread_stance`. Any other answer, or a blank text, gives none. The job uses it only with the `unread` tag on.

## Stored keys
- `evidence_keys` adds an evidence row's stored keys, each behind its own switch.
- With condition keys on, `condition_key` reuses the principle's stored keys through `compute_condition_key` ([[principle-status-derivation]]). With no model call passed, it is the normalised condition.
- With source dedup on, it adds the `source_key` and the hypothesis's `standing_quote`.
- `source_key_for( card, answer )` is the first 32 hex digits of a sha-256 of the normalised card and answer text. So a card asked twice shares one key.
