#!/usr/bin/env python3
"""
Observe Gate B ADMITTING a lineage child through a monopoly hold — row 99b09840.

WHAT THIS ANSWERS, and what it deliberately does not. Row 7451bebe proved the parent-id
tag is THREADED: six routers stamp it at the same seam, eight untagged callers were closed,
a strict marker forced its own waiver off. Tiberius, in red on that row: "THREADED IS A
FLOOR, NOT THE VERDICT." What is still unproven is that the CONSUMER ACCEPTS the child once
it is tagged. This script observes that and nothing else.

THE OBSERVABLE IS A CONJUNCTION — all three true in ONE sample of /api/queue/pool-status:

    1. monopolize_inflight is True
    2. inflight_agentic_jobs >= 1
    3. monopolize_id == THIS RUN'S OWN test-suite job id

⚠️ CLAUSE 3 IS NOT DECORATION. maria's watcher on 2026-08-21 was reading
monopolize_inflight=True off SOMEBODY ELSE'S E2E hold; one tick with any unrelated child
running and it would have printed QUALIFYING SAMPLE against a job that was not hers. On a
box several sessions submit to, "during the hold" has to mean "during MY hold". The runner
exports its own id_hash as LUPIN_TEST_MONOPOLIZE_PARENT_ID (test_suite/job.py) and that same
id_hash is what pool-status reports as monopolize_id, so the identity is directly checkable
against the job id the submit returned.

⚠️ WHAT DOES NOT COUNT, restated here so it cannot drift in the reading: the sweep not
erroring; no 900s timeout; the job eventually completing; a green suite. A deferred child
that runs AFTER the hold releases looks identical from the outside and is the exact failure
this row is about. NO QUALIFYING SAMPLE IS A FAIL, NOT INCONCLUSIVE — and this script exits
non-zero in that case rather than reporting an ambiguity.

⚠️ EVERY SAMPLE IS WRITTEN TO DISK, AS JSON LINES, FLUSHED PER SAMPLE. The 2026-08-21
attempt left no log anywhere, and that is half of why nobody could say what happened. A
verdict nobody can re-read is not evidence. The qualifying sample is printed VERBATIM, not
summarised, for the same reason.

VENUE: :8000 only, and only when it is free and on the MAIN mount. A job queued behind a rig
that recreated the container on a detached-worktree mount measures the WRONG TREE and returns
a plausible number instead of an error. Both preconditions are checked before submit, and the
script refuses rather than degrading.

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
    One HTTP call against the test server.

    ⚠️ urllib, never curl — curl is prohibited for API work (CLAUDE.md § testing
    anti-patterns). Returns ( status_code, decoded_json_or_text ).
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
    The test container must be on the MAIN checkout, not a detached worktree.

    A rig that recreated the container on a worktree mount measures the WRONG TREE and
    returns a plausible number instead of an error — which is worse than a failure, because
    nothing about the output says it happened.

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
    Render-only re-renders a PRIOR full-pipeline YAML; one must exist for the test user.

    Checked BEFORE submit because a substitution whose precondition was never verified is a
    hope rather than a substitution. Without a YAML the suite cannot spawn the child at all,
    and the run would report NO QUALIFYING SAMPLE — a FAIL, per this row — for a reason that
    has nothing to do with Gate B.

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
    :8000 must be free — nothing running, nothing queued.

    ⚠️ Reads the pool state, NOT only the user-filtered queue view. Row 62eb2e9c's precheck
    is the model: a filtered queue view shows only your own rows and will call a busy box
    idle. A monopolizer already holding is the specific thing that must not be mistaken for
    an empty box, because this script's whole subject is who holds the monopoly.

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

    ⚠️ MEASURED, NOT ASSUMED — and a plain `==` here would have failed a WORKING system.
    The submit endpoint's own field description says the job id is "ts-{uuid8}", but a live
    pool-status read on 2026-08-24 returned:

        "monopolize_id": "ts-21fd1f2b::50c73ba7-36dd-4eaf-a7e2-63256252c84f"

    i.e. the id carries a `::<user_uuid>` suffix. Comparing the documented shape against the
    live shape would report NO QUALIFYING SAMPLE while Gate B was admitting the child
    correctly — a FAIL verdict caused by the instrument, on the one row whose whole subject
    is an instrument that could not see. Found by running the preconditions against the live
    box before submitting anything.

    Ensures:
        - returns the `ts-…` identity half, whichever form the id arrives in
        - this stays an EXACT match on a unique job id, not a loose prefix test: clause 3
          must still be unable to match somebody else's monopolizer
    """
    return job_id.split( "::" )[ 0 ] if job_id else None


def qualifies( sample, my_job_id ):
    """
    All three clauses, in THIS one sample.

    Requires:
        - my_job_id is the id the submit returned for THIS run's sweep

    Ensures:
        - True only when monopolize_inflight is True AND inflight_agentic_jobs >= 1 AND
          monopolize_id names THIS run's own job
        - clause 3 compares against THIS run's job, never merely "some monopolizer" — that
          is the 2026-08-21 defect this row exists to not repeat
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
    Poll pool-status every POLL_SECONDS, writing EVERY sample to disk as it arrives.

    Ensures:
        - each sample is one JSON line in samples.jsonl, flushed immediately, so a killed
          run still leaves everything it saw (the 08-21 attempt left nothing)
        - returns ( qualifying_sample_or_None, n_samples )
        - stops early on the first qualifying sample; the row asks for ONE
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
    status, resp = _http( "POST", "/api/test-suite/submit", token=token, body={
        # ⚠️ STRINGS, NOT LISTS. The endpoint's schema rejects arrays with a 422
        # (string_type on both fields) — measured 2026-08-24 on the first fire.
        "test_types"           : "smoke",
        "pytest_args"          : f"{TARGET_SUITE} --auto-proxy",
        "auto_fix_on_failure"  : False,      # a false red must not arm the TFE treadmill (bug 67473d91)
    } )
    if status not in ( 200, 201 ):
        print( f"submit failed: HTTP {status} — {resp}" )
        return 2
    my_job_id = resp.get( "job_id" ) or resp.get( "id_hash" )
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


if __name__ == "__main__":
    sys.exit( main() )
