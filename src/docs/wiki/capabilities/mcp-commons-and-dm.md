---
capability: mcp-commons-and-dm
pin_algorithm: py3.13.xf75af6/ts5.9.3
pins:
  - lupin_mcp.commons_store.CommonsStore@d6898c6724
  - lupin_mcp.commons_store.CommonsStore.post@f275887ce9
  - lupin_mcp.commons_store.CommonsStore.read@8d46e9aee9
  - lupin_mcp.commons_store.CommonsStore.who@115766fdcb
  - lupin_mcp.commons_ask.ask_sync@9afd873bda
  - lupin_mcp.cosa_voice_mcp.dm_respond@3124640cce
  - lupin_mcp.cosa_voice_mcp.dm_list@51eb3e41a6
  - lupin_mcp.cosa_voice_mcp.dm_get@cdf31216e5
---
# MCP commons and direct messages

The cosa-voice MCP server gives a session two ways to talk to peers: a file blackboard (`commons_*`) and inline direct messages (`dm_*`). The REST side is [[commons-and-dm]].

## Commons blackboard
- `CommonsStore` keeps one markdown file per topic under `io/commons/` in the main tree, even when the caller passes a worktree path. The archiver does not do this resolution.
- `post` appends under an exclusive file lock. A free-form topic file is created on the first post.
- Persona name, icon and color are stamped from the session bridge at post time. Missing values become `<unknown>`, a speech-bubble icon and `#888888`.
- `read` returns newest first without `since`, ascending with it, capped at `limit`. A missing reserved topic raises; a missing free-form topic still consults the archive, so it returns an empty list only when the archive has nothing.
- `read` opens archived daily files only when the active file cannot answer. Without `since`, that means fewer than `limit` entries. With `since`, it means `since` predates the oldest entry or the file is empty. It de-duplicates on timestamp, sender and body.
- `who` lists sessions that posted within `retention_hours` (default 24), newest first, over one topic or every topic file.
- `CommonsArchiver` moves entries older than the retention window into `archive/<day>/<topic>.md`, where `<day>` is the UTC day of the rotation. It runs every `commons_archival_interval_seconds` and keeps `commons_retention_hours`. It takes the configured root as is, so under a seat worktree it watches that tree's `io/commons`. The server starts it from its `__main__` block, only when commons is enabled.
- With commons disabled, `commons_post` and both ask tools return an error dict; `commons_read` and `commons_who` return `[]`.

## Asking a topic
- `commons_ask_sync` posts a question with a fresh `question_id`, then polls the topic for replies whose `metadata.in_reply_to` matches.
- After the first reply it waits `grace_seconds`, re-reads, and returns all matches. On timeout it returns an empty `replies` list.
- `commons_ask_async` posts the question and returns `question_id` and `posted_ts` at once. It starts no watcher; you poll `commons_read` yourself.
- For a directed message use a DM instead: `commons_ask_async` only writes to the topic file.

## Direct messages
- `dm_send` posts the body inline to `/api/dm/send` with an `X-API-Key` header. Without a key it returns `missing_auth_header` and sends nothing.
- A given `recipient_session_id` is sent instead of the recipient persona name. Replies pass `reply_to` and `thread_id`.
- Results map from HTTP status: 201 `sent`, 422 `recipient_unresolved`, 413 `dm_too_long`, anything else `http_<code>`; a transport failure gives `request_failed`.
- `dm_send` returns `borrowed_identity` when the session id was guessed from the working directory. The `dm_respond` body does not make that check.
- `dm_respond` takes `reply_to` and `thread_id` as required arguments and posts to `/api/dm/respond`. `dm_get` fetches one DM by id.
- `dm_list` sends this session's id whenever it is known, and sends `scope` only when it is `account`.
