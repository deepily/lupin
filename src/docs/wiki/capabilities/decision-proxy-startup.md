---
capability: decision-proxy-startup
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.agents.decision_proxy.__main__.main@84ce2f57b1
  - cosa.agents.decision_proxy.__main__.parse_args@c1dbf85775
  - cosa.agents.decision_proxy.listener.DecisionListener@e9fab60778
  - cosa.agents.decision_proxy.voice_io.notify@1f32442af0
  - cosa.agents.decision_proxy.config.trust_proxy_config_from_config_mgr@a8f76a4d1a
---
# Decision proxy startup

`python -m cosa.agents.decision_proxy` wires a listener to the [[decision-proxy]] responder and runs until it is stopped. This page covers what `main` does around that, the listener and the status notices.

## What it does
- `parse_args` takes the shared proxy arguments plus `--profile` (default `swe_team`) and `--trust-mode` (`shadow`, `suggest` or `active`, default `shadow`). The session id defaults to `decision proxy`.
- `main` treats `--verbose` and `--dry-run` as `--debug`. A credential error exits with code 1.
- It loads the profile into the responder, then builds a `DecisionListener` and gives the responder the listener's token for posting answers.
- It sends a low-priority notice on connect and on disconnect, stops the listener on interrupt or terminate, and prints the responder's statistics on exit.
- `DecisionListener` extends the base listener from [[proxy-agent-base]]. It subscribes to `notification_queue_update`, `job_state_transition` and `sys_ping`.
- `voice_io.notify` sends a status notice as `decision.proxy@lupin.deepily.ai` at low priority by default. It builds its keywords with `build_notify_kwargs` ([[proxy-shared-helpers]]) and returns whether the notice was sent.
- `trust_proxy_config_from_config_mgr` reads 36 INI keys into one dict, each with a module default. Four start with `decision proxy`, the rest with `swe team trust proxy`.

## Don't
- Don't expect `main` to refuse in the shipped setup with an error code. A disabled proxy prints a message and returns normally.
- Don't expect presence settings here. See [[decision-proxy-presence]].
