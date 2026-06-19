# Phase 4 — Legacy Commons-DM Retirement: Approach Proposal (CHECKPOINT)

**Date**: 2026.06.15
**Author**: Rachel 🕊️ (builder, session `96930bc4`) — for Mr. Radio 🦉 / Rick (architect)
**Status**: APPROACH DECIDED — **Rick chose (a) FULL RETIRE, no backwards compatibility** (voice, 2026-06-15: "I'm not at all in favor of rerouting calls to deprecated method names… we get to break everything frequently in the name of doing it right. No backwards compatibility needed!"). Build on the working tree, held; deploy/cutover separately gated. Supersedes the §5 (b) recommendation below.
**Parent design**: `02-notification-native-aixai-design.md` §7 (Phase 4) + §8 (What gets retired)
**Subsumes**: bug #9 (trailing-`>` truncation) + bug #10 (stale `commons_read`/`commons_post` framing)

---

## 1. Goal (Rick, 2026-06-15)

Peer DMs use the **notification-native** path (`dm_send` → `/api/notify-peer`, `direction=ai_to_ai`,
inline body + `dm_send` reply affordance), NOT the verbose `commons_read`/`commons_post` claim-check
(~3,712 tokens/received DM → ~204, ~18×). Retire the legacy commons DM live path.

## 2. The two paths today (surveyed, file:line)

| | LEGACY claim-check | NEW notification-native |
|---|---|---|
| Send tool | `commons_send_to`, `commons_ask_async`(DM-mode), `commons_ask_sync` (`cosa_voice_mcp.py:2921/2743/2683`) | `dm_send` (`cosa_voice_mcp.py:3107`) |
| Send impl | `commons_ask.py` → `POST /api/commons/register-question` | `_dm_send_impl` → `POST /api/notify-peer` |
| Server dispatch | `execute_register_question` + `_dispatch_commons_question_received` (`commons.py:1055/1015`) — push `message=""`, body sits on the commons board | `execute_notify_peer` (`notifications.py:2874`) — **inline** `message=body`, `direction=ai_to_ai` |
| Reply path | `CommonsQuestionWatcher` polls topic, pushes `commons_answer_received` (`commons_question_watcher.py:111-354`) | symmetric `dm_send(reply_to, thread_id)` — no watcher |
| Receive (listener) | `_handle_commons_question_received` / `_handle_commons_answer_received` (`cc_notification_listener.py:537/502`) — tells recipient to `commons_read`/`commons_post` (← **bug #10**) | `_handle_event` `ai_to_ai` → `_deliver_peer_dm` (`:282/292`) — built + Cheech-approved |

**Shared / must-keep**: `_resolve_dm_recipient` (`commons.py:901`, used by BOTH paths) · `commons_ask_async`
**polling-mode** (no recipient — open questions to a topic, unrelated to DMs) · `_handle_broadcast_received`
(`:436` — broadcasts ride the same action-dispatch table; removing sibling handlers must not break it).

## 3. ⚠️ Critical constraint — the legacy path is LIVE crew infrastructure

The fleet (managers + this very session) is DM-ing over `commons_send_to` / `commons_post` **right now**.
The inbound `COMMONS PEER MESSAGE` system-reminders driving this engagement are the legacy path. Any
retire that removes the tools or the endpoint **abruptly breaks live crew comms mid-flight**. Retirement
must be staged so existing callers keep working while the body goes inline.

## 4. Options

### (a) FULL RETIRE
Repoint `commons_send_to`/`commons_ask_async`(DM) to `/api/notify-peer`; delete `register-question` +
`CommonsQuestionWatcher` + `make_question_inject_fn` + `_dispatch_commons_question_received` + the two
legacy listener handlers.
- **Blast radius (large)**: `cosa_voice_mcp.py`, `commons_ask.py`, `commons.py`, `commons_question_watcher.py`, `main.py` (watcher lifespan), `cc_notification_listener.py`, + the watcher/register-question tests.
- **Breaks**: `expect_reply=True` reply-watcher semantics (`dm_send` has no return-watcher), `question_id` correlation, `commons_ask_sync` blocking, commons-board polling fallback. **High regression risk; would disrupt live crew comms.**

### (b) REPOINT (recommended, staged) ✅
Keep the tool **names**; route their **DM-mode dispatch** through `/api/notify-peer` internally (inline
body, `ai_to_ai`). Inbound then arrives on the NEW `_deliver_peer_dm` path (already built+tested) →
framed by `build_peer_dm_reminder` → **bug #10 disappears** (no more `commons_read`/`commons_post`
instructions) AND the token win lands (inline body, no claim-check fetch).
- **Blast radius (medium)**: `commons_ask.py` DM-dispatch (repoint the recipient branch to `/api/notify-peer`), the `commons_send_to`/`commons_ask_async` docstrings, the MCP `instructions` payload (`cosa_voice_mcp.py:590-592, 720-732`). Polling-mode untouched. Listener/endpoint deletions DEFERRED.
- **`expect_reply` handling**: `commons_send_to` defaults `expect_reply=False` (no watcher needed). For `commons_ask_async(DM, expect_reply=True)`, replies ride `dm_send` threading (`reply_to`/`thread_id`) symmetrically; keep the watcher ONLY if a live caller still needs the auto-push-back (survey found the crew uses fire-and-forget + manual threaded replies, which the new path serves).
- **Low risk to live comms** (no tool/endpoint removal); the dead `register-question`/watcher get deleted in a later cleanup once telemetry shows zero hits.

### (c) REFRAME-RECEIVE-ONLY (minimal)
Only fix `_handle_commons_question_received` framing (reuse `build_peer_dm_reminder` + `dm_send` affordance).
- **Blast radius (small)**: 1 listener fn + docstrings.
- **Limitation**: the legacy dispatch payload carries **no body** (`payload={question_id, topic, asker…}`; body on the board) — so a pure receive-reframe **still needs `commons_read` to fetch the body**. It can drop the `commons_post` reply instruction but **cannot kill the claim-check fetch** → only partially fixes bug #10 and delivers **no token win**. Falls short of Rick's goal.

## 5. DECISION — **(a) FULL RETIRE, no backwards compatibility** (Rick, 2026-06-15)

My initial (b)-staged recommendation was overruled: Rick's standing doctrine is break-the-contract-and-do-it-right
([[feedback_one_descriptive_name_everywhere_break_contract]], [[feedback_no_migration_code]]) — no rerouting
through deprecated names, no back-compat shim. Delete the legacy DM path outright; peers use `dm_send`.

### Execution plan (working-tree build, held; DEPLOY/cutover separately gated)

Building on the working tree does NOT break live crew comms — the running :7999 server + the MCP server keep
serving the current code until bounced/restarted. The **cutover** (crew switches DMs to `dm_send` + server +
MCP bounce) is the gated moment; coordinated by Mr. Radio, not flipped unilaterally.

| Stage | Scope (delete unless noted) | Files |
|---|---|---|
| **S1 — MCP send tools** | Remove `commons_send_to` entirely (DM-only). Remove DM-mode (`recipient_*` branch) from `commons_ask_async` — **KEEP polling-mode** (topic questions). Remove `commons_ask_sync` DM-mode (keep any topic use). | `cosa_voice_mcp.py`, `commons_ask.py` |
| **S2 — Server dispatch + watcher** | Remove `_dispatch_commons_question_received`, `make_question_inject_fn`, the DM branch of `execute_register_question`; remove `POST /api/commons/register-question` if DM-only; remove `CommonsQuestionWatcher` + its `main.py` lifespan. **Verify** none of these back non-DM commons (broadcast/presence/polling) before deletion. | `commons.py`, `commons_question_watcher.py`, `main.py` |
| **S3 — Listener handlers** | Remove `_handle_commons_question_received` + `_handle_commons_answer_received` + their `action:` dispatch entries. **KEEP** `_handle_broadcast_received` (broadcasts ride the same table). | `cc_notification_listener.py` |
| **S4 — Docs/instructions** | MCP `instructions` payload + tool docstrings → name `dm_send`; remove the `commons_read`/`commons_post` reply etiquette + bug-filing pattern (repoint to `dm_send`). Flag external repoints (`~/.claude/CLAUDE.md`, planning-is-prompting) for Rick. | `cosa_voice_mcp.py`; external (flagged) |
| **S5 — bug #9 defensive** | Trailing `\n` after `</system-reminder>` in `build_peer_dm_reminder` (protects the surviving `dm_send` path). Pending Rick Q2 (now vs validate-first). | `hook_common.py` |
| **S6 — Tests** | Remove/repoint tests covering the deleted surfaces; 100% changed-surface on what remains. | `src/tests/**`, `src/cosa/tests/**` |

Each stage py_compile + tested; **nothing committed/pushed**; deploy/cutover gated to Rick + Mr. Radio.

## 6. Bug #9 (trailing-`>` truncation) — VALIDATED 2026-06-15: external artifact, NO code change

**Validation (Rick's validate-first)**: a byte-capture probe injected `build_peer_dm_reminder` output
through the EXACT listener sequence (`tmux send-keys -l <text>` → sleep → `send-keys Enter`) into a
`cat` capture, in two variants: (A) reminder as-is (ends `</system-reminder>`) and (B) reminder + a
trailing `\n`. **Both captures contain the FULL `</system-reminder>`** — case A ended
`b'</system-reminder>\n'`, case B `b'</system-reminder>\n\n'`. The Enter keystroke already appends a
`\n` AFTER the `>`, so the `>` is never the last byte on the wire — the trailing-`\n` defensive idea
changes nothing. **Conclusion: the truncation is NOT in our injection code; it is an external
Claude-Code-input / terminal-render artifact. The fix is NOT proven → our code is left UNTOUCHED.**
(Probe: `/tmp/bug9_probe.py`.) Since it's downstream of our boundary, it would affect the `dm_send`
path identically — not path-specific, not fixable from the repo.

### (historical proposal — superseded by the validation above)

Confirmed **NOT in our code**: `wrap=False` skips `speakerphone_wrap`/`sanitize_for_wrap` entirely; the
build is a clean f-string; `tmux send-keys -l` is byte-perfect (capture proof); server push carries
`message=""`. **Best hypothesis: a Claude-Code-input / terminal-render artifact OUTSIDE the repo.**
**Key implication**: `build_peer_dm_reminder` (the NEW path) also ends in `</system-reminder>`, so if the
clip is a terminal artifact it hits `dm_send` **equally** — retiring legacy will NOT fix bug #9.
- **Proposed defensive fix (both paths)**: emit a trailing `\n` after `</system-reminder>` so any last-char
  clip lands on a throwaway newline, not the `>`. Cheap, protects both paths. **Validate empirically on the
  new path first** (inject a peer DM, inspect the received bytes) before deciding it's worth the change.

## 7. Doc/instruction repoint inventory

| Location | In-repo? | Action |
|---|---|---|
| `cosa_voice_mcp.py:590-592` (instructions toolkit table) | ✅ in-repo | drop `commons_send_to`; name `dm_send` as the DM tool |
| `cosa_voice_mcp.py:720-732` (receipt/reply + bug-filing etiquette) | ✅ in-repo | repoint `commons_read`/`commons_post` reply pattern → `dm_send(reply_to, thread_id)` |
| `commons_send_to` / `commons_ask_async` docstrings | ✅ in-repo | already deprecation-marked; finalize wording |
| `~/.claude/CLAUDE.md` § CROSS-SESSION COMMUNICATION (~line 264) | ❌ external/global | **user must edit** (separate session) |
| `planning-is-prompting/workflow/cross-session-communication.md` | ❌ external repo | **separate repo edit / note to user** |

## 8. Open questions for Rick

1. Approve **(b) staged**, or prefer a harder **(a) full retire** now (accepting the live-comms disruption + watcher rebuild)?
2. Bug #9: apply the trailing-`\n` defensive fix to `build_peer_dm_reminder` now (protects the new path), or validate-first?
3. External doc repoints (`~/.claude/CLAUDE.md`, planning-is-prompting): want me to draft the diffs for you to apply, or just flag them?

## 9. EXECUTION — **COMMENT-OUT (not delete), revisit-later** (Rick, 2026-06-15)

**⚠️ Decision override.** Rick walked the decisions ~20:30 on 2026-06-15 and **reversed the §5 (a) FULL-DELETE call** to a **COMMENT-OUT + note-to-revisit** approach: the legacy commons-DM machinery is left in the tree behind `#` comments (+ a `# DEPRECATED (revisit-later): superseded by dm_send / notification-native path` banner at each site), NOT physically deleted. This is the reversible, low-ceremony cutover; a separate **full-removal pass** is owed later (TODO below). Built on the working tree, **held — nothing committed/pushed**; the deploy + crew cutover bounce is gated to Mr. Radio (Rick authorized the cutover bounce for this session, to run AFTER a fresh-critical reviewer).

### What landed (builder: Rachel 🕊️, session `916f4c4b`; all green + held)

| Stage | What was done (comment-out) | Files | Verification |
|---|---|---|---|
| **0 — arbiter migration** (prerequisite) | `make_dm_push_fn` now POSTs **`/api/notify-peer`** (body INLINE) instead of `register-question`; `build_register_question_payload`→`build_notify_peer_payload`; `dm_push(persona, thread_id, body)` 3-arg; call site `arbiter_job._emit_dm` passes `body`; `app.py` drops vestigial `ttl_seconds`. The durable dm-`<persona>` board write (`gateway.send_to`) is UNCHANGED (presence/receipt-polling substrate). | `arbiter_live_notify.py`, `arbiter_job.py`, `app.py`, `test_arbiter_live_notify.py`, `test_arbiter_outreach_receipts.py` | 70 tests pass; **100%** L/B on `arbiter_live_notify.py` |
| **S1 — MCP send tools** | `commons_send_to` `@mcp.tool` decorator commented out (deregistered; body left in place). `commons_ask_async` DM-mode params commented out → **polling-only** (tool stays registered). `_commons_ask_async_dispatch` DM-branch left in place w/ DEPRECATED note. `commons_ask_sync` untouched (pure polling). | `cosa_voice_mcp.py` | 705 commons/MCP unit tests pass; subprocess `list_tools` confirms `commons_send_to` absent, `commons_ask_async` present |
| **S2 — server routes + watcher daemon** | POST/DELETE `/api/commons/register-question` route decorators commented out (endpoints deregistered). `CommonsQuestionWatcher` daemon create/start/stop + import commented out in `main.py` lifespan; `init_commons_state(question_watcher=…)` arg dropped (defaults None). Pure-logic cores (`execute_register_question`/`execute_unregister_question`) + the watcher CLASS left in place (still unit-tested). | `commons.py`, `main.py`, `test_commons_ac14_registration.py` (route-registration asserts → **inverted to deregistration guards**), `test_ask_async_push_e2e.py` (module-`skip`) | 581 commons tests pass, 11 skipped; **100%** L/B on `commons.py` + `commons_question_watcher.py` |
| **S3 — listener handlers** | `_handle_commons_answer_received` + `_handle_commons_question_received` + their `_handle_action` dispatch elifs commented out (inbound peer DMs route to `_handle_peer_dm` via `direction='ai_to_ai'`). `_handle_broadcast_received` KEPT. | `cc_notification_listener.py`, `test_cc_notification_listener.py` (handler tests commented out) | listener suites green (3 pre-existing `test_voice_injection_e2e` voice-wrap failures are UNRELATED to Phase 4) |
| **S4 — instructions/docs** | MCP `instructions` payload toolkit table + autonomy tier + DM-workflow + receipt/reply etiquette + bug-filing + failure-modes repointed to **`dm_send`**; the bug-#10 `commons_read`/`commons_post` re-fetch framing dropped. | `cosa_voice_mcp.py` | 103 MCP doc tests pass; no test asserts payload content |
| **S5 — bug #9** | ✅ VALIDATED no-code-change (§6) — external CC/terminal artifact, not ours. Untouched. | — | byte-capture probe (§6) |

### TODO — full-removal pass (revisit-later)

A later cleanup should physically delete (not just uncomment) the now-dead legacy surface, once the cutover is deployed and telemetry shows zero hits:
- `commons_send_to` tool + body; `commons_ask_async` DM-mode remnants; `_commons_ask_async_dispatch` DM-branch (`cosa_voice_mcp.py`); `commons_ask.py` `_register_push_mode` + `ask_async` push-mode block.
- `execute_register_question` / `execute_unregister_question` / `make_question_inject_fn` / `_dispatch_commons_question_received` + the commented routes (`commons.py`); `CommonsQuestionWatcher` (`commons_question_watcher.py`) + its tests; the `main.py` commented lifespan block.
- The two commented listener handlers + their commented tests (`cc_notification_listener.py`, `test_cc_notification_listener.py`); the skipped `test_ask_async_push_e2e.py`.
- **KEEP regardless** (shared/live): `_resolve_dm_recipient`, `_derive_dm_topic`, broadcasts (`_handle_broadcast_received`), presence/coordination, `commons_ask_async` polling-mode, `commons_ask_sync`, the durable arbiter board write.
- External doc repoints (out-of-repo, flagged for Rick): `~/.claude/CLAUDE.md` § CROSS-SESSION COMMUNICATION, `planning-is-prompting/workflow/cross-session-communication.md`.
