---
capability: decision-proxy
pin_algorithm: py3.13.xf75af6/ts5.9.3
pins:
  - cosa.agents.decision_proxy.responder.DecisionResponder@3426a59d72
  - cosa.agents.decision_proxy.trust_tracker.TrustTracker@4b186feb3f
  - cosa.agents.decision_proxy.trust_tracker.CategoryTrust@827f2e8cf0
  - cosa.agents.decision_proxy.circuit_breaker.CircuitBreaker@ed1b3c7973
  - cosa.agents.decision_proxy.circuit_breaker.CircuitBreaker.check@37ecd22e31
  - cosa.agents.decision_proxy.smart_router.SmartRouter@dcc377b703
  - cosa.agents.swe_team.proxy.engineering_strategy.EngineeringStrategy@014671267f
  - cosa.agents.swe_team.proxy.engineering_strategy.EngineeringStrategy.gate@fb75c7f680
---
# Decision proxy

The decision proxy answers questions that ask for a response, on the user's behalf, once it has earned trust for that kind of question. This package holds the responder, the trust tracker and the circuit breaker. The classify, gate and decide logic comes from a domain profile; the shipped profile is `swe_team`, whose `EngineeringStrategy` also serves [[swe-team-orchestrator]]. The base classes are in [[proxy-agent-base]], and [[notification-proxy]] is the sibling that answers by script.

## What the responder does
- `DecisionResponder` reacts to `notification_queue_update` events and ignores notifications that do not ask for a response.
- Checks run in this order. A disabled proxy does nothing. A sender outside the allowlist is rejected, and an empty allowlist rejects everyone. A dry run sends a decline. With no strategy loaded it only counts the event.
- Otherwise the strategy returns one of four actions. `shadow` logs. `suggest` stores the decision for ratification. `act` stores it and sends the answer when it has a value. `defer` stores it and sends nothing.
- `python -m cosa.agents.decision_proxy --profile swe_team` starts it only when `decision proxy enabled` is true. The shipped INI sets it false, so by default it prints that and exits. If the profile fails to load it also exits.

## The gate
- `EngineeringStrategy.gate` first asks the circuit breaker: a tripped category gives `defer`.
- The conformal and Thompson options exist in `EngineeringStrategy`, but its three callers never turn them on. So trust mode `shadow` (the default) always gives `shadow`. In `suggest` mode, level 2 and above give `suggest` and level 1 gives `shadow`.
- In `active` mode, level 1 gives `shadow`, level 2 gives `suggest`, and level 3 and above give `act`.
- The strategy's heuristic answer is `approved`, except for deployment, destructive and architecture questions, which get `requires_review`. `EngineeringStrategy` has an optional model fallback, but no caller supplies the client and case store it needs, so it never runs.

## Trust
- `TrustTracker` keeps one `CategoryTrust` per category. Its level runs from 1 to 5 and is capped per category.
- The default model sums only the successful decisions, each weighted down as it ages, against thresholds for levels 2 to 5. A rejection adds nothing. `beta` and `blr` models are the alternatives.
- The SWE orchestrator feeds the tracker: a success when the proxy acts alone, otherwise whether the proxy agreed with the user's answer. The ratify route updates stored counters, not the tracker.

## Circuit breaker
- `check` trips a category when at least 10 decisions exist and the error rate is above its threshold. It also trips when 5 or more confidence samples average below the collapse threshold.
- A trip starts a cooldown. Under the default count model it also demotes the category; the `beta` and `blr` models read lifetime totals that a trip leaves alone. After the cooldown, the breaker stops reporting a trip, but `check` reads the same lifetime counters, so a category still over the threshold trips again.

## Smart router
- `DecisionResponder` builds a `SmartRouter`, but nothing calls its `should_defer_to_user`, so active hours and connectivity change no answer. Delete this section when row 7ddfa3b9-4645-4073-a69b-ee9bba57eab2 closes.
