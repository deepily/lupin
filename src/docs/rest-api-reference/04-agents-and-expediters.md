> Part 4 of 8 of the [Lupin REST API Quick Reference](../rest-api-reference.md): routes 8 to 17b: agents, expediters, test suite.

## 8. Embeddings (`/api/embeddings/*`)

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| POST | `/api/embeddings/generate` | JWT | Generate single embedding |
| POST | `/api/embeddings/batch` | JWT | Generate batch embeddings |
| GET | `/api/embeddings/info` | JWT | Get embedding engine info |

## 9. Mode (`/api/mode/*`)

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| GET | `/api/mode/available` | JWT | List available modes |
| GET | `/api/mode/current` | JWT | Get current mode for user |
| POST | `/api/mode/current` | JWT | Set mode for user |
| DELETE | `/api/mode/current` | JWT | Clear mode (revert to system) |

## 10. Statistics (`/api/stats/*`)

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| GET | `/api/stats/time-saved` | JWT | Personal time-saved stats |
| GET | `/api/stats/time-saved/global` | JWT | Global leaderboard stats |

## 11. Deep Research (`/api/deep-research/*`)

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| POST | `/api/deep-research/submit` | — | 🪦 **Gone (410)** — use `/api/v2/submit` with `"agent router go to deep research"`. Remove by end of 2026. |
| GET | `/api/deep-research/report` | Public | Retrieve research report (local or GCS) |
| GET | `/api/deep-research/health` | Public | Deep research subsystem health |

## 12. Podcast Generator (`/api/podcast-generator/*`)

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| POST | `/api/podcast-generator/submit` | — | 🪦 **Gone (410)** — use `/api/v2/ask` (it retires into `ask`, not `submit`: its description path held a conversation). Remove by end of 2026. |

## 12a. Presentation Generator (`/api/presentation-generator/*`)

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| POST | `/api/presentation-generator/submit` | — | 🪦 **Gone (410)** — use `/api/v2/submit` with `"agent router go to presentation generator"`. Remove by end of 2026. |

The door carried a path-escape check that nothing downstream repeated.
The guard moved onto the job (`presentation_generator/job.py`) in its own earlier commit, and the retirement waited for it.
Retiring the door first would have left a window with no check at all.

## 13. Research-to-Podcast

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| POST | `/api/deep-research-to-podcast/submit` | — | 🪦 **Gone (410)** — use `/api/v2/submit` with `"agent router go to research to podcast"`. Remove by end of 2026. |

## 13a. Research-to-Presentation

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| POST | `/api/deep-research-to-presentation/submit` | — | 🪦 **Gone (410)** — use `/api/v2/submit` with `"agent router go to research to presentation"`. Remove by end of 2026. |

## 14. Claude Code (`/api/claude-code/*`) — retired

**Retired endpoints**. The legacy direct-dispatch and interactive-control cluster was eliminated.
Four catalogued structural defects caused it: a URL contract mismatch, no auth, module-level state and a parallel pre-cj-flow path.
Use **`/api/v2/submit`** instead. It is JWT-authenticated and rides the standard CJ Flow and WebSocketManager dispatch plane.
Section 15 records the two `/api/claude-code/*` tombstones that replaced the cluster and were themselves retired.
See `src/rnd/v0.1.7/2026.05.05-claude-code-dispatch-retirement/01-plan.md`.

| Method | Path | Status |
|--------|------|--------|
| POST | `/api/claude-code/dispatch` | ❌ Retired → use `/api/v2/submit` (the `/api/claude-code/queue/submit` it originally named is itself 410) |
| POST | `/api/claude-code/{task_id}/inject` | ❌ Retired → interactive control parity pending on cj-flow path |
| POST | `/api/claude-code/{task_id}/interrupt` | ❌ Retired → interactive control parity pending on cj-flow path |
| POST | `/api/claude-code/{task_id}/end` | ❌ Retired → interactive control parity pending on cj-flow path |
| GET | `/api/claude-code/{task_id}/status` | ❌ Retired → use job-card status via CJ Flow accordion |
| WebSocket | `/api/claude-code/ws/{task_id}` | ❌ Retired → progress now arrives via `/ws/queue/{session_id}` notifications keyed by `cc-*` job_id |

## 15. Claude Code Queue (retired — use `/api/v2/submit`)

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| POST | `/api/claude-code/submit` | none | ❌ Retired → 410 Gone, use `/api/v2/submit` (remove by end of 2026) |
| POST | `/api/claude-code/queue/submit` | none | ❌ Retired → 410 Gone, use `/api/v2/submit` (remove by end of 2026) |

A tombstone carries no auth dependency, as specified.
An unauthenticated caller must learn the same thing an authenticated one does.
A 401 teaches nobody anything.

```json
POST /api/v2/submit
{
  "command"      : "agent router go to claude code",
  "args"         : { "prompt": "…", "project": "lupin", "task_type": "BOUNDED",
                     "max_turns": 50, "dry_run": false },
  "websocket_id" : "<session id>",
  "scheduled_at" : "2026-08-22T11:00:00-04:00"
}
```

`prompt` / `project` / `task_type` / `max_turns` / `dry_run` are arguments to the job. So
they go in `args`. `websocket_id` / `scheduled_at` / `monopolize` are directives to the
queue and stay top-level. `task_type` must be `BOUNDED` or `INTERACTIVE`. Anything else is
refused when the job is built.

## 16. SWE Team (`/api/swe-team/*`)

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| POST | `/api/swe-team/submit` | — | 🪦 **Gone (410)** — use `/api/v2/submit` with `"agent router go to swe team"`; `parent_id_hash` is top-level there. Remove by end of 2026. |

## 17. Test Suite (`/api/test-suite/*`)

> **Deep-dive**: See [`agents/test-suite-scheduling-guide.md`](../agents/test-suite-scheduling-guide.md)

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| POST | `/api/test-suite/submit` | — | 🪦 **Gone (410)**. Use `/api/v2/submit` with `"agent router go to test suite"` (suite arguments in `args`; `scheduled_at` top-level; a refused submit is HTTP 200 with `status: "failed"`, not a 400). Remove by end of 2026. |

## 17a. Bug Fix Expediter (`/api/v2/ask` with BFE command)

> **Deep-dive**: See [`agents/bug-fix-expediter-guide.md`](../agents/bug-fix-expediter-guide.md)

BFE is submitted via the generic `/api/v2/ask` endpoint using the agent router command string (`/api/push` was retired and answers 410). Used manually when curating which dead jobs get auto-recovery; automatic dispatch happens via the `DeadQueueWatchdog` when `bug fix expediter enabled = true` in INI.

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| POST | `/api/v2/ask` | JWT | Submit BFE job with `question = "agent router go to bug fix expediter"` and `args = { dead_job_id, extra_context (optional), dry_run (optional) }`. Returns `{ job_id }` with `bfe-` prefix. |
| POST | `/api/bug-fix-expediter/submit` | — | 🪦 **Gone (410)** — remove by end of 2026. Its refusal names `/api/v2/submit`, which accepts the decided command; the row above is the same job asked as a question through `/api/v2/ask`. Both reach BFE. |

Watchdog auto-dispatch: requires `bug fix expediter enabled = true` in `lupin-app.ini`. See the BFE guide for full INI reference, trust-to-git mapping, and the automated repair loop configuration.

## 17b. Test Fix Expediter (`/api/v2/ask` with TFE command)

> **Deep-dive**: See [`agents/test-fix-expediter-guide.md`](../agents/test-fix-expediter-guide.md)

TFE is submitted via the generic `/api/v2/ask` endpoint using the agent router command string (`/api/push` was retired and answers 410). Normally invoked automatically by `TestSuiteCompletionWatchdog` when a `TestSuiteJob` completes with failures; manual submission is supported for curated fix runs.

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| POST | `/api/v2/ask` | JWT | Submit TFE job with `question = "agent router go to test fix expediter"` and `args = { remediation_snapshot_path, source_test_suite_job_id, original_test_types (comma-separated), original_pytest_args (optional), dry_run (optional) }`. Returns `{ job_id }` with `tfe-` prefix. |
| POST | `/api/test-fix-expediter/resume-from` | — | 🪦 **Gone (410)** — use `/api/v2/resume-job` with `{ "resume_from": "<tfe id, plan path, or description>" }`. Remove by end of 2026. |

Watchdog auto-dispatch: requires `test fix expediter auto fix enabled = true` in `lupin-app.ini`. See the TFE guide for full INI reference (16 keys), six-phase pipeline, and the `TestSuiteCompletionWatchdog` eligibility gates.
