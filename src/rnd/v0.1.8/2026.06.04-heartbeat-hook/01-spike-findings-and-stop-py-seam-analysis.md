# Heartbeat Hook — Step 1 Spike Findings + `stop.py` Seam Analysis

**Author:** Tiffany 💍 (Lupin session `d1554246`, heartbeat-hook implementer)
**For:** María 🌸 (design owner) · Rachel 🕊️ (shared `Stop`/`PostToolUse` substrate) · Tiberius 👑 (manager)
**Date:** 2026-06-04
**Status:** Findings note — **NO code written.** Gates the 3-way seam conversation before any `stop.py` edit.
**Canonical design:** `planning-is-prompting/src/rnd/2026.06.02-stop-hook-natural-heartbeat-poker.md` §0 Ratified Design v1 (LOCKED).

---

## TL;DR

1. **Loop-guard is real and documented** — `stop_hook_active` is the field. CC sets it `true` on the re-prompt after a `{"decision":"block"}`. Confirmed two independent ways (claude-code-guide docs + Lupin's shipping `stop.py`). **§0 decision #6 settles: our per-session poke-cap is a BACKSTOP, not the sole guard.**
2. **This is NOT greenfield.** The heartbeat hook is an **extension of the existing `src/lupin_cli/claude_code/hooks/stop.py`** — the same production hook Rachel's token-rate instrumentation (TODO line 11) will extend. Per María: **do not modify `stop.py`'s decision flow until Rachel is looped in on the seam.**
3. **Clean seam exists.** `stop.py`'s no-voice branch (the genuine quiescence boundary) is exactly where the heartbeat-hold read + work-owed check + poke slot in — additively, behind its own per-session counter, without disturbing the voice-driven block path or the idle-waiter path.
4. **One doc discrepancy to flag:** claude-code-guide claimed a Stop-hook `reason` is "shown to the user, not fed to Claude." **Production evidence contradicts this** — `reason` IS acted on by Claude. The heartbeat poke depends on that, and §0 #5 assumes it. Resolved in favor of production evidence (details in §A.3).

---

## ⚠️ ERRATA — claude-code-guide doc correction (binding for the next implementer)

**The heartbeat poke text MUST ride the top-level `reason` field, NEVER `systemMessage`.**

- claude-code-guide (2026-06-04) stated the Stop-hook `reason` is *"shown to the user, not fed to Claude as an instruction."* **This is wrong.** Lupin production proves `reason` IS re-injected as continuation context Claude acts on (`stop.py` module docstring lines 4–7; `_ask_anything_else` returns `build_stop_block("…Ask them what they'd like done next.")` as an instruction — `stop.py:401,407`). Anthropic's own Stop-hook contract + canonical design §0 #5 agree.
- Conversely, **`systemMessage` is silently ignored by CC Stop hooks** (`hook_common.py:549`, DEPRECATED note) — which is precisely why the qualifier path falls back to tmux. Do **not** route the poke through `systemMessage`.
- **Folded into canonical PIP design §0.1 by María (2026-06-04); captured here Lupin-side so a future re-read of the doc-guide answer can't re-introduce the error.**

---

## (a) Loop-guard confirmation — §0 decision #6 settled

### A.1 — Documented semantics (claude-code-guide)

- `Stop` hook stdin includes **`stop_hook_active`** (boolean).
  - `false` → loop-guard pre-check pass; be conservative, allow the stop.
  - `true` → the hook is being re-invoked **because a previous Stop-hook block forced a continuation** and the instance stopped again. This is the re-entry signal.
- Returning `{"decision":"block","reason":"…"}` (exit 0) **cancels the stop and forces another agentic loop iteration.**
- Output must be **pure JSON** on stdout (stray text breaks parsing). `{"continue": true}` allows the stop; `{"continue": false}` halts CC entirely (takes precedence over `decision:block`).
- Documented default timeout is **600 s**; our design mandates a short (~5 s) bound instead.

### A.2 — Empirical confirmation (production `stop.py`)

The shipping hook already **depends** on this behavior — strongest possible evidence:

| Evidence | File:line | What it proves |
|---|---|---|
| Reads the field | `stop.py:658` — `stop_hook_active = payload.get( "stop_hook_active", "NOT_PRESENT" )` | The field is present in real CC Stop-hook input |
| Loop-prevention early-return | `stop.py:687-691` — `if stop_hook_active is True: emit_json({}); sys.exit(0)` | On re-fire, the hook refuses to block again → proves CC sets `True` on re-prompt |
| Backstop ceiling | `hook_common.py:44` — `MAX_STOP_BLOCKS = 3` | A per-session count cap already coexists with the field guard (belt + suspenders) |
| Per-session counter | `hook_common.py:695/721/750` — `get/increment/reset_stop_block_count(session_id)` | Counter is keyed by `session_id`, file-backed |

**Conclusion:** CC's `stop_hook_active` loop guard is real. The heartbeat poke-cap (default 3) is a **backstop** layered on top of it — exactly as §0 #6 anticipated. We are not the sole guard, but we still own a cap by construction (no storm vector; cf. Sam TTS-storm postmortem).

### A.3 — Discrepancy to flag (reason → Claude)

claude-code-guide asserted the Stop-hook `reason` is *"shown to the user, not fed to Claude as an instruction."* **Production contradicts this:**

- `stop.py` module docstring (lines 4–7): *"blocks the stop and injects the voice content as the reason — **Claude processes the user's voice input** instead of stopping."*
- `_ask_anything_else` returns `build_stop_block( "The user wants to continue working. Ask them what they'd like done next." )` (`stop.py:401,407`) — clearly an **instruction Claude acts on**, not a user-facing string.

**Resolution:** treat *"`reason` is re-injected as continuation context Claude acts on"* as correct (matches §0 decision #5). This matters: the heartbeat poke text (*"Stopped with work owed and no fresh hold… Resume, or declare a hold."*) **must** reach Claude to function, and it rides `reason`. **NOT** `systemMessage` — which `hook_common.py:549` documents as **silently ignored by CC Stop hooks** (that's why the qualifier path falls back to tmux). Heartbeat must use the top-level `reason`.

---

## (b) What `stop.py` does today — current decision structure

Entry: `main()` (`stop.py:650`). Linear decision flow:

```
1. read_hook_input() → payload; empty ⇒ emit_json({}), exit          (650-655)
2. stop_hook_active = payload.get("stop_hook_active", ...)            (658)
3. log_payload(...)                                                   (661)
4. session_id = resolve_stable_session_id(...) or fallback            (664)

5. BRANCH A — speakerphone ON  (get_speakerphone(session_id))         (671-685)
   → _try_auto_narrate(...); log speakerphone_skip; emit_json({}); exit
   ⚠ STOP IS ALWAYS ALLOWED IN SPEAKERPHONE MODE — block path never reached.

6. LOOP GUARD — if stop_hook_active is True: emit_json({}); exit      (687-691)
   ⚠ On re-fire, NEVER block again.

7. messages = drain_and_acknowledge(session_id); voice_ctx = ...      (694-695)

8. BRANCH B — voice_ctx present (voice-driven block)                  (697-707)
   count >= MAX_STOP_BLOCKS → reset + allow stop ({})
   else → increment + emit_json(build_stop_block(enrich_voice_context(voice_ctx)))
   ⚠ THE ONLY existing block-decision path.

9. BRANCH C — no voice_ctx (genuine quiescence, no user voice)        (708-737)
   reset_stop_block_count(session_id)
   load_idle_settings()
   if enabled → _arm_idle_waiter(...) + allow stop ({})   ← default
   else       → _ask_anything_else(...) → emit result
```

**Key structural facts:**
- Exactly **one** existing block path (Branch B, voice-driven). Everything else allows the stop.
- The block path is **already loop-guarded** (step 6) and **already capped** (MAX_STOP_BLOCKS=3, per-session file counter).
- `build_stop_block(reason)` → `{"decision":"block","reason":reason}` (top-level; `hook_common.py:522-542`).
- Branch A (speakerphone) early-exits **before** the loop guard and **before** any block path — a heartbeat poke would never fire for a speakerphone session unless the work-owed check is hoisted above Branch A (this is §0/Rachel Q3, a seam decision — see §C).

---

## (c) Where heartbeat slots in — additively, without disturbing existing behavior

### C.1 — The natural insertion point: Branch C (no-voice quiescence)

Branch C **is** the heartbeat's target boundary: the instance went quiet, there is **no user voice** to honor, and CC is about to allow the stop. This is precisely "quiescent with possible work owed."

Proposed additive shape (NOT yet code — for the 3-way seam review):

```
BRANCH C — no voice_ctx:
   reset_stop_block_count(session_id)          # unchanged (voice counter)

   # ── NEW: heartbeat decision (declared-hold-only discriminator) ──
   hold = read_heartbeat_hold(session_id)      # .heartbeat-hold-<session_id>.json
   if hold present AND fresh (now-held_at < ttl_seconds) AND reason non-empty:
       → honor hold → fall through to existing allow-stop behavior
   elif work_owed(session_id, payload):        # hold.work_owed, else TODO/Pending scan
       if heartbeat_poke_count(session_id) < HEARTBEAT_POKE_CAP:   # SEPARATE counter
           increment_heartbeat_poke_count(session_id)
           emit_json(build_stop_block("Stopped with work owed and no fresh hold: <specifics>. Resume, or declare a hold."))
           return
       else:  # at cap
           reset_heartbeat_poke_count(session_id)
           notify("max auto-nudges reached, awaiting user")
           → fall through to allow-stop
   # else: nothing owed → fall through to existing allow-stop behavior

   # ── existing idle-waiter / anything-else logic runs only when we did NOT poke ──
   load_idle_settings(); if enabled → _arm_idle_waiter else _ask_anything_else
```

### C.2 — Non-disturbance guarantees

| Existing behavior | How heartbeat avoids disturbing it |
|---|---|
| Voice-driven block (Branch B) | Heartbeat lives in Branch C — only reached when `voice_ctx` is empty. Voice always wins. |
| Loop guard (step 6) | Heartbeat is **downstream** of the `stop_hook_active is True` early-return → never pokes on a re-fire. |
| Voice block counter (`MAX_STOP_BLOCKS`) | Heartbeat uses a **separate** per-session counter (`HEARTBEAT_POKE_CAP`, default 3) + a distinct counter file → no cross-contamination of caps. |
| Idle-waiter / "Anything else?" | Heartbeat poke `return`s before them; if we **don't** poke (hold honored / nothing owed / at cap), the existing path runs unchanged. |
| Speakerphone skip (Branch A) | Untouched by default → grind workers run non-speakerphone (§0/Rachel Q3 option 1). Hoisting the work-owed check above Branch A is the *alternative* and is a **seam decision**, not a default. |

### C.3 — Open seam questions for the 3-way (Tiffany / María / Rachel)

1. **Shared-substrate factoring.** Rachel's token-rate work also extends `stop.py`/`PostToolUse`. Do we (a) extract a small substrate (read payload → derive session state → dispatch to {harvest-rate, heartbeat}) and refactor `stop.py` to call it, or (b) add the heartbeat block inline in Branch C and let Rachel hang harvest off `PostToolUse` separately? This is the **central design conversation** before any edit.
2. **Speakerphone posture.** Default to non-speakerphone grind workers (no change to Branch A), or hoist the work-owed check above the Branch A early-exit so speakerphone workers also self-poke? (§0/Rachel Q3.)
3. **Counter sharing vs separation.** Confirm heartbeat uses its **own** counter file (recommended) rather than reusing the voice `stop_block_count`.
4. **Work-owed oracle (§0 #3).** First implementation = declared-hold-reason + TODO `in_progress`/unstarted scan. Which TODO is authoritative for a given session, and how is "owned by me" determined? (Cheap, race-free, per §0 #7.)
5. **Idempotency / dedup** across two close Stop fires (mirror `last_autonarrated_turn_id` pattern, `stop.py:608-616`).
6. **TTL value** for the hold artifact (§0 leaves exact value as a build knob; design example uses 900 s).

---

## Artifacts referenced (all read this session — verified)

- `planning-is-prompting/src/rnd/2026.06.02-stop-hook-natural-heartbeat-poker.md` — canonical design (§0 locked)
- `src/lupin_cli/claude_code/hooks/stop.py` — production Stop hook (decision flow, loop guard)
- `src/lupin_cli/claude_code/hooks/lib/hook_common.py:44,522,695,721,750` — `MAX_STOP_BLOCKS`, `build_stop_block`, per-session counter helpers
- claude-code-guide reference answer (documented Stop-hook semantics) — 2026-06-04

## Next step

**3-way seam conversation (Tiffany + María + Rachel)** on §C.3 Q1–Q2 **before** any `stop.py` edit. No `settings.json` wiring, no `stop.py` decision-flow change until that lands. Then: hold-artifact read/write module (standalone, fully testable, 100% cov) can proceed in parallel since it does **not** touch `stop.py`.
