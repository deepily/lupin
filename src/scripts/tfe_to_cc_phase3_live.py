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

import argparse
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
DEFAULT_MODEL    = "claude-sonnet-4-6"    # production default (matrix 23-* winner 2026-04-20: 5× Opus on this workload); override via --model
DEFAULT_EFFORT   = "high"                 # extended-thinking effort; override via --effort (low/medium/high/xhigh/max/none)
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
            "src/lupin_app/static/js/notifications.js",
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
        "target_files"  : [ "src/lupin_app/static/js/notifications.js" ],
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


def _invoke_claude_p(
    container_prompt_path : str,
    worktree_path         : str,
    stream_out            : Path,
    stderr_out            : Path,
    model                 : str,
    effort                : str,
    max_budget_usd        : float | None,
) -> int:
    """Invoke the coordinator claude -p with full Phase 3 allowlist."""
    flags = [
        f'--model {model}',
        '--output-format stream-json',
        '--verbose',
        f'--max-turns {MAX_TURNS}',
    ]
    if effort and effort != "none":
        flags.append( f'--effort {effort}' )
    if max_budget_usd is not None:
        flags.append( f'--max-budget-usd {max_budget_usd}' )
    flags.append(
        '--allowedTools "Read Edit Write Bash Grep Glob Task TodoWrite '
        'mcp__cosa-voice__notify mcp__cosa-voice__ask_yes_no mcp__cosa-voice__ask_multiple_choice"'
    )
    flags.append(
        '--disallowedTools "mcp__cosa-voice__converse mcp__cosa-voice__ask_open_ended_batch WebSearch WebFetch"'
    )
    cmd = [
        "docker", "exec",
        "-w", worktree_path,
        CONTAINER, "sh", "-c",
        f'claude -p "$(cat {container_prompt_path})" ' + " ".join( flags ),
    ]
    effort_str = f", effort={effort}" if effort and effort != "none" else ""
    budget_str = f", budget=${max_budget_usd}" if max_budget_usd is not None else ""
    print(
        f"[HARNESS] Dispatching coordinator (model={model}{effort_str}, "
        f"max_turns={MAX_TURNS}{budget_str}, timeout={WALL_CLOCK_LIMIT}s)...",
        flush=True,
    )
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


# ──────────────────────── Changes-summary artifact ────────────────────────
# Pure functions — importable by unit tests. Consume data that main() already
# has in hand (parsed tfe-result, git log output, etc.) and emit a JSON + MD
# pair to /tmp so we stop doing ad-hoc analysis per run.

SUBMODULE_PATHS = ( "src/cosa/", )


def _parse_worktree_commits( git_log_output: str ) -> list:
    """Parse `git log --oneline` output into [{sha, subject}] dicts."""
    commits = []
    for line in ( git_log_output or "" ).splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split( " ", 1 )
        if len( parts ) != 2:
            continue
        commits.append( { "sha": parts[ 0 ], "subject": parts[ 1 ] } )
    return commits


def _derive_cluster_rows( parsed: dict | None, selected_fixes: list ) -> list:
    """Normalize per-cluster data, apply already_clean remapping, tag submodule touches.

    already_clean remap: a subagent reports verdict=fixed with commit_sha=null
    when the cluster's target state was already correct before the run — nothing
    to commit. That's not 'fixed', it's 'already_clean'. Closes the validator
    contract gap we identified in 21-tfe-to-cc-phase3-live-test.md.
    """
    rows = []
    parsed_clusters = ( parsed or {} ).get( "clusters" ) or {}
    for fix in selected_fixes:
        cid = fix[ "cluster_id" ]
        data = parsed_clusters.get( cid ) or {}
        verdict_raw = data.get( "verdict" ) if isinstance( data, dict ) else None
        commit_sha  = data.get( "commit_sha" ) if isinstance( data, dict ) else None
        files       = data.get( "files" ) or []
        pytest_ok   = data.get( "pytest_passed" ) if isinstance( data, dict ) else None
        notes       = data.get( "notes" ) if isinstance( data, dict ) else None

        has_sha = isinstance( commit_sha, str ) and commit_sha.strip() != ""
        if verdict_raw == "fixed" and not has_sha:
            verdict = "already_clean"
        elif verdict_raw in ( "fixed", "unclear", "failed" ):
            verdict = verdict_raw
        else:
            verdict = "unknown"

        touches = sorted( {
            prefix for prefix in SUBMODULE_PATHS
            if any( ( f or "" ).startswith( prefix ) for f in files )
        } )

        rows.append( {
            "id"                 : cid,
            "title"              : fix.get( "title", "" ),
            "verdict"            : verdict,
            "verdict_raw"        : verdict_raw,
            "commit_sha"         : commit_sha if has_sha else None,
            "files"              : list( files ),
            "pytest_passed"      : pytest_ok,
            "notes"              : notes,
            "touches_submodules" : touches,
        } )
    return rows


def _compute_overall( cluster_rows: list, total: int ) -> dict:
    counts = { "fixed": 0, "already_clean": 0, "unclear": 0, "failed": 0, "unknown": 0 }
    for r in cluster_rows:
        counts[ r[ "verdict" ] ] = counts.get( r[ "verdict" ], 0 ) + 1
    return { "clusters_total": total, **counts }


def _detect_submodule_leaks( cluster_rows: list ) -> dict:
    """Group submodule-touching clusters by submodule path."""
    leaks: dict = {}
    for r in cluster_rows:
        for sub in r[ "touches_submodules" ]:
            leaks.setdefault( sub, [] ).append( r[ "id" ] )
    return leaks


def _build_changes_artifact(
    *,
    run_id            : str,
    model_requested   : str,
    model_reported    : str | None,
    effort            : str,
    max_budget_usd    : float | None,
    worktree          : str,
    started_at        : datetime,
    ended_at          : datetime,
    duration_s        : float,
    exit_code         : int,
    validation_ok     : bool,
    validation_issues : list,
    selected_fixes    : list,
    parsed            : dict | None,
    git_log_output    : str,
    git_diffstat      : str,
) -> dict:
    cluster_rows     = _derive_cluster_rows( parsed, selected_fixes )
    worktree_commits = _parse_worktree_commits( git_log_output )
    overall          = _compute_overall( cluster_rows, total=len( selected_fixes ) )
    leaks            = _detect_submodule_leaks( cluster_rows )
    return {
        "run_id"                        : run_id,
        "model"                         : model_requested,
        "model_reported"                : model_reported,
        "effort"                        : effort,
        "max_budget_usd"                : max_budget_usd,
        "worktree"                      : worktree,
        "started_at"                    : started_at.isoformat( timespec="seconds" ),
        "ended_at"                      : ended_at.isoformat( timespec="seconds" ),
        "duration_s"                    : round( duration_s, 2 ),
        "exit_code"                     : exit_code,
        "validation_ok"                 : bool( validation_ok ),
        "validation_issues"             : list( validation_issues or [] ),
        "overall"                       : overall,
        "clusters"                      : cluster_rows,
        "worktree_commits"              : worktree_commits,
        "git_diffstat"                  : ( git_diffstat or "" ).rstrip(),
        "possibly_leaked_to_submodules" : leaks,
    }


def _render_changes_md( changes: dict ) -> str:
    """Pretty-print the artifact as Markdown."""
    o = changes[ "overall" ]
    reported_suffix = ""
    if changes[ "model_reported" ] and changes[ "model_reported" ] != changes[ "model" ]:
        reported_suffix = f" (reported: `{changes[ 'model_reported' ]}`)"
    budget_str = f"${changes[ 'max_budget_usd' ]}" if changes[ "max_budget_usd" ] is not None else "none"

    lines = [
        f"# TFE-to-CC Changes Report — {changes[ 'run_id' ]}",
        "",
        f"- **Started**: {changes[ 'started_at' ]}",
        f"- **Ended**: {changes[ 'ended_at' ]}",
        f"- **Duration**: {changes[ 'duration_s' ]}s",
        f"- **Model**: `{changes[ 'model' ]}`{reported_suffix}",
        f"- **Effort**: `{changes[ 'effort' ]}`",
        f"- **Max budget**: {budget_str}",
        f"- **Worktree**: `{changes[ 'worktree' ]}`",
        f"- **Exit code**: `{changes[ 'exit_code' ]}`",
        f"- **Validation OK**: `{changes[ 'validation_ok' ]}`",
        "",
        "## Overall",
        "",
        "| Total | Fixed | Already clean | Unclear | Failed | Unknown |",
        "|---|---|---|---|---|---|",
        f"| {o[ 'clusters_total' ]} | {o[ 'fixed' ]} | {o[ 'already_clean' ]} | {o[ 'unclear' ]} | {o[ 'failed' ]} | {o[ 'unknown' ]} |",
        "",
        "## Clusters",
        "",
        "| ID | Verdict | Commit | Files | Pytest |",
        "|---|---|---|---|---|",
    ]
    for r in changes[ "clusters" ]:
        commit = r[ "commit_sha" ] or "—"
        files  = ", ".join( f"`{f}`" for f in ( r[ "files" ] or [] ) ) or "—"
        if r[ "pytest_passed" ] is True:
            pytest = "✓"
        elif r[ "pytest_passed" ] is False:
            pytest = "✗"
        else:
            pytest = "—"
        lines.append( f"| **{r[ 'id' ]}** | `{r[ 'verdict' ]}` | `{commit}` | {files} | {pytest} |" )

    if changes[ "worktree_commits" ]:
        lines += [ "", "## Worktree commits", "", "```" ]
        for c in changes[ "worktree_commits" ]:
            lines.append( f"{c[ 'sha' ]} {c[ 'subject' ]}" )
        lines.append( "```" )

    if changes[ "git_diffstat" ]:
        lines += [
            "",
            "## Worktree diffstat vs origin/main",
            "",
            "```",
            changes[ "git_diffstat" ],
            "```",
        ]

    if changes[ "possibly_leaked_to_submodules" ]:
        lines += [
            "",
            "## ⚠️ Possibly leaked to submodules",
            "",
            "Subagents reported touching files under these submodule paths. "
            "Any commits (if made) live in the submodule's git, not the outer worktree. "
            "Inspect and commit from each submodule's context separately.",
            "",
        ]
        for sub, cids in sorted( changes[ "possibly_leaked_to_submodules" ].items() ):
            lines.append( f"- **`{sub}`** — clusters: {', '.join( cids )}" )

    if changes[ "validation_issues" ]:
        lines += [ "", "## Validation issues", "" ]
        for issue in changes[ "validation_issues" ]:
            lines.append( f"- {issue}" )

    return "\n".join( lines ) + "\n"


def _write_changes_artifacts( changes: dict, scratch: Path, timestamp: str ) -> tuple:
    """Write the JSON + MD artifacts; return (json_path, md_path)."""
    json_path = scratch / f"tfe-to-cc-changes-{timestamp}.json"
    md_path   = scratch / f"tfe-to-cc-changes-{timestamp}.md"
    json_path.write_text( json.dumps( changes, indent=2 ) + "\n" )
    md_path.write_text( _render_changes_md( changes ) )
    return json_path, md_path


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
    parser = argparse.ArgumentParser(
        description="TFE-to-CC Phase 3 LIVE harness — parallel Claude Code dispatch of bundled fixes.",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Claude model for coordinator + subagents (default: {DEFAULT_MODEL}). "
             "Accepts full IDs (claude-opus-4-7) or aliases (opus / sonnet / haiku).",
    )
    parser.add_argument(
        "--effort",
        default=DEFAULT_EFFORT,
        choices=[ "low", "medium", "high", "xhigh", "max", "none" ],
        help=f"Extended-thinking effort level (default: {DEFAULT_EFFORT}). "
             "Use 'none' to omit the --effort flag entirely.",
    )
    parser.add_argument(
        "--max-budget-usd",
        type=float,
        default=None,
        help="Optional per-invocation USD budget cap (forwarded to --max-budget-usd).",
    )
    args = parser.parse_args()

    banner_extras = f"model={args.model} | effort={args.effort}"
    if args.max_budget_usd is not None:
        banner_extras += f" | budget=${args.max_budget_usd}"
    _banner( f"TFE-to-CC Phase 3 LIVE — {len( SELECTED_FIXES )} fixes | {banner_extras}" )

    started_at  = datetime.now().astimezone()
    scratch     = Path( "/tmp" )
    run_ts      = _ts()
    stream_path = scratch / f"tfe-to-cc-phase3-stream-{run_ts}.jsonl"
    stderr_path = scratch / f"tfe-to-cc-phase3-stderr-{run_ts}.log"

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
    exit_code = _invoke_claude_p(
        container_prompt_path,
        worktree,
        stream_path,
        stderr_path,
        model          = args.model,
        effort         = args.effort,
        max_budget_usd = args.max_budget_usd,
    )
    ended_at   = datetime.now().astimezone()
    duration_s = ( ended_at - started_at ).total_seconds()

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

    # 8.5 Build & persist changes-summary artifact (JSON + MD) so we stop
    # doing ad-hoc per-run analysis by hand.
    changes = _build_changes_artifact(
        run_id            = worktree.split( "/" )[ -1 ],
        model_requested   = args.model,
        model_reported    = summary.get( "model" ),
        effort            = args.effort,
        max_budget_usd    = args.max_budget_usd,
        worktree          = worktree,
        started_at        = started_at,
        ended_at          = ended_at,
        duration_s        = duration_s,
        exit_code         = exit_code,
        validation_ok     = validation_ok,
        validation_issues = validation_issues,
        selected_fixes    = SELECTED_FIXES,
        parsed            = parsed,
        git_log_output    = git_log,
        git_diffstat      = diff_stat,
    )
    changes_json_path, changes_md_path = _write_changes_artifacts( changes, scratch, run_ts )
    print( f"[HARNESS] Changes (JSON): {changes_json_path}", flush=True )
    print( f"[HARNESS] Changes  (MD):  {changes_md_path}", flush=True )

    # 9. Build execution log section
    ts_now = datetime.now().astimezone().isoformat( timespec="seconds" )
    lines: list = [
        f"### {ts_now} — LIVE {len( SELECTED_FIXES )}-fix run",
        "",
        f"**Worktree**: `{worktree}`",
        f"**Prompt**: {len( prompt )} bytes | host: `{host_prompt_path}` | container: `{container_prompt_path}`",
        f"**Stream**: `{stream_path}`",
        f"**Changes artifact**: `{changes_json_path}` (JSON) | `{changes_md_path}` (MD)",
        "",
        "**SDK/CC path confirmation**:",
        f"- apiKeySource: `{summary.get( 'api_key_source' )}`",
        f"- model: `{summary.get( 'model' )}` (requested: `{args.model}`)",
        f"- effort: `{args.effort}`"
        + ( f" | budget: `${args.max_budget_usd}`" if args.max_budget_usd is not None else "" ),
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
        f"Machine-parseable changes artifact: `{changes_json_path}` (JSON) + `{changes_md_path}` (MD).\n"
        f"Worktree preserved at `.claude/worktrees/{worktree.split( '/' )[-1]}/` for review."
    )
    _send_high_priority_notify( msg, abstract )

    # Console summary
    _banner( "SUMMARY" )
    o = changes[ "overall" ]
    print( f"Fixed / Already-clean / Unclear / Failed: {o[ 'fixed' ]} / {o[ 'already_clean' ]} / {o[ 'unclear' ]} / {o[ 'failed' ]}  (total {o[ 'clusters_total' ]})", flush=True )
    print( f"Parser: {'fallback' if fallback_used else 'primary'}", flush=True )
    print( f"Validation: {'OK' if validation_ok else 'ISSUES'}", flush=True )
    print( f"Changes (JSON): {changes_json_path}", flush=True )
    print( f"Changes  (MD):  {changes_md_path}", flush=True )

    return 0 if ( fixed_count > 0 and validation_ok ) else 1


if __name__ == "__main__":
    sys.exit( main() )
