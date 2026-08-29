#!/usr/bin/env python3
"""
LIVE SMOKE — DM verbosity two-arm pilot, § Verification item 6.

Fires against the RUNNING :7999 dev server. It is the last check between the
build and a two-day run nobody can redo, so it exercises the REAL send path
end-to-end (never curl — urllib only).

WORKFLOW (settled with Cheech, 2026-08-03). The arm is pinned SERVER-SIDE, not
by this harness: `dm experiment arm override` only RE-LABELS a scheduled slot,
so outside the Tue/Wed window it cannot engage the gate (dm.py:1037). To verify
the live gate before 09:00, Cheech adds ONE temp slot arm=rejecting,
slot_id "TEMP-live-gate-smoke" (its date field is 2026-08-03, which keeps
anything it produces OUT of the Tue/Wed analysis), bounces, and pings
"server up, go". This harness then just SENDS and VERIFIES against that external
pin — it does not pin anything itself.

WHAT IT PROVES for the pinned rejecting arm:
  1. Over threshold → HTTP 413 (NOT 422 — the client maps 422 to
     recipient_unresolved, cosa_voice_mcp.py:3370), body names no number.
  2. Under threshold → 201, and the persisted corpus row carries
     effective_arm=rejecting, slot_id "TEMP-live-gate-smoke", length_gate=passed,
     delivery_outcome not null.
  3. The over-threshold send still writes a corpus row (finally-block) with
     length_gate=rejected — the gate is auditable even when it refuses.

The arbiter-exemption leg is DROPPED: the fleet arbiter rides the commons store,
never the /api/dm/send gate (confirmed 2026-08-03, Cheech + Tiffany), so zero
exemption hits is the CORRECT result, not a defect — nothing to smoke here.

VENUE. Sends real DMs to the live server, so it is a deliberate, operator-timed
live action run in coordination with Cheech's temp-slot bounce — not part of the
unattended unit sweep. Sends go to recipient=tiffany (self) to avoid crew noise.

RUN (when Cheech pings "server up, go"), through the wrapper that sources creds:
    ./src/tests/run-smoke-direct.sh src/tests/smoke/test_dm_experiment_live_smoke.py
Unsourced creds RAISE (fail-loud, never a false green).

Design: src/rnd/v0.2.0/2026.08.04-dm-verbosity-reduction/2026.08.04-dm-verbosity-pilot-plan.md
"""

import json
import os
import sys
import time
import unittest
import urllib.error
import urllib.request
from unittest import mock

lupin_root = os.environ.get( "LUPIN_ROOT" )
if lupin_root is None:
    raise RuntimeError( "LUPIN_ROOT not set — export LUPIN_ROOT=/path/to/project" )
src_path = os.path.join( lupin_root, "src" )
if src_path not in sys.path: sys.path.insert( 0, src_path )

import cosa.utils.util as cu   # noqa: E402


# ── Confirmed contract (Cheech, 2026-08-03) ──────────────────────────────────
REJECT_THRESHOLD_WORDS = 150
EXPECTED_SLOT_ID       = "TEMP-live-gate-smoke"   # Cheech's temp rejecting slot (date field 08-03)
# Read the SAME sink the running server writes (dm.py:353); NEVER the
# _DM_TRAFFIC_PRODUCTION_PATH self-guard constant.
from cosa.rest.routers.dm import _DM_TRAFFIC_JSONL as CORPUS_PATH   # noqa: E402

EXPECTED_ROW_FIELDS = [
    "schedule_id", "slot_id", "scheduled_arm", "effective_arm", "assigned_at_utc",
    "reject_threshold", "eligible_for_rejection", "exemption_reason", "length_gate",
    "delivery_outcome", "experiment",
]

BASE_URL  = os.environ.get( "LUPIN_TEST_BASE_URL", "http://localhost:7999" )
_EMAIL    = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL" )
_PASSWORD = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" )
_API_KEY  = os.environ.get( "LUPIN_TEST_API_KEY" )


# ═══════════════════════════════════════════════════════════════════════════
# HTTP helpers — urllib only, never curl.
# ═══════════════════════════════════════════════════════════════════════════

def _parse( raw ):
    try:
        return json.loads( raw.decode( "utf-8" ) )
    except Exception:
        return raw.decode( "utf-8", errors="replace" )


def _post_json( path, payload, headers ):
    data = json.dumps( payload ).encode( "utf-8" )
    req  = urllib.request.Request( BASE_URL + path, data=data, method="POST" )
    req.add_header( "Content-Type", "application/json" )
    for k, v in headers.items(): req.add_header( k, v )
    try:
        with urllib.request.urlopen( req, timeout=15 ) as r:
            return r.status, _parse( r.read() )
    except urllib.error.HTTPError as e:
        return e.code, _parse( e.read() )


def auth_headers():
    """
    Resolve auth headers: prefer a ck_live API key, else a JWT from /auth/login.

    Raises:
        - RuntimeError naming the missing credential path (fail-loud, never a
          silent skip — an unsourced run must go red, not read as green).
    """
    if _API_KEY:
        return { "X-API-Key": _API_KEY }
    if _EMAIL and _PASSWORD:
        status, body = _post_json( "/auth/login", { "email": _EMAIL, "password": _PASSWORD }, {} )
        if status != 200:
            raise RuntimeError( f"/auth/login failed: {status} {body!r}" )
        tokens = body.get( "tokens", body ) if isinstance( body, dict ) else {}
        token  = tokens.get( "access_token" ) or tokens.get( "accessToken" )
        if not token:
            raise RuntimeError( f"no access_token in login body: {body!r}" )
        return { "Authorization": f"Bearer {token}" }
    raise RuntimeError(
        "No credentials. Run via ./src/tests/run-smoke-direct.sh (it sources "
        "~/.lupin/test-env.sh), or export LUPIN_TEST_API_KEY."
    )


# ═══════════════════════════════════════════════════════════════════════════
# Corpus read-back.
# ═══════════════════════════════════════════════════════════════════════════

def _corpus_line_count():
    if not os.path.exists( CORPUS_PATH ): return 0
    with open( CORPUS_PATH, encoding="utf-8" ) as fh:
        return len( fh.read().splitlines() )


def _new_rows( since ):
    if not os.path.exists( CORPUS_PATH ): return []
    with open( CORPUS_PATH, encoding="utf-8" ) as fh:
        lines = fh.read().splitlines()
    return [ json.loads( ln ) for ln in lines[ since : ] if ln.strip() ]


def _send( headers, word_count ):
    """Send one DM of `word_count` words to self (tiffany); return (status, resp, new_row)."""
    before  = _corpus_line_count()
    payload = {
        "sender_session_id" : f"smoke-{int( time.time() * 1000 )}",
        "recipient_persona" : "tiffany",
        "body"              : " ".join( [ "word" ] * word_count ),
        "sender_persona"    : "tiffany",
        "sender_icon"       : "💍",
        "sender_project"    : "lupin",
    }
    status, resp = _post_json( "/api/dm/send", payload, headers )
    time.sleep( 0.4 )   # let the finally-block corpus write land
    rows = _new_rows( before )
    return status, resp, ( rows[ -1 ] if rows else None )


# ═══════════════════════════════════════════════════════════════════════════
# The run — verify the externally-pinned rejecting arm.
# ═══════════════════════════════════════════════════════════════════════════

def run( expected_arm="rejecting" ):
    results = []   # (label, passed, detail)
    headers = auth_headers()

    # ── over threshold → 413, no number, corpus row length_gate=rejected ──
    over_status, over_resp, over_row = _send( headers, REJECT_THRESHOLD_WORDS + 50 )
    results.append( ( "over-threshold → 413 (not 422)", over_status == 413, f"status {over_status}" ) )
    results.append( ( "413 body names no number", str( REJECT_THRESHOLD_WORDS ) not in json.dumps( over_resp ), "threshold leaked" ) )
    if over_row is not None:
        results.append( ( "over-row length_gate == rejected", over_row.get( "length_gate" ) == "rejected", f"got {over_row.get('length_gate')!r}" ) )
        results.append( ( "over-row effective_arm == expected", over_row.get( "effective_arm" ) == expected_arm, f"got {over_row.get('effective_arm')!r}" ) )
        results.append( ( "over-row slot_id == expected", over_row.get( "slot_id" ) == EXPECTED_SLOT_ID, f"got {over_row.get('slot_id')!r}" ) )
    else:
        results.append( ( "over-threshold wrote a corpus row", False, "no new row — is the arm pinned + served?" ) )

    # ── under threshold → 201, row effective_arm/passed/delivered ──
    under_status, under_resp, under_row = _send( headers, REJECT_THRESHOLD_WORDS - 50 )
    results.append( ( "under-threshold → 2xx", 200 <= under_status < 300, f"status {under_status}" ) )
    if under_row is not None:
        results.append( ( "under-row effective_arm == expected", under_row.get( "effective_arm" ) == expected_arm, f"got {under_row.get('effective_arm')!r}" ) )
        results.append( ( "under-row length_gate == passed", under_row.get( "length_gate" ) == "passed", f"got {under_row.get('length_gate')!r}" ) )
        results.append( ( "under-row delivery_outcome not null", under_row.get( "delivery_outcome" ) is not None, f"got {under_row.get('delivery_outcome')!r}" ) )
        results.append( ( "under-row carries all expected fields", all( f in under_row for f in EXPECTED_ROW_FIELDS ),
                          f"missing={[ f for f in EXPECTED_ROW_FIELDS if f not in under_row ]}" ) )
    else:
        results.append( ( "under-threshold wrote a corpus row", False, "no new row" ) )

    return results


def main( argv=None ):
    import argparse
    p = argparse.ArgumentParser( description="DM-verbosity live gate smoke (verifies an externally-pinned arm)." )
    p.add_argument( "--expected-arm", default="rejecting", help="the arm Cheech pinned server-side (default rejecting)" )
    args = p.parse_args( argv )

    print( f"DM-verbosity live smoke → {BASE_URL}  (expecting arm={args.expected_arm}, slot={EXPECTED_SLOT_ID})" )
    results = run( args.expected_arm )
    width   = max( len( r[ 0 ] ) for r in results )
    passed  = sum( 1 for _, ok, _ in results if ok )
    for label, ok, detail in results:
        print( f"  {'PASS' if ok else 'FAIL'}  {label.ljust( width )}  {'' if ok else detail}" )
    print( f"\n{passed}/{len( results )} checks passed" )
    return 0 if passed == len( results ) else 1


# ═══════════════════════════════════════════════════════════════════════════
# Collectable unit checks — NO live server. Earn the file its slot in the gated
# smoke root (test_gate_reachability_census) AND pin the fail-loud creds contract.
# ═══════════════════════════════════════════════════════════════════════════

class TestLiveSmokeContracts( unittest.TestCase ):

    def test_auth_headers_raises_when_no_credentials( self ):
        """No creds → RuntimeError, never a silent skip (María, 2026-08-03)."""
        with mock.patch.multiple( sys.modules[ __name__ ], _API_KEY=None, _EMAIL=None, _PASSWORD=None ):
            with self.assertRaises( RuntimeError ):
                auth_headers()

    def test_expected_row_fields_cover_the_plan_critical_keys( self ):
        for key in ( "effective_arm", "slot_id", "length_gate", "delivery_outcome" ):
            self.assertIn( key, EXPECTED_ROW_FIELDS )


if __name__ == "__main__":
    sys.exit( main() )
