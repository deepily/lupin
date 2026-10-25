---
capability: decision-strategy-contract
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.agents.decision_proxy.base_decision_strategy.BaseDecisionStrategy@86a9e55272
  - cosa.agents.decision_proxy.base_decision_strategy.DecisionResult@8b64d13727
  - cosa.agents.decision_proxy.category_classifier.CategoryClassifier@1c6c0bc795
  - cosa.agents.decision_proxy.xml_models.ClassificationResult@b9645b951d
  - cosa.agents.decision_proxy.xml_models.TrustDecision@945efd9ad0
  - cosa.agents.decision_proxy.xml_models.RatificationRequest@597c341bea
  - cosa.agents.decision_proxy.xml_models.DecisionSummary@5628507cce
---
# Decision strategy contract

A decision strategy turns a question into one of four actions: `shadow`, `suggest`, `act` or `defer`. `BaseDecisionStrategy` fixes the three steps, and domain packages fill them in. The shipped domain is [[swe-team-orchestrator]]. The trust and responder side is in [[decision-proxy]].

## What it does
- `BaseDecisionStrategy` requires `name`, `classify`, `gate` and `decide`. `available` and `can_handle` default to `True`.
- `evaluate` calls `classify`, then `gate`, then `decide`. It calls `decide` only when the gate said `act` or `suggest`, so `value` stays `None` for `shadow` and `defer`.
- `evaluate` passes trust level 1 to `gate`. A caller that holds a real trust level calls the steps itself.
- `DecisionResult` carries `action`, `value`, `category`, `confidence`, `trust_level` and `reason`. The defaults are category `unknown`, confidence 0.0 and level 1.
- `CategoryClassifier` requires `classify`, which returns a category name and a confidence, and `get_categories`, which returns the category table.
- `ClassificationResult` holds a category, a confidence from 0 to 1 and a method that defaults to `keyword`.
- `TrustDecision` is the record of one gated decision: the question, sender, action, value, confidence, trust level 1 to 5 and reason. The domain defaults to `swe`.
- `RatificationRequest` holds a decision id, an approve flag and optional feedback. `DecisionSummary` holds pending counts by category and by trust level.

## Don't
- Don't import `notification_proxy` or `swe_team` from this package. Each module states that rule.
- Don't look for callers of the four pydantic models. No module under `src/cosa` imports them, so they describe a shape only.
