---
capability: decision-proxy
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.agents.decision_proxy.responder.DecisionResponder@f11a853e54
  - cosa.agents.decision_proxy.trust_tracker.TrustTracker@e6ea84b97f
  - cosa.agents.decision_proxy.trust_tracker.CategoryTrust@9a28bb3dc6
  - cosa.agents.decision_proxy.circuit_breaker.CircuitBreaker@ed1b3c7973
  - cosa.agents.decision_proxy.circuit_breaker.CircuitBreaker.check@37ecd22e31
  - cosa.agents.decision_proxy.smart_router.SmartRouter@6734207a13
  - cosa.agents.swe_team.proxy.engineering_strategy.EngineeringStrategy@0b7f9fefbf
  - cosa.agents.swe_team.proxy.engineering_strategy.EngineeringStrategy.gate@0ee4450d30
---
# Decision proxy

The decision proxy answers questions that ask for a response, on the user's behalf, once it has earned trust for that kind of question. This package holds the responder, the trust tracker and the circuit breaker. The classify, gate and decide logic comes from a domain profile; the shipped profile is `swe_team`, whose `EngineeringStrategy` also serves [[swe-team-orchestrator]]. The base classes are in [[proxy-agent-base]], and [[notification-proxy]] is the sibling that answers by script.

## What the responder does
- `DecisionResponder` reacts to `notification_queue_update` events and ignores notifications that do not ask for a response. Its statistics print under the title `Decision Proxy Statistics`.
- Checks run in this order. A disabled proxy does nothing. A sender outside the allowlist is rejected, and an empty allowlist rejects everyone. A dry run sends a decline. With no strategy loaded it only counts the event.
- Otherwise the strategy returns one of four actions. `shadow` logs. `suggest` stores the decision for ratification. `act` stores it and sends the answer when it has a value, unless the smart router defers it (see Smart router). `defer` stores it and sends nothing. A `shadow` or `defer` row keeps an empty decision value, so the proxy's own guess is never cited as precedent.
- `python -m cosa.agents.decision_proxy --profile swe_team` starts it only when `decision proxy enabled` is true. The shipped INI sets it false, so by default it prints that and exits. If the profile fails to load it also exits.

## The gate
- `EngineeringStrategy.gate` first asks the circuit breaker: a tripped category gives `defer`.
- The conformal and Thompson options exist in `EngineeringStrategy`, but its three callers never turn them on. So trust mode `shadow` (the default) always gives `shadow`. In `suggest` mode, level 2 and above give `suggest` and level 1 gives `shadow`.
- In `active` mode, level 1 gives `shadow` and level 2 gives `suggest`. Level 3 gives `act` at classification confidence 0.80 or more, else `suggest`.  Level 4 gives `act`, except `suggest` for the destructive category, below confidence 0.50, and for a 10% audit sample. Level 5 always gives `act`. A Thompson draw can only lower the result.
- The strategy's heuristic answer is `approved`, except for deployment, destructive and architecture questions, which get `requires_review`. `EngineeringStrategy` has an optional model fallback, but no caller supplies the client and case store it needs, so it never runs.

## Trust
- `TrustTracker` keeps one `CategoryTrust` per category. Its level runs from 1 to 5 and is capped per category.
- The default model sums only the successful decisions, each weighted down as it ages, against thresholds for levels 2 to 5. A rejection adds nothing. `beta` and `blr` models are the alternatives, chosen by `swe team trust proxy trust model` (see [[decision-proxy-startup]]). A circuit-breaker trip is recorded: the level stays capped at the demoted level until new successes close the gap to the next threshold. A stored trip is restored with the counters, so a demotion survives the next job. `restore_category` restores a category's counters, its per-day decision history and, under the `blr` model only, its saved BLR state. `blr_state_for` returns that state for saving, and `None` under `count` or `beta`. `record_decision_with_features` feeds the BLR model a decision with its question's features.
- The SWE orchestrator feeds the tracker: a success when the proxy acts alone, otherwise whether the proxy agreed with the user's answer. The ratify route updates stored counters, not the tracker.

## Circuit breaker
- `check` trips a category when at least 10 decisions exist and the error rate is above its threshold. It also trips when 5 or more confidence samples average below the collapse threshold.
- A trip starts a cooldown. It also demotes the category by the configured number of levels under every model: `beta` and `blr` have their counters lowered too. After the cooldown, `check` reads the same lifetime counters, so a category still over the threshold trips again.

## Smart router
- `DecisionResponder` asks `SmartRouter` before posting an automatic answer. In active hours, with the named human connected, it posts nothing and records a defer. The feed is `user_presence.sessions_feed`; a failing feed reads as not connected. The SWE orchestrator does not consult the router. Router and responder take the zone for the active hours from `decision proxy timezone` when none is passed. An absent key raises.
