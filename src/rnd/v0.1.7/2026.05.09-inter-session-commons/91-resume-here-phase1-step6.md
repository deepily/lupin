# Resume Here — Phase 1 Step 6 (INI keys + paired splainer entries)

| Field | Value |
|---|---|
| **Created** | 2026-05-11 (session `9a4a601d`, Rachel 🕊️) |
| **Phase 1 progress** | Steps 3a + 3b + 4 + 5 CLOSED; steps 6-8 remain |
| **Read first** | `00-index.md` → this file → `02-phase1-file-commons-design.md` §3 AC12 + §5 step 6 |
| **Supersedes** | `91-resume-here-phase1-step5.md` (step 5 is now closed) |

---

## What's done (steps 3a + 3b + 4 + 5)

| File | Status |
|---|---|
| `src/lupin_mcp/commons_persona_matcher.py` | ✅ + 12 tests + 100% lines/branches |
| `src/lupin_mcp/commons_store.py` | ✅ + 37 tests (AC10b stress + branch backfill) + 100% lines/branches |
| `src/lupin_mcp/commons_archival.py` | ✅ + 26 tests + 100% lines/branches |
| `src/lupin_mcp/commons_ask.py` | ✅ + 7 tests + 100% lines/branches |
| `src/lupin_mcp/cosa_voice_mcp.py` | ✅ MODIFIED — 5 `@mcp.tool` shims registered; AC14 subprocess test green |
| `src/tests/helpers/mcp_stdio_test_client.py` | ✅ NEW helper for fastmcp subprocess testing |
| `src/tests/unit/commons/test_commons_*.py` | ✅ 83 tests passing under `--cov-branch --cov-fail-under=100` |

**Full commons suite gate** (verify before starting step 6):

```bash
PYTHONPATH=src:$PYTHONPATH /mnt/DATA01/include/www.deepily.ai/projects/lupin/src/cosa/.venv/bin/python \
  -m pytest src/tests/unit/commons/ -v \
  --cov=lupin_mcp.commons_persona_matcher \
  --cov=lupin_mcp.commons_store \
  --cov=lupin_mcp.commons_archival \
  --cov=lupin_mcp.commons_ask \
  --cov-branch --cov-fail-under=100
```

Should report: **83 passed; 309 stmts / 80 branches / 0 missing; 100.00% coverage.**

## What's next (step 6)

Wire the 6 commons INI keys per AC12. Land them in both files (CLAUDE.md mandate: **every** INI key requires a paired splainer entry).

### Target keys (under `[Lupin: Production]` / `[Lupin: Baseline]`)

| Key | Default | Used by |
|---|---|---|
| `commons enabled` | `True` | `cosa_voice_mcp._commons_enabled()` — when False, all 5 tools short-circuit and the archival daemon does not start |
| `commons storage path` | `/io/commons` | Future override for `CommonsStore` root (currently hardcoded to `<LUPIN_ROOT>/io/commons`) |
| `commons retention hours` | `24` | `CommonsArchiver(retention_hours=...)` |
| `commons archival interval seconds` | `3600` | `CommonsArchiver(interval_seconds=...)` |
| `commons broadcast rate limit seconds` | `30` | Phase 2 broadcast endpoint (Q11) — declare now, consume in Phase 2 |
| `commons ask sync grace seconds` | `1.0` | `commons_ask_sync` default `grace_seconds` (currently hardcoded as `_COMMONS_ASK_SYNC_GRACE_SECONDS_DEFAULT`) |

### Wiring work (step 6)

1. Add the 6 keys to `src/conf/lupin-app.ini` under the appropriate section.
2. Add **paired explanations** for each key to `src/conf/lupin-app-splainer.ini` (per CLAUDE.md `lupin-app.ini` ↔ `lupin-app-splainer.ini` mandate).
3. Replace the hardcoded `_commons_enabled()` body in `cosa_voice_mcp.py` with a `ConfigurationManager`-driven lookup. Cache the value at module load to avoid per-call overhead.
4. Replace `_COMMONS_ASK_SYNC_GRACE_SECONDS_DEFAULT` with an INI lookup, also cached at module load.
5. Replace the hardcoded `CommonsStore` root in `_get_commons_store()` with `commons storage path` (relative paths resolve under `LUPIN_ROOT`).
6. **Archival daemon boot**: instantiate `CommonsArchiver(...)` at MCP server module load **only if** `commons enabled = True` and start its daemon thread. This is the AC12 architectural requirement ("If `commons enabled = false`, MCP server does NOT register commons tools and does NOT start archival daemon").

**Test the wiring**:
- A standalone unit test that monkey-patches `ConfigurationManager` to assert the lookups happen with the right key names + cache properly.
- Coverage gate: keep `--cov-branch --cov-fail-under=100` on all 4 commons modules. The `cosa_voice_mcp.py` shims are NOT in coverage scope (out-of-band, exercised via AC14).

## Step 7 (after 6)

`src/tests/smoke/test_commons_two_session_roundtrip.py` — two child Python processes both pointed at a shared tempdir; one posts, the other reads + asserts the entry round-trips. Bypasses the MCP layer per T3 ratification. Venue: **`:7999` (AI-discretionary)** — no server dependency, non-destructive, fast.

## Step 8 (after 7)

AC12 config-toggle subprocess test: spawn `python -m lupin_mcp.cosa_voice_mcp` with `commons enabled=false` in a test INI; assert commons tools NOT in `tools/list`; repeat with `enabled=true` and assert they ARE present. Reuses `tests/helpers/mcp_stdio_test_client.py` (already in place from step 5). Also covers the AC14 final verification.

## Open operational concerns (unchanged from step 5 resume)

### Docker image promotion

Candidate `lupin:1.0.0-pytest-cov` (6ff1643d8796, 31.7GB) is ready. User decides when/if to promote.

### Cross-repo MCP tool catalog audit (PIP TODO)

After Phase 1 lands the 5 commons MCP tools, audit + update consumer-facing documentation in every repo that references the cosa-voice MCP tool catalog. Filed at `<planning-is-prompting>/TODO.md`. Defer until step 8 closes the milestone.

## Read order for fresh session

1. **`00-index.md`** — milestone overview + Q-decision summary + Prior-art table
2. **This file** — what's done + what's next
3. **`02-phase1-file-commons-design.md`** §3 AC12 + §5 step 6 — the AC contracts step 6 must satisfy
4. **`90-execution-log.md`** — full execution status incl. steps 4 + 5 evidence sections

## Verification commands fresh session can run

```bash
# Confirm all prior steps still pass (full commons suite + branch gate)
PYTHONPATH=src:$PYTHONPATH /mnt/DATA01/include/www.deepily.ai/projects/lupin/src/cosa/.venv/bin/python \
  -m pytest src/tests/unit/commons/ -v \
  --cov=lupin_mcp.commons_persona_matcher \
  --cov=lupin_mcp.commons_store \
  --cov=lupin_mcp.commons_archival \
  --cov=lupin_mcp.commons_ask \
  --cov-branch --cov-fail-under=100

# Should report: 83 passed; 100% lines / 100% branches

# Confirm MCP tool registration still works (AC14)
PYTHONPATH=src:$PYTHONPATH /mnt/DATA01/include/www.deepily.ai/projects/lupin/src/cosa/.venv/bin/python \
  -m pytest src/tests/unit/commons/test_commons_mcp_subprocess.py -v
```

If both green, step 6 can begin.
