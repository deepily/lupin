---
capability: mcp-broadcast-handler
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - lupin_mcp.broadcast_handler.handle_broadcast@518fae7350
---
# Broadcast handler

The listener-side step that turns an operator broadcast into one injected reminder and one ack. The server half is [[commons-and-dm]].

## What it does
- `handle_broadcast` needs a `body` and a `broadcast_id` in the notification payload. Without them it returns `error` and posts no ack.
- A line is a directive when it opens with a run of `@name` tokens that ends in a colon. It reaches a session when any name is that session's persona.
- Every other line goes to all sessions.
- With a roster of live personas, a directive counts only if one name resembles a roster persona. Otherwise it is prose and goes to all.
- It injects a reminder wrapper and posts an ack to `broadcast-acks`. The status is `completed`, or `completed-with-withheld` when lines were withheld or an `@` token matched nobody.
- The ack summary cuts the delivered body to 200 characters. The withheld count and each unresolved token are added in front of it, so the whole summary can run longer.

## Don't
- Don't pass a body that holds a `system-reminder` tag. It is refused with the status `rejected-malformed` and nothing is injected.

## Invariants
- A body with no line for this persona gets the status `skipped` and no injection.
- The bias is toward delivery: an unclear line goes to everyone and the ack says so.
- With no roster the contamination check is off, so a name glued to prose can still match nobody.
