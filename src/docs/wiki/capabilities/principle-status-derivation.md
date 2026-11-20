---
capability: principle-status-derivation
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - cosa.agents.prediction_engine.principle_status.derive_statuses@e95ab3f6f3
  - cosa.agents.prediction_engine.principle_status.usable_at@f0eb3e6a86
---
# Principle status derivation

What the learner believes about a principle at the moment of one ask. Status is derived and never stored. It is read from the append-only evidence rows ([[rest-preference-principle-tables]]).

## What it does
- `usable_at( row, asked_at )` is True when three things hold at the ask. The answer was known. The row was already extracted. The row was not retracted.
- `derive_statuses` returns a result per principle, or None when no evidence was usable at the ask. A principle first extracted after the ask is absent.
- A result holds the status, conditions, episode count, session count and the ruling that decided it.
- There are four statuses. Hypothesis means one episode, or sessions that cannot be told apart. Established means two or more distinct sessions.
- Contested means one condition holds evidence on both sides. Retracted means only contradicting evidence, or the owner ruled it out.
- Extractor rows count only for the current version and their own principle. A ruling or split row counts across versions, and the latest usable one decides.
- A ruling speaks for the principle it names and for any principle that continues it. Owner, scope and dimension are never used to match.
- A standing ruling clears contested only for contradictions answered at or before its own answer time. A later contradiction can contest the principle again.
- A split's contradicting row is never a ruling. After a split, a later contradiction on the other side's feature value does not count against the principle.
- A retracting ruling is final. Nothing is read or written outside the arguments.

## Don't
- Don't store a status. Two replays of one ask must see what the live system saw.
