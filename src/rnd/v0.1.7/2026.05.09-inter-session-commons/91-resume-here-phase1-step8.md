# Resume Here — Phase 1 Step 8 (AC12 Config-Toggle Subprocess Test + Phase 1 Closure)

| Field | Value |
|---|---|
| **Created** | 2026-05-11 (session `9a4a601d`, Rachel 🕊️) |
| **Phase 1 progress** | Steps 3a + 3b + 4 + 5 + 6 + 7 CLOSED; step 8 is the final step before Phase 1 closure |
| **Read first** | `00-index.md` → this file → `02-phase1-file-commons-design.md` §3 AC12 + AC14 + §5 step 8 |
| **Supersedes** | `91-resume-here-phase1-step7.md` (step 7 is now closed) |

---

## What's done (steps 3a + 3b + 4 + 5 + 6 + 7)

| File | Status |
|---|---|
| `src/lupin_mcp/commons_persona_matcher.py` | ✅ + 12 tests + 100% lines/branches |
| `src/lupin_mcp/commons_store.py` | ✅ + 37 tests + 100% lines/branches |
| `src/lupin_mcp/commons_archival.py` | ✅ + 26 tests + 100% lines/branches |
| `src/lupin_mcp/commons_ask.py` | ✅ + 7 tests + 100% lines/branches |
| `src/lupin_mcp/cosa_voice_mcp.py` | ✅ MODIFIED — 5 tools + INI-driven config cache + daemon boot |
| `src/conf/lupin-app.ini` | ✅ 6 commons keys under `[Lupin: Baseline]` |
| `src/conf/lupin-app-splainer.ini` | ✅ 6 paired explanations |
| `src/tests/helpers/mcp_stdio_test_client.py` | ✅ reusable fastmcp stdio client |
| `src/tests/unit/commons/test_commons_mcp_subprocess.py` | ✅ AC14 happy-path verified |
| `src/tests/smoke/test_commons_two_session_roundtrip.py` | ✅ AC11 verified (3 tests, 0.51s) |

**Aggregate gate**:

```bash
PYTHONPATH=src:$PYTHONPATH /mnt/DATA01/include/www.deepily.ai/projects/lupin/src/cosa/.venv/bin/python \
  -m pytest src/tests/unit/commons/ src/tests/smoke/test_commons_two_session_roundtrip.py -v \
  --cov=lupin_mcp.commons_persona_matcher \
  --cov=lupin_mcp.commons_store \
  --cov=lupin_mcp.commons_archival \
  --cov=lupin_mcp.commons_ask \
  --cov-branch --cov-fail-under=100
```

Should report: **86 passed** (83 unit + 3 smoke); 100% coverage on the 4 commons modules.

## What's next (step 8)

Land `src/tests/unit/commons/test_commons_mcp_config_toggle_subprocess.py` per AC12. This is the final integration test before Phase 1 closure.

### AC12 contract (verbatim)

> "config-toggle subprocess test (per P2 A1 ratification): AI writes test INI with
>  `commons enabled=false`, spawns `python -m lupin_mcp.cosa_voice_mcp` test
>  subprocess via `subprocess.Popen` with stdio MCP transport, calls `list_tools`
>  and asserts commons tools NOT in response; kills subprocess; repeats with
>  `commons enabled=true` and asserts commons tools ARE present. Uses shared
>  MCP-stdio test helper."

### Tests required

1. **`test_ac12_commons_disabled_omits_tools`** — Spawn the MCP server with `commons enabled=false` injected via a custom INI; assert NONE of the 5 commons tools appear in `tools/list`; assert stderr contains `[commons] disabled — archival daemon NOT started`.
2. **`test_ac12_commons_enabled_registers_tools`** — Spawn with `commons enabled=true`; assert all 5 commons tools appear; assert stderr contains `[commons] archival daemon started`. (This is roughly the existing AC14 happy-path test, but with explicit INI injection rather than relying on the project default.)

### Mechanics — how to inject the test INI

The MCP server reads INI values via `ConfigurationManager(env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS")`. The env var contains CLI-args-style overrides. Two options:

**Option A — pass overrides via env var** (preferred):

```python
env[ "LUPIN_CONFIG_MGR_CLI_ARGS" ] = '{"commons enabled": "false"}'
```

Inspect `cosa.config.configuration_manager.ConfigurationManager.__init__` to confirm the env-var-decoded shape and how `cli_args` overrides INI values. The `cli_args` parameter at line 82 is the entry point.

**Option B — write a temp INI** (heavier, but ensures the INI lookup path is exercised end-to-end):

Write `commons enabled=false` into a tempfile INI; pass its path via `config_path=...` somehow. May require a wrapper script.

**Recommendation**: try Option A first. Fall back to B if `cli_args` doesn't support the override route cleanly.

### Stderr capture for daemon-start assertion

The `MCPStdioClient` already captures stderr in a PIPE (see `src/tests/helpers/mcp_stdio_test_client.py:43`). After closing the client, read `self.proc.stderr.read()` and assert the log line. But: stderr is consumed during error paths — may need to extract a method like `client.read_stderr_so_far()` or buffer it asynchronously. Inspect the helper before changing.

### Venue

`:7999` AI-discretionary — same bucket as AC14 (subprocess test, non-destructive, fast). Existing AC14 test runs in ~3s; AC12 will run in ~6s for 2 subprocess spawns.

### Coverage gate

Step 8 adds a new test file but does NOT extend the 100% coverage gate (it tests `cosa_voice_mcp.py`'s tool-registration logic, which is intentionally NOT in the 4-module coverage scope). The 4 commons modules must stay at 100%.

## Phase 1 closure (after step 8)

Once step 8 lands:

1. **Update `90-execution-log.md`** — all 8 steps closed; add a "Phase 1 milestone" section at the top.
2. **Update `00-index.md`** — Phase 1 status flips from 🟡 to ✅; supersede `91-resume-here-phase1-step8.md`.
3. **Write a Phase 1 closure post-mortem** at `src/rnd/v0.1.7/2026.05.09-inter-session-commons/92-phase1-closure.md` — what landed, what deferred, what was learned. Reference Phase 2 unblocked.
4. **Update `TODO.md`** — Phase 2 (user→all broadcast surface) becomes the next eligible task.
5. **Cross-repo MCP tool catalog audit** — file the long-standing `<planning-is-prompting>/TODO.md` follow-up to action.

## Open operational concerns

### Docker image promotion (unchanged)

Candidate `lupin:1.0.0-pytest-cov` is parked. User decides on promotion.

### `commons storage path` absolute-path support (deferred)

Phase 4 refactor target.

### Restart the cosa-voice MCP server in this session

The 5 new commons MCP tools are registered in source but NOT yet in the running cosa-voice subprocess for the current Claude Code session. To use them in the current session, the user needs to restart cosa-voice (or start a fresh Claude Code session). This is a USER-LEVEL operation per the prior CLAUDE.md MCP-restart guidance.

## Read order for fresh session

1. **`00-index.md`** — milestone overview + Q-decision summary
2. **This file** — what's done + what's next
3. **`02-phase1-file-commons-design.md`** §3 AC12 + AC14 + §5 step 8
4. **`90-execution-log.md`** — full execution history (steps 4-7 evidence)
5. **`src/cosa/config/configuration_manager.py`** §`__init__` + §`get` — for the `cli_args` env-var route used in step 8 test

## Verification commands fresh session can run

```bash
# Confirm all prior steps still pass (units + smoke + branch gate)
PYTHONPATH=src:$PYTHONPATH /mnt/DATA01/include/www.deepily.ai/projects/lupin/src/cosa/.venv/bin/python \
  -m pytest src/tests/unit/commons/ src/tests/smoke/test_commons_two_session_roundtrip.py -v \
  --cov=lupin_mcp.commons_persona_matcher \
  --cov=lupin_mcp.commons_store \
  --cov=lupin_mcp.commons_archival \
  --cov=lupin_mcp.commons_ask \
  --cov-branch --cov-fail-under=100

# Should report: 86 passed; 100% lines / 100% branches on 4 commons modules

# Hand-verify the daemon boot path
CLAUDE_SESSION_ID=test-session PYTHONPATH=src:$PYTHONPATH timeout 3 \
  /mnt/DATA01/include/www.deepily.ai/projects/lupin/src/cosa/.venv/bin/python \
  -m lupin_mcp.cosa_voice_mcp 2>&1 < /dev/null | grep "archival daemon"
```

If both green, step 8 can begin.
