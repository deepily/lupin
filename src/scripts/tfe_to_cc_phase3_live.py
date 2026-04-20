#!/usr/bin/env python3
"""
TFE-to-CC Phase 3 LIVE run — full 11-fix set from tfe-72adc928 baseline.

Dispatches one bounded `claude -p` with a coordinator + Task-subagent prompt
against a fresh git worktree. Tools: Read, Edit, Write, Bash, Grep, Glob,
Task, + full cosa-voice MCP allowlist (notify for breadcrumbs, ask_yes_no /
ask_multiple_choice for mid-flight escalation). Blocking MCP enabled per
user direction so they can be pinged on bluetooth while watching a movie.

Usage:
    PYTHONPATH=src:$PYTHONPATH python3 src/scripts/tfe_to_cc_phase3_live.py

Paired design/log:
    src/rnd/v0.1.6/2026.04.10-test-fix-expediter/19-tfe-to-cc-design.md
    src/rnd/v0.1.6/2026.04.10-test-fix-expediter/21-tfe-to-cc-phase3-live-test.md
"""

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


_PROJECT_ROOT = Path( __file__ ).resolve().parent.parent.parent
sys.path.insert( 0, str( _PROJECT_ROOT / "src" ) )

from cosa.agents.tfe_to_cc.prompts.bundle_phase3 import build_fix_bundle_prompt
from cosa.agents.tfe_to_cc.prompts.output_contract import (
    parse_result_block,
    validate_result_payload,
    parse_result_from_git_log,
)


CONTAINER        = "lupin-rest-test"
MODEL            = "claude-sonnet-4-6"    # testing-mode override; production default is opus-4-7
MAX_TURNS        = 200                    # coordinator budget; subagents have their own internal budgets
WALL_CLOCK_LIMIT = 3600                   # 1 hour — user is watching a movie
EXECUTION_LOG    = (
    _PROJECT_ROOT
    / "src/rnd/v0.1.6/2026.04.10-test-fix-expediter/21-tfe-to-cc-phase3-live-test.md"
)


# ────────────────────────────────────────────────────────────────────────
# The 11 selected proposals from tfe-a1c6e15a's Phase 2 voice gate
# (operator CBR-predicted; same baseline we've been running end-to-end)
# ────────────────────────────────────────────────────────────────────────

SELECTED_FIXES = [
    {
        "cluster_id"    : "C1",
        "title"         : "Re-capture all 12 visual baselines with current fixture",
        "fix_type"      : "test_patch",
        "confidence"    : 0.90,
        "target_files"  : [
            "io/test-suite/visual-baselines/test_visual_regression/test_visual_page/",
            "src/tests/e2e_ui/conftest.py",
        ],
        "failing_tests" : [ "test_visual_page" ],
        "description"   : (
            "The 12 baseline PNGs in `io/test-suite/visual-baselines/test_visual_regression/test_visual_page/` "
            "were captured before `browser_type_launch_args` in `src/tests/e2e_ui/conftest.py` was modified. "
            "Recapture baselines by running `pytest --update-snapshots -k visual` (or the project wrapper "
            "`./src/scripts/run-e2e-ui-tests.sh --bg --update-snapshots -k visual`), then commit the refreshed PNGs. "
            "NOTE: this is an EXPENSIVE fix that runs a full Chromium playwright suite. If you don't have "
            "Chromium/playwright easily runnable in this context, you may report verdict=\"unclear\" with a note "
            "that this fix requires an interactive update-snapshots run and skip rather than force."
        ),
    },
    {
        "cluster_id"    : "C2",
        "title"         : "Add missing PRODUCT_NAMES entry for TFE Resume agent",
        "fix_type"      : "code_patch",
        "confidence"    : 0.97,
        "target_files"  : [ "src/cosa/rest/todo_fifo_queue.py" ],
        "failing_tests" : [ "test_all_agentic_agents_have_product_names" ],
        "description"   : (
            "The `PRODUCT_NAMES` class-level dict in `TodoFifoQueue` (lines 941-951 of `todo_fifo_queue.py`) is "
            "missing the key `'agent router go to test fix expediter resume'` that was introduced in "
            "`agent_registry.py` line 251. The test `test_all_agentic_agents_have_product_names` iterates every "
            "key in `AGENTIC_AGENTS` and asserts a matching `PRODUCT_NAMES` entry exists. Add the display name "
            "`'Test Fix Expediter Resume (resume a stalled TFE job)'` to the `PRODUCT_NAMES` dict."
        ),
    },
    {
        "cluster_id"    : "C3",
        "title"         : "Fix stale AGENTIC_AGENTS count assertions (9\u219210)",
        "fix_type"      : "test_patch",
        "confidence"    : 0.97,
        "target_files"  : [
            "src/tests/unit/test_deep_research_to_presentation.py",
            "src/tests/unit/test_runtime_argument_expeditor.py",
            "src/cosa/agents/runtime_argument_expeditor/agent_registry.py",
        ],
        "failing_tests" : [ "test_registry_agent_count", "test_registry_has_nine_agents" ],
        "description"   : (
            "A 10th agent was added to `AGENTIC_AGENTS` in `agent_registry.py` after the count-guard assertions "
            "were last written. Grep reveals the stale literal `== 9` in three places: the directly failing test "
            "(`test_deep_research_to_presentation.py:386`), a parallel test file "
            "(`test_runtime_argument_expeditor.py:365`), and the production `quick_smoke_test()` helper "
            "(`agent_registry.py:429`). Update all three to `== 10`. Note: the current file may show different "
            "test-name or literal due to prior TFE runs\u2014use Read to verify actual state before editing."
        ),
    },
    {
        "cluster_id"    : "C3b",
        "title"         : "Fix stale count in failing test only (minimal scope)",
        "fix_type"      : "test_patch",
        "confidence"    : 0.97,
        "target_files"  : [ "src/tests/unit/test_deep_research_to_presentation.py" ],
        "failing_tests" : [ "test_registry_agent_count" ],
        "description"   : (
            "Narrower variant of C3: touch only `src/tests/unit/test_deep_research_to_presentation.py` line 386. "
            "Update `assert len( AGENTIC_AGENTS ) == 9` to `== 10`. NOTE: C3 above may already have landed this "
            "file's change. If the file already asserts `== 10`, verdict=\"unclear\" with note \"superseded by C3\"."
        ),
    },
    {
        "cluster_id"    : "C4",
        "title"         : "Add resume_from to all_agents union profile in config.py",
        "fix_type"      : "code_patch",
        "confidence"    : 0.97,
        "target_files"  : [ "src/cosa/agents/notification_proxy/config.py" ],
        "failing_tests" : [ "test_all_agents_profile_covers_all_arg_names" ],
        "description"   : (
            "The `all_agents` profile (lines 97-118) must contain an answer for every `fallback_questions` key "
            "across all registered agents. The new entry `'agent router go to test fix expediter resume'` added "
            "`resume_from` as a fallback_question, but it's missing from `all_agents`. Add the line "
            "`\"resume_from\" : \"tfe-mock1234::user1\"` after the existing `\"dead_job_id\"` entry (~line 113), "
            "matching the existing pattern of mock values."
        ),
    },
    {
        "cluster_id"    : "C5",
        "title"         : "Remove stale icon_only/before_after assertions from placeholder test",
        "fix_type"      : "test_patch",
        "confidence"    : 0.97,
        "target_files"  : [ "src/tests/unit/test_presentation_visual_renderer.py" ],
        "failing_tests" : [ "test_placeholder_supported_types" ],
        "description"   : (
            "The test `test_placeholder_supported_types` still asserts that `PlaceholderRenderer.SUPPORTED_TYPES` "
            "contains `'icon_only'` and `'before_after'`, but those two types were intentionally moved to "
            "`NanoBananaRenderer`. Delete the stale assertion lines (around lines 80-81), leaving the still-valid "
            "`'screenshot'` assertion on line 79."
        ),
    },
    {
        "cluster_id"    : "C5b",
        "title"         : "Extend NanoBanana test to cover relocated icon_only/before_after types",
        "fix_type"      : "test_patch",
        "confidence"    : 0.90,
        "target_files"  : [ "src/tests/unit/test_presentation_visual_renderer.py" ],
        "failing_tests" : [ "test_placeholder_supported_types" ],
        "description"   : (
            "Companion to C5: in addition to removing the stale placeholder assertions (C5), extend the existing "
            "`NanoBananaRenderer` SUPPORTED_TYPES test block (around lines 143-148) to assert that `'icon_only'` "
            "and `'before_after'` are present in `NanoBananaRenderer.SUPPORTED_TYPES`. This prevents a silent "
            "coverage gap after the refactor. NOTE: if C5 has already landed, only the NanoBanana extension "
            "part remains\u2014inspect the file first."
        ),
    },
    {
        "cluster_id"    : "C6",
        "title"         : "Update stale agent-count assertion from 9 to 10",
        "fix_type"      : "test_patch",
        "confidence"    : 0.97,
        "target_files"  : [
            "src/tests/unit/test_runtime_argument_expeditor.py",
            "src/cosa/agents/runtime_argument_expeditor/agent_registry.py",
        ],
        "failing_tests" : [ "test_registry_has_nine_agents" ],
        "description"   : (
            "The test `test_registry_has_nine_agents` was written when the registry had 9 entries. Update both "
            "the assertion value AND the test name/docstring to reflect the current count of 10. Also update the "
            "smoke test in `agent_registry.py:429` to match. "
            "NOTE: current file state may already show `_five_agents` asserting `== 5` due to prior TFE partial "
            "edits\u2014use Read first to discover what's actually there, then update the number that's there "
            "to 10 (whether starting from 5 or 9)."
        ),
    },
    {
        "cluster_id"    : "C8",
        "title"         : "Restore stop.py hook path and add delete-btn to renderHistoryActions",
        "fix_type"      : "code_patch",
        "confidence"    : 0.92,
        "target_files"  : [
            "src/lupin_cli/claude_code/hooks/stop.py",
            "src/fastapi_app/static/js/notifications.js",
        ],
        "failing_tests" : [ "TestVoiceBlocking", "TestNotifyUserSync" ],
        "description"   : (
            "Two independent code bugs. (1) In `stop.py` around lines 344-350, the "
            "`_should_ask_anything_else` / `_ask_anything_else` / `notify_user_sync` branch was commented out "
            "with a `# disable temporarily` marker, causing `main()` to always emit `{}`. Restore the original "
            "if/else block by removing the comment markers + the `emit_json({})` short-circuit. "
            "(2) In `notifications.js` `renderHistoryActions()` (lines ~6089-6113), a guard `if ( !canRetry ) "
            "return ''` prevents any buttons from rendering for completed/pending jobs. Remove the early-return; "
            "always emit a `.delete-btn` calling `deleteHistoryJob`; conditionally emit `.retry-btn` when "
            "`canRetry` is true."
        ),
    },
    {
        "cluster_id"    : "C8b",
        "title"         : "Restore commented-out _ask_anything_else branch in stop.py",
        "fix_type"      : "code_patch",
        "confidence"    : 0.92,
        "target_files"  : [ "src/lupin_cli/claude_code/hooks/stop.py" ],
        "failing_tests" : [ "TestVoiceBlocking", "TestNotifyUserSync" ],
        "description"   : (
            "Narrower variant of C8 Part (1) only: remove the `# disable temporarily` comment markers and the "
            "bare `emit_json({})` replacement at lines 344-350, restoring the original conditional logic. "
            "NOTE: if C8 has already fixed this, file will reflect the restoration; verdict=\"unclear\" and note "
            "\"superseded by C8\"."
        ),
    },
    {
        "cluster_id"    : "C8c",
        "title"         : "Fix renderHistoryActions to always emit .delete-btn",
        "fix_type"      : "code_patch",
        "confidence"    : 0.92,
        "target_files"  : [ "src/fastapi_app/static/js/notifications.js" ],
        "failing_tests" : [ "renderHistoryActions" ],
        "description"   : (
            "Narrower variant of C8 Part (2) only: remove the early `if ( !canRetry ) return ''` guard in "
            "`renderHistoryActions()` (around lines 6089-6113 of `notifications.js`), restructure to always emit "
            "a `.delete-btn` via `window.notificationsUI.deleteHistoryJob(job.id_hash)`, and keep `.retry-btn` "
            "conditional on `canRetry`. NOTE: if C8 landed, this may already be done\u2014verdict=\"unclear\" "
            "and note \"superseded by C8\" if so."
        ),
    },
]


# Diagnoses pulled from Phase 1 results (the completed tfe-a1c6e15a report's
# per-cluster diagnoses captured during earlier runs).
DIAGNOSES = {
    "C1"  : {
        "root_cause"    : "The session-scoped `browser_type_launch_args` fixture in `src/tests/e2e_ui/conftest.py` was modified after visual baselines were captured; new Chromium flags subtly alter font/subpixel rendering.",
        "error_category": "fixture_bug",
    },
    "C2"  : {
        "root_cause"    : "A new agent entry `'agent router go to test fix expediter resume'` was added to `AGENTIC_AGENTS` in `agent_registry.py`, but the parallel `PRODUCT_NAMES` dict was not updated.",
        "error_category": "code_bug",
    },
    "C3"  : {
        "root_cause"    : "The test `test_registry_agent_count` has a stale hardcoded assertion `assert len(AGENTIC_AGENTS) == 9`, but the registry now contains 10 entries.",
        "error_category": "test_bug",
    },
    "C3b" : {
        "root_cause"    : "Same root cause as C3, narrower scope (single file).",
        "error_category": "test_bug",
    },
    "C4"  : {
        "root_cause"    : "The new agent's `resume_from` fallback question key is missing from the `all_agents` union profile in `config.py`.",
        "error_category": "code_bug",
    },
    "C5"  : {
        "root_cause"    : "Test asserts `PlaceholderRenderer.SUPPORTED_TYPES` contains types that were intentionally moved to `NanoBananaRenderer`.",
        "error_category": "test_bug",
    },
    "C5b" : {
        "root_cause"    : "Companion to C5; relocated types need explicit test coverage in the NanoBanana block.",
        "error_category": "test_bug",
    },
    "C6"  : {
        "root_cause"    : "Test `test_registry_has_nine_agents` was written when registry had 9 entries; it now has 10. Test name + assertion value both stale.",
        "error_category": "test_bug",
    },
    "C8"  : {
        "root_cause"    : "Two independent code bugs: (1) stop.py main() branch commented out disabling voice-blocking path; (2) notifications.js renderHistoryActions early-return prevents .delete-btn from rendering.",
        "error_category": "code_bug",
    },
    "C8b" : {
        "root_cause"    : "Subset of C8: just the stop.py commented-out branch.",
        "error_category": "code_bug",
    },
    "C8c" : {
        "root_cause"    : "Subset of C8: just the notifications.js renderHistoryActions early-return.",
        "error_category": "code_bug",
    },
}


# ────────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────────

def _ts() -> str:
    return datetime.now( timezone.utc ).strftime( "%Y%m%dT%H%M%SZ" )


def _banner( title: str ) -> None:
    print( "", flush=True )
    print( "=" * 72, flush=True )
    print( f"  {title}", flush=True )
    print( "=" * 72, flush=True )


def _create_smoke_worktree() -> str:
    """Create a fresh worktree off origin/main inside the container. Returns container path."""
    ts = _ts()
    name = f"phase3-live-{ts}"
    container_path = f"/var/lupin/.claude/worktrees/{name}"
    proc = subprocess.run(
        [
            "docker", "exec", CONTAINER, "sh", "-c",
            f"cd /var/lupin && git worktree add {container_path} origin/main",
        ],
        capture_output=True, text=True, timeout=60,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"Failed to create worktree: rc={proc.returncode} "
            f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
        )
    print( f"[HARNESS] Worktree created: {container_path}", flush=True )
    return container_path


def _write_prompt_to_container( prompt: str, host_scratch: Path ) -> tuple:
    """Write prompt to container AND persist a host-side copy for reflection."""
    ts = _ts()
    container_path = f"/tmp/tfe_to_cc_phase3_prompt_{ts}.md"
    host_path      = host_scratch / f"tfe_to_cc_phase3_prompt_{ts}.md"
    proc = subprocess.run(
        [ "docker", "exec", "-i", CONTAINER, "sh", "-c", f"cat > {container_path}" ],
        input=prompt.encode( "utf-8" ),
        capture_output=True, timeout=15,
    )
    if proc.returncode != 0:
        raise RuntimeError( f"Failed to write prompt to container: {proc.stderr!r}" )
    host_path.write_text( prompt )
    print( f"[HARNESS] Prompt {len( prompt )} bytes → container: {container_path} | host: {host_path}", flush=True )
    return container_path, host_path


def _invoke_claude_p( container_prompt_path: str, worktree_path: str,
                      stream_out: Path, stderr_out: Path ) -> int:
    """Invoke the coordinator claude -p with full Phase 3 allowlist."""
    cmd = [
        "docker", "exec",
        "-w", worktree_path,
        CONTAINER, "sh", "-c",
        (
            f'claude -p "$(cat {container_prompt_path})" '
            f'--model {MODEL} '
            f'--output-format stream-json '
            f'--verbose '
            f'--max-turns {MAX_TURNS} '
            f'--allowedTools "Read Edit Write Bash Grep Glob Task TodoWrite '
            f'mcp__cosa-voice__notify mcp__cosa-voice__ask_yes_no mcp__cosa-voice__ask_multiple_choice" '
            f'--disallowedTools "mcp__cosa-voice__converse mcp__cosa-voice__ask_open_ended_batch WebSearch WebFetch"'
        ),
    ]
    print( f"[HARNESS] Dispatching coordinator (max_turns={MAX_TURNS}, timeout={WALL_CLOCK_LIMIT}s)...", flush=True )
    start = time.time()
    with open( stream_out, "wb" ) as out, open( stderr_out, "wb" ) as err:
        try:
            proc = subprocess.run( cmd, stdout=out, stderr=err, timeout=WALL_CLOCK_LIMIT )
        except subprocess.TimeoutExpired:
            print( f"[HARNESS] TIMEOUT after {WALL_CLOCK_LIMIT}s", flush=True )
            return -1
    duration = time.time() - start
    print( f"[HARNESS] Exit code {proc.returncode} | duration {duration:.1f}s", flush=True )
    return proc.returncode


def _parse_stream( path: Path ) -> dict:
    summary: dict = {
        "api_key_source"  : None,
        "model"           : None,
        "result"          : None,
        "assistant_text"  : "",
        "tool_use_count"  : 0,
        "tool_use_names"  : {},   # name → count
        "rate_limit_info" : None,
        "raw_event_count" : 0,
        "parse_errors"    : 0,
    }
    chunks: list = []
    with open( path ) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            summary[ "raw_event_count" ] += 1
            try:
                obj = json.loads( line )
            except json.JSONDecodeError:
                summary[ "parse_errors" ] += 1
                continue
            t = obj.get( "type" )
            if t == "system" and obj.get( "subtype" ) == "init":
                summary[ "api_key_source" ] = obj.get( "apiKeySource" )
                summary[ "model" ] = obj.get( "model" )
            elif t == "assistant":
                msg = obj.get( "message" ) or {}
                for block in msg.get( "content", [] ) or []:
                    btype = block.get( "type" )
                    if btype == "text":
                        chunks.append( block.get( "text" ) or "" )
                    elif btype == "tool_use":
                        name = block.get( "name" ) or "?"
                        summary[ "tool_use_count" ] += 1
                        summary[ "tool_use_names" ][ name ] = summary[ "tool_use_names" ].get( name, 0 ) + 1
            elif t == "rate_limit_event":
                summary[ "rate_limit_info" ] = obj.get( "rate_limit_info" )
            elif t == "result":
                summary[ "result" ] = obj
    summary[ "assistant_text" ] = "\n".join( chunks )
    return summary


def _git_log_worktree( worktree_path: str ) -> str:
    proc = subprocess.run(
        [
            "docker", "exec", CONTAINER, "sh", "-c",
            f"cd {worktree_path} && git log --oneline origin/main..HEAD 2>&1",
        ],
        capture_output=True, text=True, timeout=15,
    )
    return proc.stdout if proc.returncode == 0 else ""


def _git_diff_stat( worktree_path: str ) -> str:
    proc = subprocess.run(
        [
            "docker", "exec", CONTAINER, "sh", "-c",
            f"cd {worktree_path} && git diff --stat origin/main 2>&1",
        ],
        capture_output=True, text=True, timeout=15,
    )
    return proc.stdout if proc.returncode == 0 else ""


def _append_to_execution_log( section_md: str ) -> None:
    existing = EXECUTION_LOG.read_text() if EXECUTION_LOG.exists() else (
        "# 21 — TFE-to-CC Phase 3 (Apply Fixes) — Live Test Execution Log\n\n"
        "**Paired design**: `19-tfe-to-cc-design.md`\n"
        "**Paired Phase 1 log**: `20-tfe-to-cc-phase1-live-test.md`\n\n"
        "---\n"
    )
    EXECUTION_LOG.write_text( existing.rstrip() + "\n\n" + section_md.rstrip() + "\n" )
    print( f"[HARNESS] Execution log: {EXECUTION_LOG}", flush=True )


def _send_high_priority_notify( message: str, abstract: str ) -> None:
    """Send urgent notification via cosa-voice MCP HTTP route (the same pipe CC uses)."""
    # We post directly to the Lupin REST notify endpoint with response_requested=false
    # to avoid blocking. Uses the same test-server auth path the harness script opened.
    try:
        import urllib.request, urllib.parse
        params = {
            "message"           : message,
            "type"              : "task",
            "priority"          : "urgent",
            "target_user"       : os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL", "ricardo.felipe.ruiz@gmail.com" ),
            "sender_id"         : "tfe-to-cc-phase3-harness@lupin.deepily.ai",
            "abstract"          : abstract,
        }
        # We need auth. Reuse the test-env login.
        email    = os.environ[ "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL" ]
        password = os.environ[ "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" ]
        req = urllib.request.Request(
            "http://localhost:8000/auth/login",
            data = json.dumps( { "email": email, "password": password } ).encode(),
            headers = { "Content-Type": "application/json" },
        )
        token = json.loads( urllib.request.urlopen( req, timeout=10 ).read() )[ "tokens" ][ "access_token" ]
        qs = urllib.parse.urlencode( params )
        req = urllib.request.Request(
            f"http://localhost:8000/api/notify?{qs}",
            data = b"", method = "POST",
            headers = { "Authorization": f"Bearer {token}" },
        )
        urllib.request.urlopen( req, timeout=10 ).read()
        print( "[HARNESS] High-priority notification sent.", flush=True )
    except Exception as e:
        print( f"[HARNESS] Notification send failed: {e}", flush=True )


# ────────────────────────────────────────────────────────────────────────
# Main
# ────────────────────────────────────────────────────────────────────────

def main() -> int:
    _banner( f"TFE-to-CC Phase 3 LIVE — {len( SELECTED_FIXES )} fixes" )

    scratch = Path( "/tmp" )
    stream_path = scratch / f"tfe-to-cc-phase3-stream-{_ts()}.jsonl"
    stderr_path = scratch / f"tfe-to-cc-phase3-stderr-{_ts()}.log"

    # 1. Create fresh worktree
    worktree = _create_smoke_worktree()

    # 2. Build prompt
    prompt = build_fix_bundle_prompt(
        selected_fixes       = SELECTED_FIXES,
        diagnoses            = DIAGNOSES,
        worktree_path        = worktree,
        source_suite         = "ts-d3df4d87 (tfe-72adc928 baseline; 11-fix CBR-predicted set)",
        emit_breadcrumbs     = True,
        allow_mcp_escalation = True,
    )

    # 3. Write prompt to container + persist host copy (for reflection later)
    container_prompt_path, host_prompt_path = _write_prompt_to_container( prompt, scratch )

    # 4. Dispatch coordinator
    exit_code = _invoke_claude_p( container_prompt_path, worktree, stream_path, stderr_path )

    # 5. Parse
    summary = _parse_stream( stream_path )

    # 6. Extract tfe-result JSON (primary) or fall back to git log
    parsed = parse_result_block( summary[ "assistant_text" ] )
    fallback_used = False
    if parsed is None:
        git_log = _git_log_worktree( worktree )
        parsed = parse_result_from_git_log(
            git_log,
            expected_cluster_ids=[ f[ "cluster_id" ] for f in SELECTED_FIXES ],
        )
        fallback_used = parsed is not None

    validation_ok, validation_issues = validate_result_payload( parsed )

    # 7. Cross-check: for each verdict=fixed cluster, verify a commit exists
    git_log = _git_log_worktree( worktree )
    diff_stat = _git_diff_stat( worktree )

    # 8. Compute headline numbers
    result = summary.get( "result" ) or {}
    if parsed and parsed.get( "clusters" ):
        fixed_count = sum(
            1 for c in parsed[ "clusters" ].values()
            if isinstance( c, dict ) and c.get( "verdict" ) == "fixed"
        )
    else:
        fixed_count = 0

    # 9. Build execution log section
    ts_now = datetime.now().astimezone().isoformat( timespec="seconds" )
    lines: list = [
        f"### {ts_now} — LIVE {len( SELECTED_FIXES )}-fix run",
        "",
        f"**Worktree**: `{worktree}`",
        f"**Prompt**: {len( prompt )} bytes | host: `{host_prompt_path}` | container: `{container_prompt_path}`",
        f"**Stream**: `{stream_path}`",
        "",
        "**SDK/CC path confirmation**:",
        f"- apiKeySource: `{summary.get( 'api_key_source' )}`",
        f"- model: `{summary.get( 'model' )}`",
        "",
        "**Outcome**:",
        f"- Exit code: `{exit_code}`",
        f"- result.subtype: `{result.get( 'subtype' )}`",
        f"- result.is_error: `{result.get( 'is_error' )}`",
        f"- result.num_turns (coordinator): `{result.get( 'num_turns' )}`",
        f"- result.duration_ms: `{result.get( 'duration_ms' )}`",
        f"- result.total_cost_usd (informational): `{result.get( 'total_cost_usd' )}`",
        f"- Raw event count: {summary.get( 'raw_event_count' )}",
        f"- Tool use count: {summary.get( 'tool_use_count' )}",
        f"- Tool breakdown: {summary.get( 'tool_use_names' )}",
        "",
        f"**Verdict**: **{fixed_count} / {len( SELECTED_FIXES )} fixes landed** (vs. SDK path's 0/11 baseline)",
        f"- Parser: {'fallback (git log)' if fallback_used else 'primary (tfe-result fence)'}",
        f"- Validation OK: {validation_ok}",
    ]
    if validation_issues:
        lines.append( "- Validation issues:" )
        for i in validation_issues:
            lines.append( f"    - {i}" )
    lines.append( "" )
    if parsed:
        lines.append( "**Per-cluster verdicts**:" )
        lines.append( "" )
        lines.append( "```json" )
        lines.append( json.dumps( parsed, indent=2 ) )
        lines.append( "```" )
        lines.append( "" )
    lines.append( "**Git state in worktree**:" )
    lines.append( "" )
    lines.append( "```" )
    lines.append( f"$ git log --oneline origin/main..HEAD" )
    lines.append( git_log.strip() or "(no commits)" )
    lines.append( "" )
    lines.append( f"$ git diff --stat origin/main" )
    lines.append( diff_stat.strip() or "(no diffs)" )
    lines.append( "```" )

    _append_to_execution_log( "\n".join( lines ) )

    # 10. High-priority notification to user
    msg = f"TFE-to-CC Phase 3 complete: {fixed_count}/{len( SELECTED_FIXES )} fixes landed"
    abstract = (
        f"**Run**: {len( SELECTED_FIXES )}-fix parallel dispatch via `claude -p` + Task subagents\n"
        f"**Worktree**: `{worktree}`\n"
        f"**Coordinator**: {result.get( 'num_turns' )} turns, "
        f"{(result.get( 'duration_ms' ) or 0) / 1000:.0f}s wall\n"
        f"**Tool budget breakdown**: {summary.get( 'tool_use_names' )}\n"
        f"**Exit code**: {exit_code}\n"
        f"**apiKeySource**: {summary.get( 'api_key_source' )}\n"
        f"**Headline**: {fixed_count}/{len( SELECTED_FIXES )} fixes landed "
        f"(SDK baseline tfe-a1c6e15a was 0/11)\n\n"
        f"Full analysis + per-cluster JSON verdicts in "
        f"`src/rnd/v0.1.6/2026.04.10-test-fix-expediter/21-tfe-to-cc-phase3-live-test.md`.\n"
        f"Worktree preserved at `.claude/worktrees/{worktree.split( '/' )[-1]}/` for review."
    )
    _send_high_priority_notify( msg, abstract )

    # Console summary
    _banner( "SUMMARY" )
    print( f"Fixed: {fixed_count} / {len( SELECTED_FIXES )}", flush=True )
    print( f"Parser: {'fallback' if fallback_used else 'primary'}", flush=True )
    print( f"Validation: {'OK' if validation_ok else 'ISSUES'}", flush=True )

    return 0 if ( fixed_count > 0 and validation_ok ) else 1


if __name__ == "__main__":
    sys.exit( main() )
