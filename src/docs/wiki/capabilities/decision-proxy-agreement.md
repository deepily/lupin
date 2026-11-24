---
capability: decision-proxy-agreement
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - cosa.agents.decision_proxy.agreement.forecast_agreement@cccd2465f2
  - cosa.agents.decision_proxy.agreement.reframe_blocks_promotion@d3696af9f0
  - cosa.agents.decision_proxy.agreement.reframe_rate@4186de5ee3
  - cosa.agents.decision_proxy.agreement.rule_agreement@983b5eae1a
  - cosa.agents.decision_proxy.config.neither_is_no_ruling_enabled@7ac15677c6
  - cosa.agents.decision_proxy.config.shadow_forecast_recording_enabled@d68b684497
---
# Decision proxy agreement

The two agreements the trust gate records for a proxy decision, kept apart, and the switch that stores a shadow forecast ([[decision-proxy]], [[swe-team-orchestrator]]). The functions are pure: no database, no I/O.

## What it does
- `forecast_agreement( forecast_value, user_answer )` says whether the human's answer agreed with the proxy's forecast. A human approval scores True only when the forecast was `approved`, and a refusal scores True when the forecast was anything else. A `requires_review` forecast scores True whatever the human answered, because the human looked, which is what it asked for. A human approval with any other forecast, or none, scores False.
- `rule_agreement( action, user_answer )` says whether the answer agreed with the policy disposition. An `act` or `suggest` row implies approval: True when the human approved, False when not. It is None for a `shadow` or `defer` row and for a row nobody answered. It is stored in its own nullable `rule_agreement` column on `proxy_decisions`.
- "Rule" is one manager's reading, which the plan does not define more exactly.
- `shadow_forecast_recording_enabled` reads `decision proxy shadow forecast recording enabled`: True stores the proxy's forecast in a shadow row's decision value. The code default is false and the shipped INI sets it true. An absent key reads false, and an unreadable config prints one line and reads false (through the shared `read_switch`), so the row is still written.
- `neither_is_no_ruling_enabled` reads `decision proxy neither means reframe enabled` (renamed from `decision proxy neither is no ruling enabled` on 24 Nov 2026). The code default is false; the shipped INI is true since 24 Nov 2026. The swe orchestrator always asks through `ask_confirmation_answer`, which returns a `ConfirmationAnswer` (stance, comment, raw text). Every decision row stores `answer_source`, whatever the switch says. It is `human` when the promotion gate's own test, `answer_posted_by_the_operator`, accepts the server's stamp. It is `not_operator` when a stamp is present and the gate refuses it, as it does an API-key answer. It is `default` when the server applied the default for an offline user. It is `unattributed` with no stamp, as with a test double, and `proxy` for an auto-approval. Only a `human` answer stores `answer_stance`, `answer_comment`, `answer_raw` and the answerer's id and method. A default's or an unattributed answer's text goes under `answer_unowned_raw`. Recording is not behaviour. With the switch on, a `neither` is no ruling. `forecast_agreement` answers `None`, the trust counters are unchanged, `record_decision` is skipped, and a `[PROXY-REFRAME]` line is logged. The decision row is still written, with the stance and comment in its metadata. So a neither (Rick deferred the decision) stays distinct from a `defer` action (the model deferred to Rick). `reframe_blocks_promotion` says whether a category's last 20 asks hold more than 1 neither in 10. The orchestrator hands each stance to `EngineeringStrategy.note_stance`. While the rate is over the bar, `get_trust_level` holds the category at the level it had when the block began, so it cannot be promoted. Demotion still applies and the counters are never touched. With the switch off, every score is exactly as before: a `neither` counts as a no, though its stance is stored.
- `reframe_rate( recent_stances )` returns the share of neither stances among the last `REFRAME_WINDOW` entries, 0.0 for an empty list.
- `reframe_blocks_promotion( recent_stances )` is True only when that rate is strictly above `REFRAME_BAR`, and False at the bar.
