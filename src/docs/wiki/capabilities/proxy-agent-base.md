---
capability: proxy-agent-base
pin_algorithm: py3.13.xf75af6/ts5.9.3
pins:
  - cosa.agents.utils.proxy_agents.base_listener.BaseWebSocketListener@4e50b0aaba
  - cosa.agents.utils.proxy_agents.base_listener.BaseWebSocketListener.run@4b6bdc5716
  - cosa.agents.utils.proxy_agents.base_responder.BaseResponder@2f8100ee7a
  - cosa.agents.utils.proxy_agents.base_responder.BaseResponder.submit_response@4398825b2a
  - cosa.agents.utils.proxy_agents.base_strategy.BaseStrategy@c7fe75f5cc
  - cosa.agents.utils.proxy_agents.rest_submitter.submit_notification_response@981676295e
  - cosa.agents.utils.proxy_agents.base_config.get_credentials@2ba167182f
  - cosa.agents.utils.proxy_agents.base_config.get_anthropic_api_key@4d25966729
  - cosa.agents.utils.proxy_agents.base_cli.add_common_args@6a0b3d1ecd
---
# Proxy agent base

The shared layer under the proxy agents: a WebSocket listener, a responder base class, a strategy protocol, a REST submitter, connection settings and command-line flags. Its modules import nothing from `notification_proxy`, `decision_proxy` or `swe_team`. [[decision-proxy]] builds on most of it. [[notification-proxy]] has its own listener and responder. It takes only the connection defaults, four reconnect constants, `get_credentials` and `get_anthropic_api_key`.

## Who uses what
- `DecisionResponder` extends `BaseResponder`, and `DecisionListener` extends `BaseWebSocketListener`. The decision proxy's entry point also uses `add_common_args`.
- Two other classes extend the listener: `OrchestratorNotificationClient` in `swe_team` and `CCNotificationListener` in the Claude Code hooks library.
- `BaseStrategy` and the two `route_to_strategies` methods have no caller outside the tests. Neither proxy's responder uses them.

## The listener
- `run` logs in with `POST /auth/login` and opens `/ws/queue/<session id>`. It sends an `auth_request` with the bearer token and its subscribed events, then waits up to 10 seconds for `auth_success`.
- It answers `sys_ping` with `sys_pong` and hands every other message to the `on_event` callback.
- After a drop or a failed login it waits and tries again. The wait is 2 to the power of the attempt count in seconds, capped at 10. It is shortened by up to half at random, never lengthened.
- It stops after 10 attempts in a row. A successful authentication resets the count.
- `authorization` is the `Bearer` token of the last login, or `None` before the first.

## The responder and submitter
- `BaseResponder` keeps a stats dict and leaves `handle_event` to the subclass. `route_to_strategies` skips an unavailable strategy and returns the first answer that is not `None`; the async variant also awaits a coroutine result.
- `submit_response` calls `submit_notification_response` with the token from `authorization_fn`. The entry points set that function to read the listener's token when the answer is posted.
- `submit_notification_response` posts `notification_id` and `response_value` to `/api/notify/response` with a 30 second timeout. Only HTTP 200 returns `True`; every other outcome is logged and returns `False`.

## Settings and flags
- Defaults are `localhost` and port 7999. A comment in `base_config` says the server's settle deadline is derived from the reconnect cap, so the two must change together.
- `get_credentials` takes the email and password from the flags, else from `LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL` and `LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD`, and raises `ValueError` if either is missing.
- `get_anthropic_api_key` reads `ANTHROPIC_API_KEY_FIREWALLED`, then the firewalled key file, else returns `None`. For the cost difference see [[bounded-claude-code-jobs]].
- `add_common_args` adds `--host`, `--port`, `--email`, `--password`, `--session-id`, `--debug`, `--verbose` and `--dry-run`.
