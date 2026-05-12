# Resume Here — Phase 1 Step 7 (Two-Session Smoke Test)

| Field | Value |
|---|---|
| **Created** | 2026-05-11 (session `9a4a601d`, Rachel 🕊️) |
| **Phase 1 progress** | Steps 3a + 3b + 4 + 5 + 6 CLOSED; steps 7-8 remain |
| **Read first** | `00-index.md` → this file → `02-phase1-file-commons-design.md` §3 AC11 + §5 step 7 |
| **Supersedes** | `91-resume-here-phase1-step6.md` (step 6 is now closed) |

---

## What's done (steps 3a + 3b + 4 + 5 + 6)

| File | Status |
|---|---|
| `src/lupin_mcp/commons_persona_matcher.py` | ✅ + 12 tests + 100% lines/branches |
| `src/lupin_mcp/commons_store.py` | ✅ + 37 tests + 100% lines/branches |
| `src/lupin_mcp/commons_archival.py` | ✅ + 26 tests + 100% lines/branches |
| `src/lupin_mcp/commons_ask.py` | ✅ + 7 tests + 100% lines/branches |
| `src/lupin_mcp/cosa_voice_mcp.py` | ✅ MODIFIED — 5 `@mcp.tool` shims + ConfigurationManager-driven config cache + archival daemon boot wired to `__main__` |
| `src/conf/lupin-app.ini` | ✅ 6 commons keys under `[Lupin: Baseline]` |
| `src/conf/lupin-app-splainer.ini` | ✅ 6 paired explanations |
| `src/tests/helpers/mcp_stdio_test_client.py` | ✅ reusable fastmcp stdio subprocess client |
| `src/tests/unit/commons/test_commons_*.py` | ✅ 83 tests under `--cov-branch --cov-fail-under=100` |

**Full commons suite gate** (verify before starting step 7):

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

## What's next (step 7)

Land `src/tests/smoke/test_commons_two_session_roundtrip.py` per AC11.

### AC11 contract (verbatim)

> "two child Python processes (each with distinct persona) directly import
>  `CommonsStore`, both pointed at a shared `tempfile.TemporaryDirectory()`.
>  One posts to `coordination` topic, the other reads and verifies the entry.
>  **No server dependency** — pure local file I/O via tempdir. **Venue:
>  `:7999` AI-discretionary** (per the §TESTING VENUES rubric: non-destructive,
>  fast, isolated; MCP layer bypassed for Phase 1 smoke per T3 ratification —
>  direct `CommonsStore` tests the file-store + matcher + frontmatter logic;
>  MCP-tool-registration end-to-end coverage handled separately by AC12 +
>  AC14 via subprocess-spawn helper)."

### Suggested shape

```python
# src/tests/smoke/test_commons_two_session_roundtrip.py
import subprocess
import sys
import tempfile
from pathlib import Path

def _spawn_poster(tmpdir, persona_name, persona_icon, persona_color, body):
    """Spawn a child Python that posts a single entry to the `coordination` topic."""
    code = f'''
from lupin_mcp.commons_store import CommonsStore
store = CommonsStore({tmpdir!r})
store.post(
    topic="coordination", body={body!r},
    sender_session_id="poster-session",
    persona_name={persona_name!r},
    persona_icon={persona_icon!r},
    persona_color={persona_color!r},
    metadata={{ "kind": "status" }},
)
'''
    return subprocess.run([sys.executable, "-c", code], env={ "PYTHONPATH": "src:" + (... or "") }, check=True)

def test_two_session_roundtrip_via_commons_store():
    with tempfile.TemporaryDirectory() as tmp:
        _spawn_poster(tmp, "Maria", "🌸", "#A040A0", "hello from Maria")
        # Now spawn a reader process and capture its output...
```

Prior art: `src/tests/unit/commons/test_commons_store.py::test_ac10b_real_fcntl_concurrent_append` already uses the multi-process pattern (5 procs × 100 posts). Use it as the template.

### Tests required

1. **`test_two_session_roundtrip`** — Process A posts, Process B reads + asserts entry visible with correct persona/body/metadata.
2. **`test_two_session_distinct_personas`** — Process A (Maria 🌸) posts, Process B (Tiberius 🌑) posts; main process reads + asserts both entries present with distinct persona stamps.
3. **Optional**: `test_two_session_question_answer_roundtrip` — Process A posts a question via `commons_ask.ask_async`; Process B reads + posts a reply with `metadata.in_reply_to`; main asserts the correlation is visible via `_find_replies`.

### Venue

`:7999` AI-discretionary (per AC11). No server hit — pure local file I/O via tempdir.

### Coverage gate

Step 7 doesn't extend the 100% coverage gate (smoke tests live in `src/tests/smoke/`, separate from `src/tests/unit/commons/`). But if step 7 introduces any new code in `src/lupin_mcp/`, it needs to keep the gate at 100%.

## Step 8 (after 7)

AC12 config-toggle subprocess test: spawn `python -m lupin_mcp.cosa_voice_mcp` with `commons enabled=false` injected via a test INI; assert commons tools NOT in `tools/list`; assert daemon does NOT start (check stderr does NOT contain "[commons] archival daemon started"); repeat with `commons enabled=true` and assert both ARE present. Reuses `tests/helpers/mcp_stdio_test_client.py` (already in place). Also covers AC14 final verification.

The tricky part of step 8: spawning the MCP subprocess with a *test* INI so `commons enabled=false` actually takes effect. This requires either (a) `LUPIN_CONFIG_MGR_CLI_ARGS` env var pointing at a test config, or (b) directly setting the env var to JSON CLI args. Inspect `cosa.config.configuration_manager.ConfigurationManager.__init__` for the supported routes.

## Open operational concerns (unchanged from step 6 resume)

### Docker image promotion

Candidate `lupin:1.0.0-pytest-cov` still parked; user decides on promotion.

### Cross-repo MCP tool catalog audit (PIP TODO)

After Phase 1 lands the 5 commons MCP tools, audit + update consumer-facing documentation in every repo that references the cosa-voice MCP tool catalog. Filed at `<planning-is-prompting>/TODO.md`. Defer until step 8 closes the milestone.

### `commons storage path` absolute-path support (deferred follow-up)

`_commons_storage_root()` currently treats the INI value as relative to `LUPIN_ROOT` (with the `/io/commons` default pass-through). Phase 4 (Postgres-backed commons + Multiplexer Commons tab) is the natural place to refactor for absolute-path support if needed.

## Read order for fresh session

1. **`00-index.md`** — milestone overview + Q-decision summary + Prior-art table
2. **This file** — what's done + what's next
3. **`02-phase1-file-commons-design.md`** §3 AC11 + §5 step 7 — the AC contract step 7 must satisfy
4. **`90-execution-log.md`** — full execution status including the step 4/5/6 evidence sections

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

# Hand-verify the daemon boot path (should print "[commons] archival daemon started")
CLAUDE_SESSION_ID=test-session PYTHONPATH=src:$PYTHONPATH timeout 3 \
  /mnt/DATA01/include/www.deepily.ai/projects/lupin/src/cosa/.venv/bin/python \
  -m lupin_mcp.cosa_voice_mcp 2>&1 < /dev/null | grep "archival daemon"
```

If all three green, step 7 can begin.
