---
capability: notification-proxy
pin_algorithm: py3.13.xf75af6/ts5.9.3
pins:
  - cosa.agents.notification_proxy.responder.NotificationResponder@bbae59b303
  - cosa.agents.notification_proxy.responder.NotificationResponder.handle_event@23ea9bdd9a
  - cosa.agents.notification_proxy.strategies.expediter_rules.ExpediterRuleStrategy@bf4c4fe8e4
  - cosa.agents.notification_proxy.strategies.expediter_rules.ExpediterRuleStrategy.can_handle@edfcb2354c
  - cosa.agents.notification_proxy.strategies.llm_script_matcher.LlmScriptMatcherStrategy@96aa4d1fb7
  - cosa.agents.notification_proxy.strategies.llm_fallback.LLMFallbackStrategy.can_handle@5d4011dcca
  - cosa.agents.notification_proxy.option_sentinels.resolve@ea4d9954a8
  - cosa.agents.notification_proxy.scalar_answers.drop_non_scalar_answers@01e3287d5a
---
# Notification proxy

The notification proxy answers questions that ask for a response by following a script for a test profile. It is a separate process, started with `python -m cosa.agents.notification_proxy`. It listens to `notification_queue_update` events. [[decision-proxy]] is the sibling that answers by earned trust instead of a script. This proxy has its own listener and responder. From [[proxy-agent-base]] it takes only the connection defaults, four reconnect constants and two credential helpers.

## Choosing an answer
- `NotificationResponder.handle_event` routes `notification_queue_update` events to `_handle_notification_update`. That method skips a notification that asks for no response and one marked `human_only`. A response-requesting one with no id is counted as an error.
- In a dry run it sends a decline instead: `no` for a yes/no card and `cancel` for the rest.
- Strategies are tried in order, and the first answer wins: the script matcher, then the rules, then the cloud fallback. If none answers, the notification is skipped.
- The strategy mode picks which exist. `llm_script` (the default) builds the script matcher. `rules` builds no matcher. `auto` builds the matcher and also tries the rules when it gave no answer. The cloud fallback is built in every mode.

## The three strategies
- `LlmScriptMatcherStrategy` matches the card against the profile's Q&A script. It only handles notifications whose sender is on the accepted list, and only when its model client is available. On a batch card it drops non-scalar answers like the rule strategy does.
- `ExpediterRuleStrategy` answers yes/no with `yes`, a multiple-choice card with its first option, and an open-ended card by keyword. A batch card gets profile values. `drop_non_scalar_answers` keeps only string, number and boolean ones as strings and logs each drop. The sender check is the same.
- The sender check compares the sender id, with any `#suffix` removed, to each accepted entry. The list comes from the script's `sender_ids`, else `arg.expeditor@lupin.deepily.ai`.
- `LLMFallbackStrategy.can_handle` checks only that its client exists and a response was requested. It does not look at the sender.
- The fallback uses the Anthropic SDK directly with the firewalled key. Without a key it is unavailable. For the cost difference see [[bounded-claude-code-jobs]].

## Checks before submitting
- The responder checks every answer. One shaped like an option sentinel is resolved against the card's options. A malformed sentinel, or one that matches no option, is skipped.
- On a multiple-choice card, an answer under a header the card never asked, or with a value it never offered, is not submitted.

## Submitting
- The answer is posted to `/api/notify/response`, with an `Authorization` header when the listener has a token. Only an HTTP 200 counts as sent. Every other failure is logged and counted as an error.
