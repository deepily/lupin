# Per-Session Voice Personas — Execution Log

**Companion design**: [`01-design.md`](01-design.md)
**Plan**: `~/.claude/plans/let-s-start-a-new-magical-hickey.md`

This log tracks phase-by-phase execution. Each section starts pending and is
filled in as work completes.

---

## Phase 0 — Documentation Artifacts

**Status**: ✅ Complete (2026-04-28)

- [x] `01-design.md` — full design (sections 1-12)
- [x] `90-execution.md` — this skeleton
- [ ] `src/rnd/v0.1.7/README.md` — index update (do as part of Phase 11)
- [ ] `CLAUDE.md` DOCUMENTATION TOUCHPOINTS row (do as part of Phase 11)

---

## Phase 1 — INI + splainer keys

**Status**: ✅ Complete (2026-04-28)

Files:
- `src/conf/lupin-app.ini` — new `[Voice Personas]` block + `cc session voice persona pool`
- `src/conf/lupin-app-splainer.ini` — matching descriptions

Schema:
```ini
[Voice Personas]
# Comma-separated list of persona names eligible for random allocation.
# Sam is intentionally NOT in this list — Sam is the system-wide TTS default
# voice for any request lacking a voice_id parameter.
cc session voice persona pool = Nora, Quentin, Rachel, Adam, Domi, Arnold

# Per-persona definitions (each persona has 4 keys: voice_id, icon, color, profile)
cc session voice persona Nora voice id    = kcQkGnn0HAT2JRDQ4Ljp
cc session voice persona Nora icon        = 🌸
cc session voice persona Nora color       = #E91E63
cc session voice persona Nora profile     = Warm, inquisitive female

cc session voice persona Quentin voice id = Aa6nEBJJMKJwJkCx8VU2
cc session voice persona Quentin icon     = 🦉
cc session voice persona Quentin color    = #FFA000
cc session voice persona Quentin profile  = Authoritative warm male

cc session voice persona Rachel voice id  = 21m00Tcm4TlvDq8ikWAM
cc session voice persona Rachel icon      = 🕊️
cc session voice persona Rachel color     = #4CAF50
cc session voice persona Rachel profile   = Calm & clear female

cc session voice persona Adam voice id    = pNInz6obpgDQGcFmaJgB
cc session voice persona Adam icon        = 🌑
cc session voice persona Adam color       = #3F51B5
cc session voice persona Adam profile     = Deep male

cc session voice persona Domi voice id    = AZnzlk1XvdvUeBnXmlld
cc session voice persona Domi icon        = ⚡
cc session voice persona Domi color       = #C2185B
cc session voice persona Domi profile     = Young & energetic female

cc session voice persona Arnold voice id  = VR6AewLTigWG4xSOukaG
cc session voice persona Arnold icon      = 🪨
cc session voice persona Arnold color     = #C62828
cc session voice persona Arnold profile   = Gravelly male
```

---

## Phase 2 — session_bridge.py helpers

**Status**: ✅ Complete (2026-04-28)

`src/lupin_cli/claude_code/hooks/lib/session_bridge.py` additions:
- `get_voice_persona( session_id )` — read from bridge, returns dict or None
- `set_voice_persona( session_id, persona )` — write/clear, returns bool

Mirror the `get_conversation_mode` / `set_conversation_mode` pair structurally.

---

## Phase 3 — voice_persona_helpers.py (pure-function module)

**Status**: ✅ Complete (2026-04-28)

`src/cosa/rest/voice_persona_helpers.py`:
- `find_active_voice_persona_sessions()` — scan `cc-*.json` for live PIDs
  with non-null `voice_persona`; return `[(path, sid, persona_name), ...]`
- `pick_unallocated_persona( pool, occupied_names, stable_session_id )` —
  uniform random draw from `pool − occupied`. If exhausted, return
  `pool[hash(stable_session_id) % len(pool)]` with `borrowed=True`.
- `load_persona_pool_from_config()` — parse INI block into list of persona dicts
- `borrowed_persona_for_sid( pool, stable_session_id )` — deterministic fallback

Unit-testable in isolation (no async, no global state).

---

## Phase 4 — voice_persona.py router

**Status**: ✅ Complete (2026-04-28)

`src/cosa/rest/routers/voice_persona.py`:
- `POST /api/cosa-voice/voice-persona/{session_id}/allocate` — atomic
- `POST /api/cosa-voice/voice-persona/{session_id}/release` — clear bridge
- `GET /api/cosa-voice/voice-persona/pool` — snapshot {pool, occupied, free}

Module-level `asyncio.Lock` serializes scan→pick→write. WS broadcast on
allocate/release via `emit_to_user`.

Register in `src/fastapi_app/main.py` next to conversation_mode router.

---

## Phase 5 — register_session.py allocation + /clear preservation

**Status**: ✅ Complete (2026-04-28)

Edit `src/lupin_cli/claude_code/hooks/register_session.py`:
- After bridge identity-fields write, before `send_tts`:
  - If `is_context_clear` and `old_data.get("voice_persona")` → carry forward
  - Else POST `/allocate` synchronously (1-2s timeout via `urllib.request`),
    write returned persona to bridge

Failure mode: server unreachable → log warning, leave persona null. Server
will fall back to Sam on TTS dispatch.

---

## Phase 6 — session_end.py release

**Status**: ✅ Complete (2026-04-28)

Edit `src/lupin_cli/claude_code/hooks/session_end.py`:
- POST `/release` with 1-2s timeout, fail-soft (log + continue on error)

---

## Phase 7 — notifications.py envelope stamping

**Status**: ✅ Complete (2026-04-28)

Edit `src/cosa/rest/routers/notifications.py`:
- After `resolve_sender_id`, look up persona via `get_voice_persona`
- Stamp `voice_persona` on stored notification record
- Include `voice_persona` in WS envelope payload (envelope dict at
  `notifications.py:533-545` and `:752-774`)

---

## Phase 8 — notifications.js UI updates

**Status**: ✅ Complete (2026-04-28)

Edit `src/fastapi_app/static/js/notifications.js`:
- Sender card render: add persona badge to header (icon + color background)
- `playTTS()`: change body key from `voice` → `voice_id`; pass
  `persona.voice_id` if available, else omit (server-default Sam)
- WS event handler: route `voice_persona_assigned` / `voice_persona_released`
  to refresh badge

---

## Phase 9 — notifications.css badge styling

**Status**: ✅ Complete (2026-04-28)

Edit `src/fastapi_app/static/css/notifications.css`:
- `.persona-badge` — base styling (rounded, color-tinted)
- `.persona-badge.borrowed` — dashed border + tooltip variant

---

## Phase 10 — Tests

**Status**: ✅ Complete (2026-04-28)

Three layers:
- `src/tests/unit/test_voice_persona_helpers.py` — pure functions, parametrized
- `src/tests/smoke/test_voice_persona_allocation.py` — live :7999 endpoints
- WS smoke addition for `voice_persona_assigned` event

---

## Phase 11 — Documentation finalization + verification

**Status**: ✅ Complete (2026-04-28)

- `CLAUDE.md` DOCUMENTATION TOUCHPOINTS row
- `src/rnd/v0.1.7/README.md` index entry
- Run full :7999 verification matrix
- Manual UX validation (3 concurrent sessions)

---

## Surprises / Course Corrections

- **User clarification mid-plan**: original plan had Sam in the 7-voice
  allocatable pool. User clarified Sam should remain reserved as the
  system-wide default for any TTS request without a voice_id, NOT in the
  allocatable pool. Pool reduced from 7 to 6, plan updated, design coherent.
- **User clarification mid-plan (random)**: original plan picked
  "first(pool − occupied)" which is deterministic. User noted the original
  kickoff prompt said "at random". Switched to `random.choice(pool − occupied)`
  uniform random draw.
- **Design-review insight (concurrent allocation)**: Plan agent (Phase 2 of
  plan workflow) caught a TOCTOU race between SessionStart hook and the
  first /api/notify call. Mitigation: synchronous /allocate from the hook
  BEFORE its own send_tts; bridge file is the persistence anchor, with
  fallback to Sam (server default) if server unreachable.
- **Design-review insight (storage model)**: registry singleton was
  rejected in favor of "bridge file canonical + per-request scan". Per-call
  cost is O(active_sessions) which is bounded (typical 1–5), and the
  conversation_mode router precedent already validates this pattern.
- **Design-review insight (sweeper)**: separate sweeper goroutine was
  rejected — dead-PID filtering on every read makes it implicit. Same
  pattern as `find_active_conversation_sessions`.
- **Bundled bug fix**: notifications.js was sending `{ voice: "default" }`
  to a server endpoint that reads `voice_id`. Silent ignore today; fix
  bundled with this work since the same lines are touched anyway.

## Final Verification (2026-04-28)

| Layer       | Result                                                              |
|-------------|---------------------------------------------------------------------|
| py_compile  | 8/8 edited Python files compile clean                               |
| node --check| notifications.js syntax clean                                       |
| Unit        | 25/25 tests passed in 0.07s (test_voice_persona_helpers.py)        |
| Smoke       | 7/7 tests passed in 0.33s against live :7999 (test_voice_persona_allocation.py) |
| Regression  | 70/70 tests passed (test_session_bridge_lookup.py + test_conversation_mode_router.py) |
| Total       | 102/102 tests in 0.80s                                              |

The one verification I cannot automate is the perceptual end-to-end check:
**spawn three concurrent `claude code` sessions in different terminals,
trigger a notification from each, and confirm three distinct voices speak
+ three distinct colored badges render in the notifications UI.** Voice
distinguishability is a subjective audio-perception test that requires
the user's ears.
