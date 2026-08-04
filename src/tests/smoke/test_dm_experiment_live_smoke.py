#!/usr/bin/env python3
"""
LIVE SMOKE — DM verbosity two-arm pilot, § Verification item 6.

Fires against the RUNNING :7999 dev server before Tue 2026-08-04 09:00
America/New_York. It is the last check between the build and a two-day run
nobody can redo, so it exercises the REAL send path end-to-end (never curl —
urllib only) rather than a mocked core.

WHAT IT PROVES (per plan § Verification item 6):
  1. Pin each arm via the override INI key, send one DM per arm, read the
     persisted corpus row back, and confirm `effective_arm`, `slot_id`,
     `length_gate` match the pinned arm.
  2. `rejecting` over threshold returns 413 (NOT 422 — the client already maps
     422 to recipient_unresolved, cosa_voice_mcp.py:3370), body names no number.
  3. An arbiter-shaped poke SURVIVES a pinned `rejecting` slot — the arbiter is
     the one exempt sender (matched by its fixed sender_session_id, no
     sender_persona). If its poke died in a rejecting hour a stalled session
     would sit unpoked for a full hour.

VENUE. This SENDS real DMs and pins a runtime arm, so it is a deliberate,
operator-authorized live action against :7999 — run it manually near the
deadline, not in the unattended unit sweep. It does not mutate the DB corpus
destructively (it reads its own freshly-written rows back and tolerates them),
but it is not idempotent-free, so it is a script with a main(), not a collected
pytest by default.

⚠️ CONTRACT BLOCK BELOW — four values are owned by the implementers (Rachel's
dm.py lane, Clayton's config/schedule lane) and were NOT yet landed when this
harness was written. Each is defaulted to the plan's documented value and
flagged CONFIRM. Verify every one against the merged code before the 09:00 run;
a harness that asserts against a guessed field name is a false green.

RUN (09:00 Tuesday) — through the wrapper that sources creds, NEVER bare python:
    ./src/tests/run-smoke-direct.sh src/tests/smoke/test_dm_experiment_live_smoke.py
run-smoke-direct.sh:36 sources ~/.lupin/test-env.sh so nobody has to remember;
a bare run with unsourced creds RAISES RuntimeError (fail-loud, never a false green).

Design: src/rnd/v0.2.0/2026.08.04-dm-verbosity-reduction/2026.08.04-dm-verbosity-pilot-plan.md
Row/field reference: plan § Implementation item 4 (Corpus row).
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

import cosa.utils.util as cu


# ═══════════════════════════════════════════════════════════════════════════
# CONTRACT BLOCK — CONFIRM each against merged code before the 09:00 run.
# ═══════════════════════════════════════════════════════════════════════════

# (1) CONFIRM — the INI key that pins a single arm (plan § item 8 / § Files:
#     "override, threshold, exemption keys"). Setting it forces every send into
#     that arm regardless of the schedule, for smoke + Thursday's demo.
ARM_OVERRIDE_KEY = "dm experiment arm override"

# (2) CONFIRMED (Cheech, 2026-08-03) — reject threshold in words (plan § item 5).
REJECT_THRESHOLD_WORDS = 150

# (3) CONFIRMED (Cheech, 2026-08-03) — read the SAME sink the running server
#     writes: _DM_TRAFFIC_JSONL at dm.py:353. NEVER _DM_TRAFFIC_PRODUCTION_PATH
#     (the separate self-guard constant the conftest never patches). Imported
#     from the module so it tracks any path change rather than duplicating it.
from cosa.rest.routers.dm import _DM_TRAFFIC_JSONL as CORPUS_PATH  # noqa: E402

# (4) CONFIRM — the exempt arbiter sender_session_id (plan § C / § item 5:
#     "matched by its fixed sender_session_id"). Source from the arbiter poker's
#     configured identity (heartbeat_poker_commons_gateway.from_environment).
#     Left None so the arbiter leg SKIPS-LOUD rather than sending as a wrong id.
ARBITER_SENDER_SESSION_ID = os.environ.get( "LUPIN_ARBITER_SENDER_SESSION_ID" )

# Fields the classifier + analysis depend on (plan § item 4). Presence-checked
# on the read-back row for both arms.
EXPECTED_ROW_FIELDS = [
    "schedule_id", "slot_id", "scheduled_arm", "effective_arm", "assigned_at_utc",
    "reject_threshold", "eligible_for_rejection", "exemption_reason", "length_gate",
    "delivery_outcome", "follows_rejection", "chars", "est_tokens",
    "word_count_version", "experiment",
]

BASE_URL      = os.environ.get( "LUPIN_TEST_BASE_URL", "http://localhost:7999" )
_EMAIL        = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL" )
_PASSWORD     = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" )
_API_KEY      = os.environ.get( "LUPIN_TEST_API_KEY" )   # ck_live_... alternative to JWT


# ═══════════════════════════════════════════════════════════════════════════
# HTTP helpers — urllib only, never curl (§ testing anti-patterns).
# ═══════════════════════════════════════════════════════════════════════════

def _post_json( path, payload, headers ):
    """
    POST json to BASE_URL+path. Returns (status_code, parsed_body_or_text).

    Requires:
        - path starts with "/"; payload is JSON-serializable; headers is a dict
    Ensures:
        - returns the HTTP status even on 4xx/5xx (HTTPError is caught, not raised)
    """
    data = json.dumps( payload ).encode( "utf-8" )
    req  = urllib.request.Request( BASE_URL + path, data=data, method="POST" )
    req.add_header( "Content-Type", "application/json" )
    for k, v in headers.items(): req.add_header( k, v )
    try:
        with urllib.request.urlopen( req, timeout=15 ) as r:
            return r.status, _parse( r.read() )
    except urllib.error.HTTPError as e:
        return e.code, _parse( e.read() )


def _get_json( path, headers ):
    """GET json from BASE_URL+path. Returns (status_code, parsed_body_or_text)."""
    req = urllib.request.Request( BASE_URL + path, method="GET" )
    for k, v in headers.items(): req.add_header( k, v )
    try:
        with urllib.request.urlopen( req, timeout=15 ) as r:
            return r.status, _parse( r.read() )
    except urllib.error.HTTPError as e:
        return e.code, _parse( e.read() )


def _parse( raw ):
    try:
        return json.loads( raw.decode( "utf-8" ) )
    except Exception:
        return raw.decode( "utf-8", errors="replace" )


def auth_headers():
    """
    Resolve auth headers: prefer a ck_live API key, else a JWT from /auth/login.

    Ensures:
        - returns {"X-API-Key": ...} or {"Authorization": "Bearer ..."}
    Raises:
        - RuntimeError naming the missing credential path (the exact blocker a
          freshly-spawned session hits — creds are not inherited)
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
        "No credentials. Export LUPIN_TEST_API_KEY (ck_live_...), or "
        "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL + _PASSWORD, into this session."
    )


# ═══════════════════════════════════════════════════════════════════════════
# Corpus read-back — tail the JSONL the server writes.
# ═══════════════════════════════════════════════════════════════════════════

def read_new_corpus_rows( since_line_count ):
    """
    Return corpus rows appended after `since_line_count` lines.

    Requires:
        - since_line_count is the len() of the corpus at send time
    Ensures:
        - returns a list of parsed JSON rows written after that point
    """
    if not os.path.exists( CORPUS_PATH ): return []
    with open( CORPUS_PATH, encoding="utf-8" ) as fh:
        lines = fh.read().splitlines()
    return [ json.loads( ln ) for ln in lines[ since_line_count : ] if ln.strip() ]


def corpus_line_count():
    if not os.path.exists( CORPUS_PATH ): return 0
    with open( CORPUS_PATH, encoding="utf-8" ) as fh:
        return len( fh.read().splitlines() )


# ═══════════════════════════════════════════════════════════════════════════
# Arm pinning — set the override key and hot-reload so the running server reads it.
# ═══════════════════════════════════════════════════════════════════════════

def pin_arm( arm, headers ):
    """
    Pin the runtime arm to `arm` for the duration of the smoke.

    ⚠️ CONFIRM the pin mechanism against merged code. Two candidates:
      (a) an admin endpoint that sets the override + invalidates caches, or
      (b) editing the INI `ARM_OVERRIDE_KEY` then POST /api/init to hot-reload
          (the cache_registry path test_dm_length_thresholds_reload.py exercises).
    Until confirmed this raises so the run FAILS LOUD rather than silently
    sending into the schedule's arm instead of the pinned one.
    """
    raise NotImplementedError(
        f"CONFIRM arm-pin mechanism for '{ARM_OVERRIDE_KEY}' against Rachel/Clayton's "
        f"merged code (admin endpoint vs INI edit + /api/init). Do NOT assume — a "
        f"wrong pin sends into the scheduled arm and the smoke lies."
    )


def send_and_read( arm, word_count, headers, sender_session_id=None, sender_persona="tiffany" ):
    """
    Send one DM of `word_count` words in the (already-pinned) `arm`, read back
    the corpus row it produced.

    Returns:
        dict { status, row_or_None } — status is the HTTP code; row is the
        single new corpus row (or None if the send was rejected pre-write).
    """
    body    = " ".join( [ "word" ] * word_count )
    before  = corpus_line_count()
    payload = {
        "sender_session_id" : sender_session_id or f"smoke-{int( time.time() )}",
        "recipient_persona" : "cheech",
        "body"              : body,
        "sender_project"    : "lupin",
    }
    if sender_persona is not None:
        payload[ "sender_persona" ] = sender_persona   # arbiter leg omits this
    status, resp = _post_json( "/api/dm/send", payload, headers )
    time.sleep( 0.3 )   # let the tail write land
    new_rows = read_new_corpus_rows( before )
    return { "status": status, "resp": resp, "row": new_rows[ -1 ] if new_rows else None }


# ═══════════════════════════════════════════════════════════════════════════
# The run.
# ═══════════════════════════════════════════════════════════════════════════

def _check_row_shape( row, expected_arm, results ):
    missing = [ f for f in EXPECTED_ROW_FIELDS if f not in row ]
    results.append( ( f"[{expected_arm}] row carries all expected fields", not missing, f"missing={missing}" ) )
    if "effective_arm" in row:
        ok = row[ "effective_arm" ] == expected_arm
        results.append( ( f"[{expected_arm}] effective_arm matches pin", ok, f"got {row.get('effective_arm')!r}" ) )
    results.append( ( f"[{expected_arm}] slot_id present", bool( row.get( "slot_id" ) ), f"got {row.get('slot_id')!r}" ) )
    results.append( ( f"[{expected_arm}] delivery_outcome not null", row.get( "delivery_outcome" ) is not None, f"got {row.get('delivery_outcome')!r}" ) )


def run():
    results = []   # (label, passed, detail)
    headers = auth_headers()

    # ── blind: over + under both accepted (no gate); quality key withheld ──
    pin_arm( "blind", headers )
    for wc in ( REJECT_THRESHOLD_WORDS + 50, REJECT_THRESHOLD_WORDS - 50 ):
        r = send_and_read( "blind", wc, headers )
        results.append( ( f"[blind {wc}w] accepted (2xx)", 200 <= r[ "status" ] < 300, f"status {r['status']}" ) )
        results.append( ( f"[blind {wc}w] quality key ABSENT (not null)", isinstance( r[ "resp" ], dict ) and "quality" not in r[ "resp" ], "quality present" ) )
        if r[ "row" ]: _check_row_shape( r[ "row" ], "blind", results )

    # ── rejecting: over → 413 no-number; under → accepted ──
    pin_arm( "rejecting", headers )
    over = send_and_read( "rejecting", REJECT_THRESHOLD_WORDS + 50, headers )
    results.append( ( "[rejecting over] returns 413 (not 422)", over[ "status" ] == 413, f"status {over['status']}" ) )
    body_text = json.dumps( over[ "resp" ] )
    results.append( ( "[rejecting over] body names no number", str( REJECT_THRESHOLD_WORDS ) not in body_text, "threshold leaked in body" ) )
    under = send_and_read( "rejecting", REJECT_THRESHOLD_WORDS - 50, headers )
    results.append( ( "[rejecting under] accepted (2xx)", 200 <= under[ "status" ] < 300, f"status {under['status']}" ) )
    if under[ "row" ]: _check_row_shape( under[ "row" ], "rejecting", results )

    # ── arbiter poke survives a rejecting slot (the one exempt sender) ──
    if ARBITER_SENDER_SESSION_ID:
        arb = send_and_read( "rejecting", REJECT_THRESHOLD_WORDS + 50, headers,
                             sender_session_id=ARBITER_SENDER_SESSION_ID, sender_persona=None )
        results.append( ( "[arbiter over/rejecting] NOT rejected (exempt)", arb[ "status" ] != 413, f"status {arb['status']}" ) )
        if arb[ "row" ]:
            results.append( ( "[arbiter] length_gate == exempt", arb[ "row" ].get( "length_gate" ) == "exempt", f"got {arb['row'].get('length_gate')!r}" ) )
            results.append( ( "[arbiter] exemption_reason present", bool( arb[ "row" ].get( "exemption_reason" ) ), f"got {arb['row'].get('exemption_reason')!r}" ) )
    else:
        results.append( ( "[arbiter] SKIPPED — LUPIN_ARBITER_SENDER_SESSION_ID unset", False, "CONFIRM (4) and set the env var" ) )

    return results


# ═══════════════════════════════════════════════════════════════════════════
# Collectable unit checks — NO live server. These earn the file its slot in the
# gated smoke root (test_gate_reachability_census: a file that collects nothing
# reads as barren) AND pin the two fail-loud contracts the 09:00 run depends on:
# a wrong arm-pin must raise, and unsourced creds must raise — never a false green.
# ═══════════════════════════════════════════════════════════════════════════

class TestLiveSmokeFailLoudContracts( unittest.TestCase ):

    def test_pin_arm_raises_until_mechanism_confirmed( self ):
        """pin_arm must fail loud until the pin mechanism is confirmed against the
        merged diff — a silent no-op would send into the SCHEDULED arm and the
        smoke would lie about which arm it measured."""
        with self.assertRaises( NotImplementedError ):
            pin_arm( "blind", {} )

    def test_auth_headers_raises_when_no_credentials( self ):
        """No creds → RuntimeError, never a silent skip. An unsourced 09:00 run
        goes red loudly instead of reading as green (María, 2026-08-03)."""
        with mock.patch.multiple( sys.modules[ __name__ ], _API_KEY=None, _EMAIL=None, _PASSWORD=None ):
            with self.assertRaises( RuntimeError ):
                auth_headers()

    def test_expected_row_fields_cover_the_plan_critical_keys( self ):
        """The read-back shape check must include the fields the classifier + gate
        depend on; dropping one silently would let a malformed row pass."""
        for key in ( "effective_arm", "slot_id", "length_gate", "delivery_outcome", "follows_rejection" ):
            self.assertIn( key, EXPECTED_ROW_FIELDS )


def main():
    print( f"DM-verbosity live smoke → {BASE_URL}" )
    results = run()
    width = max( len( r[ 0 ] ) for r in results )
    passed = 0
    for label, ok, detail in results:
        mark = "PASS" if ok else "FAIL"
        print( f"  {mark}  {label.ljust( width )}  {'' if ok else detail}" )
        passed += 1 if ok else 0
    print( f"\n{passed}/{len( results )} checks passed" )
    return 0 if passed == len( results ) else 1


if __name__ == "__main__":
    sys.exit( main() )
