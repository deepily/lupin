# Resume Here — Phase 1 Step 4 (`commons_archival.py`)

| Field | Value |
|---|---|
| **Created** | 2026-05-11 (session `f9608a41`, Tiberius 🌑) |
| **Phase 1 progress** | Steps 3a + 3b CLOSED; steps 4-8 remain |
| **Read first** | `00-index.md` → this file → `02-phase1-file-commons-design.md` §3 AC9 + §5 step 4 |

---

## What's done (steps 3a + 3b)

| File | Status |
|---|---|
| `src/lupin_mcp/commons_persona_matcher.py` (91 LOC) | ✅ + 12 tests + 100% coverage |
| `src/lupin_mcp/commons_store.py` (332 LOC) | ✅ + 36 tests + 100% coverage + AC10b stress test (5 procs × 100 posts = 500 entries) verified |
| `src/tests/unit/commons/test_commons_persona_matcher.py` | ✅ |
| `src/tests/unit/commons/test_commons_store.py` | ✅ |
| `src/tests/unit/commons/__init__.py` | ✅ |
| Coverage tooling — local cosa venv | ✅ pytest-cov 7.1.0 + coverage 7.14.0 |
| `pyproject.toml` | ✅ pytest-cov added to dev deps |
| `uv.lock` | ✅ regenerated cleanly (only 2 deps added, 55 lines, torch/flash-attn untouched) |
| `docker/lupin/Dockerfile` | ⏸️ Image candidate built at `lupin:1.0.0-pytest-cov`; **NOT promoted** to `lupin:1.0.0` yet |

## What's next (step 4)

**`commons_archival.py`** — daemon thread for 24h rotation. Per AC9:

- Scan `<root>/io/commons/*.md` every `commons archival interval seconds` (default 3600)
- For each topic with entries >24h old: split off into `<root>/io/commons/archive/yyyy-mm-dd/<topic>.md`
- Atomic per-topic batch (read all, filter, write remaining to active, write aged to archive — all under fcntl)
- Reserved topics rotate but retain their frontmatter
- On write failure: log + retry next interval (no data loss)

**Prior art reuse (per F3 REUSE)**: template from `src/cosa/rest/running_fifo_queue.py:95-107` `_ghost_job_sweep_loop` — threading.Event, daemon=True, exception-catch + backoff.

**Tests required** (per AC10):
- `test_commons_archival.py` 5+ tests:
  1. 24h cutoff split (seed 25h / 23h / 1h entries; assert split correctly)
  2. Archive dir auto-creation (yyyy-mm-dd subdir)
  3. Reserved topic retention (frontmatter preserved after rotation)
  4. Rotation idempotence (running twice produces same result)
  5. Daemon crash + restart (`test_write_failure_no_data_loss` per AC9 verification)

**Coverage gate**: `pytest --cov=lupin_mcp.commons_archival --cov-fail-under=100 src/tests/unit/commons/test_commons_archival.py`

## Open operational concerns

### Docker image promotion

Candidate `lupin:1.0.0-pytest-cov` (6ff1643d8796, 31.7GB) is ready. Per `feedback_no_auto_promote_tags.md`, AI does NOT promote. User decides when/if to:

```bash
docker tag lupin:1.0.0-pytest-cov lupin:1.0.0
# Then bounce affected containers if pytest-cov is needed in them
```

Phase 1 progress does NOT depend on this — AC10 enforces locally via the cosa venv install.

### Coverage tooling scope

Currently scoped to commons modules only (per C3 ratification). User's "100% Always Full stop" directive is **commons-specific** for now. Generalization to broader Python policy = deferred follow-up.

## Read order for fresh session

1. **`00-index.md`** — milestone overview + Q-decision summary + Prior-art table
2. **This file** — what's done + what's next
3. **`02-phase1-file-commons-design.md`** §3 AC8 + AC9 + AC10 + §5 step 4 — the AC contracts step 4 must satisfy
4. **`90-execution-log.md`** — full execution status

## Verification commands fresh session can run

```bash
# Confirm step 3 work still passes
PYTHONPATH=src:$PYTHONPATH /mnt/DATA01/include/www.deepily.ai/projects/lupin/src/cosa/.venv/bin/python -m pytest src/tests/unit/commons/ -v --cov=lupin_mcp.commons_persona_matcher --cov=lupin_mcp.commons_store --cov-fail-under=100

# Should report: 48 passed; 100% coverage on both modules
```

If that's green, step 4 can begin.
