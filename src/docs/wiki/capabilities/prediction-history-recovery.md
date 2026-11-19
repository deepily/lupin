---
capability: prediction-history-recovery
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - cosa.agents.prediction_engine.ask_family.classify_asks@1bbd58d887
  - cosa.agents.prediction_engine.ask_family.normalise_text@bb1ed05536
  - cosa.agents.prediction_engine.history_source_count.count_source_population@14269787bd
  - cosa.agents.prediction_engine.history_source_count.format_source_count@12b3d99c7a
  - cosa.agents.prediction_engine.history_source_count.parse_psql_tables@191a576534
  - cosa.agents.prediction_engine.history_context_rebuild.rebuild_context@430b9d2311
  - cosa.agents.prediction_engine.history_context_rebuild.reconstructable_stage@fc08c5e5d8
  - cosa.agents.prediction_engine.history_derive.asks_of@bd988bdbba
  - cosa.agents.prediction_engine.history_derive.attribution_tier@b18100399a
  - cosa.agents.prediction_engine.history_derive.derive_answer@c91d16e829
  - cosa.agents.prediction_engine.history_derive.derive_dataset@df892be731
  - cosa.agents.prediction_engine.history_derive.write_dataset@455e90befe
  - cosa.agents.prediction_engine.history_uses.assign_use@82a9b25d25
  - cosa.agents.prediction_engine.history_uses.assign_uses@b640f7d88b
  - cosa.agents.prediction_engine.history_recover.offered_fields@c290f3d760
  - cosa.agents.prediction_engine.history_recover.recover_by_family@15ff500efc
  - cosa.agents.prediction_engine.history_recover.recover_example@927c65f39e
  - cosa.agents.prediction_engine.history_funnel.format_funnel@b31bb96a23
  - cosa.agents.prediction_engine.history_funnel.prove_import@b891f7ec0e
  - cosa.agents.prediction_engine.history_funnel.reproduce_inventory@73f5d59ea0
  - cosa.agents.prediction_engine.history_funnel.yield_funnel@30182ba22d
---
# Prediction history recovery

Turns old notification rows into examples the prediction engine can learn from, in five steps plus a proof that one family imports ([[prediction-engine]]). It touches no database. No recovered example joins the frozen cohort.

## Steps
- Count: `count_source_population( text )` reads the baseline inventory's psql tables (`parse_psql_tables`) and gives the first funnel stages with the reason each drops rows. `format_source_count` prints them.
- Family: `classify_asks( asks )` gives each ask a family (response type, category, normalised title), a retry group, a project and `is_retry_copy`. `normalise_text` reduces a title or message to the words that name the kind of ask. The replay report, the family back-off and this track all call it.
- Derive: `asks_of` shapes rows as ask dicts. `derive_answer` decodes the stored answer. `attribution_tier` names the actor: none, timeout_default, recipient, other_account or unknown_actor. `derive_dataset` makes one example per original row and counts the unreadable. `write_dataset` writes originals and derived set with manifests and checks both.
- Rebuild: `rebuild_context( target, notifications, session_window )` joins an ask to earlier notifications, strongest link first. The order is the one it answers, thread, job, full sender, then a time-bounded session match. Nothing later than the ask is read. `reconstructable_stage` counts the rebuilt.
- Use: `assign_use` gives one example train_or_test, prompt_only, sensitivity or vocabulary_only, the first rule that applies. `assign_uses` does all and counts by use and reason.
- Recover: `recover_example` reads an answer by response family. `offered_fields` reads the fields an ask offered. `recover_by_family` groups by response type then family.

## Proof
- `reproduce_inventory` checks a family's asks reproduce the inventory counts by state. `yield_funnel` counts them through each stage naming every drop. `prove_import` runs both and checks the dataset twice. `format_funnel` prints it.
