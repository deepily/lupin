# Rio ⚡ — deep_research Coverage Handoff (SDK/network tier)

**Author:** Rio ⚡ (session 7973faae) · **Date:** 2026-05-31 · **For:** the fresh author taking the deep_research SDK/network tier
**Manager:** Tiberius 👑 · **Reviewer/Gate:** Krishna 🦚 · cosa venv ONLY (`src/cosa/.venv`, py3.11/pytest 9.0.2)

This seeds whoever picks up the remaining `cosa/agents/deep_research/` modules. The pure-logic + prompt
tiers are DONE; what's left is the SDK/network-bound tier, which needs careful boundary-mocking and the
`run-sdk-cov.sh` runner. Read this, then go straight to the module list in §2.

---

## 1. DONE (10/~21 modules) — do NOT re-touch

All test-only, cosa venv, boundary-mocked (no real network/model/file I/O), discriminating assertions.

| Module | Stmts/Miss/Br/BrPart | Cover | Notes |
|---|---|---|---|
| `config.py` | 53/1/10/1 | 97% = 100% reachable | 1 pragma: `:160` float-coercion arm (no float field; fixed key_map) |
| `state.py` | 84/0/0/0 | 100% | Pydantic models + validation-bound rejections |
| `search_cache.py` | 90/0/24/0 | 100% | tempfile-isolated FS; corrupt-JSON + IOError + non-.json-skip arms |
| `cost_tracker.py` | 107/0/28/0 | 100% | pricing tiers, budget enforcement, aggregation |
| `rate_limiter.py` | 105/4/36/3 | 95% = 100% reachable | 3 pragmas applied (`:225`, `:302`, `:316-318`) — see §3 |
| `voice_io.py` | 19/0/0/0 | 100% | thin re-export wrapper; `reconfigure()` + identity checks |
| `prompts/clarification.py` | 21/0/8/0 | 100% | builder + JSON-fence parser |
| `prompts/planning.py` | 36/0/10/0 | 100% | audience matrix + theme clustering |
| `prompts/subagent.py` | 28/0/10/0 | 100% | audience matrix + `get_system_prompt_with_params` |
| `prompts/synthesis.py` | 39/0/18/0 | 100% | per-finding optional-field arcs |
| `prompts/__init__.py` | 5/0/0/0 | 100% | re-exports (covered on import) |

**Commit refs:** pure-logic batch (config/state/search_cache/cost_tracker/rate_limiter/voice_io) = `3e293eb`.
Prompt-tier batch (clarification + planning/subagent/synthesis/__init__) = **pending Krishna Gate D** at handoff time
(reported sub-batches 3 & 4). Test files live under `src/cosa/tests/unit/agents/deep_research/`.

**3 prod bugs I surfaced (memory lane, all fixed by Tiberius):** #5 `file_based get_snapshot_by_id` undefined
`self.solution_snapshots`; #8 `FileBasedSolutionManager` uninstantiable (missing `save_snapshot` abstractmethod).
No prod bugs found in the deep_research pure-logic/prompt tier.

---

## 2. REMAINING SDK/network tier (~5,209 LOC) — your work

Suggested order: easy/pure first (`nodes`, `tools`, `narrowing_mocks`), then SDK (`__init__`, `cosa_interface`,
`api_client`), then the big orchestration (`job`, `orchestrator`, `narrowing_harness`), then `cli` (huge, argparse).

| Module | LOC | Boundary-mock surface |
|---|---|---|
| `tools/__init__.py` | 17 | trivial re-exports — likely covered on import |
| `nodes/__init__.py` | 41 | re-exports / small — check for logic |
| `narrowing_mocks.py` | 455 | mock LLM client (deterministic responses); `asyncio.run` in smoke only. Mostly pure — good early win |
| `__init__.py` | 210 | reads `ANTHROPIC_API_KEY_FIREWALLED` env (`ENV_VAR_NAME`); patch `os.environ` / the env read. NEVER set bare `ANTHROPIC_API_KEY` |
| `cosa_interface.py` | 378 | per-task dispatch context (contextvars/asyncio task-local); voice_io dispatch. Patch the dispatcher boundary; no real notify |
| `api_client.py` | 707 | `from anthropic import AsyncAnthropic` (guarded: `AsyncAnthropic=None` if import fails). Patch `AsyncAnthropic` + `ANTHROPIC_API_KEY_FIREWALLED`. Mock the async client + `.messages.create`. **NEVER touch the firewalled key / spend** |
| `orchestrator.py` | 894 | `asyncio.gather` of subagent tasks; `web_search` tool dispatch. Mock api_client + rate_limiter + cost_tracker; use `IsolatedAsyncioTestCase` + AsyncMock |
| `job.py` | 559 | `AgenticJobBase` subclass; bridges async `_execute()` via `asyncio.run`. Mock the orchestrator + voice_io; stub `asyncio.sleep` |
| `narrowing_harness.py` | 696 | `argparse` CLI + `asyncio` run loop. Drive `parse_args` with explicit argv lists; mock the narrowing client |
| `cli.py` | 1252 | `argparse` + `import anthropic`. Biggest single file — pace yourself; test each subcommand's arg parsing + dispatch with the client mocked |

### MANDATORY runner for the SDK-chain modules
`api_client`, `orchestrator`, `job`, `cli`, `__init__`, `cosa_interface` import-chain into `claude_agent_sdk` →
`mcp.types`, which trips a **KeyError under the bare coverage tracer**. Use the committed runner:

```bash
src/cosa/tests/run-sdk-cov.sh <test_path> --cov=<module.dotted.path> --cov-report=term-missing
```

It pre-imports `claude_agent_sdk` BEFORE the cov tracer starts. (Modules that import cleanly under plain
`pytest --cov`: `voice_io`, all `prompts/*`, `state`, `config`, `search_cache`, `cost_tracker`, `rate_limiter` —
confirmed this session. The SDK chain only bites the network tier.)

### Cost-safety invariant (CLAUDE.md § COST MODEL)
Deep Research rides the **firewalled SDK path** (`AsyncAnthropic(api_key=ANTHROPIC_API_KEY_FIREWALLED)`) — billed
per token. Tests MUST mock `AsyncAnthropic` at the boundary so ZERO real calls fire. Never read/set the real key.

---

## 3. Reusable patterns from the done tier

**(a) Unreachable defensive-fallback pragma (loop-invariant).** `rate_limiter` had 3 "shouldn't reach here"
guards that are provably dead because *window tokens are the SUM of records*:
- `:302` `return 0` — over-limit implies non-empty records (empty ⇒ sum 0 < limit ⇒ returned earlier).
- `:316-318` post-loop fallback — `tokens_to_remove ∈ [1, window]`; cumulative reaches window ⇒ loop returns first.
- `:225` (get_estimated) — in the `target>0` branch, cumulative reaches current ⇒ `0 ≤ target` on the last record.

Pattern: cover EVERY reachable arc, then propose `# pragma: no cover  # <invariant reason>` to Tiberius with the
proof; he confirms unreachability (Krishna re-confirms) + applies. NEVER set phantom state to "color" dead lines.

**(b) Audience-guideline branch matrix.** `planning/subagent/synthesis` each have a 4-key dict
(`beginner/general/expert/academic`) consumed via `DICT.get(audience, DICT["academic"])`. To 100% it:
loop `for audience, marker in [...]` with `subTest`, asserting the injected marker text, PLUS one
`audience="nonsense"` case for the `.get` fallback arm. Also cover `audience_context` present/absent and (planning)
the clarified-query-vs-original branches.

**(c) Markdown-fence JSON parser arms.** Every `parse_*_response` strips ` ```json `→` ``` `→ trailing ` ``` `.
Cover all four: plain JSON, ```json-fenced, **bare**-```-fenced (distinct arm), trailing-fence-only, + malformed→ValueError.

**(d) Watch for `**bold**` markdown in asserts.** Several builders emit `**Additional Audience Context**:` /
`**Research Approach**:`. Assert the label and the value SEPARATELY, not a `"Label: value"` substring (the `**`
before the colon breaks naive matches). Cost me two red tests — don't repeat it.

**(e) Cadence/process.** Report each sub-batch to Tiberius via `commons_send_to(recipient="tiberius")` **directed
push** (plain `commons_post`/reply-to-qid does NOT reliably reach him). No git add/commit/push — Tiberius stages
on Krishna's APPROVE. `quick_smoke_test` + `if __name__` are coverage-excluded via `exclude_also` (pyproject) — don't test them.

---

## 4. One-line resume
Start at `narrowing_mocks.py` (mostly pure, early win) → `__init__.py`/`cosa_interface.py` → `api_client.py`
(AsyncAnthropic mocked) via `run-sdk-cov.sh` → `orchestrator`/`job` (IsolatedAsyncioTestCase) → `narrowing_harness`/`cli`
(argparse). Real lines only. ⚡
