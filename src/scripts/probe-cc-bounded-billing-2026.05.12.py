#!/usr/bin/env python3
"""
THROWAWAY ONE-OFF PROBE — 2026-05-12

Question being answered:
    Does the Lupin BOUNDED ClaudeCodeJob path bill against the Anthropic API
    (via the firewalled ANTHROPIC_API_KEY_FIREWALLED), or is it covered by
    the Claude Code Max subscription that the Claude Code CLI uses?

Theory under test (Rick):
    - ANTHROPIC_API_KEY is reserved for the Claude Code CLI (Max subscription).
    - ANTHROPIC_API_KEY_FIREWALLED is the firewalled key used by *other*
      agents (Deep Research, notification proxy, decision proxy) that
      explicitly call the Anthropic SDK.
    - The bounded ClaudeCodeJob path uses the CLI / Claude Agent SDK auth,
      NOT the firewalled key, so it should be billed at $0 / covered by Max.
    - Grep across src/cosa/agents/claude_code/, src/scripts/, src/conf/
      shows ZERO references to ANTHROPIC_API_KEY or the firewalled name.

Experimental design (Rick):
    Two clusters of 5 prompts each.
    - Cluster A: in-repo only (Read/Grep/Write to /tmp). Cheaper if billing on.
    - Cluster B: web search + synthesis. Expensive if billing on.
    1-minute spacing between every execution so the credit-balance UI has
    time to settle and any jump correlates to a specific job.

NOT a checked-in test. NOT pytest. One-off probe — delete after use.
"""

import json
import os
import sys
import time
from datetime import datetime
from typing import Optional

import requests


# ───────────────────────────────────────────────────────────────────────────
# Config
# ───────────────────────────────────────────────────────────────────────────

BASE_URL              = os.environ.get( "LUPIN_API_URL", "http://localhost:7999" )
EMAIL                 = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL" )
PASSWORD              = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" )
WAIT_BETWEEN_JOBS_S   = 60      # 1 minute between every job submission
POLL_INTERVAL_S       = 5
POLL_TIMEOUT_S        = 240     # 4 min cap per job

SUBMIT_ENDPOINT = f"{BASE_URL}/api/claude-code/submit"
JOB_ENDPOINT    = f"{BASE_URL}/api/job-history"

PROBE_RUN_ID = f"probe-{int( time.time() )}"


# ───────────────────────────────────────────────────────────────────────────
# Prompts
# ───────────────────────────────────────────────────────────────────────────

CLUSTER_A_IN_REPO = [
    {
        "label"     : "A1_dir_listing_summary",
        "max_turns" : 8,
        "prompt"    : (
            "Read the file /var/lupin/src/cosa/rest/routers/_dir_listing.py "
            "thoroughly. Write a 200-word technical summary of how the "
            "_build_view_url function routes file extensions to viewer URLs "
            "(directories, .md/.txt/.json/.yaml/.yml text files, .mp3/.wav "
            "audio, .pdf, .pptx, images). Save the summary to "
            f"/tmp/{PROBE_RUN_ID}-a1-result.txt. Use Read and Write tools "
            "only. Do not access the web."
        ),
    },
    {
        "label"     : "A2_agentic_subclass_inventory",
        "max_turns" : 10,
        "prompt"    : (
            "Use Grep to find all Python files under "
            "/var/lupin/src/cosa/agents/ that define classes inheriting from "
            "AgenticJobBase. For each, list the class name and the file path. "
            "Save the inventory as a markdown table to "
            f"/tmp/{PROBE_RUN_ID}-a2-result.txt. Use Grep, Read, and Write "
            "only. Do not access the web."
        ),
    },
    {
        "label"     : "A3_history_2026_05_12_summary",
        "max_turns" : 10,
        "prompt"    : (
            "Read /var/lupin/history.md and identify all entries dated "
            "2026-05-12. For each session listed under that date, write a "
            "2-sentence summary of what was accomplished. Save the summary to "
            f"/tmp/{PROBE_RUN_ID}-a3-result.txt. Use Read and Write tools "
            "only. Do not access the web."
        ),
    },
    {
        "label"     : "A4_lupin_app_ini_categorization",
        "max_turns" : 10,
        "prompt"    : (
            "Read /var/lupin/src/conf/lupin-app.ini and group all keys under "
            "the [Lupin: Baseline] section into thematic categories (e.g., "
            "'queue', 'auth', 'tts', 'agents', 'websocket', etc.). Provide a "
            "count and 2-3 example key names per category. Save the "
            f"categorization to /tmp/{PROBE_RUN_ID}-a4-result.txt. Use Read "
            "and Write only. Do not access the web."
        ),
    },
    {
        "label"     : "A5_security_posture_diff",
        "max_turns" : 10,
        "prompt"    : (
            "Read /var/lupin/src/cosa/rest/routers/docs_files.py and "
            "/var/lupin/src/cosa/rest/routers/io_files.py. Identify the 3 "
            "most significant differences in how they validate paths and "
            "enforce security (whitelist, traversal blocking, extension "
            "checks). Save a 300-word comparison to "
            f"/tmp/{PROBE_RUN_ID}-a5-result.txt. Use Read and Write only. Do "
            "not access the web."
        ),
    },
]

CLUSTER_B_WEB_SYNTH = [
    {
        "label"     : "B1_anthropic_pricing_2026",
        "max_turns" : 15,
        "prompt"    : (
            "Search the web for the latest Anthropic Claude API pricing "
            "announcements from 2026. Summarize the per-token costs for the "
            "Opus 4.x, Sonnet 4.x, and Haiku 4.x model families. Cite the "
            "sources you find. Save the 300-word summary to "
            f"/tmp/{PROBE_RUN_ID}-b1-result.txt. Use WebSearch and/or "
            "WebFetch as needed."
        ),
    },
    {
        "label"     : "B2_fastapi_polymorphic_endpoints_2026",
        "max_turns" : 15,
        "prompt"    : (
            "Search the web for emerging FastAPI best practices in 2026 "
            "around polymorphic endpoint design (single endpoint returning "
            "different Content-Types based on the resolved resource). "
            "Synthesize the top 3 recommended patterns into a 300-word "
            f"write-up. Save to /tmp/{PROBE_RUN_ID}-b2-result.txt. Use "
            "WebSearch and/or WebFetch as needed."
        ),
    },
    {
        "label"     : "B3_playwright_visual_regression_2026",
        "max_turns" : 15,
        "prompt"    : (
            "Search the web for the most-discussed approaches to Playwright "
            "visual regression testing in 2026 (snapshot strategies, baseline "
            "management, CI integration). Pick the top 3 emerging patterns "
            "and write a 300-word comparison. Save to "
            f"/tmp/{PROBE_RUN_ID}-b3-result.txt. Use WebSearch and/or "
            "WebFetch as needed."
        ),
    },
    {
        "label"     : "B4_claude_agent_sdk_use_cases",
        "max_turns" : 15,
        "prompt"    : (
            "Search the web for the most-discussed Claude Agent SDK use "
            "cases on GitHub trending repositories or Hacker News as of "
            "2026. Pick the top 3 and summarize each in 100 words. Save to "
            f"/tmp/{PROBE_RUN_ID}-b4-result.txt. Use WebSearch and/or "
            "WebFetch as needed."
        ),
    },
    {
        "label"     : "B5_mcp_ecosystem_growth_2026",
        "max_turns" : 15,
        "prompt"    : (
            "Search the web for recent news about the Model Context Protocol "
            "(MCP) ecosystem growth in 2026. Identify the top 3 developments "
            "(new MCP servers, tooling, integrations) and synthesize a "
            f"300-word summary. Save to /tmp/{PROBE_RUN_ID}-b5-result.txt. "
            "Use WebSearch and/or WebFetch as needed."
        ),
    },
]


# ───────────────────────────────────────────────────────────────────────────
# Helpers
# ───────────────────────────────────────────────────────────────────────────

def _ts() -> str:
    return datetime.now().strftime( "%H:%M:%S" )


def _print( msg: str ) -> None:
    print( f"[{_ts()}] {msg}", flush=True )


def _auth() -> dict:
    if not EMAIL or not PASSWORD:
        _print( "ERROR: missing LUPIN_TEST_INTERACTIVE_MOCK_JOBS_{EMAIL,PASSWORD}" )
        sys.exit( 1 )
    r = requests.post(
        f"{BASE_URL}/auth/login",
        json    = { "email": EMAIL, "password": PASSWORD },
        timeout = 10,
    )
    r.raise_for_status()
    token = r.json()[ "tokens" ][ "access_token" ]
    return { "Authorization": f"Bearer {token}" }


def _extract_cost_usd( job: dict ) -> Optional[ float ]:
    """Lifted from test_claude_code_max_subscription.py — tolerant of where cost lands."""
    artifacts = job.get( "artifacts" ) or {}
    if isinstance( artifacts, dict ):
        if "cost_usd" in artifacts:
            return float( artifacts[ "cost_usd" ] )
        if "total_cost_usd" in artifacts:
            return float( artifacts[ "total_cost_usd" ] )
        cs = artifacts.get( "cost_summary" )
        if isinstance( cs, dict ) and "total_cost_usd" in cs:
            return float( cs[ "total_cost_usd" ] )
    cs = job.get( "cost_summary" )
    if isinstance( cs, dict ) and "total_cost_usd" in cs:
        return float( cs[ "total_cost_usd" ] )
    metadata = job.get( "metadata_json" ) or {}
    if isinstance( metadata, dict ):
        if "cost_usd" in metadata:
            return float( metadata[ "cost_usd" ] )
        cs = metadata.get( "cost_summary" )
        if isinstance( cs, dict ) and "total_cost_usd" in cs:
            return float( cs[ "total_cost_usd" ] )
    return None


def _run_one( headers: dict, item: dict ) -> dict:
    label    = item[ "label" ]
    prompt   = item[ "prompt" ]
    max_turn = item[ "max_turns" ]

    _print( f"submit  [{label}]" )
    submit = requests.post(
        SUBMIT_ENDPOINT,
        headers = headers,
        json    = {
            "prompt"    : prompt,
            "project"   : "lupin",
            "task_type" : "BOUNDED",
            "max_turns" : max_turn,
            "dry_run"   : False,
        },
        timeout = 15,
    )
    if submit.status_code != 200:
        _print( f"  submit HTTP {submit.status_code}: {submit.text[:200]}" )
        return { "label": label, "job_id": None, "state": "submit_error", "cost_usd": None, "elapsed_s": 0.0, "error": submit.text[:500] }
    job_id = submit.json().get( "job_id" )
    _print( f"  job_id = {job_id}" )

    started = time.time()
    deadline = started + POLL_TIMEOUT_S
    final    = None
    while time.time() < deadline:
        try:
            r = requests.get( f"{JOB_ENDPOINT}/{job_id}", headers=headers, timeout=10 )
            if r.status_code == 200:
                job = r.json()
                state = ( job.get( "state" ) or job.get( "status" ) or "" ).lower()
                if state in ( "done", "complete", "completed", "finished", "dead", "failed", "error" ):
                    final = job
                    break
        except Exception:
            pass
        time.sleep( POLL_INTERVAL_S )

    elapsed = time.time() - started
    if not final:
        _print( f"  TIMEOUT after {elapsed:.0f}s" )
        return { "label": label, "job_id": job_id, "state": "poll_timeout", "cost_usd": None, "elapsed_s": elapsed }

    cost  = _extract_cost_usd( final )
    state = ( final.get( "state" ) or final.get( "status" ) or "unknown" ).lower()
    _print( f"  state={state} cost_usd={cost} elapsed={elapsed:.1f}s" )
    return { "label": label, "job_id": job_id, "state": state, "cost_usd": cost, "elapsed_s": elapsed, "raw": final }


def _print_summary( cluster_a: list, cluster_b: list ) -> None:
    _print( "" )
    _print( "============================================================" )
    _print( "SUMMARY — bounded ClaudeCodeJob billing probe" )
    _print( "============================================================" )
    _print( f"{'Label':<40} {'State':<10} {'Cost USD':>10} {'Elapsed':>10}" )
    _print( "-" * 74 )
    total_a = 0.0
    total_b = 0.0
    for r in cluster_a:
        cost_str = f"${r['cost_usd']:.4f}" if r[ "cost_usd" ] is not None else "n/a"
        _print( f"{r['label']:<40} {r['state']:<10} {cost_str:>10} {r['elapsed_s']:>9.1f}s" )
        total_a += ( r[ "cost_usd" ] or 0 )
    _print( "-" * 74 )
    for r in cluster_b:
        cost_str = f"${r['cost_usd']:.4f}" if r[ "cost_usd" ] is not None else "n/a"
        _print( f"{r['label']:<40} {r['state']:<10} {cost_str:>10} {r['elapsed_s']:>9.1f}s" )
        total_b += ( r[ "cost_usd" ] or 0 )
    _print( "-" * 74 )
    _print( f"Cluster A total (in-repo)       : ${total_a:.4f}" )
    _print( f"Cluster B total (web synth)     : ${total_b:.4f}" )
    _print( f"GRAND TOTAL (reported by jobs)  : ${total_a + total_b:.4f}" )
    _print( "" )
    _print( "Compare against your Anthropic console credit-balance UI delta." )
    _print( "Theory: console delta should be ~$0 if Max-subscription auth is used." )


# ───────────────────────────────────────────────────────────────────────────
# Main
# ───────────────────────────────────────────────────────────────────────────

def main() -> None:
    _print( f"probe run id = {PROBE_RUN_ID}" )
    _print( f"BASE_URL = {BASE_URL}" )
    _print( f"jobs = 10, wait_between_jobs = {WAIT_BETWEEN_JOBS_S}s (uniform incl. between clusters)" )
    headers = _auth()
    _print( "auth OK" )

    cluster_a_results = [ ]
    cluster_b_results = [ ]

    _print( "" )
    _print( "=== CLUSTER A: in-repo only (cheap if billing on) ===" )
    for idx, item in enumerate( CLUSTER_A_IN_REPO ):
        if idx > 0:
            _print( f"sleep {WAIT_BETWEEN_JOBS_S}s before next job…" )
            time.sleep( WAIT_BETWEEN_JOBS_S )
        cluster_a_results.append( _run_one( headers, item ) )

    _print( "" )
    _print( f"--- end Cluster A; sleep {WAIT_BETWEEN_JOBS_S}s before Cluster B ---" )
    time.sleep( WAIT_BETWEEN_JOBS_S )

    _print( "" )
    _print( "=== CLUSTER B: web search + synthesis (expensive if billing on) ===" )
    for idx, item in enumerate( CLUSTER_B_WEB_SYNTH ):
        if idx > 0:
            _print( f"sleep {WAIT_BETWEEN_JOBS_S}s before next job…" )
            time.sleep( WAIT_BETWEEN_JOBS_S )
        cluster_b_results.append( _run_one( headers, item ) )

    _print_summary( cluster_a_results, cluster_b_results )

    # Persist raw results for forensic review
    raw_path = f"/tmp/{PROBE_RUN_ID}-raw.json"
    with open( raw_path, "w" ) as f:
        json.dump( {
            "probe_run_id" : PROBE_RUN_ID,
            "base_url"     : BASE_URL,
            "cluster_a"    : cluster_a_results,
            "cluster_b"    : cluster_b_results,
        }, f, indent=2, default=str )
    _print( f"raw results saved to {raw_path}" )


if __name__ == "__main__":
    main()
