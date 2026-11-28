---
capability: principle-status-derivation
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - cosa.agents.prediction_engine.principle_status.derive_statuses@d693b5534b
  - cosa.agents.prediction_engine.principle_status.rows_by_principle@05ba6912a8
  - cosa.agents.prediction_engine.principle_status.status_deriver@4ef42d5c03
  - cosa.agents.prediction_engine.principle_status.StatusesOnRead@e974577670
  - cosa.agents.prediction_engine.principle_status.StatusesOnRead.get@1b940d50a6
  - cosa.agents.prediction_engine.principle_status.usable_at@f0eb3e6a86
  - cosa.agents.prediction_engine.principle_status.compute_condition_key@f642ce8cd5
  - cosa.agents.prediction_engine.principle_status.normalise_key@a0e1d03ead
  - cosa.agents.prediction_engine.principle_status.switch_on@15bc7cfe9c
---
# Principle status derivation

What the learner believes about a principle at the moment of one ask. Status is derived and never stored. It is read from the append-only evidence rows ([[rest-preference-principle-tables]]).

## What it does
- `usable_at( row, asked_at )` is True when three things hold at the ask. The answer was known. The row was already extracted. The row was not retracted.
- `derive_statuses` returns a result per principle, or None when no evidence was usable at the ask. A principle first extracted after the ask is absent.
- `status_deriver` groups the usable rows by principle once, so `derive_statuses` is linear. `StatusesOnRead` derives a status only when asked.
- A result holds the status, conditions, episode count, session count and the ruling that decided it.
- There are four statuses. Hypothesis means one episode, or sessions that cannot be told apart. Established means two or more distinct sessions.
- Contested means one condition holds evidence on both sides. Retracted means only contradicting evidence, or the owner ruled it out.
- Extractor rows count only for the current version and their own principle. A ruling or split row counts across versions, and the latest usable one decides.
- A ruling speaks for the principle it names and for any principle that continues it. Owner, scope and dimension are never used to match.
- A standing ruling clears contested only for contradictions answered at or before its own answer time. A later contradiction can contest the principle again.
- A split's contradicting row is never a ruling. After a split, a later contradiction on the other side's feature value does not count against the principle.
- A retracting ruling is final. Nothing is read or written outside the arguments. An `uninformative` row counts for nothing.

## Switches and keys
- Two switches, both off, are read through `switch_on`, which treats an unreadable setting as off. `derive_statuses` takes `condition_keys` and `source_dedup` arguments that override them.
- With `principle learner condition keys enabled` on, conditions are grouped by their stored `condition_key`, and no model is called.
- With `principle learner source dedup enabled` on, supporting rows that share a `source_key` count once, and each result also carries the standing and inferred counts.
- `normalise_key( text )` case-folds a condition, keeps one space per run and drops end punctuation. It returns None for nothing left.
- `compute_condition_key( condition, existing_keys, complete )` gives a condition its key when its evidence row is written. A blank condition gives None. A wording that matches an existing key reuses it with no model call. Otherwise the model names an existing key or a new one. A reply it cannot read falls back to the normalised condition.

## Don't
- Don't store a status. Two replays of one ask must see what the live system saw.
