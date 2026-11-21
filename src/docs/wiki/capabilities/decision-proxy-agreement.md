---
capability: decision-proxy-agreement
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - cosa.agents.decision_proxy.agreement.forecast_agreement@2c4f0e7d87
  - cosa.agents.decision_proxy.agreement.rule_agreement@983b5eae1a
  - cosa.agents.decision_proxy.config.shadow_forecast_recording_enabled@8412770605
---
# Decision proxy agreement

The two agreements the trust gate records for a proxy decision, kept apart, and the switch that stores a shadow forecast ([[decision-proxy]], [[swe-team-orchestrator]]). The functions are pure: no database, no I/O.

## What it does
- `forecast_agreement( forecast_value, user_answer )` says whether the human's answer agreed with the proxy's forecast. A human approval scores True only when the forecast was `approved`, and a refusal scores True when the forecast was anything else. A `requires_review` forecast scores True whatever the human answered, because the human looked, which is what it asked for. A human approval with any other forecast, or none, scores False.
- `rule_agreement( action, user_answer )` says whether the answer agreed with the policy disposition. An `act` or `suggest` row implies approval: True when the human approved, False when not. It is None for a `shadow` or `defer` row and for a row nobody answered. It is stored in its own nullable `rule_agreement` column on `proxy_decisions`.
- "Rule" is one manager's reading, which the plan does not define more exactly.
- `shadow_forecast_recording_enabled` reads `decision proxy shadow forecast recording enabled`: True stores the proxy's forecast in a shadow row's decision value. The code default is false and the shipped INI sets it true. An absent key reads false, and an unreadable config prints one line and reads false, so the row is still written.
