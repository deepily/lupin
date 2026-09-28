#!/usr/bin/env python3
"""
submit-test-suite.py — submit ONE test-suite job to a Lupin server's /api/test-suite/submit.

The sanctioned door for :8000 runs (CLAUDE.md § Testing venues), wrapped so a seat does not
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
"""
import argparse, json, os, sys

import requests


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
        - returns the JSON body for /api/test-suite/submit, omitting unset optional fields
    """
    payload = {
        "test_types"          : args.test_types,
        "auto_fix_on_failure" : args.auto_fix,
        "dry_run"             : args.dry_run,
    }
    if args.pytest_args  is not None: payload[ "pytest_args" ]  = args.pytest_args
    if args.scheduled_at is not None: payload[ "scheduled_at" ] = args.scheduled_at
    return payload


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
    print( f"POST {args.base_url}/api/test-suite/submit {json.dumps( payload )}" )
    resp = requests.post( f"{args.base_url}/api/test-suite/submit",
                          headers={ "Authorization": f"Bearer {token}" }, json=payload, timeout=10 )
    print( f"HTTP {resp.status_code}: {resp.text[ :1000 ]}" )
    return 0 if resp.status_code in ( 200, 201, 202 ) else 3


if __name__ == "__main__":
    sys.exit( main( sys.argv[ 1: ] ) )
