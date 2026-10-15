---
capability: rest-core-podcast-cards
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.rest.podcast_proxy.StartRefusal@26f44c9ab4
  - cosa.rest.podcast_proxy.start_refusal@4eb858d8de
  - cosa.rest.podcast_proxy.asker_label@cc8bd9c6ac
  - cosa.rest.podcast_proxy.binding_id@62a7fbe674
  - cosa.rest.podcast_proxy.card_payload@8179fd6d43
  - cosa.rest.podcast_proxy.card_text@f1c40de3d0
  - cosa.rest.podcast_proxy.card_state@385f16fd1b
  - cosa.rest.podcast_proxy.max_age_seconds@21b01c71e6
  - cosa.rest.podcast_proxy.dry_run_enabled@e839d6ab46
---
# Podcast proxy: the approval card and the start

The question the operator answers, and the checks before a job starts. The file check is [[rest-core-podcast-door]].

## Card
- `card_payload( facts, asker, session_id )` is what the server stores: `kind`, `command`, `scope_path`, `server_path`, `name`, `size`, `sha256`, `asked_by` and `asked_by_session`. Every value is server-made.
- `asker_label` reads `<persona> (<id>)` for a session the bridge knows, else `an unrecognized session (<id>)`. The caller's actor string is never in it.
- `binding_id( session_id, seat )` is the first 8 characters of the seat's stable id, or the given id for an unknown seat. A re-spun seat still finds its card. It is a courtesy, not a lock.
- `card_text( payload )` returns the `(question, abstract)` pair. The question holds no path or hash.
- `card_state( card, now )` is one of `waiting`, `yes`, `wrong_login`, `no`, `default_answer` or `expired`.

## Start
- `start_refusal( card, actor_session, now, max_age )` is `None` only when all of these hold. The card exists with this feature's payload. It was asked and answered. The answer is a yes a person gave on the operator's own login. The caller is the asking seat by stable id. The card is no older than `max_age`. Otherwise it returns a `StartRefusal` with status, code and message.
- `max_age_seconds` reads the INI age, default 900. It raises `ValueError` for zero or less.
- `dry_run_enabled` is true when `LUPIN_PODCAST_PROXY_DRY_RUN` is `true`, `1` or `yes`, or the INI key is true. A dry run does every check, writes the spent-card row and queues nothing.
