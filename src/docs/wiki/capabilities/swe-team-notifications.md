---
capability: swe-team-notifications
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.agents.swe_team.cosa_interface.ask_confirmation@24a6c17bf4
  - cosa.agents.swe_team.cosa_interface.get_feedback@08e962bb98
  - cosa.agents.swe_team.cosa_interface.get_sender_id@63b6e070e0
  - cosa.agents.swe_team.cosa_interface.notify_progress@261bc51e7a
  - cosa.agents.swe_team.cosa_interface.request_decision@cdb054d0a8
  - cosa.agents.swe_team.voice_io.reconfigure@8265f4719a
  - cosa.agents.swe_team.notification_client.OrchestratorNotificationClient@38473751dd
---
# SWE team notifications

The orchestrator talks to the user and the proxy through `cosa_interface`, and listens for messages the user sends to a running job through `OrchestratorNotificationClient`. The run itself is in [[swe-team-orchestrator]].

## What it does
- `get_sender_id( role, session_id )` builds `swe.<role>@<project>.deepily.ai`. It cuts the session id at `::` and adds the rest as a `#` suffix.
- `notify_progress` sends a fire-and-forget notice for a role, at medium priority by default.
- `ask_confirmation` asks a yes/no question and returns a bool. The default answer is `no` and the wait is 120 seconds.
- `request_decision` presents multiple-choice questions and returns a dict of answers, with a 300 second wait. `get_feedback` returns the user's reply text, or `None`.
- Each call first copies the module's session id and target user onto the shared dispatcher. `notify_progress` also copies the session name.
- `voice_io.reconfigure` binds the shared voice layer back to this module. Call it at the start of a run, because the last package to bind wins.
- `OrchestratorNotificationClient` subscribes to `notification_queue_update` and `sys_ping` under the session id `swe-notif-<job id>`.
- It keeps only `user_initiated_message` notifications for its own job id. Each goes on a shared queue with message, priority, timestamp and sender.
- An `urgent` message also sets a shared event, so the orchestrator checks in at once.
- `start` runs it in a daemon thread with its own event loop. `stop_sync` closes the socket and waits up to 5 seconds for the thread.

## Invariants
- The client makes its login token in-process from the user's email. If the user is not found, login returns `None`.
