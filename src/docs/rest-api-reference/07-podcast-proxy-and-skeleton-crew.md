> Part 7 of 9 of the [Lupin REST API Quick Reference](../rest-api-reference.md): routes 25b and 25c: podcast proxy, skeleton crew switch and fleet cap.

## 25b. Podcast Proxy (`/api/podcast-proxy/*`)

A seat asks for a podcast of a document on the operator's behalf.
The server judges the file and writes the yes/no card itself. It starts the job only after the operator's own yes.
Every refusal is `{ detail: { code, message } }`.
The card binds to the seat's stable session id, and the actor is `<persona> <first 8 hex of the stable id>`.
That check is a courtesy. The lock is the operator's yes bound to the file's hash, plus one spent-card row per card.
Auth for all three: X-API-Key or Bearer JWT.

| Method | Path | Summary |
|--------|------|---------|
| POST | `/api/podcast-proxy/ask` | Body `{ path, actor }`, `path` in doc-viewer form `<scope>/<path>`. Judges the file, files a yes/no card whose default is no, returns `{ card_id, name, size, sha256, asked_by, expires_at, pushed }`. 400 `bad_actor` or a door code (`bad_path`, `not_found`, `viewer_refused`, `wrong_kind`, `too_large`, `credential`, `unreadable`); 404 `no_operator`. 409 `waiting_card` with `card_id` beside the code when a live card for the same bytes exists. |
| POST | `/api/podcast-proxy/start` | Body `{ card_id, actor }`. Re-checks the stored card and the file, spends the card once, queues the job from a copy of the judged bytes, returns `{ card_id, job_id, status, name, queue_position }`. 404 `no_card`, `no_operator`; 400 `bad_actor`; 403 `bad_card`, `not_answered`, `default_answer`, `not_yes`, `wrong_login`, `wrong_session`, `too_old`; 409 `file_refused`, `hash_mismatch`, `spent`, `claimed_no_job` (a start is under way or one did not finish: read the card status before asking again). 502 `queue_failed` (fixed sentence, cause in the server log; the same card may retry). With INI `podcast proxy dry run = true` (default false) the checks and the claim run, the spent row takes a `dry-run-` job id, nothing is copied or queued. And the answer's `status` is `dry run`. |
| GET | `/api/podcast-proxy/card/{card_id}` | Where a card stands: `{ card_id, scope_path, name, size, sha256, asked_by_session, state, expires_at, spent, job_id }`, with `state` one of `waiting`, `yes`, `no`, `default_answer`, `expired`, `wrong_login`, `claimed_no_job`. 404 `no_card`. |
| GET | `/api/podcast-proxy/from-viewer/check` | Query `path` in doc-viewer form. Runs the start's whole file judgement without keeping content, so the doc viewer shows its "Make a podcast" button only for a file that can be podcast. Returns `{ ok, name, size }`. 403 `not_a_person` (API key, or a token with no email); 400 with a door code. Bearer JWT of a signed-in person. |
| POST | `/api/podcast-proxy/from-viewer` | Body `{ path }`. The in-page confirmation is the yes, so there is no card. Judges the file, claims one job per person, file and bytes inside `podcast proxy card max age seconds` (a derived id in the spent-card table; a click after the window starts a new job), queues the job for the caller, returns `{ job_id, status, name, queue_position, size }`. 403 `not_a_person`; 400 with a door code; 409 `spent` with `job_id` beside the code, or `claimed_no_job`; 502 `queue_failed`. Each click writes its copy under its own folder. Dry run applies as for start. |

## 25c. Skeleton Crew Switch and Fleet Cap (`/api/arbiter/*`)

One operator switch that stops all spawning and mutes the Stop poke.
The value is the boolean `cc session skeleton crew enabled` in `src/conf/lupin-app.ini`.
Every reader reads that file fresh, so a flip needs no restart. A key that is absent reads as off.
Design note: `src/rnd/v0.2.2/2026.10.10-skeleton-crew-toggle-design.md`. Full schemas: `/docs`.

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/arbiter/fleet-size-cap` | API key or JWT | The fleet dial: `{ cap, ceiling, live, skeleton_crew }`. `skeleton_crew` is `{ on, since, set_by, settings_mute_while_off }`, read fresh from the file. An unreadable file reads as off. `set_by` says the setter is unknown when the attribution record disagrees with the file. `settings_mute_while_off` is true when the poke is muted in `settings.json` while the switch is off. |
| PUT | `/api/arbiter/fleet-size-cap` | Admin JWT | Body `{ cap }`, a whole number from 1 up to the configured ceiling (422 above it, and nothing is written). Writes `cc session fleet size cap` to the configuration file and returns the body of the GET above, re-read from the file. 403 for a caller presenting only `X-API-Key`, so a manager cannot raise its own cap, and 403 for a signed-in user without the admin role. 409 when the key is absent or defined twice. The GET stays open to an API key or a JWT. |
| PUT | `/api/arbiter/skeleton-crew` | Admin JWT | Body `{ on }` (a bare JSON boolean, else 422). Writes the attribution record, then the file, then tells every live session through an acknowledged broadcast. Returns the same body as the GET above, re-read from the file. 403 for a caller presenting only `X-API-Key`, so a manager cannot flip it. 409 when the key is defined twice. 500 naming the cause when the file cannot be written, and nothing is announced. A failed broadcast does not fail the flip. |

**What the switch does while on.**

| Door | Result |
|---|---|
| `spawn_sessions` and `start-cc-with-tmux.sh` called by an agent | Refused with a message that names the state. A person at a terminal is still allowed |
| A one-for-one re-spin | Allowed while the credit is fresh. `dismiss_sessions` mints one credit per persona it killed, valid for 15 minutes. The launcher spends it once |
| Stop-hook poke | Muted, and a manager's Stop text is the operator's single line, with no staffing text |
| The arbiter's external manager pokes on `:8001` | Unchanged, because the operator kept them as the stall alarm |

The file mute from 25a stays a separate lever.
`GET /api/heartbeat/poke-mute` reports which of the two muted the poke in its `source` field.

---
