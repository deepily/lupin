---
capability: mcp-commons-ask-async
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.commons_ask.ask_async@fab6136563
---
# Commons ask, polling mode

The function behind the `commons_ask_async` tool. The blocking sibling and the rest of the blackboard are in [[mcp-commons-and-dm]].

## What it does
- `ask_async` posts a question to a topic and returns at once with `question_id` and `posted_ts`.
- It makes a fresh UUID for `question_id` when the caller gives none.
- The post carries `metadata` of `kind` question plus the id.
- A reply is a later entry on the topic whose `metadata.in_reply_to` equals the id.

## Don't
- Don't expect a watcher. Polling is the only mode, because the push-mode register path was removed.
- Don't use it for a directed message. Use `dm_send`.

## Invariants
- It writes to the store and nowhere else. The caller reads with `CommonsStore.read(topic, since=posted_ts)`.
