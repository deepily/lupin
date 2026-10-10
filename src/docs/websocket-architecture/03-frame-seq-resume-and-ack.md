> Part 3 of 5 of the [WebSocket Architecture Overview](../websocket-architecture.md): frame seq, resume and ack.

#### Frame seq, resume, and ack (part 2)

A device's socket can go away and come back without losing frames. Every frame to a
**slot holder** carries a monotonic `seq`; the server retains them. The client reconnects
with `last_seq` in its `auth_request` and gets the backlog after it; its `ack` trims what
it has processed. A session with no slot — every web client — gets none of this, and pays
nothing for it.

| direction | shape |
|---|---|
| `auth_request` | `+ "last_seq": int` — absent or 0 means a fresh client with nothing to resume |
| every frame to a slot holder | `+ "seq": int`, monotonic **per slot**, starting at 1 |
| after the replay | `{ "type": "resume_complete", "replayed": N, "gap": bool, "seq": <server's current seq for the slot> }` |
| client → server | `{ "type": "ack", "seq": N }` |

Warning: **The buffer is keyed on the slot, not the session, and `disconnect()` does not sweep
it**. A session id dies with its socket. The slot is what survives a reconnect, so it is
the only key a resume can be built on. It is also what keeps supersession honest — the
successor inherits the buffer and the seq **continues** rather than restarting. So a
reconnecting client is never handed a second frame 1 carrying different contents while
its `last_seq` quietly means two things.

Warning: **`gap` is the field that is easy to get silently wrong**. A partial replay that does
not announce itself is worse than no replay: the client believes it is current and stops
asking. `gap` is true exactly when the server cannot **prove** continuity from `last_seq`.
That means frames were evicted by the cap, or nothing is retained at all against a non-zero `last_seq`.
A server restart looks like that from the client's side. It is false for
`last_seq` 0 against an unknown slot, or every device's first-ever connection would
trigger a pointless full refetch.

**A hole between the replay and the held frames is announced**. The per-device
buffer is bounded, and live frames keep arriving while the replay is on the wire. So the
oldest of them can be evicted before they are sent. `replay_and_resume` checks that each
next batch starts at `cursor + 1`. A hole found during the replay proper sets `gap` on the
one `resume_complete`. A hole found after that frame has already gone out with `gap: false` is followed by a **second** `resume_complete { gap: true }`.
That second frame is sent once, however many holes there are.
It goes out before the frames that lie past the hole. So the client refetches instead of trusting them.

Warning: **`resume_complete.seq` is the server's current seq, never an echo of the client's
`last_seq`**. After a reset the two differ, and a client that adopted its own stale number
back would discard every new frame as already seen. The client sets `last_seq =
resume_complete.seq` when it arrives.

Warning: **live frames are held until the replay drains**. A live frame sent while the backlog is
still going out would overtake it. And a client deduping on `seq` would then drop the
replayed frames as old. So between `begin_resume` and the end of `replay_and_resume` a
session's frames are stamped and buffered but not sent (`resuming_sessions`). The fan-out
still counts the device as reached, since the frame will arrive. `disconnect()` discards the
hold.

**Bounded at both ends**, because the buffers are kept after their sockets close, and per-slot capping alone would bound nothing.
`websocket device frame buffer size` (default 200) caps frames per slot.
`websocket device frame buffer max slots` (default 64) caps slots.
Eviction takes the least-recently-emitted-to slot **that has no connected holder** first.
The device most likely to come back is the one whose backlog is worth keeping. A slot whose socket is open is never evicted, however quiet.
When every slot past the ceiling is live, the map exceeds `max slots` by at most the number of connected holders.
That logs one `[WS]` warning per crossing, not per frame.
The next write after holders disconnect evicts back down.

`resume_complete` is **not** in `websocket available events`, by rule. The endpoint
sends it directly like `auth_success` and it never passes through the subscription filter.
Listing it would imply a path that does not exist.

| Method | Signature | Description |
|--------|-----------|-------------|
| `buffer_frame_for_slot` | `(slot, message) -> dict` | Assigns the slot's next seq, retains a stamped **copy**, returns it. The copy matters: `emit_to_user` builds one message and fans it out. So stamping in place would give every device the last writer's number — invisible with a single device connected. Which is how it would ship |
| `frames_since` | `(slot, last_seq) -> (list, bool)` | The retained frames after `last_seq`, plus whether continuity is proven (see `gap` above). A `last_seq` **beyond** the slot's current seq means the numbering reset under the client (a server restart). So it answers `gap: true` with the whole buffer rather than an empty, falsely-current replay |
| `begin_resume` | `(session_id) -> bool` | Starts **holding** a slot holder's live frames: they are still stamped and buffered, but not sent, until `replay_and_resume` drains. The router calls it right after `connect()` with **no `await` in between**. That adjacency is what leaves no window for a live frame to go out unheld. Returns `False` for a session holding no slot |
| `replay_and_resume` | `async (session_id, last_seq, send) -> Optional[dict]` | Sends the backlog after `last_seq`, then `resume_complete`, then releases everything held since `begin_resume`. All in seq order — and returns the `resume_complete` frame. `None`, sending nothing, for a session holding no slot |
| `ack_frames` | `(session_id, seq) -> int` | Drops that session's slot buffer up to and including `seq`; returns how many went. A session holding no slot is a silent no-op, so an ack cannot reach another device's buffer |

**Close code**. A displaced socket receives `CLOSE_CODE_SUPERSEDED` = **4004**, reason
`"superseded"` (Tiffany's ruling). Permanent: the client must not reconnect it.

Warning: **A new code, not a reuse — this shipped as 4001, was cut to 4003, and both were taken**.
4001 is auth failure, which the browser answers with a token refresh that means nothing for a
supersede. 4003 is `CLOSE_CODE_AUTH_SUBSCRIPTION_DENIED`.
It is reserved server-side and never emitted.
But the code is **live on the client**.
`QueueTransport.ts` lists it in `PERMANENT_CLOSE_CODES`.
`notifications.js` renders it "Permission denied for one or more notification streams".
A reserved server code can still be a spoken-for client one, which is worth remembering.
4004 is free in both places.
