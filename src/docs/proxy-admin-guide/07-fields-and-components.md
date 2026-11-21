# Decision Proxy: Fields and Components

The trust gate keeps four facts apart, and this part says where each lives and which switches act.

## 10. The Separate Fields

A human who approves a deployment has not made the proxy fail. The gate therefore keeps four facts in four places.

| Fact | Where it lives | What it holds |
|---|---|---|
| Policy disposition | `proxy_decisions.action` | shadow, suggest, act or defer |
| Shadow forecast | `proxy_decisions.decision_value` | what the proxy decided, or NULL. A shadow row stores NULL |
| Human response | `notifications.response_value` | the human's answer, joined by `notification_id` and never copied |
| Rule agreement | `proxy_decisions.rule_agreement` | whether the human answer agreed with what the action implies |

**Success** means the human answer agreed with the forecast. It is computed by `forecast_agreement` in `decision_proxy/agreement.py`.
A human approving a deployment scores as success when the forecast was "approved" or "requires_review".

**Rule agreement** is a separate nullable column. It is never folded into success.
An act or suggest row implies approval, so the column is true when the human approved and false when they did not.
It is NULL for a shadow row, for a defer row, and for a row nobody answered.
This is Mr. Radio's reading of "rule", for Rick to confirm, because the plan does not define it more precisely.

The column came with alembic revision `c4d8e1a6b392`, chained after `7a3e9c5d1b28`. The revision is written and not applied.
Rows written before it read NULL, and nothing backfills them.

### A forecast of requires_review

A forecast of `requires_review` asks for a human look, so a human approval of it scores as success (ruled 20 Nov 2026).
A decline still scores True, and an approval against any other non-"approved" forecast still scores False.

### What the 5 Nov rows show

The audit of the 43 organic rows of 5 Nov is in `src/rnd/v0.2.4/2026.11.17-online-preference-learning-upgrades/2026.11.20-trust-gate-5-nov-audit.md`.
Forty-two rows are shadow rows with no stored forecast, because `log_shadow` writes NULL there. The row cannot show what the proxy forecast.
One row is an act row that auto-approved with no human answer.
None of the 43 notification ids joins to a row of `notifications`, because the orchestrator mints a fresh id for each decision.

## 11. Components and Switches

Each key below sits under the decision proxy's sections of `lupin-app.ini`. The state column has three values.

- **Live**: code reads the key and acts on it.
- **Dormant**: the key is configured and parsed, and nothing acts on its value.
- **Unreachable**: the key is parsed, and no code in the tree implements the feature behind it.

`swe team enabled` is **Dormant**. Nothing reads it, and enforcing it would give the SWE team orchestrator new acting behaviour.
It keeps its name, because a rename would change the INI contract for no gain.
A test fails when a key under the decision proxy's sections is missing from this table.

| Key | Value | State | What reads it |
|---|---|---|---|
| `swe team enabled` | `false` | Dormant | Nothing reads it, so it gates nothing. Enforcing it is Rick's decision. |
| `swe team trust mode` | `shadow` | Live | `strategy_builder.py` builds the strategy in this mode: shadow, suggest or active. |
| `decision proxy shadow forecast recording enabled` | `true` | Live | `shadow_forecast_recording_enabled` in `decision_proxy/config.py`; the swe orchestrator and the responder store the forecast in a shadow row's decision value. |
| `decision proxy enabled` | `false` | Live | `decision_proxy/__main__.py` refuses to start the proxy when false. |
| `decision proxy active hours start` | `09` | Live | `user_presence.py` reads them and `SmartRouter` routes by them. |
| `decision proxy active hours end` | `22` | Live | `user_presence.py` reads them and `SmartRouter` routes by them. |
| `decision proxy timezone` | `America/Chicago` | Live | `app_timezone.get_decision_proxy_timezone` reads it for the active hours. |
| `decision proxy human user id` | `(empty)` | Live | `user_presence.py` reads it to find the human. |
| `swe team trust proxy trust model` | `count` | Live | `TrustTracker` picks count, beta or blr by it. An unknown value refuses to start. |
| `swe team trust proxy l2 threshold` | `50` | Live | `TrustTracker` uses them with the count model. |
| `swe team trust proxy l3 threshold` | `200` | Live | `TrustTracker` uses them with the count model. |
| `swe team trust proxy l4 threshold` | `500` | Live | `TrustTracker` uses them with the count model. |
| `swe team trust proxy l5 threshold` | `1000` | Live | `TrustTracker` uses them with the count model. |
| `swe team trust proxy decay half life days` | `14` | Live | `TrustTracker` weights and prunes its history by it. |
| `swe team trust proxy rolling window days` | `30` | Live | `TrustTracker` weights and prunes its history by it. |
| `swe team trust proxy circuit breaker error rate threshold` | `0.15` | Live | `strategy_builder.py` passes it to `CircuitBreaker`. |
| `swe team trust proxy circuit breaker confidence collapse threshold` | `0.3` | Live | `strategy_builder.py` passes it to `CircuitBreaker`. |
| `swe team trust proxy circuit breaker auto demotion levels` | `2` | Live | `strategy_builder.py` passes it to `CircuitBreaker`. |
| `swe team trust proxy circuit breaker recovery cooldown seconds` | `3600` | Live | `strategy_builder.py` passes it to `CircuitBreaker`. |
| `swe team trust proxy l4 audit sample rate` | `0.10` | Live | `strategy_builder.py` passes it to `EngineeringStrategy` as its audit rate. |
| `swe team trust proxy similarity threshold` | `0.75` | Dormant | Read into the proxy config, but `strategy_builder.py` never passes it on. The strategy runs on its own default. |
| `swe team trust proxy decisions table` | `proxy_decisions` | Live | `responder.py` names the table it logs decisions to. |
| `swe team trust proxy beta l2 rate threshold` | `0.70` | Live | `strategy_builder.py` builds the level tables from it. `TrustTracker` uses them with the beta model. |
| `swe team trust proxy beta l3 rate threshold` | `0.80` | Live | `strategy_builder.py` builds the level tables from it. `TrustTracker` uses them with the beta model. |
| `swe team trust proxy beta l4 rate threshold` | `0.90` | Live | `strategy_builder.py` builds the level tables from it. `TrustTracker` uses them with the beta model. |
| `swe team trust proxy beta l5 rate threshold` | `0.95` | Live | `strategy_builder.py` builds the level tables from it. `TrustTracker` uses them with the beta model. |
| `swe team trust proxy beta l2 min samples` | `20` | Live | `strategy_builder.py` builds the level tables from it. `TrustTracker` uses them with the beta model. |
| `swe team trust proxy beta l3 min samples` | `50` | Live | `strategy_builder.py` builds the level tables from it. `TrustTracker` uses them with the beta model. |
| `swe team trust proxy beta l4 min samples` | `100` | Live | `strategy_builder.py` builds the level tables from it. `TrustTracker` uses them with the beta model. |
| `swe team trust proxy beta l5 min samples` | `200` | Live | `strategy_builder.py` builds the level tables from it. `TrustTracker` uses them with the beta model. |
| `swe team trust proxy cbr top k` | `5` | Dormant | Read into the proxy config, but `strategy_builder.py` never passes it on. The strategy runs on its own default. |
| `swe team trust proxy cbr confidence threshold` | `0.60` | Dormant | Read into the proxy config, but `strategy_builder.py` never passes it on. The strategy runs on its own default. |
| `swe team trust proxy thompson enabled` | `false` | Dormant | Read into the proxy config, but `strategy_builder.py` never passes it on. The strategy runs on its own default. |
| `swe team trust proxy thompson act threshold` | `0.90` | Dormant | Read into the proxy config, but `strategy_builder.py` never passes it on. The strategy runs on its own default. |
| `swe team trust proxy thompson suggest threshold` | `0.70` | Dormant | Read into the proxy config, but `strategy_builder.py` never passes it on. The strategy runs on its own default. |
| `swe team trust proxy bald enabled` | `false` | Unreachable | Read into the proxy config. No code in the tree implements the feature. |
| `swe team trust proxy bald defer threshold` | `0.50` | Unreachable | Read into the proxy config. No code in the tree implements the feature. |
| `swe team trust proxy conformal enabled` | `false` | Dormant | Read into the proxy config, but `strategy_builder.py` never passes it on. The strategy runs on its own default. |
| `swe team trust proxy conformal alpha` | `0.10` | Dormant | Read into the proxy config, but `strategy_builder.py` never passes it on. The strategy runs on its own default. |
| `swe team trust proxy icrl enabled` | `false` | Dormant | Read into the proxy config, but `strategy_builder.py` never passes it on. The strategy runs on its own default. |
| `swe team trust proxy icrl top k` | `5` | Dormant | Read into the proxy config, but `strategy_builder.py` never passes it on. The strategy runs on its own default. |

