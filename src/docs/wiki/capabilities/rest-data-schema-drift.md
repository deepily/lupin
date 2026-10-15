---
capability: rest-data-schema-drift
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.rest.db.schema_drift.model_names_by_table@325ad453ff
  - cosa.rest.db.schema_drift.read_revisions@a9ff47f736
  - cosa.rest.db.schema_drift.check_schema_drift@56a3cb51de
  - cosa.rest.db.schema_drift.format_drift_alarm@2682a48210
  - cosa.rest.db.schema_drift.build_drift_notification@4c6bb7a847
  - cosa.rest.db.schema_drift.push_drift_notification@dd013e4942
  - cosa.rest.db.schema_drift.deliver_drift_notification@e349db57e1
  - cosa.rest.db.schema_drift.schedule_drift_notification@4f9535330f
---
# Schema drift alarm

At boot, after auto-migrate, the server compares the ORM models with the live database and shouts if a model maps something the database lacks. It never stops the boot. Migrations and the session are in [[db-session-and-schema]].

## What it does
- `check_schema_drift( database_url )` reflects the database and returns `{ drift, db_revision, head_revision }`, or `None` when nothing is wrong. It writes nothing.
- It finds a missing table (one finding, columns not listed) or a missing column. It also finds a revision gap, when the stamped revision and the script head are both readable and differ.
- It can raise. The boot path calls `emit_startup_drift_alarm`, which never raises and prints the alarm to stderr. That function is pinned on [[db-session-and-schema]].
- `model_names_by_table( base )` maps table name to model class name for the alarm text.
- `read_revisions( engine )` returns the stamped revision and the migration head. Either is `None` when unreadable, and it never raises.
- `format_drift_alarm` writes the text. A missing table or column gives a `CRITICAL` header. A revision gap alone gives a `WARNING` header.
- `build_drift_notification( report )` returns a short spoken line with the count and the full alarm as the detail.
- `push_drift_notification` looks the recipient up by email and queues an urgent alert. It warns and returns `False` when the email matches no user.
- `deliver_drift_notification` runs that push in a worker thread with a 5 second default limit. It catches any `Exception`, prints a warning, and returns `False`.
- `schedule_drift_notification` creates the delivery task, or returns `None` for no report, no recipient, no queue, or when the task cannot be created.

## Don't
- Don't treat a clean report as a full check. Only "model has, database lacks" is tested, by name; types and defaults are not compared.
- Don't rely on the notification. The stderr alarm is the record; the notification is a second channel.
- Don't await the task `schedule_drift_notification` returns before the app serves. The call itself is synchronous and returns an `asyncio.Task`.

## Invariants
- Boot is never refused for drift.
- An empty recipient means no notification is attempted.
- Only tables on `postgres_models.Base` are seen.
