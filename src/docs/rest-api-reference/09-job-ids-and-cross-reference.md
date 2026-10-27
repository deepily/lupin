> Part 9 of 9 of the [Lupin REST API Quick Reference](../rest-api-reference.md): job id prefixes and cross-reference.

## Job ID Prefixes

| Prefix | Job Type | Submit Endpoint |
|--------|----------|-----------------|
| `dr-` | Deep Research | `/api/v2/submit` with `"agent router go to deep research"` (`/api/deep-research/submit` is now 410) |
| `pg-` | Podcast Generator | `/api/v2/ask` with `"agent router go to podcast generator"` (`/api/podcast-generator/submit` is now 410) |
| `rp-` | Research-to-Podcast | `/api/v2/submit` with `"agent router go to research to podcast"` (`/api/deep-research-to-podcast/submit` is now 410) |
| `cc-` | Claude Code | `/api/v2/submit` with `"agent router go to claude code"` (both `/api/claude-code/*` doors are now 410) |
| `swe-` | SWE Team | `/api/v2/submit` with `"agent router go to swe team"` (`/api/swe-team/submit` is now 410) |
| `ts-` | Test Suite | `/api/v2/submit` with `"agent router go to test suite"` (`/api/test-suite/submit` is now 410) |
| `bfe-` | Bug Fix Expediter | `/api/v2/ask` with `"agent router go to bug fix expediter"` (`/api/push` is now 410) |
| `tfe-` | Test Fix Expediter | `/api/v2/ask` with `"agent router go to test fix expediter"` (`/api/push` is now 410) |
| `mock-` | Mock Job | `/api/v2/submit` with `"agent router go to mock job"` (`/api/mock-job/submit` is now 410) |

---

## Cross-Reference: Deep-Dive Documentation

| Topic | Document |
|-------|----------|
| Notification system | [`notification-api.md`](../notification-api.md) |
| Decision proxy | [`proxy-admin-guide.md`](../proxy-admin-guide.md) |
| WebSocket architecture | [`websocket-architecture.md`](../websocket-architecture.md) |
| WebSocket events | [`websocket-events.md`](../websocket-events.md) |
| CC transcript console | [`websocket-events.md`](../websocket-events.md) § CC Transcript Console Events |
| WebSocket troubleshooting | [`websocket-troubleshooting.md`](../websocket-troubleshooting.md) |
| Interactive testing | [`automated-interactive-testing.md`](../automated-interactive-testing.md) |
| Frontend architecture | [`lupin-mpa-frontend-architecture.md`](../lupin-mpa-frontend-architecture.md) |

## 29. Pair Labelling (`/api/pair-labelling/*`)

A reviewer labels the pairs of a blind `semdup_pair` packet from the page `/app/pair-labelling?reviewer=<name>`. The default reviewer is `rick`.
The packet is `packet-<reviewer>.jsonl` in the folder named by `LUPIN_PAIR_LABELLING_DIR`, which defaults to the packets folder of the run named in `pair_labelling.py`.
Labels go to `labels-<reviewer>.jsonl` beside it, and `read_labels` accepts the file. The router never opens the run's key folder.
Each label is written to a temp file, checked with `read_labels`, and renamed over the old file. A re-answer therefore replaces the pair's line.

| Method | Path | Auth | Summary |
|---|---|---|---|
| GET | `/api/pair-labelling/state` | API key or JWT | `{ reviewer, total, labelled, unsure, resume }`; `resume` is the first unlabelled position, else the first unsure one, else null |
| GET | `/api/pair-labelling/item` | API key or JWT | One pair by `position`: `{ position, total, labelled, item_id, a, b, label }`, with nothing about its type or origin |
| POST | `/api/pair-labelling/label` | API key or JWT | Write `{ item_id, same_job, unsure, note, reviewer }`, then answer as `state` does |

`same_job` true is `AS_PROPOSED`, false is `NONE`, `symbols` is empty, and `OTHER` is never written.
Unsure is the leaning choice plus a note that starts `UNSURE:`.
The rule is `SAME_JOB_OF_CHOICE` in `src/cosa/repo/labelling/pair_labels.py`. The proof reads labels with `same_job_labels( path )`.

Failures:

- 404: an unknown reviewer, pair or position.
- 422: a bad reviewer name, or a note over 2,000 characters.
- 500: a packet or labels file that fails validation.
