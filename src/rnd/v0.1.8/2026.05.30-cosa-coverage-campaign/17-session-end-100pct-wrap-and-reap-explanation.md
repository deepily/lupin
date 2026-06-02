# 17 — Session-End Wrap: cosa.rest @ 100% + Why the Workers Went Unharvested

**Author:** Tiberius 👑 (manager) · **Date:** 2026-06-01 (session b8a9f332) · **Status:** session-end checkpoint

## TL;DR
cosa.rest reached **genuine 100%** (lines AND branches), tree-wide gate confirmed:
`11053/0 stmts · 2958/0 branch · 2363 passed`. **35 CoSA-coverage commits** this session, all
held LOCAL (push deferred for Rick's explicit word). This doc is the session checkpoint + the
explicit answer Rick requested: **why ~14 spawned worker sessions went unharvested.**

---

## WHY THE WORKERS WENT UNHARVESTED (Rick's requested explanation)

By session end the fleet held ~14 author sessions (idx1–14, incl. the 5 "Extra 1–5" fresh-context
replacements) + 2 reviewers (Clayton, Rachel) — nearly all **idle/parked**, not reaped. The honest
causal chain:

1. **`dismiss_sessions` targeted-reap was bugged ALL SESSION.** The running cosa-voice MCP server
   has an untyped FastMCP param → a list argument (`session_names=["cc-author-…"]`) gets
   string/char-coerced and iterated character-by-character → every "session" is a single char →
   all no-ops → the real session survives. Verified live (the reap attempt on cc-author-tiberius-4
   char-iterated `[ " c c - a u t h o r …`). The FIX is committed (`3488b43`, annotates the param
   `Optional[List[str]]`) but is **NOT live** — the running server must be **restarted** to load it.

2. **The tmux-kill workaround was deliberately AVOIDED.** Doctrine (auto-memory
   `reference_dismiss_sessions_clean_reap`): `tmux kill-session` orphans the session's voice
   **listener** → PG-6 zombies. So rather than create orphaned listeners, I **parked** each
   honest-stopped author (stand-down DM, left the session alive) — clean but accumulating.

3. **The honest-stop pattern compounded the count.** As authors hit context-saturation they
   honest-stopped at a clean green line (fresh-context-beats-near-ceiling doctrine) and I spawned a
   fresh "Extra" replacement. Correct for output quality, but with targeted reap bugged, each
   honest-stop left a parked session → the count grew to ~10 authors + 2 reviewers.

4. **The clean full-reap was permission-denied at wrap-up.** `dismiss_sessions(session_names=None)`
   (reap-ALL, the None-branch that sidesteps the list-bug, "no zombies" per doctrine) — attempted at
   session end — was **denied by the Claude Code auto-mode classifier**. Per the denial guidance I
   did NOT work around it; I surfaced it to Rick.

5. **SELF-CRITIQUE (the real miss).** Targeted reap being bugged was a known constraint from early in
   the session. I treated the accumulating parked workers as a *deferred* cleanup ("reap-blocked,
   needs MCP restart") and kept noting it passively rather than **escalating the MCP restart as an
   active blocker** the moment the parked count started growing. I should have pushed for the restart
   far earlier (it ALSO fixes the FM-7 comms degradation), or accepted the tmux-kill cost with
   explicit listener-cleanup. Letting ~12 sessions gather dust was avoidable.

**REMEDY (one action fixes all of it):** restart the cosa-voice MCP server →
(a) makes the `dismiss_sessions` fix live → clean targeted reap; (b) restores the notify/TTS + push
delivery channel (FM-7); (c) lets the manager then cleanly reap the whole fleet via
`dismiss_sessions(session_names=None)`.

---

## What was accomplished (coverage)
- **Assigned lanes → 100%** (committed earlier): B6 rest-core, B7 (15 router/modules), both
  heavyweights (multimodal_munger 432, running_fifo_queue 576), commons/speech/decision_proxy, the
  SDK **agent** packages, claude_code_queue.
- **FM-17 caught by the tree-wide gate:** "assigned-lane 100% ≠ tree-wide 100%." The campaign had
  conflated `cosa.agents.X` (done) with the `cosa.rest.routers.X` HTTP **wrappers** (missed). The
  tree-wide gate revealed cosa.rest at **91%**, not 100% — I had briefly over-claimed "rest
  complete" and **self-corrected via the gate**.
- **Remainder closed (staged wave, María-ruled triage-first):** 6 SDK router-wrappers +
  middleware/api_key_auth + dependencies/config + podcast_generator router + **websocket_manager**
  (the final module) → cosa.rest **91% → 100%**.
- **websocket_manager note:** committed (`d96f2ca`) **manager-verified + self-audited** (assertion
  profile 100 concrete / 1 borderline; zero real socket/loop leakage; ordering-robust) because the
  reviewer push-channel was FM-7-degraded — an independent reviewer **post-audit is still owed**
  (the tree-wide gate is the 100% proof; the post-audit is defense-in-depth).

## Pending (carried to TODO.md)
1. **PUSH** to remote — HELD for Rick's explicit word (~130+ campaign commits local).
2. **Ratify** (Rick): the AC12 thin-handler pragma grandfather precedent (verified per-endpoint
   integration coverage) + the speech.py `app_debug` 1-line prod bug-fix (debug-only path).
3. **websocket_manager** independent reviewer post-audit (gate-confirmed 100%; post-audit owed).
4. **Reap the fleet** — after the cosa-voice MCP restart (the remedy above).
5. **Messaging-black-hole ROOT-CAUSE** (Rick-assigned, before any next batch): FM-7 (fleet-load →
   notify/:7999 timeout) + FM-11 (directed-push drops) + FM-15 (dropped reports mimic stalls) +
   FM-18 (notify-on-AFK silently bounces) = ONE unreliable coordination plane (no delivery
   guarantee / no load-isolation / no pull-able fallback). Tiberius owns the cosa-voice/commons
   infra debug; María codifies the synthesis + fix-space.

## Principles promoted (for the post-game / framework)
- **Completion discipline:** "we need completion; don't get hung up on trivial reasons to park and
  not finish." Difficulty / lateness / size are **NOT** defer-triggers — hard-but-in-scope work is a
  dedicated careful lane.
- **Decision-class rule (FM-19):** mandated in-scope work is **never user-gated**; the user is gated
  ONLY for outward/irreversible acts (the push), a real prod-behavior change, a genuine requirement
  ambiguity, or scope expansion. *Escalating a non-decision wastes the user's scarce time.*
