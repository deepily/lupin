> Part 1 of 9 of the [Lupin REST API Quick Reference](../rest-api-reference.md): legend and retired queue doors.

# Lupin REST API Quick Reference

> For detailed request/response schemas, see the interactive API docs at `/docs` (Swagger UI) or `/redoc` (ReDoc).

---

## Authentication Legend

| Symbol | Meaning |
|--------|---------|
| **Public** | No authentication required |
| **JWT** | Bearer token in `Authorization: Bearer <token>` header |
| **Admin** | JWT + `admin` role required |
| **API Key** | `X-API-Key` header |

---

## 🪦 Retired queue doors — gone (410), remove by end of 2026

Rick ruled that there is one entry point, and it is v2. Eighteen routes used to put work on the queue; sixteen are retired.
Each retired route stays registered so it can answer **410 Gone** with a body naming its replacement.
A deleted route is invisible, and nothing would stop someone re-adding it because the product needs it.
These stubs are removed by the end of 2026.

**The survivors**:

- `POST /api/v2/ask`: a bare question, which the router routes.
- `POST /api/v2/submit`: work whose command is already decided.
- `POST /api/v2/resume`: resume a parked question.
- `POST /api/v2/resume-job`: resume a stalled job from its checkpoint.
- `POST /api/v2/ask-audio`: `/api/v2/ask` with the question spoken. It transcribes, then asks through the same flow, so it is not a separate way onto the queue (see the Speech I/O section).

**Retired so far:**

| Retired door | Use instead |
|---|---|
| `POST /api/push` | `/api/v2/ask` |
| `POST /api/job-history/{job_id}/retry` | `/api/v2/ask` |
| `POST /api/bug-fix-expediter/submit` | `/api/v2/submit` |
| `POST /api/deep-research/submit` | `/api/v2/submit` |
| `POST /api/deep-research-to-podcast/submit` | `/api/v2/submit` |
| `POST /api/deep-research-to-presentation/submit` | `/api/v2/submit` |
| `POST /api/presentation-generator/submit` | `/api/v2/submit` |
| `POST /api/podcast-generator/submit` | `/api/v2/ask` |
| `POST /api/swe-team/submit` | `/api/v2/submit` |
| `POST /api/push-agentic` | `/api/v2/submit` |
| `POST /api/jobs/{id_hash}/resume-from-checkpoint` | `/api/v2/resume-job` |
| `POST /api/test-fix-expediter/resume-from` | `/api/v2/resume-job` |
| `POST /api/mock-job/submit` | `/api/v2/submit` |
| `POST /api/test-suite/submit` | `/api/v2/submit` |

The two question-shaped doors went first, when `/api/v2/ask` was the only live replacement.
The submit-shaped ones had to wait until `/api/v2/submit` existed and could build an agentic job.
A 410 naming a route that answers "I do not understand" teaches a caller less than the error it replaced.

`/api/podcast-generator/submit` is the one job-queueing door that retires into `ask` rather than `submit`.
Its description flow asked the user which document they meant, and which languages and audience they wanted.
It could also answer "cancelled". That is a conversation, which `ask` holds and `submit` refuses to hold, by choice.

**No queue door is left live**. `/api/test-suite/submit` retired last.
Rick ruled "retire after v2 gap". The gap was `queue_position`, now `AskResponse.queue_position`.
It is the todo queue's size right after the push, and null when nothing was queued. Every in-repo caller has moved.

A test-suite job is now `POST /api/v2/submit` with this body:

```json
{ "command": "agent router go to test suite",
  "args": { "test_types", "pytest_args", "dry_run", "auto_fix_on_failure", "env_vars" },
  "scheduled_at": "<optional>" }
```

The job forces `monopolize` itself. **What differs for a caller**:

- Success is `status: "waiting"`, not `queued`.
- A refused submit is **HTTP 200 with `status: "failed"` and the cause in `error`**, not the 400 the old door answered.
- A refusal covers an unknown suite name and malformed or contradictory `pytest_args`.

`cosa.agents.test_suite.v2_client` builds the body and reads the reply.

**The mock-job door retired**. Rick ruled to keep what it does.
The earlier "0 callers" figure counted shipped code only. Four test suites called it: the 12-scenario proxy suite, the swe-team proxy suite, the expeditor mock-job smoke and the CJ Flow pause/schedule e2e.
So its two modes became one command, `agent router go to mock job`, on `POST /api/v2/submit`.
That command is test scaffolding: it is not speakable and is not on the router prompt or card.

- **plain** (no `voice_command`) queues a zero-cost `MockAgenticJob`.
- **expeditor test** (`voice_command` given) runs the `RuntimeArgumentExpeditor`. It queues a dry-run job of the command it matches, with optional `force_failure_mode`.

Arguments go in `args`. `scheduled_at`, `monopolize` and `websocket_id` are top-level.
The response differs from the old door's:

- `status` is `waiting`, not `queued`.
- The old `config` dict is at `submit_details.config`.
- A cancelled interview is `status: failed` with `route_reason: expeditor_cancelled`.

The suites share `src/tests/helpers/mock_job_v2.py`, which maps a v2 response back to the old shape.
`GET /api/mock-job/health` is unchanged.
