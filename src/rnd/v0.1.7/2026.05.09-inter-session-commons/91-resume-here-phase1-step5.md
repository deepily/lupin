# Resume Here — Phase 1 Step 5 (Register 5 MCP tools in `cosa_voice_mcp.py`)

| Field | Value |
|---|---|
| **Created** | 2026-05-11 (session `9a4a601d`, Rachel 🕊️) |
| **Phase 1 progress** | Steps 3a + 3b + 4 CLOSED; steps 5-8 remain |
| **Read first** | `00-index.md` → this file → `02-phase1-file-commons-design.md` §3 AC4 + AC6 + AC11 + AC12 + AC14 + §5 step 5 |
| **Supersedes** | `91-resume-here-phase1-step4.md` (step 4 is now closed) |

---

## What's done (steps 3a + 3b + 4)

| File | Status |
|---|---|
| `src/lupin_mcp/commons_persona_matcher.py` (91 LOC) | ✅ + 12 tests + 100% lines/branches |
| `src/lupin_mcp/commons_store.py` (332 LOC) | ✅ + 37 tests (incl AC10b real-fcntl stress, +1 branch backfill) + 100% lines/branches |
| `src/lupin_mcp/commons_archival.py` (230 LOC) | ✅ + 26 tests + 100% lines/branches |
| `src/tests/unit/commons/test_commons_persona_matcher.py` | ✅ |
| `src/tests/unit/commons/test_commons_store.py` | ✅ (+1 branch-backfill test) |
| `src/tests/unit/commons/test_commons_archival.py` | ✅ NEW |
| `src/tests/unit/commons/__init__.py` | ✅ |
| Coverage tooling — local cosa venv | ✅ pytest-cov 7.1.0 + coverage 7.14.0 |
| `pyproject.toml` | ✅ pytest-cov in dev deps |
| `uv.lock` | ✅ regenerated cleanly |
| `docker/lupin/Dockerfile` | ⏸️ Image candidate at `lupin:1.0.0-pytest-cov`; **NOT promoted** to `lupin:1.0.0` yet |

**Full commons suite gate** (verify before starting step 5):

```bash
PYTHONPATH=src:$PYTHONPATH /mnt/DATA01/include/www.deepily.ai/projects/lupin/src/cosa/.venv/bin/python \
  -m pytest src/tests/unit/commons/ -v \
  --cov=lupin_mcp.commons_persona_matcher \
  --cov=lupin_mcp.commons_store \
  --cov=lupin_mcp.commons_archival \
  --cov-branch --cov-fail-under=100
```

Should report: **75 passed; 280 stmts / 72 branches / 0 missing; 100.00% coverage.**

## What's next (step 5)

Register **5 MCP tools** in `src/lupin_mcp/cosa_voice_mcp.py` per AC4 + AC6:

1. `commons_post(topic, body, metadata?, priority?)` — wraps `CommonsStore.post`
2. `commons_read(topic, since?, limit?)` — wraps `CommonsStore.read`
3. `commons_who(topic?, retention_hours?)` — wraps `CommonsStore.who`
4. `commons_ask_sync(topic, body, timeout_seconds, hybrid_grace_seconds?)` — sync ask/answer; correlation via `metadata.in_reply_to`
5. `commons_ask_async(topic, body)` — fire-and-forget ask; replies surface via Phase 3 WS push (Phase 1 just records the question)

Plus AC14: subprocess verification — spawn the MCP server as a child process, list registered tools, assert all 5 commons tools present.

**Prior art reuse**:
- F4 — registration pattern at `lupin_mcp/cosa_voice_mcp.py:620-1050` (existing `notify_*_sync`/`async` tools)
- F10 — `metadata.in_reply_to` UUID correlation pattern at `cosa/rest/notification_fifo_queue.py:50-51`
- F11 — `uuid.uuid4()` and `uuid.uuid4().hex[:8]` short-form

**Tests required** (per AC10 hybrid-grace 4-case sub-list):
- `test_commons_ask.py` — 4 tests for `commons_ask_sync` hybrid-grace timing:
  1. Reply arrives before grace expiry → return reply
  2. Reply arrives during grace window → return reply
  3. Reply arrives after timeout → return None
  4. No reply ever → return None at timeout
- `test_commons_mcp_subprocess.py` — AC14: spawn MCP, enumerate tools, assert all 5 present (per Cluster A P2 ratification)

**Coverage gate**: keep the suite at **100% lines + branches + functions** across all commons modules (including any new files step 5 introduces).

## Open operational concerns

### Docker image promotion (unchanged from step 4 resume)

Candidate `lupin:1.0.0-pytest-cov` (6ff1643d8796, 31.7GB) is ready. User decides when/if to promote. Phase 1 progress does not depend on this — AC10 enforces locally via the cosa venv install.

### Coverage tooling scope (unchanged)

Currently scoped to commons modules only (per C3 ratification). Generalization to broader Python policy = deferred follow-up.

### Step 4 byproduct — branch coverage hygiene

While running step 4's `--cov-branch` gate, one defensive branch in `commons_store.py:306->303` surfaced as uncovered. Backfilled with `test_who_same_session_older_entry_skipped`. **Lesson for steps 5-8**: always run with `--cov-branch` from the start, not just `--cov`. The step 3 verification command in this resume doc is already updated.

## Read order for fresh session

1. **`00-index.md`** — milestone overview + Q-decision summary + Prior-art table
2. **This file** — what's done + what's next
3. **`02-phase1-file-commons-design.md`** §3 AC4 + AC6 + AC11 + AC12 + AC14 + §5 step 5 — the AC contracts step 5 must satisfy
4. **`90-execution-log.md`** — full execution status incl. step 4 evidence section

## Verification commands fresh session can run

```bash
# Confirm step 3 + 4 work still passes (full commons suite + branch gate)
PYTHONPATH=src:$PYTHONPATH /mnt/DATA01/include/www.deepily.ai/projects/lupin/src/cosa/.venv/bin/python \
  -m pytest src/tests/unit/commons/ -v \
  --cov=lupin_mcp.commons_persona_matcher \
  --cov=lupin_mcp.commons_store \
  --cov=lupin_mcp.commons_archival \
  --cov-branch --cov-fail-under=100

# Should report: 75 passed; 100% lines / 100% branches
```

If that's green, step 5 can begin.
