---
capability: rest-services-fleet-tables
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.rest.postgres_models.Notification@74eecfa097
  - cosa.rest.postgres_models.ProxyDecision@08b7b65095
  - cosa.rest.postgres_models.TrustState@0c29757d8e
  - cosa.rest.postgres_models.PredictionLog@3638bc1147
  - cosa.rest.postgres_models.JobHistory@9040d3c885
  - cosa.rest.postgres_models.ServerLifecycle@dc6a76b380
  - cosa.rest.postgres_models.ApprovalSetting@ab38c60138
  - cosa.rest.postgres_models.PodcastProxySpentCard@92ce8d11ce
  - cosa.rest.postgres_models.TaskItem@65a21ee90e
  - cosa.rest.postgres_models.TaskEvent@db2b5a9cc5
  - cosa.rest.postgres_models.TaskPromotionTicket@cb0bf5b83e
---
# Notification, job and task-store tables

The models in `cosa.rest.postgres_models` behind notifications, the decision proxy, CJ Flow persistence and the unified task store. Read [[task-store]] for the rules that sit on top of `TaskItem`, and [[decision-proxy]] for the proxy tables.

## What it does
- `Notification` is sender-aware: `sender_id`, `recipient_id` (a user UUID), `message`, and a `state` that defaults to `created`. Deleting the recipient cascades.
- `ProxyDecision` logs every decision the proxy classified and acted on or shadowed; `ratification_state` defaults to `not_required` and extra data goes in JSONB.
- `TrustState` holds the per-user, per-domain, per-category trust level and statistics, with the circuit breaker stored as JSONB.
- `PredictionLog` pairs one prediction with the human's later answer. `accuracy_match` stays null until the outcome is recorded.
- `JobHistory` is the CJ Flow job record. Its primary key is the scoped `id_hash` string, not a UUID, and `user_id` is a string with no foreign key.
- `ServerLifecycle` is one row, key `singleton`. The heartbeat stamps `last_available_at`; startup reads it to catch up scheduled jobs inside the downtime.
- `ApprovalSetting` is one row per approval-policy key, plus a migration marker row, with who wrote it and when.
- `PodcastProxySpentCard` marks a podcast proxy card as having started its one job. The primary key makes two simultaneous starts impossible.
- `TaskItem` is one row per obligation; status defaults to `queued`, and a `CHECK` requires `next_chase_ts` when status is `blocked` and `blocked_by` names a persona. `TaskEvent` is its append-only audit trail, written in the same transaction as each change.
- `TaskPromotionTicket` records one promotion out of the holding area and how it resolved: `pending`, `approved`, `refused`, `superseded` or `stalled`.

## Don't
- Don't read a ticket's `to_status` from the notification; it lives on the ticket.
- Don't treat `JobHistory.id_hash` as a UUID.

## Invariants
- A non-`pending` ticket carries `resolved_at`, and a `refused` one carries its refusal text.
