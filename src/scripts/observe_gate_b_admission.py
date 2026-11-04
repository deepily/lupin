#!/usr/bin/env python3
"""
Observe Gate B admitting a lineage child through a monopoly hold.

What this answers, and what it does not:
    The parent-id tag is threaded: six routers stamp it at the same seam. Threaded is a
    floor, not the verdict. What is still unproven is that the consumer accepts the
    child once it is tagged. This script observes that and nothing else.

The observable is a conjunction, all three true in one sample of /api/queue/pool-status:

    1. monopolize_inflight is True
    2. inflight_agentic_jobs >= 1
    3. monopolize_id equals this run's own test-suite job id

Clause 3 is required. Another session's E2E hold also shows monopolize_inflight=True.
One tick with any unrelated child running would then print a qualifying sample for a
job that was not ours. The runner exports its own id_hash as LUPIN_TEST_MONOPOLIZE_PARENT_ID
(test_suite/job.py), and pool-status reports that same id_hash as monopolize_id. The
identity is checked against the job id the submit returned.

What does not count: the sweep not erroring, no 900s timeout, the job eventually
completing, a green suite. A deferred child that runs after the hold releases looks
identical from outside, and it is the failure this script exists to detect. No qualifying
sample is a fail, never inconclusive, and the script exits non-zero in that case.

Every sample is written to disk as JSON lines, flushed per sample, so a killed run still
leaves a log. The qualifying sample is printed verbatim, not summarised.

Venue: :8000 only, and only when it is free and on the main mount. A job queued behind a
rig that recreated the container on a detached-worktree mount measures the wrong tree.
It returns a plausible number instead of an error. Both preconditions are checked before
submit, and the script refuses rather than degrading.

Usage:
    python3 src/scripts/observe_gate_b_admission.py --out io/gate-b/<stamp>/
    python3 src/scripts/observe_gate_b_admission.py --dry-run     # preconditions only, no submit
"""

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

# Bootstrap: this script runs before cosa is importable.
_lupin_root = os.environ.get( "LUPIN_ROOT" )
if _lupin_root is None:
    raise RuntimeError( "LUPIN_ROOT not set -- export LUPIN_ROOT=/path/to/project" )
_src_path = os.path.join( _lupin_root, "src" )
if _src_path not in sys.path: sys.path.insert( 0, _src_path )

from cosa.agents.test_suite.v2_client import submit_body, read_reply


BASE_URL      = "http://localhost:8000"
TEST_CONTAINER = "lupin-rest-test"
POLL_SECONDS  = 2.0

# The suite whose pytest-spawned child is exactly the job Gate B must admit.
#
# ⚠️ SUBSTITUTION, DELIBERATE AND APPROVED (Mr Radio, 2026-08-24). Row 99b09840's METHOD
# names test_presentation_live_smoke.py. This uses the RENDER-ONLY sibling, and the
# substitution is recorded in the row itself so nobody reads it as quietly not running the
# named file.
#
# It is the SAME experiment, not a cheaper approximation. The observable is whether the
# consumer ADMITS a tagged child while a monopolizer holds; Gate B does not care what the
# child COMPUTES. Verified equivalent on the three things that decide the reading:
#   · same routing command       "agent router go to presentation generator"
#   · same lineage stamp         reads LUPIN_TEST_MONOPOLIZE_PARENT_ID, sets parent_id_hash
#                                TOP-LEVEL (render_only:266-268 == live:279-281)
#   · same lineage probe         writes its row to LUPIN_TEST_LINEAGE_PROBE_FILE
#
# And the live file cannot be made cheaper: get_scenario_indices always returns [0], so it
# has exactly one scenario and its floor is real LLM spend on output nobody reads.
# Render-only skips content-generation phases 1-5 and re-renders an existing YAML — its own
# header states "~$0 (no LLM calls). Cap: $0.10".
#
# ⚠️ Its header also warns Gemini costs can be non-zero if NanoBanana or Veo fire. The cap
# bounds it; if the cap BITES that is a finding about the render path, to be reported as a
# result rather than shrugged off.
TARGET_SUITE  = "src/tests/smoke/test_presentation_render_only_smoke.py"

# Render-only re-renders a PRIOR full-pipeline YAML, so one must already exist for the test
# user. Checked before submit — a substitution whose precondition was never verified is a
# hope, not a substitution.
YAML_DIR      = "io/presentations/interactive.job.tester@lupin.deepily.ai"


def _http( method, path, token=None, body=None, timeout=30 ):
    """
    One HTTP call against the test server, using urllib (curl is prohibited for API work).

    Returns ( status_code, decoded_json_or_text ).
    """
    url  = f"{BASE_URL}{path}"
    data = json.dumps( body ).encode() if body is not None else None
    req  = urllib.request.Request( url, data=data, method=method )
    req.add_header( "Content-Type", "application/json" )
    if token:
        req.add_header( "Authorization", f"Bearer {token}" )
    try:
        with urllib.request.urlopen( req, timeout=timeout ) as resp:
            raw = resp.read().decode()
            try:    return resp.status, json.loads( raw )
            except json.JSONDecodeError: return resp.status, raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:    return e.code, json.loads( raw )
        except json.JSONDecodeError: return e.code, raw


def login():
    """
    Obtain a JWT for the pool-status and submit endpoints.

    Requires:
        - LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL / _PASSWORD in the environment

    Ensures:
        - returns the access token
        - raises with the credential names rather than a bare KeyError, because a missing
          credential is the commonest reason this script cannot start
    """
    email    = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL" )
    password = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" )
    if not email or not password:
        raise RuntimeError(
            "set LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL and "
            "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD (CLAUDE.md § TEST CREDENTIALS)"
        )
    status, payload = _http( "POST", "/auth/login", body={ "email": email, "password": password } )
    if status != 200:
        raise RuntimeError( f"login failed: HTTP {status} — {payload}" )
    return payload[ "tokens" ][ "access_token" ]


# ---------------------------------------------------------------------------
# Preconditions — refuse rather than measure the wrong thing
# ---------------------------------------------------------------------------

def check_mount():
    """
    The test container must be on the main checkout, not a detached worktree.

    A rig that recreated the container on a worktree mount measures the wrong tree and
    returns a plausible number instead of an error. That is worse than a failure, because
    nothing in the output says it happened.

    Ensures:
        - returns ( ok, detail ); never raises on a docker hiccup, so the caller can report
          "could not verify" distinctly from "verified wrong"
    """
    try:
        out = subprocess.run(
            [ "docker", "inspect", "-f",
              '{{range .Mounts}}{{.Source}}->{{.Destination}}{{"\\n"}}{{end}}', TEST_CONTAINER ],
            capture_output=True, text=True, timeout=30
        )
    except Exception as e:                                   # docker absent / not reachable
        return None, f"could not run docker inspect: {e}"
    if out.returncode != 0:
        return None, f"docker inspect failed: {out.stderr.strip()}"

    mounts   = [ m for m in out.stdout.splitlines() if m.strip() ]
    worktree = [ m for m in mounts if "/.claude/worktrees/" in m or "/worktrees/" in m ]
    if worktree:
        return False, "container is mounted on a WORKTREE: " + "; ".join( worktree )
    return True, f"{len( mounts )} mounts, none under a worktree path"


def check_prior_yaml():
    """
    Render-only re-renders a prior full-pipeline YAML; one must exist for the test user.

    Checked before submit. Without a YAML the suite cannot spawn the child, and the run
    would report a fail for a reason unrelated to Gate B.

    Ensures:
        - returns ( ok, detail ) naming the newest YAML found, or saying none was
    """
    root = os.environ.get( "LUPIN_ROOT", "." )
    d    = os.path.join( root, YAML_DIR )
    if not os.path.isdir( d ):
        return False, f"no such directory: {d}"
    yamls = [ f for f in os.listdir( d ) if f.endswith( ".yaml" ) ]
    if not yamls:
        return False, f"no .yaml in {d}"
    newest = max( yamls, key=lambda f: os.path.getmtime( os.path.join( d, f ) ) )
    return True, f"{len( yamls )} found, newest {newest}"


def check_idle( token ):
    """
    :8000 must be free: no monopolizer holding and no agentic job in flight.

    Reads the pool state, not the user-filtered queue view, which shows only the caller's
    own rows and calls a busy box idle. A monopolizer already holding must not pass as an
    empty box. Queued work that has not started is not examined.

    Ensures:
        - returns ( ok, pool_payload )
    """
    status, pool = _http( "GET", "/api/queue/pool-status", token=token )
    if status != 200:
        return False, { "error": f"pool-status HTTP {status}", "payload": pool }
    busy = bool( pool.get( "monopolize_inflight" ) ) or int( pool.get( "inflight_agentic_jobs", 0 ) ) > 0
    return ( not busy ), pool


# ---------------------------------------------------------------------------
# The observation
# ---------------------------------------------------------------------------

def _job_key( job_id ):
    """
    The identity half of a job id, for comparing a monopolize_id against a submit response.

    The submit endpoint documents the job id as "ts-{uuid8}", but pool-status returns a
    `::<user_uuid>` suffix after it. A plain `==` would report no qualifying sample while
    Gate B was admitting the child correctly, a fail caused by the instrument.

    Ensures:
        - returns the `ts-…` identity half, whichever form the id arrives in
        - this stays an exact match on a unique job id, not a loose prefix test: clause 3
          must still be unable to match somebody else's monopolizer
    """
    return job_id.split( "::" )[ 0 ] if job_id else None


def qualifies( sample, my_job_id ):
    """
    All three clauses, in this one sample.

    Requires:
        - my_job_id is the id the submit returned for this run's sweep

    Ensures:
        - True only when monopolize_inflight is True and inflight_agentic_jobs >= 1 and
          monopolize_id names this run's own job
        - clause 3 compares against this run's job, never merely "some monopolizer",
          so that another session's hold is not read as ours
    """
    mine = _job_key( my_job_id )
    return (
        bool( sample.get( "monopolize_inflight" ) )
        and int( sample.get( "inflight_agentic_jobs", 0 ) ) >= 1
        and mine is not None
        and _job_key( sample.get( "monopolize_id" ) ) == mine
    )


def watch( token, my_job_id, out_dir, max_seconds ):
    """
    Poll pool-status every POLL_SECONDS, writing every sample to disk as it arrives.

    Ensures:
        - each sample is one JSON line in samples.jsonl, flushed immediately, so a killed
          run still leaves everything it saw, where an unflushed run leaves nothing
        - returns ( qualifying_sample_or_None, n_samples )
        - stops early on the first qualifying sample, since one is all the verdict needs
    """
    os.makedirs( out_dir, exist_ok=True )
    path      = os.path.join( out_dir, "samples.jsonl" )
    started   = time.time()
    n         = 0
    qualifying = None

    with open( path, "a" ) as fh:
        while time.time() - started < max_seconds:
            status, pool = _http( "GET", "/api/queue/pool-status", token=token )
            n += 1
            record = {
                "n"            : n,
                "elapsed_s"    : round( time.time() - started, 2 ),
                "http_status"  : status,
                "my_job_id"    : my_job_id,
                "sample"       : pool,
                "qualifies"    : qualifies( pool, my_job_id ) if status == 200 else False,
            }
            fh.write( json.dumps( record ) + "\n" )
            fh.flush()
            os.fsync( fh.fileno() )                          # survive a kill, not just an exit

            if record[ "qualifies" ]:
                qualifying = record
                break
            time.sleep( POLL_SECONDS )

    return qualifying, n


def main():
    ap = argparse.ArgumentParser( description="Observe Gate B admitting a lineage child (row 99b09840)" )
    ap.add_argument( "--out", default="io/gate-b/latest", help="directory for samples.jsonl + verdict.json" )
    ap.add_argument( "--max-seconds", type=int, default=1800, help="how long to watch after submit" )
    ap.add_argument( "--dry-run", action="store_true", help="check preconditions only; do NOT submit" )
    ap.add_argument( "--watch-only", metavar="JOB_ID",
                     help="do NOT submit; resume watching an ALREADY-submitted job by id. "
                          "Exists because the watcher can be killed (a shell timeout, a "
                          "disconnect) while the job keeps running server-side — re-submitting "
                          "would start a SECOND monopolizer and measure the wrong one." )
    args = ap.parse_args()

    print( "── preconditions ──" )
    yaml_ok, yaml_detail = check_prior_yaml()
    print( f"  prior YAML for re-render: {yaml_ok}  ({yaml_detail})" )
    if not yaml_ok:
        print( "REFUSING: render-only re-renders an existing YAML; without one it cannot spawn the child." )
        return 2

    mount_ok, mount_detail = check_mount()
    print( f"  mount on main checkout : {mount_ok}  ({mount_detail})" )
    if mount_ok is False:
        print( "REFUSING: a worktree mount measures the WRONG TREE and returns a plausible number." )
        return 2

    token = login()
    idle_ok, pool = check_idle( token )
    print( f"  :8000 idle             : {idle_ok}" )
    print( f"  pool now               : {json.dumps( pool )}" )

    if args.dry_run:
        print( "\n--dry-run: preconditions only, nothing submitted." )
        return 0 if ( idle_ok and mount_ok ) else 1

    if not idle_ok:
        print( "REFUSING: :8000 is not free. Queueing behind a live gate is a different experiment." )
        return 2

    if args.watch_only:
        # Resuming: the job is already in flight, so the idle check does not apply — the box
        # being busy with MY OWN job is the state we are here to observe.
        my_job_id = args.watch_only
        print( f"\n── watch-only: resuming on {my_job_id}, NOT submitting ──" )
        qualifying, n = watch( token, my_job_id, args.out, args.max_seconds )
        return _report( args, my_job_id, qualifying, n )

    print( "\n── submit ──" )
    # Through /api/v2/submit (the old /api/test-suite/submit is retired). ⚠️ STRINGS, NOT
    # LISTS for test_types and pytest_args -- the schema rejected arrays with a 422 when
    # measured 2026-08-24, and the v2 factory parses the same strings.
    status, resp = _http( "POST", "/api/v2/submit", token=token, body=submit_body(
        "smoke",
        pytest_args         = f"{TARGET_SUITE} --auto-proxy",
        auto_fix_on_failure = False,     # a false red must not arm the TFE treadmill (bug 67473d91)
    ) )
    ok, info = read_reply( status, resp )
    if not ok:
        print( f"submit failed: HTTP {status} — {info[ 'error' ]}" )
        return 2
    my_job_id = info[ "job_id" ]
    print( f"  job_id: {my_job_id}" )
    print( f"  full response: {json.dumps( resp )}" )

    print( f"\n── watching pool-status every {POLL_SECONDS}s, writing every sample ──" )
    qualifying, n = watch( token, my_job_id, args.out, args.max_seconds )

    return _report( args, my_job_id, qualifying, n )


def _report( args, my_job_id, qualifying, n ):
    """Write verdict.json and print the sample verbatim. Shared by the submit and resume paths."""
    verdict = {
        "row"                : "99b09840",
        "my_job_id"          : my_job_id,
        "samples_taken"      : n,
        "samples_path"       : os.path.join( args.out, "samples.jsonl" ),
        "qualifying_sample"  : qualifying,
        "verdict"            : "PASS" if qualifying else "FAIL",
    }
    with open( os.path.join( args.out, "verdict.json" ), "w" ) as fh:
        json.dump( verdict, fh, indent=2 )

    print( f"\n── verdict: {verdict['verdict']} ──" )
    print( f"  samples taken : {n}" )
    print( f"  written to    : {verdict['samples_path']}" )
    if qualifying:
        # VERBATIM, not summarised — the row asks for the sample itself.
        print( "  qualifying sample, verbatim:" )
        print( json.dumps( qualifying, indent=2 ) )
        return 0

    print( "  NO QUALIFYING SAMPLE. Per row 99b09840 this is a FAIL, not inconclusive:" )
    print( "  a deferred child that runs AFTER the hold releases looks identical from" )
    print( "  outside, and is the exact failure this row exists to detect." )
    return 1


if __name__ == "__main__":  # pragma: no cover - unreachable under pytest: __name__ is the
                            #   module name, never "__main__"
    sys.exit( main() )
