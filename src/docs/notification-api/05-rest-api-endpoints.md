> Part 5 of 16 of the [Lupin Notification API Reference](../notification-api.md): REST API endpoints.

## 4. REST API Endpoints

For the complete endpoint reference with request/response schemas, see:
- **Interactive docs**: `/docs` (Swagger UI) or `/redoc` (ReDoc). Always current
- **Quick reference table**: [rest-api-reference.md](../rest-api-reference.md)

The notification endpoints are in the `notifications` tag group — **24 routed endpoints** (counted from `notifications.router.routes`; it moves, so re-derive rather than quoting this) covering:
- `POST /api/notify` — Core dispatch (fire-and-forget or SSE blocking)
- `POST /api/notify/response`. User response submission
- `GET/DELETE /api/notifications/*` — CRUD operations
- `GET /api/notifications/conversation/*` — Conversation threading
- `GET /api/notifications/senders*`. Sender activity queries
- `GET /api/notifications/broadcast-acks/{broadcast_id}` — one broadcast's saved ack tally
- `POST /api/notifications/generate-gist` — LLM session naming

### 4.1 GET /api/notifications/broadcast-acks/{broadcast_id}

Rebuild one broadcast's ack tally from the saved notification rows — which seats acked,
with what status, and when. Added with store (parent), implementing Rick's ruling that acks are saved alongside the notifications
rather than existing only as an in-memory push.

**Auth**: API key or Bearer JWT. The recipient is the authenticated account and there is
no user id in the path. So a caller can only ever read acks addressed to itself.

| parameter | in | default | meaning |
|---|---|---|---|
| `broadcast_id` | path | — | the broadcast's id, as written into `payload.broadcast_id` |
| `limit` | query | 500 | rows scanned before the latest-per-session fold |

**Response** `200`

```json
{
  "status"       : "success",
  "broadcast_id" : "11111111-aaaa-4bbb-8ccc-222222222222",
  "ack_count"    : 2,
  "acks": [
    {
      "id"            : "8f1c…",
      "broadcast_id"  : "11111111-aaaa-4bbb-8ccc-222222222222",
      "session_id"    : "f19a8996-2fdc-425d-82bc-0e99f3cd8db2",
      "persona_name"  : "Mr. Radio",
      "persona_icon"  : "🦉",
      "persona_color" : "#FFA000",
      "ack_status"    : "completed",
      "body_summary"  : "⚠️ :7999 is bouncing NOW — hold notifications…",
      "state"         : "delivered",
      "created_at"    : "2026-09-23T21:37:31.717091+00:00"
    }
  ],
  "timestamp": "2026-09-23T17:37:32-04:00"
}
```

Other codes: `400` when the credential is not a UUID, `500` on a query fault. A broadcast
nobody has acked is `200` with `ack_count: 0` — an answer, not an absence.

Warning: **This read ignores delivery state, and it must**. The undelivered drain
(`GET /api/notifications/undelivered`) answers *what did I miss while offline* and
therefore skips anything already delivered to a socket. An ack that lands while a browser
is open is marked delivered instantly. So a tally rebuilt from the undelivered inbox comes
back empty for the very acks the user already half-saw. This endpoint asks a different
question — *which seats have acked this broadcast*. Its answer does not depend on whether a socket happened to be open.
Adding a state filter here would break that.
Removing the undelivered drain's own state filter would break the drain.

**Where the rows come from**: `CommonsAckWatcher._persist_ack_row` saves each ack as a
`commons_broadcast_ack` notification addressed to the broadcaster, with the identity in
the new `payload` column. And marks it `delivered` immediately so it never joins the AFK
inbox as a bodiless "missed notification".

Warning: **A saved ack is excluded from the sender rosters and the conversation reads**.
That is six queries in all, via `NotificationRepository.NON_CONVERSATION_TYPES`: the two rosters
(`get_sender_last_activities`, `get_sender_last_activities_visible`) and the four
conversation/history reads (`get_sender_conversation`,
`get_sender_conversations_by_date`, `get_sender_date_summaries`,
`get_active_conversation`). Deliberately not `count_by_sender` or `get_by_recipient`, which also return acks but have no caller outside tests. Those queries group by `sender_id` and
filter on nothing else, so any row saved into `notifications` becomes a *sender*. Without the exclusion a seat appears in `/api/notifications/senders-visible` — and
therefore in the multiplexer's strip and the operator focus bar. Which hydrate from it —
purely for having acked a broadcast. Before the conversation reads were covered too, `/api/notifications/active-conversation/{user_email}` would answer with a seat that had merely acked.
The history hydration also gained date buckets that existed for no other reason. None of it was visible: the multiplexer's `normalizeHistoryRow` drops an
empty-message row at render. So the rows never appeared while the counts, the buckets
and the active-conversation pick were all silently wrong. The exclusion holds whatever
`sender_id` an ack carries: even a perfectly attributed ack would inflate that seat's `notification_count`
and drag its `last_activity` forward. A broadcast ack is a tally element, and
`/api/notifications/broadcast-acks/{broadcast_id}` is where it is meant to be read.

Warning: **An ack row's `sender_id` is `claude.code@unknown.deepily.ai#<hash8>`, and the
`unknown` is a measurement rather than a gap**. The commons store is shared across
projects — a `lupin-mobile` or `planning-is-prompting` seat acks into the same topic. And a commons entry carries no project and no sender id, only `sender_session_id` plus
persona fields. Naming a project here would file a peer project's ack under this one. And it would look correct in every tally because the persona and the broadcast would
still be right. The seat's 8-char session prefix is carried, because the entry supplies
it and `_voice_persona_for_sender_id` matches on exactly those characters. The persist runs on the watcher's own daemon
thread and cannot block or fail the live push. A failure prints a `[CommonsAckWatcher] ❌
ack not saved` line regardless of the debug flag.

**Not a new aggregate**. There is no ack table and no ack cache — this reads the same
`notifications` rows the watcher writes. And it works only because those acks are saved.

**Live probe** (write-only, run at the operator's discretion — it interrupts every live
seat): `src/scripts/probe_broadcast_ack_two_sided.py`.

### 4.2 GET /api/notifications/awaiting-response

The response cards still waiting for the caller's answer, oldest first, in the shape a live push carries.
Both pages call it at load, so a card filed while the page was closed is drawn as a Yes/No card.

Shape: `{ status, awaiting_count, notifications, timestamp }`.
Each notification carries these fields:

- `id`, `sender_id`, `sender_persona`, `sender_icon`
- `title`, `message`, `abstract`, `type`, `priority`
- `job_id`, `payload`, `state`
- `response_requested` (always true), `response_type`, `response_default`, `response_options`, `timeout_seconds`
- `suppress_ding` (always true), `created_at`
- `voice_persona`

`voice_persona` is the sender's persona from the session bridge, or null, under the key a live push uses.

- `timeout_seconds` is the whole seconds left to the row's expiry, rounded up, so a page restarts its countdown where the server's clock stands. A row with no expiry keeps its own timeout.
- A row past its expiry, or soft-hidden, is left out. A row the user has answered is not waiting. So it is left out too.
- A pure read: nothing is marked delivered or answered. `400` when the credential is not a UUID, `500` on a query fault.
- It reads `NotificationRepository.get_pending_for_recipient`, not the undelivered inbox: a card pushed to an open page is already `delivered` and is still waiting.

---
