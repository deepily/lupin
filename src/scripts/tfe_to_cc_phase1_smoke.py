#!/usr/bin/env python3
"""
TFE-to-CC Phase 1 (diagnose) live smoke test.

Invokes `claude -p` inside lupin-rest-test against a real failure cluster
(C6 from tfe-a1c6e15a), checks the output contract, and writes results
to the execution log in docs.

This is a read-only probe — no file writes, no git ops outside /tmp, no
SDK involvement. Safe to run unattended; blocking MCP tools are disabled.

Usage:
    PYTHONPATH=src:$PYTHONPATH python3 src/scripts/tfe_to_cc_phase1_smoke.py

Paired design doc:
    src/rnd/v0.1.6/2026.04.10-test-fix-expediter/20-tfe-to-cc-phase1-live-test.md
"""

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


# Make cosa importable from project root
_PROJECT_ROOT = Path( __file__ ).resolve().parent.parent.parent
sys.path.insert( 0, str( _PROJECT_ROOT / "src" ) )

from cosa.agents.tfe_to_cc.prompts.bundle_phase1 import build_diagnosis_bundle_prompt
from cosa.agents.tfe_to_cc.prompts.output_contract import (
    parse_diagnosis_block,
    parse_diagnosis_fallback,
    validate_diagnosis_payload,
)


CONTAINER        = "lupin-rest-test"
MODEL            = "claude-sonnet-4-6"      # testing mode per user note; real runs default to opus-4-7
MAX_TURNS        = 20
WALL_CLOCK_LIMIT = 300                        # seconds
EXECUTION_LOG    = (
    _PROJECT_ROOT
    / "src/rnd/v0.1.6/2026.04.10-test-fix-expediter/20-tfe-to-cc-phase1-live-test.md"
)


# The synthetic smoke cluster — realistic failure from tfe-a1c6e15a baseline
CLUSTER_C6 = {
    "cluster_id"             : "C6",
    "failure_count"          : 1,
    "shared_error_signature" : "AssertionError: assert 5 == 10",
    "affected_files_guess"   : [
        "src/tests/unit/test_runtime_argument_expeditor.py",
        "src/cosa/agents/runtime_argument_expeditor/agent_registry.py",
    ],
    "failing_tests" : [
        {
            "test_name"         : "src/tests/unit/test_runtime_argument_expeditor.py::TestAgentRegistry::test_registry_has_five_agents",
            "error_type"        : "AssertionError",
            "error_message"     : "assert 5 == 10",
            "traceback_excerpt" : (
                "src/tests/unit/test_runtime_argument_expeditor.py:360: AssertionError\n"
                ">       assert len( JOB_ARG_CONTRACTS ) == 5\n"
                "E       assert 10 == 5\n"
                "E        +  where 10 = len({ ...ten entries... })"
            ),
        }
    ],
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


def _write_prompt_to_container( container: str, host_scratch: Path, prompt: str ) -> str:
    """Copy prompt into the container at a known /tmp path; returns the container path."""
    container_path = f"/tmp/tfe_to_cc_phase1_prompt_{_ts()}.md"
    proc = subprocess.run(
        [ "docker", "exec", "-i", container, "sh", "-c", f"cat > {container_path}" ],
        input=prompt.encode( "utf-8" ),
        capture_output=True,
        timeout=15,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"Failed to write prompt into container: rc={proc.returncode} stderr={proc.stderr!r}"
        )
    # Also save on host for inspection
    host_copy = host_scratch / f"tfe_to_cc_phase1_prompt_{_ts()}.md"
    host_copy.write_text( prompt )
    print( f"[SMOKE] Prompt: {len( prompt )} bytes  →  host: {host_copy}  |  container: {container_path}", flush=True )
    return container_path


def _run_claude_p( container: str, prompt_path: str, stream_out: Path, stderr_out: Path ) -> int:
    """Invoke `docker exec ... claude -p ...` streaming stdout to stream_out (jsonl)."""
    cmd = [
        "docker", "exec", container, "sh", "-c",
        (
            f'claude -p "$(cat {prompt_path})" '
            f'--model {MODEL} '
            f'--output-format stream-json '
            f'--verbose '
            f'--max-turns {MAX_TURNS} '
            f'--allowedTools "Read Grep Glob mcp__cosa-voice__notify" '
            f'--disallowedTools "Edit Write Bash mcp__cosa-voice__converse mcp__cosa-voice__ask_yes_no mcp__cosa-voice__ask_multiple_choice mcp__cosa-voice__ask_open_ended_batch"'
        ),
    ]
    print( f"[SMOKE] Invoking claude -p (model={MODEL}, max_turns={MAX_TURNS}, timeout={WALL_CLOCK_LIMIT}s)...", flush=True )
    start = time.time()
    with open( stream_out, "wb" ) as out, open( stderr_out, "wb" ) as err:
        try:
            proc = subprocess.run( cmd, stdout=out, stderr=err, timeout=WALL_CLOCK_LIMIT )
        except subprocess.TimeoutExpired:
            print( f"[SMOKE] TIMEOUT after {WALL_CLOCK_LIMIT}s", flush=True )
            return -1
    duration = time.time() - start
    print( f"[SMOKE] Exit code: {proc.returncode}  |  duration: {duration:.1f}s", flush=True )
    return proc.returncode


def _parse_stream( path: Path ) -> dict:
    """Parse the stream-json file into a summary dict."""
    summary: dict = {
        "api_key_source"   : None,
        "model"            : None,
        "result"           : None,
        "assistant_text"   : "",
        "tool_use_count"   : 0,
        "tool_use_names"   : [],
        "rate_limit_info"  : None,
        "raw_event_count"  : 0,
        "parse_errors"     : 0,
    }
    text_chunks: list = []
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
                        text_chunks.append( block.get( "text" ) or "" )
                    elif btype == "tool_use":
                        summary[ "tool_use_count" ] += 1
                        summary[ "tool_use_names" ].append( block.get( "name" ) or "?" )
            elif t == "rate_limit_event":
                summary[ "rate_limit_info" ] = obj.get( "rate_limit_info" )
            elif t == "result":
                summary[ "result" ] = obj
    summary[ "assistant_text" ] = "\n".join( text_chunks )
    return summary


def _append_to_execution_log( section_md: str ) -> None:
    """Append a dated section to the execution log."""
    try:
        existing = EXECUTION_LOG.read_text()
    except FileNotFoundError:
        existing = ""
    new_content = existing.rstrip() + "\n\n" + section_md.rstrip() + "\n"
    EXECUTION_LOG.write_text( new_content )
    print( f"[SMOKE] Execution log updated: {EXECUTION_LOG}", flush=True )


def _run_passed( summary: dict, parsed: dict | None, validation_ok: bool, exit_code: int ) -> bool:
    """The plan's success criteria (1-6), in ONE place.

    Both the logged verdict and the process exit code read this. They used to state the
    criteria separately and had drifted apart: the log applied `is_error` and the turn-budget
    cap, the exit code did not, so an unattended run could write a FAIL verdict and still
    exit 0.
    """
    result = summary.get( "result" ) or {}
    return (
        exit_code == 0
        and summary.get( "api_key_source" ) == "none"
        # no `result` truthiness test: an absent result event leaves `result` == {} and the
        # subtype check below already fails it. A mutation removing such a clause SURVIVES,
        # because it is an equivalent mutant rather than an untested one.
        and result.get( "subtype" ) == "success"
        and result.get( "is_error" ) is False
        and parsed is not None
        and validation_ok
        and int( result.get( "num_turns" ) or 0 ) < MAX_TURNS
    )


def _format_execution_section( summary: dict, parsed: dict | None, validation_ok: bool,
                                validation_issues: list, fallback_used: bool,
                                exit_code: int, stream_path: Path, prompt_size: int ) -> str:
    ts = datetime.now().astimezone().isoformat( timespec="seconds" )
    result = summary.get( "result" ) or {}

    def _fmt( v ): return "?" if v is None else v

    lines: list = []
    lines.append( f"### {ts} — Phase 1 live smoke run (C6 cluster, model={MODEL})" )
    lines.append( "" )
    lines.append( "**Run metadata**:" )
    lines.append( f"- Prompt size: {prompt_size} bytes" )
    lines.append( f"- Container: `{CONTAINER}`" )
    lines.append( f"- Model: `{MODEL}` (testing-mode override; production default will be opus-4-7)" )
    lines.append( f"- Max turns: {MAX_TURNS}" )
    lines.append( f"- Stream-json dump: `{stream_path}`" )
    lines.append( "" )
    lines.append( "**Outcome**:" )
    lines.append( f"- Exit code: `{exit_code}`" )
    lines.append( f"- apiKeySource: `{_fmt( summary.get( 'api_key_source' ) )}` (expect `\"none\"` for Max subscription)" )
    lines.append( f"- Model used: `{_fmt( summary.get( 'model' ) )}`" )
    lines.append( f"- Raw event count: {summary.get( 'raw_event_count' )}" )
    lines.append( f"- Tool use count: {summary.get( 'tool_use_count' )}  |  tools: {summary.get( 'tool_use_names' )}" )
    if result:
        lines.append( f"- Result subtype: `{_fmt( result.get( 'subtype' ) )}`" )
        lines.append( f"- is_error: `{_fmt( result.get( 'is_error' ) )}`" )
        lines.append( f"- num_turns: `{_fmt( result.get( 'num_turns' ) )}`" )
        lines.append( f"- duration_ms: `{_fmt( result.get( 'duration_ms' ) )}`" )
        lines.append( f"- total_cost_usd (informational — paper cost on Max): `{_fmt( result.get( 'total_cost_usd' ) )}`" )
    rate_info = summary.get( "rate_limit_info" )
    if rate_info:
        lines.append( f"- rate_limit_info: `{rate_info}`" )
    lines.append( "" )

    lines.append( "**Diagnosis output**:" )
    if parsed:
        lines.append( f"- Parse source: {'fallback (regex)' if fallback_used else 'primary (fenced JSON)'}" )
        lines.append( f"- Validation: {'PASS' if validation_ok else 'FAIL'}" )
        if validation_issues:
            lines.append( "- Validation issues:" )
            for issue in validation_issues:
                lines.append( f"    - {issue}" )
        lines.append( "" )
        lines.append( "```json" )
        lines.append( json.dumps( parsed, indent=2 ) )
        lines.append( "```" )
    else:
        lines.append( "- Both primary + fallback parsers failed." )
        # Include last 2000 chars of assistant text for inspection
        tail = ( summary.get( "assistant_text" ) or "" )[ -2000: ]
        if tail:
            lines.append( "- Assistant text tail (last 2000 chars):" )
            lines.append( "  ```" )
            for ln in tail.splitlines():
                lines.append( f"  {ln}" )
            lines.append( "  ```" )
    lines.append( "" )

    # Overall pass/fail verdict per the plan's success criteria
    verdict_ok = _run_passed( summary, parsed, validation_ok, exit_code )
    lines.append( f"**Verdict**: {'✅ PASS' if verdict_ok else '❌ FAIL'} vs. plan success criteria (1-6)" )

    return "\n".join( lines )


# ────────────────────────────────────────────────────────────────────────
# Main
# ────────────────────────────────────────────────────────────────────────

def main() -> int:
    _banner( "TFE-to-CC Phase 1 (diagnose) live smoke" )

    # Scratch dir on host
    scratch_root = Path( "/tmp" )
    stream_path  = scratch_root / f"tfe-to-cc-phase1-stream-{_ts()}.jsonl"
    stderr_path  = scratch_root / f"tfe-to-cc-phase1-stderr-{_ts()}.log"

    # 1. Build prompt
    prompt = build_diagnosis_bundle_prompt(
        clusters        = [ CLUSTER_C6 ],
        failure_context = { "source_suite": "smoke-test (synthesized from tfe-a1c6e15a C6 baseline)" },
    )
    prompt_size = len( prompt )

    # 2. Write prompt into container
    container_prompt_path = _write_prompt_to_container( CONTAINER, scratch_root, prompt )

    # 3. Invoke claude -p
    exit_code = _run_claude_p( CONTAINER, container_prompt_path, stream_path, stderr_path )

    # 4. Parse stream
    summary = _parse_stream( stream_path )

    # 5. Extract diagnosis block + validate
    fallback_used = False
    parsed = parse_diagnosis_block( summary[ "assistant_text" ] )
    if parsed is None:
        parsed = parse_diagnosis_fallback( summary[ "assistant_text" ] )
        fallback_used = parsed is not None

    validation_ok, validation_issues = validate_diagnosis_payload( parsed )

    # 6. Print summary + append to execution log
    _banner( "SUMMARY" )
    print( f"apiKeySource      : {summary.get( 'api_key_source' )!r}", flush=True )
    print( f"model             : {summary.get( 'model' )!r}", flush=True )
    print( f"tool_use_count    : {summary.get( 'tool_use_count' )}", flush=True )
    print( f"tool_use_names    : {summary.get( 'tool_use_names' )}", flush=True )
    if summary.get( "result" ):
        r = summary[ "result" ]
        print( f"result.subtype    : {r.get( 'subtype' )!r}", flush=True )
        print( f"result.is_error   : {r.get( 'is_error' )!r}", flush=True )
        print( f"result.num_turns  : {r.get( 'num_turns' )!r}", flush=True )
        print( f"result.total_cost : {r.get( 'total_cost_usd' )!r}", flush=True )
    print( f"parser_used       : {'fallback' if fallback_used else 'primary'}", flush=True )
    print( f"validation_ok     : {validation_ok}", flush=True )
    if validation_issues:
        print( "validation_issues :", flush=True )
        for iss in validation_issues:
            print( f"  - {iss}", flush=True )

    section = _format_execution_section(
        summary           = summary,
        parsed            = parsed,
        validation_ok     = validation_ok,
        validation_issues = validation_issues,
        fallback_used     = fallback_used,
        exit_code         = exit_code,
        stream_path       = stream_path,
        prompt_size       = prompt_size,
    )
    _append_to_execution_log( section )

    # Exit 0 on verdict PASS, else 1 — the SAME predicate the logged verdict used
    return 0 if _run_passed( summary, parsed, validation_ok, exit_code ) else 1


if __name__ == "__main__":  # pragma: no cover - unreachable under pytest: __name__ is the module name, never "__main__"
    sys.exit( main() )
