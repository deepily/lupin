# 07 — Rachel 🕊️ Lane Handoff: io_models (remainder) + watchdog (target 3)

> **Author:** Rachel 🕊️ (campaign author #3, seat "Clayton", session 79f57922)
> **Written:** 2026-05-31, at a clean green-line honest-stop.
> **For:** whoever (fresh author) picks up the remainder of Rachel's pile.
> **Manager:** Tiberius 👑 (session 3047b30f). Gate: author → Tiberius disk-verify → Mr. Radio 🦉 audit → Tiberius commits. **Authors do NOT commit.**

---

## TL;DR — pile state

Rachel's assigned pile was **3 targets**: (1) `prediction_engine/`, (2) `io_models/`, (3) `rest/test_suite_completion_watchdog.py`.

| Target | State |
|---|---|
| **1. prediction_engine/** | ✅ **COMPLETE.** 7 files, 237 tests + 1 xfailed. 6 files genuine 100%; `prediction_engine.py` 99% — blocked by exactly the 2 lines of **prod-bug #11** (tripwire armed, NOT fixed). Tiberius confirmed the bug and **owns the fix** (he's de-arming the xfail in `test_prediction_engine.py`). Reported as sub-batches 1 + 2; disk-verified. **Do not touch — it's the manager's to close.** |
| **2. io_models/** | 🟡 **PARTIAL.** Green baseline restored (5 stale legacy tests repaired). `utils/`: `prompt_template_processor.py` + `xml_parser_factory.py` 100%; `util_xml_pydantic.py` 97% (2 pragma proposals — see below). `xml_models.py` 57%→79% (6 of ~16 classes done: Simple/Command/YesNo/Receptionist/Code/Calendar). Full io_models suite GREEN (135 passed). **Remainder below.** |
| **3. watchdog** | ⬜ **UNTOUCHED.** `src/cosa/rest/test_suite_completion_watchdog.py` (13 KB). No existing test. Needs a fresh read. |

---

## Canonical interpreter & measurement (NON-NEGOTIABLE)

cosa venv ONLY (py3.11 / pytest 9.0.2). No SDK/scipy in this pile → plain pytest-cov (NOT run-sdk-cov.sh).

```bash
# measure
PYTHONPATH=src src/cosa/.venv/bin/python -m pytest src/cosa/agents/io_models/tests/ \
  --cov=cosa.agents.io_models --cov-branch --cov-report=term-missing -p no:cacheprovider -q
```

**Coverage config (`pyproject.toml [tool.coverage]`) EXCLUDES** `def quick_smoke_test` and `if __name__ == .__main__.:`. So **do NOT write tests for smoke-test functions or main guards** — they're out of the denominator. Cover only production logic. (This is the single biggest time-saver; the legacy migration tests predate it.)

**COST INVARIANT:** boundary-mock everything; ZERO API spend. Never read `ANTHROPIC_API_KEY_FIREWALLED`. (The io_models classes are pure Pydantic over inline XML — no LLM/network/DB seams at all, so no mocking is even needed for xml_models.)

---

## Target 2 remainder — `xml_models.py` (12 classes, ~114 lines)

**The pattern is uniform.** Every class is a `BaseXMLModel` subclass with: typed fields, `@field_validator`s, often a `get_example_for_template()` classmethod, sometimes a custom `to_xml()`, plus small helper methods. The test recipe (see `tests/test_xml_models_extra.py`, which I just wrote for the first 4 classes — **extend it, same style**):

1. construct from valid kwargs + `from_xml(...)` an inline XML string;
2. exercise each `field_validator` with valid AND invalid input (invalid → `pytest.raises(ValidationError ...)`);
3. call every helper method on both branches;
4. call `get_example_for_template()`;
5. `to_xml()` round-trip.

**Branch gotchas I hit (will recur):**
- Validators with `if v.lower() not in valid_list: pass` (e.g. `CommandResponse.validate_command`, `YesNoResponse.validate_answer`) — cover BOTH the in-list and not-in-list inputs (both just `return v`, but the `if` needs both arcs).
- `Literal[...]` fields (e.g. `ReceptionistResponse.category`) — an out-of-set value raises `ValidationError` (Pydantic, before your validator).
- Loop-skip arcs like `SimpleResponse.get_content` `56->55` — feed a non-string field first then a string field.

**Classes still needing tests** (line numbers as of 2026-05-31; CodeResponse + CalendarResponse are now DONE):

| Class | Line | Notes |
|---|---|---|
| `BrainstormIdeas` | 1137 | small (1120 region) |
| `CodeBrainstormResponse` | 1182 | gaps 1161-1378 — the biggest remaining block |
| `FormatterResponse` | 2257 | small (2294-2296) |
| `VoxCommandResponse` | 2299 | 2328,2338 |
| `AgentRouterResponse` | 2393 | 2421-2449 |
| `GistResponse` | 2504 | 2533-2545 |
| `ConfirmationResponse` | 2602 | 2629-2655 |
| `QualifierClassification` | 2712 | 2733-2753 |
| `FuzzyFileMatchResponse` | 2816 | 2850-2871 |
| `TFEResumeMatchResponse` | 2933 | 2969-2990 |
| (gaps on already-partly-covered) | — | `get_example_for_template`/helpers on BugInjection/IterativeDebugging*/Weather: lines 1631,1658-60,1866,1874,1895-904,1945,1987,2003-49,2195-201 |

These last ones are quick: the migration tests construct the models but never call `get_example_for_template()` or some helpers — just add those calls.

### `utils/util_xml_pydantic.py` — TWO PRAGMAS PROPOSED (manager applies; both HELD by Tiberius pending his own verification)
1. **Lines 24-25** — `except ImportError: raise ImportError("xmltodict is required...")`. xmltodict is a hard dep (installed), so the except is unreachable. A reload-based cover was TRIED and REMOVED: `importlib.reload(util_xml_pydantic)` redefines `BaseXMLModel`, and the xml_models classes still subclass the original → from_xml's `except ValidationError` stops wrapping → cross-test pollution (CodeResponse test passed alone, failed in-suite). Pragma is the clean choice. Proposed: `# pragma: no cover - xmltodict is a hard dependency; ImportError guard unreachable when installed`.
2. **Lines 210-212** — the `else: model_data = xml_dict` arm of `from_xml()`. Unreachable: `xmltodict.parse()` yields exactly one root key for valid XML; malformed multi-root raises `ExpatError` first (caught earlier). Proposed: `# pragma: no cover - xmltodict yields exactly one root for valid XML; >1-root else unreachable`.

With both applied, `util_xml_pydantic.py` = TRUE 100% (currently 97%). `prompt_template_processor.py` + `xml_parser_factory.py` are already 100%.

### Stale-test repairs already done (green baseline) — for audit context
5 legacy tests in `tests/{test_bug_injector_migration,test_iterative_debugging_migration,test_weather_migration}.py` repaired to the CURRENT documented contract (NOT bug-ratification): `line_number=-1` is a valid sentinel; empty `<bug>` is rejected by design; `get_parser_strategy()`/`get_strategy_name()` were removed in the Session-116 Pydantic-only refactor → rewritten to assert the command→model map / `_get_debugging_model`. Before/after note was sent to Tiberius; each `def` carries a `( Repaired 2026-05-31: ... )` docstring.

---

## Target 3 — `test_suite_completion_watchdog.py` (UNTOUCHED)

`src/cosa/rest/test_suite_completion_watchdog.py` (13 KB). It's PRODUCTION code (a watchdog that manages test-suite completion) — NOT a test file — and is explicitly in the coverage denominator (the over-broad `*/test_*.py` omit was REMOVED 2026-05-31 precisely so this + `routers/test_suite.py` + `swe_team/test_runner.py` are measured). No SDK/scipy → plain pytest-cov. Read it first, identify boundaries (likely threading/timers, the test-suite queue, DB or notification seams), boundary-mock them, and target 100% lines+branches+functions. Suggested test home: `src/cosa/tests/unit/rest/test_test_suite_completion_watchdog.py` (a sibling `test_test_suite_router.py` already exists there per the repo's untracked-files list) OR mirror the in-package convention — confirm placement with Tiberius (he noted both conventions coexist; don't move existing files).

---

## Key learnings to carry

- **prod-bug #11** (`prediction_engine.py:990` imports `LlmClientFactory` from the wrong module → swallowed ImportError → dead LLM-synthesis tier). Tripwire pattern: xfail(strict=True) on the correct contract + a pin on current behavior + leave the bug-blocked lines uncovered (NO pragma). Manager owns the fix + de-arm.
- **Measure the FULL suite**, not a single new test file in isolation — sibling tests cover overlapping classes (I briefly misread a 49% from measuring my file alone).
- **Read-flake discipline** (Tiberius): if a read looks truncated/inconsistent, RE-READ before trusting; never author against a bad read; never report an unmeasured number.
- **NEVER use `importlib.reload` to cover module-top import guards in this package.** Reloading `util_xml_pydantic` redefines `BaseXMLModel`; xml_models classes keep subclassing the *original*, so their inherited `from_xml`'s `except ValidationError` stops wrapping → silent cross-test pollution (a test that passes in isolation fails in-suite). Always run the FULL suite (not just the new file) to catch this class of pollution. Prefer a pragma for hard-dep import guards.
- Reach Rachel's seat at `commons_send_to(recipient="rachel")` if continuity questions arise (until reaped).
