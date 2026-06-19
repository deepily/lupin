# Thread A — Stop-hook idle behavior (3-way enum) — Implementation Log (Clayton 😎)

**Status:** ✅ GREEN at implementer tier, **REVIEW-READY** (Tiberius, 2026-06-06). Built in an isolated worktree; **live `stop.py` byte-untouched**; delivered as an apply-clean patch. **NO commits** (commit on Rick's word).
**Author:** Clayton 😎 (Implementer). **Manager:** Tiberius 👑 · **Reviewer:** Krishna 🦚 (re-engaging) · **Tester:** Mr-Radio 🦉.
**Provenance:** Rick-ratified 3-way toggle (design change mid-build). Context: `2026.06.06-heartbeat-poke-scaffold-vs-v2.1-supersession.md`.

---

## Deliverables
1. **3-way enum flag** `stop hook idle behavior` = `none | ask | idle_announce` (DEFAULT `idle_announce`), in `lupin-app.ini [Lupin: Baseline]` + a matching `lupin-app-splainer.ini` entry (project config mandate). Read via `_stop_hook_idle_behavior()`.
2. **Drop the superseded poke scaffold**: removed `_send_poke_report` + the full per-outcome `_heartbeat_state_sentence` + the commented PAUSED block. KEPT: heartbeat poke, oracle log, genuine-idle beacon, `emit_outcome`. (The per-Stop /api/notify PUSH was the FM-7 multiplier; v2.1 direct-state PULL supersedes it.)
3. **Restore the speakerphone short-circuit** to clean pre-experiment behavior (chorus/conversation sessions skip Branch-C entirely — auto-narrate only — never idle-announce). Greened `test_speakerphone_on_skips_everything`. Zero dangling commented experiment remnants.

## Key design points (for the reviewer)
- **`_stop_hook_idle_behavior()`** reads `ConfigurationManager(env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS", silent=True, mute_splainer=True).get("stop hook idle behavior", default="idle_announce")` **wrapped in `contextlib.redirect_stdout`** — the CfgMgr banners print to **stdout, which is the Stop hook's JSON protocol channel**; the redirect prevents protocol corruption. Fail-safe: returns `idle_announce` on any error / unrecognized value / None; **never raises; never writes stdout**. Stop fires per-TURN (not per-tool) so the CfgMgr parse cost is acceptable (precedent: UserPromptSubmit loads it every turn).
- **Branch-C gate** (after `_run_heartbeat` returns None):
  - `ask` → legacy verbatim: `load_idle_settings()` → `_arm_idle_waiter` (idle_detection enabled) or `_ask_anything_else` (immediate). Includes the restored `except ValueError` fail-safe.
  - `idle_announce` (DEFAULT) → `get_voice_persona` → `_announce_idle(session_id, persona_name)` (ONE low-pri failsafe `AsyncNotificationRequest`, "I'm {persona}. Idle — nothing owed.", sender_id = persona) → `emit_json({})`.
  - `none` → silent `emit_json({})`.
- **`_announce_idle`** is a SINGLE low-pri fire-and-forget notify (NOT the dropped per-outcome spam); try/except, never blocks the Stop. `_idle_sentence` is the tiny seed kept from the dropped scaffold's NOT_OWED case.

## Tests — 177 PASS (:7999 tier; not gated by the :8000 auth matrix)
| Area | Result |
|---|---|
| Reds greened (TestNotifyUserSync ×9, test_notification_mode_runs_normal_flow, test_no_poke_falls_through_to_idle, test_drain_before_ask, test_no_voice_calls_ask_anything_else, test_speakerphone_on_skips_everything) | PASS |
| NEW `test_stop_hook_idle_behavior.py`: config reader matrix (each value / invalid→default / None→default / CfgMgr-error→default / case+whitespace), `_idle_sentence` (persona/none), `_announce_idle` (success + failsafe), gate branches (none / idle_announce / idle_announce-missing-persona / ask-invalid-settings) | PASS |
| Full stop + heartbeat + session-bridge-idle suites | 177 PASS |

**Coverage:** **100% on touched code** — the new helpers (`stop.py` 231-308) + the Branch-C gate (1063-1090), verified no missing lines in those ranges. File-level `stop.py` is 60%; the other 122 missing lines are **PRE-EXISTING** untested functions (`_ask_anything_else` / `_run_heartbeat` / `_arm_idle_waiter` / `_try_auto_narrate` / `_emit_genuine_idle` — subprocess/LLM-calling, ~58% before this work). Per Tiberius's ruling (option a) this is a SEPARATE coverage-campaign item, not Thread A's charter (mirrors the toolhook lane: cover touched + justified pragma).

## Deliverable
`clayton-threadA-idle-behavior.patch` — 6 files (stop.py + lupin-app.ini + splainer + 2 edited test files + 1 new test file), 645 lines, **base = live working tree** (stop.py's experiment is uncommitted; the patch lands experiment-keepers + resolution as one coherent commit), `git apply --check` CLEAN. Worktree `/tmp/clayton-threadA-wt` kept as reference.

## Handoffs
- Krishna 🦚: verify touched-code 100%, that the 122 missing lines are genuinely pre-existing, 3-way gate semantics, the config fail-safe + stdout-redirect, zero scaffold remnants.
- Mr-Radio 🦉: :7999 unit/integration tier (Thread A is :7999 — not blocked by the :8000 auth-matrix gate).
- Pre-existing `stop.py` coverage debt → tracked follow-up (Tiberius queuing).
