# 25 — Prod-Bug Fixes: dispatcher `self.debug` + `cosa_interface.ask_yes_no`

> **For:** the morning-gate record (2026-06-03). Author: Tiberius 👑 (`1333e106`).
> **Authorized:** Rick, voice, 2026-06-03 — "go ahead and fix the 2 bugs that you've identified" → "document and checkpoint your changes".
> **Supersedes the "NOT fixed — your gate" posture** in doc 22 §3 and doc 23 §3.3. Both bugs are now fixed at source, both tripwire pins de-armed, full-tree green.

---

## TL;DR

The two prod bugs found (but deliberately left pinned) during the overnight coverage marathon are now **fixed at the source**, their tripwire pins **de-armed**, both touched source files **re-certified 100% line+branch+function**, and the **full canonical unit gate is green**: `13,309 passed · 1 xfailed · 0 failed` (3m28s). The cert's 2 xfailed dropped to 1 — Bug B's strict xfail was de-armed; the surviving xfail is the other pre-existing one (untouched). Held uncommitted until Rick's explicit checkpoint word.

---

## Bug A — `ClaudeCodeDispatcher` reads an uninitialized `self.debug`

**File:** `src/cosa/orchestration/claude_code/dispatcher.py`

**Defect:** `_run_interactive`'s `RateLimitEvent` branch (line ~468) reads `self.debug`, but `__init__` never set it → `AttributeError` on any rate-limit during an interactive session. The broad `except Exception` swallowed it, so the interactive session **died** ("object has no attribute 'debug'") instead of logging and continuing.

**Fix (source):** `__init__` now accepts `debug: bool = False` and sets `self.debug = debug` (alongside the other instance attrs, vertically aligned per house style). Default `False` preserves all existing behavior — no caller passes `debug`, so zero behavior change for existing callers; the rate-limit branch now logs (debug on) or no-ops (debug off) cleanly.

**Test de-arm:** `test_run_interactive_rate_limit_event_is_prod_bug` (the AttributeError pin) removed, replaced by:
- `test_run_interactive_rate_limit_event_debug_off_handled_cleanly` — debug off → no raise → clean `"No result received"` (covers the `if self.debug:` False arm).
- `test_run_interactive_rate_limit_event_debug_on_logs` — debug on → emits the debug line (covers the True arm), asserted via `capsys`.

**Coverage:** `dispatcher.py` → 239 stmts / 86 branch / 0 miss = **100%**.

## Bug B — `cosa_interface.ask_yes_no` calls a nonexistent dispatcher method

**File:** `src/cosa/agents/test_suite/cosa_interface.py`

**Defect:** `ask_yes_no` called `_dispatcher.ask_yes_no(...)`, which does not exist on `AgentNotificationDispatcher` (it exposes only `ask_confirmation`, with a different signature) → `AttributeError` on every call. Pinned pre-marathon (2026-06-01, commit `533d273`, Clayton-approved) by a `strict=True` xfail in `test_cosa_interface.py`.

**Fix (source):** `ask_yes_no` now mirrors the module's own `notify_progress` pattern — copies identity (`sender_id` / `session_name` / `target_user`) onto the shared `_dispatcher`, then delegates to the real `ask_confirmation` (→ `bool`) and translates the result into this module's documented `"yes"`/`"no"` string contract. `queue_name` is not forwarded (the confirmation path has no queue routing) — noted inline. No live production caller exists (`test_suite/voice_io.ask_yes_no` binds the core `voice_io` helper, not this one), so the fix is a clean latent-bug repair with no blast radius.

**Test de-arm:** the `strict=True` xfail and the AttributeError pin removed; 4 contract tests added — yes-arm, no-arm, identity-copy + arg-forwarding, and module-`SESSION_NAME` fallback. Unused `import pytest` removed.

**Coverage:** `cosa_interface.py` → 27 stmts / 2 branch / 0 miss = **100%**.

---

## Verification ladder (all green)

| Layer | Result |
|---|---|
| `py_compile` (both sources) | ✅ |
| Targeted suites + branch coverage | ✅ dispatcher 100%, cosa_interface 100% (71 passed) |
| Full canonical unit gate (`src/tests/unit/` + `src/cosa/tests/unit/`) | ✅ **13,309 passed · 1 xfailed · 0 failed** · 201 subtests · 3m28s |

**Coverage-measurement note:** branch coverage was measured package-level (`--cov=cosa`), not module-level (`--cov=cosa.orchestration.claude_code.dispatcher`). A module-level `--cov` target eagerly imports the dispatcher at coverage startup in a bare `sys.modules`, tripping a known `claude_agent_sdk` → `mcp.types` → pydantic-generics `KeyError: 'pydantic.root_model'` artifact. Package-level cov (as the marathon used) avoids it. This is a tooling artifact, not a code defect.

## Files touched (this checkpoint)

| File | Kind | Change |
|---|---|---|
| `src/cosa/orchestration/claude_code/dispatcher.py` | source | Bug A: `__init__` initializes `self.debug` |
| `src/cosa/agents/test_suite/cosa_interface.py` | source | Bug B: `ask_yes_no` → `ask_confirmation` delegation |
| `src/cosa/tests/unit/orchestration/claude_code/test_dispatcher.py` | test | de-arm pin → 2 debug-arm tests |
| `src/cosa/tests/unit/agents/test_suite/test_cosa_interface.py` | test | remove xfail + pin → 4 contract tests |
| `src/rnd/.../22-overnight-grind-findings.md` | doc | mark Bug A resolved |
| `src/rnd/.../23-overnight-grind-certified-complete.md` | doc | mark both bugs resolved |
| `src/rnd/.../25-…ask-yes-no.md` | doc | this fix record |

Parallel-session safety: staged **only** these files — never session `7bca7a96`'s in-flight notification-reset work.
