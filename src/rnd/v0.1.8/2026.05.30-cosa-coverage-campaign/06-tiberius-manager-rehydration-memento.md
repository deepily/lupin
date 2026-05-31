# 06 — Tiberius Manager Rehydration Memento

> **Purpose:** rehydrate the CoSA 100%-Coverage Campaign **manager** (Tiberius 👑) into a
> fresh session and resume exactly where the prior session left off. Read this FIRST,
> then the two author handoffs (`04-mr-radio-lane-handoff.md`, `05-rio-deep-research-handoff.md`)
> and the overnight debrief (`03-overnight-grind-debrief.md`).
>
> Written 2026-05-31 at the natural stand-down point of the agents-tier campaign.

---

## TL;DR — where we are

- **8 agent packages COMPLETE @ genuine 100%, ALL COMMITTED LOCAL (no push):**
  `podcast_generator · bug_fix_expediter · presentation_generator · test_fix_expediter ·
  deep_research · swe_team · shared · claude_code` (+ calculator/memory/repo tiers from earlier runs).
- **67 Krishna gate reviews, all genuine 100%.** 25 pragmas confirmed unreachable.
  **10 real prod bugs found + fixed.** 1 dead-code deletion. 1 coverage-config fix. 0 hollow tests.
- **Working tree is CLEAN.** ~50 commits held local on branch `wip-v0.1.8-...`. **NOTHING PUSHED**
  (Rick's standing hold: "no push until I review at the end of the run").
- **Fleet fully stood down:** all author sessions + Krishna (reviewer) reaped. Only Rick's
  terminals remain. Rehydration = spawn fresh.

## What's LEFT (the resume work-list)

1. **Backlog modules (need fresh author(s)):** `cosa/agents/decision_proxy`,
   `notification_proxy`, `io_models`, `prediction_engine`, and the 2 omit-surfaced prod
   modules `cosa/rest/routers/test_suite.py` + `cosa/rest/test_suite_completion_watchdog.py`.
   **Do a fresh `git ls-files`/grep inventory of ALL uncovered cosa code first** — the campaign
   focused on `agents/`; verify what's left tree-wide (rest/, memory/, config/, utils/, app/, lib/).
2. **2 cosmetic cleanups (manager-owned, low priority):**
   - `cosa/agents/shared/git_strategist.py` `commit_and_pr_multi` — fully implemented but its
     header/§comment/quick_smoke_test still say "STUB → NotImplementedError" (coverage-excluded
     smoke; would fail if run). Refresh the stale doc/smoke.
   - `cosa/agents/deep_research/orchestrator.py` `_generate_abstract_async` (orphaned, zero callers)
     **+ the bigger architectural question: is the whole `ResearchOrchestratorAgent` class unused?**
     (`run_research`/job.py use an inline pipeline, not this class.) **Escalated to Rick — HIS call,
     do NOT unilaterally delete a whole class.**
3. **The push decision is Rick's** — do not push the ~50 held commits without his explicit word.

---

## The manager doctrine (how this campaign is run — internalize all of it)

### Canonical interpreter — NON-NEGOTIABLE
- ALL pytest/coverage runs through the **cosa venv**: `src/cosa/.venv/bin/python` (py3.11.5 / pytest 9.0.2).
  The lupin `.venv` (py3.13 / pytest 8.4.2) **silently masks failures** — never use it.
- **SDK-adjacent packages** (anything importing `claude_agent_sdk` → `mcp.types`, or `scipy`):
  run via **`src/cosa/tests/run-sdk-cov.sh`** — it pre-imports `claude_agent_sdk` (warms pydantic's
  `_GENERIC_TYPES_CACHE` before the cov tracer → dodges `KeyError: 'pydantic.root_model'`) AND
  pre-warms `scipy` (`from scipy.stats import beta; import scipy.optimize` → dodges the
  `scipy.optimize._highspy` lazy-load `ModuleNotFoundError` under the tracer). Both are the same
  tracer-×-lazy-import class. `unset COVERAGE_CORE` does NOT fix either.
- Standard runner (non-SDK): `PYTHONPATH=src src/cosa/.venv/bin/python -m pytest <path> --cov=<dotted.module> --cov-report=term-missing -q -p no:cacheprovider`.

### The defense-in-depth GATE (Krishna 🦚 is the reviewer)
1. Author reports a sub-batch with a **verbatim coverage table** (quoted from disk).
2. **Manager disk-verifies** every number itself (trust ZERO remembered numbers).
3. **Queue Krishna** (`commons_send_to recipient="krishna"`) with the re-measure command;
   he **independently re-measures** + audits for hollow assertions / coloring / bug-ratification / phantoms.
4. **Commit ONLY on Krishna's explicit APPROVE**, at the re-measured numbers. Never route around the gate.
5. For **manager-owned prod fixes**: queue Krishna a prod-fix-**legitimacy** re-review (he checks the
   diff is behavior-correct + the de-arm asserts the corrected contract, NOT green-washing).

### Tripwire pattern (how real bugs are surfaced — this is the campaign's "quiet win": 10 latent bugs hiding behind green suites)
- Author finds a prod bug → **does NOT fix it** → arms an `@unittest.expectedFailure` /
  `@pytest.mark.xfail(strict=True)` asserting the **CORRECT contract** + a **pin test** capturing
  current (buggy) behavior. Module sits at <100% by exactly the bug-blocked lines.
- **NEVER pragma a bug-blocked line** — that masks exactly what the tripwire flags.
- **Manager owns ALL prod fixes + dead-code cleanups.** After the fix: de-arm the xfail (it now
  passes), remove/repoint the obsolete pin, add tests for any now-reachable lines (a bug fix SHIFTS
  coverage — formerly-dead except/cancel arcs become live), re-verify 100%, then gate.

### Pragma discipline
- `# pragma: no cover` / `# pragma: no branch` ONLY on **independently-confirmed-unreachable**
  defensive branches, with a same-line reason. Manager confirms (read the loop invariant / AST-count
  list lengths / trace the guard) BEFORE applying; authors **propose**, manager **batch-applies**.
- Ratified pragma classes: optional-dep `except ImportError` guards (installed dep → False arm dead);
  `async with` trailing-if false-arc (coverage `__aexit__` arc artifact, both outcomes tested → `no branch`);
  defensive dead branches behind a guaranteeing guard.
- **Dead code with zero callers** is DELETED (not pragma'd) — *unless* it's a whole-class/architectural
  question (escalate to Rick). Add a `not hasattr(...)` resurrection-guard test when deleting.

### Surgical git staging — MANDATE
- **NEVER `git add <dir>` or `git add -A`.** Stage **explicit files**, then `git diff --cached --stat`
  BEFORE every commit. (A dir-add once swept an author's WIP test file into a gate commit; a pragma
  edit once duplicated a line — Krishna caught both.) Commit message ends with the Co-Authored-By trailer.

### Fleet management — THE LESSON RICK DROVE HOME (2026-05-31)
- **Dismiss-on-completion, NOT park-indefinitely.** When an author finishes its lane and you decide
  the next lane needs a fresh start, **reap the finished session immediately** — do not keep it idle
  "in case." Keeping 8 idle sessions alive was the mistake Rick flagged.
- **Why spawn fresh vs reuse a finished author:** a session that's written 300+ tests is near its
  context ceiling; starting a fresh 5000-LOC lane in it yields degraded/phantom tests. Fresh context
  genuinely outperforms on a NEW big lane. (This part of the reasoning is sound — the miss was not reaping.)
- **`dismiss_sessions` MCP tool is BUGGED:** it stringifies the `session_names` list arg and iterates
  it character-by-character (also echoes `write_memento` as the string `"false"`) → dismisses nothing.
  **Workaround: `tmux kill-session -t cc-author-tiberius-N`** per session. CAUTION: `tmux has-session`
  does prefix-matching (`-1` matches `-10`); trust `tmux ls`, not `has-session`. **Raw tmux-kill frees
  the process but does NOT update the cosa-voice dashboard** (only `dismiss_sessions` updates the
  lineage manifest) → the dashboard shows stale "alive" entries that aren't real processes; they
  self-prune. Flag this to Rick if he sees a high session count.
- **Cap concurrent authors at ~2** — Krishna is a single reviewer (the bottleneck); more authors just
  queue. One report per turn through the gate is the right cadence.
- **Honest-stop discipline (model it + reward it):** authors stop at clean green lines rather than push
  phantom-risk work at deep context, write a handoff memento, and you spawn fresh. This is GOOD.

### Directed-push cadence
- All author↔manager messages via **`commons_send_to(recipient="<persona>", body=...)`** (reliable tmux push).
  Plain `commons_post`/reply-to-qid only surface on poll. **Directed pushes still occasionally drop**
  (`register_network_error` / transient) — **verify `dm_dispatched:true` and re-send if missing.** Run a
  periodic `commons_who` liveness sweep (Rick's "heartbeat poker") — it caught a 60-min idle author whose
  assignment never pushed, and dropped sub-batch reports.

### Cost safety — INVARIANT
- Tests are **boundary-mocked** (LLM/SDK/web_search/subprocess/git/fs) → **ZERO API spend.** The
  **firewalled `ANTHROPIC_API_KEY_FIREWALLED` is NEVER read** (patch `cu.get_api_key` / `os.environ`
  with `clear=True` / explicit `api_key="test-key"`; mock `AsyncAnthropic` + `messages.create`). Verify
  this on every billed-boundary module (deep_research api_client was the critical one).

### Reusable test patterns (seed every new author)
- `sdk_query` → async-gen stub yielding REAL `TextBlock`/`ToolUseBlock`/`AssistantMessage` +
  `MagicMock(spec=ResultMessage/RateLimitEvent)`.
- The **"neither-type fall-through"** SDK arcs (a block/message that's none of the known types →
  elif-false) are the sneaky orchestrator partials — cover with a bare `MagicMock()`.
- Big orchestrators (1800-2300 LOC): **split `test_<x>_orchestrator_helpers.py` + `_phases.py`**.
- Keep **real Pydantic validation** in the loop where the prod contract enforces it (it catches bad mock shapes).
- Optional-dep `except ImportError` guards: cover GENUINELY via `importlib.reload` under
  `patch.dict(sys.modules, {"<dep>": None})` rather than pragma, when feasible.

---

## The 10 prod bugs (the campaign's real value — all FIXED + Krishna-verified)
1–4. Earlier memory-tier: `to_jsons` `_normalizer` TypeError · `delete_snapshot` return-before-del ·
   `solution_manager_factory` gcs KeyError · `prompt_formatter` swapped `write_string_to_file` args.
5. presentation orchestrator Gate-4 `present_choices` wrong signature → TypeError-swallowed → could never cancel.
6. presentation orchestrator shadowed duplicate `_read_file` → dead `except FileNotFoundError`
   (fixed by rename `_read_file_or_raise` / `_read_file_or_none`).
7. deep_research `BudgetExceededError` bare Exception lacked `current_cost`/`budget_limit` → handler AttributeError.
8. deep_research `cli.py` `logger.error` with no `logger` imported → NameError on theme/topic-select failure.
9. swe_team `_execute_live` success-count over-report: escalation updated `state[...][-1]` but not the
   local `results` list → abandoned task counted as success (`results[-1] = result` fix).
10. claude_code `job.py` `from cosa.app.configuration_manager` (cosa.app doesn't exist) → bare-except-
    swallowed ModuleNotFoundError → operator INI max_turns/timeout silently ignored (`cosa.app`→`cosa.config`).

## How to RESUME (fresh Tiberius checklist)
1. Phase A MCP startup (fetch cosa-voice schemas, `get_session_info` — your persona resolves to
   **Tiberius**; do NOT assume an icon, let `get_session_info` confirm it), then
   `set_session_topic("CoSA coverage — backlog + cleanup")`.
2. Read this memento + `04`/`05` handoffs + `03` debrief. `git log --oneline -30` to see banked packages.
3. Inventory remaining uncovered cosa code tree-wide (not just agents/).
4. Spawn **Krishna** (reviewer) + **1–2 fresh authors** (`spawn_sessions`, role=author). Seed authors with
   the relevant handoff doc via `seed_memento`. Apply ALL doctrine above.
5. **Reap each author the moment its lane is done** (tmux kill workaround until `dismiss_sessions` is fixed).
6. Hold all pushes for Rick. Surface the 2 flagged findings (orphaned class, stale smoke) for his call.

**Rick's voice persona = "Rio" is the assistant, "Rick" is the user.** User is **Rick** (Ricardo). He
listens from a distance via TTS — keep spoken `notify` to headline+takeaway, detail in `abstract`,
doc links only in `abstract`, always pros/cons + a recommendation on decision asks.
