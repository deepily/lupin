"""
DM verbosity two-arm pilot — § Verification item 5 (integration).

Item 5 asks for TestClient integration: over/under threshold in each arm,
asserting HTTP status AND the corpus row shape. That splits cleanly into two
layers, and only one of them depends on the not-yet-landed send-path gate:

  LAYER A — corpus ROW SHAPE (green against HEAD today).
    `_persist_dm_row` ALREADY takes an `experiment=None` param and, when it is
    supplied, merges it in AND drops the legacy `arm` key (dm.py:434-437). The
    plan's load-bearing invariant — "no row ever carries BOTH `arm` and
    `effective_arm`" (María, 2026-08-03) — is therefore verifiable NOW at the
    writer, before Rachel's caller lands. These tests pin that invariant so a
    later change that re-introduces a double-stamped row reddens here.

  LAYER B — HTTP STATUS through the real route (413 not 422, arm-pinned).
    Needs the send-path gate + assignment_at() + the override key, all in
    Rachel's dm.py lane and Clayton's config lane. Those cases are specified
    below as a work-order and SKIPPED with an explicit reason — NOT written
    against guessed field names (Cheech, 2026-08-03: "get them from her diff
    rather than guessing"). Un-skip and fill against the merged diff.

The TestClient scaffold (Layer B fixtures) is proven-green today by a baseline
send that exercises the wiring without any experiment field.

Venue: :7999 AI-discretionary — non-destructive. The corpus sink is redirected
to a temp file (patch.object on _DM_TRAFFIC_JSONL, NEVER on the
_DM_TRAFFIC_PRODUCTION_PATH self-guard constant); the DB persist is mocked; the
notification queue is a mock. Nothing outlives the test. Fast (<5s).

Design: src/rnd/v0.2.0/2026.08.04-dm-verbosity-reduction/2026.08.04-dm-verbosity-pilot-plan.md
"""

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ── The threshold + experiment vocabulary the plan pins (Cheech-confirmed: 150) ──
REJECT_THRESHOLD_WORDS = 150

# A representative in-window experiment dict — the SHAPE plan § item 4 describes.
# Its exact contents are Rachel's to finalize; these tests assert only the
# INVARIANTS that hold regardless of the exact values (disjoint vocabulary,
# delivery_outcome present + non-null, effective_arm carried through).
def _experiment_dict( effective_arm="rejecting", length_gate="passed", delivery_outcome="delivered" ):
    return {
        "schedule_id"            : "dm-verbosity-two-arm-v1",
        "slot_id"                : "2026-08-04T09",
        "scheduled_arm"          : effective_arm,
        "effective_arm"          : effective_arm,
        "assigned_at_utc"        : "2026-08-04T13:00:00+00:00",
        "reject_threshold"       : REJECT_THRESHOLD_WORDS,
        "eligible_for_rejection" : effective_arm == "rejecting",
        "exemption_reason"       : None,
        "length_gate"            : length_gate,
        "delivery_outcome"       : delivery_outcome,
        "follows_rejection"      : False,
        "est_tokens"             : 12,
        "word_count_version"     : 1,
        "experiment"             : "two-arm-v1",
    }


# ═══════════════════════════════════════════════════════════════════════════
# LAYER A — corpus ROW SHAPE invariants (green against HEAD).
# ═══════════════════════════════════════════════════════════════════════════

class _WriterHarness( unittest.TestCase ):
    """Redirect the corpus sink to a temp file for every writer-level test."""

    def setUp( self ):
        import cosa.rest.routers.dm as dm
        self.dm          = dm
        self.corpus_path = os.path.join( tempfile.mkdtemp(), "dm_traffic.jsonl" )
        p = patch.object( dm, "_DM_TRAFFIC_JSONL", self.corpus_path )
        p.start()
        self.addCleanup( p.stop )

    def _write( self, **overrides ):
        kwargs = dict(
            body_text    = "word " * 20,
            from_persona = "tiffany",
            from_session = "sess-a",
            from_project = "lupin",
            to_persona   = "cheech",
            to_session   = "sess-b",
            quality      = None,
        )
        kwargs.update( overrides )
        self.dm._persist_dm_row( **kwargs )

    def _row( self ):
        lines = open( self.corpus_path, encoding="utf-8" ).read().splitlines()
        self.assertEqual( len( lines ), 1, f"expected exactly one corpus row, got {len( lines )}" )
        return json.loads( lines[ 0 ] )


class TestDisjointArmVocabulary( _WriterHarness ):
    """
    The plan's load-bearing invariant: a row NEVER carries both the legacy `arm`
    and the experiment `effective_arm`. A row asserting both would tell the
    classifier two contradictory things about the same send.
    """

    def test_baseline_row_carries_arm_not_effective_arm( self ):
        """experiment=None → legacy `arm` present, no experiment vocabulary."""
        self._write( experiment=None )
        row = self._row()
        self.assertIn( "arm", row )
        self.assertNotIn( "effective_arm", row )

    def test_in_window_row_carries_effective_arm_not_arm( self ):
        """experiment supplied → experiment vocabulary present, legacy `arm` ABSENT."""
        self._write( experiment=_experiment_dict( effective_arm="rejecting" ) )
        row = self._row()
        self.assertIn( "effective_arm", row )
        self.assertEqual( row[ "effective_arm" ], "rejecting" )
        self.assertNotIn( "arm", row )                     # the disjoint-vocabulary invariant

    def test_no_row_ever_carries_both_keys( self ):
        """Direct statement of the invariant across both branches."""
        for exp in ( None, _experiment_dict() ):
            with self.subTest( experiment=exp ):
                open( self.corpus_path, "w" ).close()      # reset to one-row precondition
                self._write( experiment=exp )
                row = self._row()
                self.assertFalse( "arm" in row and "effective_arm" in row,
                                  f"row carries BOTH arm and effective_arm: {row}" )


class TestDeliveryOutcomeCarriedThrough( _WriterHarness ):
    """
    `delivery_outcome` must survive the write and never be null in an in-window
    row (plan § item 4, Mr Radio 2026-08-03: initialized not_attempted, never
    left null). The writer is the last hop before disk, so pin it here.
    """

    def test_delivery_outcome_present_and_non_null( self ):
        self._write( experiment=_experiment_dict( delivery_outcome="not_attempted" ) )
        row = self._row()
        self.assertIn( "delivery_outcome", row )
        self.assertIsNotNone( row[ "delivery_outcome" ] )
        self.assertEqual( row[ "delivery_outcome" ], "not_attempted" )

    def test_length_gate_and_delivery_outcome_stay_separate( self ):
        """A row written pre-delivery cannot honestly claim 'accepted' — the two
        fields are independent, so a passed gate with a failed delivery is
        representable (plan § Gate placement)."""
        self._write( experiment=_experiment_dict( length_gate="passed", delivery_outcome="failed" ) )
        row = self._row()
        self.assertEqual( row[ "length_gate" ],      "passed" )
        self.assertEqual( row[ "delivery_outcome" ], "failed" )


# ═══════════════════════════════════════════════════════════════════════════
# LAYER B — TestClient scaffold (proven-green baseline) + the HTTP work-order.
# ═══════════════════════════════════════════════════════════════════════════

_TEST_USER_ID = "11111111-2222-3333-4444-555555555555"
_SID_CHEECH   = "cheechsess000000001"


def _write_bridge( tmp: Path, sid: str ) -> Path:
    bridge = {
        "stable_session_id" : sid,
        "session_id"        : sid,
        "owner_user_id"     : _TEST_USER_ID,
        "last_activity_iso" : "2026-08-03T12:00:00+00:00",
        "speakerphone_on"   : False,
        "idle_detection"    : { "last_interaction_at": time.time() },
    }
    path = tmp / f"cc-{sid}.json"
    path.write_text( json.dumps( bridge ) )
    return path


@pytest.fixture
def corpus_path( tmp_path, monkeypatch ):
    import cosa.rest.routers.dm as dm
    path = str( tmp_path / "dm_traffic.jsonl" )
    monkeypatch.setattr( dm, "_DM_TRAFFIC_JSONL", path )    # redirect the sink, never the guard
    return path


@pytest.fixture
def pinned_inactive_policy():
    """
    Pin the experiment policy INACTIVE for the test, then restore. Two hermeticity
    reasons, both real:
      1. WALL-CLOCK: an unpinned send lazily loads the REAL schedule; during the
         live pilot window (Tue/Wed 09:00-23:00 ET) that flips this baseline send
         into the experiment path (413 / quality suppressed) — a time-of-day pass,
         same class as the h1/h7 gates (Rachel, 2026-08-03).
      2. NO LEAK: reset in teardown so this test never leaves a pinned singleton —
         the discipline test_ask_idempotency_bounce_d2 skipped, which cost ~150
         files a false 500.
    """
    import cosa.rest.dm_experiment as dm_experiment
    import cosa.rest.routers.dm as dm
    dm_experiment.set_policy( dm_experiment.make_inactive_policy() )
    yield
    dm_experiment.reset_policy()
    dm.reset_dm_experiment_state()


@pytest.fixture
def client( tmp_path, monkeypatch, corpus_path, pinned_inactive_policy ):
    """Stripped app mounting only the dm router (modeled on test_dm_endpoint_smoke.py)."""
    import cosa.rest.routers.dm as dm
    from cosa.rest.middleware.api_key_auth import require_api_key_or_jwt
    from cosa.rest.routers.notifications import get_notification_queue

    sessions = [ ( _write_bridge( tmp_path, _SID_CHEECH ), _SID_CHEECH,
                   { "name": "cheech", "icon": "🌿", "color": "#66BB6A" } ) ]

    def _fake_find_active_sessions( stale_threshold_seconds=43200, require_persona=True ):
        return [ t for t in sessions if t[ 2 ] ] if require_persona else list( sessions )

    monkeypatch.setattr(
        "lupin_cli.claude_code.hooks.lib.session_bridge.find_active_sessions",
        _fake_find_active_sessions,
    )
    monkeypatch.setattr(
        "lupin_cli.claude_code.hooks.lib.session_bridge.build_sender_id_for_cc",
        lambda session_id=None: f"claude.code@lupin.deepily.ai#{( session_id or '' )[ :8 ]}",
    )
    monkeypatch.setattr( dm, "_persist_dm_send_sync", lambda **kw: "row-1" )

    app = FastAPI()
    app.include_router( dm.router )
    app.dependency_overrides[ require_api_key_or_jwt ] = lambda: _TEST_USER_ID
    class _Q:
        def push_notification( self, **kwargs ): pass
    app.dependency_overrides[ get_notification_queue ] = lambda: _Q()
    return TestClient( app )


def _words( n ):
    return " ".join( [ "word" ] * n )


class TestTestClientScaffoldBaseline:
    """Proves the item-5 HTTP harness wiring works against HEAD, independent of any
    experiment field — so Layer B's real cases plug into a known-good scaffold."""

    def test_a_normal_dm_is_accepted_and_writes_a_corpus_row( self, client, corpus_path ):
        resp = client.post( "/api/dm/send", json = {
            "sender_session_id" : "sid-asker",
            "recipient_persona" : "cheech",
            "body"              : _words( 20 ),
            "sender_persona"    : "tiffany",
            "sender_icon"       : "💍",
            "sender_project"    : "lupin",
        } )
        assert resp.status_code == 201, resp.text
        rows = open( corpus_path, encoding="utf-8" ).read().splitlines()
        assert len( rows ) == 1
        row = json.loads( rows[ 0 ] )
        assert row[ "to" ]     == "cheech"
        assert row[ "words" ]  == 20
        assert row[ "origin" ] == "test"                   # written under pytest to the redirected sink


# ─── LAYER B WORK-ORDER — un-skip and fill against Rachel's merged diff ───────
#
# Each needs the send-path gate + assignment_at() + the override key. Do NOT
# write these against guessed field names; read them from the diff first, then
# assert:
#
#   [rejecting, over 150w]  → HTTP 413 (NOT 422 — client maps 422 to
#                             recipient_unresolved, cosa_voice_mcp.py:3370);
#                             body names no number; corpus length_gate="rejected".
#   [rejecting, under 150w] → 201; length_gate="passed"; effective_arm="rejecting".
#   [blind, over 150w]      → 201 (no gate); `quality` key ABSENT (not null);
#                             effective_arm="blind".
#   [blind, under 150w]     → 201; effective_arm="blind".
#   [arm resolves once]     → a request straddling an hour boundary uses ONE arm.
#   [every length_gate × delivery_outcome combination] incl. delivery failure
#                             AFTER a passed gate → delivery_outcome="failed".
#
@pytest.mark.skip( reason="Layer B — needs Rachel's send-path gate + assignment_at() + "
                          "override key; fill against the merged diff, not guessed field names" )
class TestArmGateOverHttp:
    def test_rejecting_over_threshold_returns_413_not_422( self ):
        raise NotImplementedError


if __name__ == "__main__":
    unittest.main()
