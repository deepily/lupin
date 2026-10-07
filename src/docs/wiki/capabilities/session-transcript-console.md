---
capability: session-transcript-console
pin_algorithm: py3.13.xf75af6/ts5.9.3
pins:
  - cosa.rest.cc_transcript_mapper.map_records@98ee5b4526
  - cosa.rest.cc_transcript_tailer.CcTranscriptTailer@d8e0b02bef
  - cosa.rest.cc_transcript_tailer.CcTranscriptTailer.poll_once@af91a8d8e7
  - cosa.rest.cc_transcript_tailer.read_backlog@dc430655e2
  - cosa.rest.cc_transcript_tailer.resolve_transcript_path@26e6df1fcf
  - cosa.rest.routers.cc_transcript.get_cc_transcript@5d260a1ab5
  - cosa.rest.routers.websocket.handle_cc_transcript_verb@92ea280a22
---
# Session transcript console

Shows another Claude Code seat's transcript as display blocks: a REST backlog plus a live WebSocket tail. Admin accounts only. TypeScript symbols are not pinned because the index lacked them.

## How a seat is read
- `resolve_transcript_path` reads the seat's session bridge by exact id and returns `transcript_path` verbatim, or "" if the file is missing here.
- `map_records` keeps only `assistant` and `user` records. A block's `kind` comes from the content type, not the role.
- A `tool_result` block carries `name` only when its call was seen in the same index. A budget of 0 means unbounded.
- `read_backlog` serves the last N bytes, a page before an offset, or a forward window. `get_cc_transcript` defaults to the configured tail.
- A seat with no resolvable file answers 200 with empty blocks and `watchable: false`.

## Live tail
- `handle_cc_transcript_verb` handles `cc_transcript_watch` and `cc_transcript_unwatch` on the queue socket. One shared `CcTranscriptTailer` serves each seat.
- The watch that creates the tailer starts at the client's `from_offset`; later watchers join it mid-stream. It polls, then flushes one `cc_transcript_append` frame per coalesce window.
- The shipped INI sets 0.25 s polling, a 300 ms coalesce window and a 30 s grace period before the tailer stops with no watcher. An unwatch or a disconnect that empties a seat stops its tailer at once.
- `poll_once` treats a changed bridge path as a `/clear`: new epoch, offset 0 and a chunk flagged `rotated`. The loop then announces a `rotated` state frame. A shrunken file also yields `rotated`, with a time-suffixed epoch.
- A watch is refused with `cc_transcript_state` reasons `admin_only` or `not_found`. A stale non-null `file_epoch` gets `epoch_mismatch`.

## The browser side
- `SessionTranscriptStore` drops a chunk whose offset does not abut the last one, then makes one REST repair read forward.
- It clears its buffer and re-reads the backlog on a new epoch. It sends nothing before `auth_success`.
- `SessionTranscriptRenderer` shows `text` as markdown and everything else as plain text. An unknown kind is shown, not dropped.
- `SessionTranscriptRoster` resolves a seat chip's 8-hex prefix to the full id through `/api/cc-transcript-roster`. If more than one seat shares the prefix, it narrows by persona name, ignoring case. It resolves to nothing if more than one still matches.
- `notifications.js` holds a separate legacy copy of this client logic.

## When not to use it
- The server's `ended` state has no producer: `mark_seat_ended` has no caller outside tests, and the tailer's ring is written but never read.
- Admin gates differ: REST uses `require_admin`, WebSocket uses the session's stored admin flag. See [[cc-session-bridge]] for the bridge it reads and [[websocket-events]] for the event list.
