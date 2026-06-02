# 16 — cosa.rest Remainder Handoff (post-tree-wide-gate, FM-17)

**Author:** Tiberius 👑 (manager) · **Date:** 2026-06-01 · **Status:** scoped, staged

## TL;DR
The campaign's *assigned lanes* are all at 100% and committed (85 modules, 30 commits this
session, latest `e0b5a54`). BUT the **tree-wide gate** (`run-sdk-cov.sh src/cosa/tests/unit/rest/
--cov=cosa.rest`) shows **cosa.rest = 91%** (11053 stmts / **818 miss**). Root cause = **FM-17:
agent-vs-router conflation** — the campaign covered `cosa.agents.X` (100%) but MISSED the
`cosa.rest.routers.X` HTTP wrappers that delegate to them. This doc scopes the remainder.

## Triage verdict (done by manager before spawn)
**NO clean grandfather wins.** None of the 10 remaining modules carries an AC12 thin-dispatcher
docstring; they have real uncovered logic (not integration-only-by-design like commons). Some have
integration coverage, but they are NOT thin dispatchers → they need **genuine unit tests**, not
AC12 grandfathering. (If an author finds a router IS a pure thin pass-through + fully
integration-covered, propose AC12-grandfather to the manager WITH named-test evidence — but expect this to be rare.)

## Full remainder profile (cosa.rest, sub-100%)
| Module | stmts/miss | cover | tonight? |
|---|---|---|---|
| `websocket_manager.py` (1274 LoC) | 326/275 | ~16% | **DEFER → ramp** (complex, own lane, Rick) |
| `routers/podcast_generator.py` (637 LoC) | 285/247 | ~13% | **DEFER → ramp** (big real logic) |
| `routers/deep_research.py` | 106/70 | ~34% | idx11 |
| `routers/presentation_generator.py` | 81/52 | ~36% | idx11 |
| `routers/swe_team.py` | 62/36 | ~42% | idx11 |
| `routers/deep_research_to_presentation.py` | 60/34 | ~43% | idx11 |
| `routers/deep_research_to_podcast.py` | 52/29 | ~44% | idx11 |
| `routers/bug_fix_expediter.py` | 50/28 | ~44% | idx11 |
| `middleware/api_key_auth.py` | 48/38 | ~21% | idx12 |
| `dependencies/config.py` | 18/9 | ~50% | idx12 |

## Tonight's SCOPED wave (staged, per María's ruling)
- **idx11** — the 6 small SDK ROUTER-WRAPPERS (deep_research, presentation_generator, swe_team,
  deep_research_to_presentation, deep_research_to_podcast, bug_fix_expediter ≈ 249 miss). They
  WRAP the already-100% agent packages → pattern: **mock the agent/job-factory the router
  delegates to, unit-test the router's request validation + job submission + response/streaming
  arcs.** Group ~3 routers per cluster.
- **idx12** — `middleware/api_key_auth.py` (38) + `dependencies/config.py` (9). Small, real unit
  tests (mock the api-key repo / config_mgr). One cluster.
- **DEFERRED to the 2026-06-05 ramp / Rick** — `websocket_manager.py` (275, complex) +
  `routers/podcast_generator.py` (247). Per María's ramp safety-valve: don't force-grind complex
  modules unattended into the night.

## Gate protocol (unchanged)
cosa venv ONLY (`src/cosa/.venv/bin/python`, `PYTHONPATH=src:src/cosa/tests/unit/infrastructure`);
SDK-adjacent routers (deep_research/podcast/swe_team/bfe import claude_agent_sdk) → run via
`src/cosa/tests/run-sdk-cov.sh <args>`. 3-layer gate: author measure → manager disk re-measure
(COMPLETE bundled test-set, name the files) → reviewer re-verify → surgical-guard commit
(`git diff --cached --stat` + BAD/N/DR check; deep_research AGENT cli.py/orchestrator.py pair stays
OUT). Test-only; prod bug → tripwire + DM; NEW pragmas unreachable-only + read-contract-source +
propose to manager. ZERO GPU/DB/net/LLM/FIREWALLED. G1 dual-key `_patch_fastapi_main`.

## Honest framing (for the digest / Rick)
Tonight = "85 assigned-lane modules @100% + cosa.rest **91% tree-wide**"; the remainder is a
**newly-scoped cluster** (FM-17 conflation, caught by the tree-wide gate), on the 06-05 ramp — NOT
"rest complete." Stand down at a clean boundary if a cluster won't close cleanly tonight.
