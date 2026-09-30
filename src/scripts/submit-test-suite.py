#!/usr/bin/env python3
"""
submit-test-suite.py — submit ONE test-suite job to a Lupin server through POST /api/v2/submit
(command `agent router go to test suite`; the old /api/test-suite/submit is retired to 410).

The sanctioned door for :8000 runs (CLAUDE.md § Testing venues; /api/v2/submit), wrapped so a seat does not
hand-roll a login + POST each time. It does NOT check the venue is idle — run
`PYTHONPATH=src python3 -m cosa.rest.venue_idle --port 8000` first and read its exit code.

Usage:
    submit-test-suite.py --test-types e2e_b --pytest-args "-v -k 'name_a or name_b'"
    submit-test-suite.py --test-types e2e_a --scheduled-at 2026-09-28T19:00:00-04:00
    submit-test-suite.py --test-types unit --dry-run

Credentials: LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL / _PASSWORD (the shared tester account).
auto_fix_on_failure defaults to FALSE (landing-run convention, bug 67473d91); pass --auto-fix
only for a deliberate bug-hunt.

Exit codes: 0 submitted · 1 bad usage or missing credentials · 2 login failed · 3 submit refused
(v2 answers HTTP 200 with status "failed" for a refused submit -- e.g. an unknown suite name --
so the exit code reads the reply, not the HTTP code)
"""
import argparse, json, os, sys

# Bootstrap: this script runs before cosa is importable.
_lupin_root = os.environ.get( "LUPIN_ROOT" )
if _lupin_root is None:
    raise RuntimeError( "LUPIN_ROOT not set -- export LUPIN_ROOT=/path/to/project" )
_src_path = os.path.join( _lupin_root, "src" )
if _src_path not in sys.path: sys.path.insert( 0, _src_path )

import requests

from cosa.agents.test_suite.v2_client import submit_body, read_reply


def parse_args( argv ):
    """
    Requires:
        - argv is a list of command-line strings

    Ensures:
        - returns the parsed namespace; --test-types is required
    """
    p = argparse.ArgumentParser( description="Submit one test-suite job." )
    p.add_argument( "--test-types",   required=True, help="comma-separated suite names, e.g. e2e_b or e2e_a,e2e_b" )
    p.add_argument( "--pytest-args",  default=None,  help="extra pytest args, one shell-style string" )
    p.add_argument( "--scheduled-at", default=None,  help="ISO datetime; omit to run now" )
    p.add_argument( "--base-url",     default=os.environ.get( "LUPIN_SCHEDULE_BASE_URL", "http://localhost:8000" ) )
    p.add_argument( "--auto-fix",     action="store_true", help="enable TFE auto-dispatch for this run" )
    p.add_argument( "--dry-run",      action="store_true", help="queue the job but skip the pytest subprocess" )
    return p.parse_args( argv )


def build_payload( args ):
    """
    Requires:
        - args is the namespace from parse_args

    Ensures:
        - returns the JSON body for /api/v2/submit, omitting unset optional fields
        - auto_fix_on_failure is always sent (False unless --auto-fix), per the landing-run convention
    """
    return submit_body(
        args.test_types,
        pytest_args         = args.pytest_args,
        dry_run             = args.dry_run,
        auto_fix_on_failure = args.auto_fix,
        scheduled_at        = args.scheduled_at,
    )


def main( argv ):
    """
    Requires:
        - the tester credentials are exported

    Ensures:
        - prints the server's response and returns an exit code per the module docstring
    """
    args     = parse_args( argv )
    email    = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL" )
    password = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" )
    if not email or not password:
        print( "ERROR: set LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL and _PASSWORD", file=sys.stderr )
        return 1

    login = requests.post( f"{args.base_url}/auth/login", json={ "email": email, "password": password }, timeout=10 )
    if login.status_code != 200:
        print( f"ERROR: login to {args.base_url} answered {login.status_code}: {login.text[ :300 ]}", file=sys.stderr )
        return 2
    token = login.json()[ "tokens" ][ "access_token" ]

    payload = build_payload( args )
    print( f"POST {args.base_url}/api/v2/submit {json.dumps( payload )}" )
    resp = requests.post( f"{args.base_url}/api/v2/submit",
                          headers={ "Authorization": f"Bearer {token}" }, json=payload, timeout=10 )
    print( f"HTTP {resp.status_code}: {resp.text[ :1000 ]}" )
    try:    body = resp.json()
    except ValueError: body = None
    ok, info = read_reply( resp.status_code, body )
    if ok: print( f"queued: job_id={info[ 'job_id' ]} queue_position={info[ 'queue_position' ]}" )
    else:  print( f"REFUSED: {info[ 'error' ]}", file=sys.stderr )
    return 0 if ok else 3


if __name__ == "__main__":
    sys.exit( main( sys.argv[ 1: ] ) )
