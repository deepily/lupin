# 26 — Lupin-Side Post-Game Companion (CoSA all-tiers coverage marathon)

> **Author:** Tiberius 👑 (`1333e106`), 2026-06-03. **Authorized:** Rick's post-game walkthrough (9 decisions ratified).
> **Pairs with (hub):** María's PIP framework synthesis — `planning-is-prompting/src/rnd/2026.06.03-all-tiers-grind-postgame.md` (§3.6 ratified decisions + summary table). This doc is the **Lupin-infra lens**; María's is the **framework/process lens**. Cross-linked both ways (hub-spoke, doc-18 pattern).
> **Scope:** what the marathon taught us about *Lupin's infrastructure* — the server/MCP coupling, the two prod bugs, the hermeticity machinery, and the coverage-tooling traps. Process/coordination lessons live in the hub.

---

## TL;DR

The CoSA tree reached certified **100% line+branch+function** (412 files, 38,447 stmts/0 miss, 11,172 branches/0 partial; gate 13,300→13,309 passed / 0 failed) on a 5-author disjoint-lane fleet. This companion records the Lupin-infrastructure root causes behind the campaign's friction and the two prod bugs it surfaced — so the next campaign hits them as known terrain, not surprises.

---

## 1. The two prod bugs — root cause + fix (now closed)

Both were **missing-attribute crashes** hiding behind tripwire pins; both are now fixed at source, de-armed, and committed (`71d0645`). Full record: doc 25.

| Bug | Root cause | Why it hid | Fix |
|---|---|---|---|
| **A — `dispatcher.py` `self.debug`** | `_run_interactive`'s RateLimitEvent branch read `self.debug`; `__init__` never set it → AttributeError, swallowed by a broad `except` → interactive session silently died | Only fires on a rate-limit *during an interactive session* — a rare, hard-to-reach path; no test exercised it pre-campaign | `__init__` takes `debug=False`, sets `self.debug`; 2 tests cover both arms |
| **B — `cosa_interface.ask_yes_no`** | Called `_dispatcher.ask_yes_no`, which never existed (dispatcher exposes only `ask_confirmation`) → AttributeError on every call | No live caller (`test_suite/voice_io.ask_yes_no` binds the *core* helper), so it never ran in prod | Delegate to real `ask_confirmation` (→ bool), return `"yes"/"no"`; strict xfail + pin removed, 4 contract tests |

**Lupin-infra lesson:** both bugs lived on **rarely-exercised side paths** of the Claude-Code/MCP dispatch surface. 100% coverage is exactly the gate that forces these paths to be *named* — the tripwire-pin doctrine (assert the buggy behavior so coverage is honest without masking) let the campaign reach 100% *and* hand Rick an accurate bug ledger instead of silently papering over them.

## 2. `:7999` / MCP coupling + saturation (P1 coordination — keep-alive gap)

The campaign's #1 operational fault was **keep-alive**: with Rick asleep, no clean `owner_id` resolver existed, so the heartbeat-poker couldn't self-launch; María held the fleet warm with a manual ~10-min push-DM cadence. This is a Lupin-infra gap, not a process gap:

- **Root cause:** the poker needs an `owner_user_id` to attribute its self-poke job, and there is no resolver that works without an interactive user session. Neither manager would confabulate one or submit a CJ-Flow job as Rick.
- **Ratified direction (PG-D1/D2):** P0 = heartbeat-poker, but its **design is a separate dedicated conversation** (don't build blind); **`owner_id` pre-resolution is in scope** for that design.
- **Coordination-plane (PG-D3):** the empty-broadcast bug is now known **intermittent → race** (not a flat failure); prioritize it. Durable-AFK-inbox (lever D) **landed** (`722e624` Phase-1 outbox + lever-D inbox, `8447eec` age-cap drain). The async-`:7999`-handlers half is **unconfirmed from recent log markers** — needs the originating session's commit reference before we call it landed (verify-before-catalog).

## 3. Hermeticity machinery — FM-21 (and candidate FM-22)

- **FM-21 (cross-test config/registry pollution):** module-attribute monkeypatches were defeated under full-tree load because function-local `from cosa.config.configuration_manager import ConfigurationManager` re-resolved the real `@singleton`. Fixed per-polluter at-source during the grind. The **systemic kill** is a global hermetic-config autouse fixture (`cache_registry.invalidate_all` + `ConfigurationManager(_reset_singleton=True)` in a new `src/cosa/tests/conftest.py`).
  - **Ratified (PG-D4):** **Rachel** is authorized to design + isolation-verify it; land **only** on a clean full-suite gate (isolation-green AND full-tree-green, staged revert otherwise). Blast-radius guard intact.
- **Candidate FM-22 (`io_files` order/loop-state nondeterminism):** a one-time non-reproducing collection-order artifact (gate4 1-fail self-healed via intervening peer commits; 3/3 fresh-hashseed green after). **Monitor only** — real-fix recipe in doc 90; name FM-22 held until a recurrence *with* a captured `--tb=long`.

## 4. Coverage-tooling trap (new, Lupin-infra-specific)

**Module-level `--cov` targets break on the MCP import chain.** Running `--cov=cosa.orchestration.claude_code.dispatcher` (a *specific module*) eagerly imports the dispatcher at coverage startup in a bare `sys.modules`, tripping `claude_agent_sdk → mcp.types → pydantic-generics` → `KeyError: 'pydantic.root_model'` at **collection time**. Package-level `--cov=cosa` (what the marathon used) avoids it — the package import is lazy and the full suite establishes pydantic state before any module-level generic is built.

**Rule for the next campaign:** measure coverage with **`--cov=cosa`** (package), never `--cov=<dotted.module.path>`, on any tree that imports `claude_agent_sdk`/`mcp`. This is a tooling artifact, not a code defect — but it will silently abort an isolated coverage run and look like a test failure.

## 5. What worked (keep — Lupin-infra lens)

- **Disjoint-lane partition** → collision-free parallel commits across 5 authors.
- **Green-before-commit + per-batch adversarial reviewer-gate** (Krishna 8/8, 0 hollow) → no flaky/red tree ever committed into.
- **Harvest-not-reauthor** (io_models: 215 existing tests relocated via `git mv` into canonical roots → 100% with **zero new test lines**).
- **Tripwire-pin doctrine** → honest 100% that *surfaces* prod bugs instead of masking them (the two bugs above are the proof).
- **Package-level coverage measurement** → sidesteps the §4 MCP/pydantic artifact.

## 6. Failure modes → improvements (Lupin-infra lens)

| Failure mode | Improvement |
|---|---|
| **Stale planning baselines** (projected ~12k miss, real ~2.3k) | Fresh tree-wide `--cov=cosa` gap-map as **Step 0** before any spawn |
| **FM-21 cross-test pollution** (config/registry `sys.modules` bleed; isolation-green/full-red) | Global hermetic-config autouse fixture + standing isolation-AND-full-tree gate (PG-D4, Rachel) |
| **Module-level `--cov` MCP/pydantic KeyError** (§4) | Mandate package-level `--cov=cosa` on any `claude_agent_sdk`-importing tree |
| **Keep-alive gap** (no `owner_id` resolver while Rick slept) | Fix the `owner_id` resolver / ship the per-instance poker (P0 design deep-dive, PG-D2) |
| **Two prod bugs on rare dispatch side-paths** | Already fixed (doc 25); the lesson is that 100%-with-tripwire-pins is what found them |
| **A red 100% gate may not be YOUR change — bisect before theorizing** | Deleting 4 "redundant" shallow legacy agent test files left the tree at 99% (1 stmt short), caught by `--cov-fail-under=100`. I first theorized "stray cross-tree incidental coverage" from a shallow agent test — **WRONG**. `--cov-report=term-missing` (untruncated) + `git blame` on the actual missing line (`notifications.py:1291`) proved it was an untested `except HTTPException: raise` in a *different* author's commit (`c0db33d`, a new dismiss endpoint), unrelated to the harvest. The agent harvest was coverage-SAFE. **Lesson:** when a full-tree gate goes red after your change, find the EXACT missing line (`--cov-report=term-missing`) and `git blame` it BEFORE attributing cause — in a multi-author fleet the red is often a peer's pre-existing gap, not your edit. Verify-before-catalog applies to coverage diagnosis too. |

## 7. Cross-links

- **Hub (framework/process synthesis):** `planning-is-prompting/src/rnd/2026.06.03-all-tiers-grind-postgame.md`
- **Certification record:** doc 23 (this dir) · **Findings/bug ledger:** doc 22 · **Bug-fix record:** doc 25 · **io_files watch-note:** doc 90
- **Bugs fixed in:** commit `71d0645` (LOCAL).
