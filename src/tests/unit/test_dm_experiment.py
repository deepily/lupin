"""
Unit tests for the DM verbosity two-arm pilot (plan items 3/4/5):

    - the runtime policy object (cosa.rest.dm_experiment): assignment_at frozen-clock
      contract, schedule/config loading, the singleton seams
    - the in-window send path (cosa.rest.routers.dm.execute_dm_send): arm resolution,
      the 413 length gate, the crash-safe corpus row, follows_rejection + its slot
      boundary reset, the arbiter exemption, and the operator override

Design: src/rnd/v0.2.0/2026.08.04-dm-verbosity-reduction/2026.08.04-dm-verbosity-pilot-plan.md
"""

import collections
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import cosa.rest.dm_experiment as dm_experiment


# ── Fixture slots: two ADJACENT hour-blocks with DIFFERENT arms, so a boundary test
# and a frozen-clock "one arm" test have real neighbours to cross. ──────────────────
SLOT_A = { "slot_id": "tue-09", "arm": "rejecting", "local_hour": 9,
           "start_utc": "2026-08-04T13:00:00+00:00", "end_utc": "2026-08-04T14:00:00+00:00" }
SLOT_B = { "slot_id": "tue-10", "arm": "blind", "local_hour": 10,
           "start_utc": "2026-08-04T14:00:00+00:00", "end_utc": "2026-08-04T15:00:00+00:00" }

_IN_A = datetime( 2026, 8, 4, 13, 30, tzinfo=timezone.utc )   # inside SLOT_A
_IN_B = datetime( 2026, 8, 4, 14, 30, tzinfo=timezone.utc )   # inside SLOT_B


# ═════════════════════════════════════════════════════════════════════════════════
# Policy object — assignment_at, parsing, loading, singleton
# ═════════════════════════════════════════════════════════════════════════════════

class TestAssignmentAt( unittest.TestCase ):
    """The frozen-clock contract: inside → the slot, outside → None, naive → raise."""

    def setUp( self ):
        self.policy = dm_experiment.make_policy( slots=[ SLOT_A, SLOT_B ] )

    def test_inside_a_slot_returns_its_arm( self ):
        self.assertEqual( self.policy.assignment_at( _IN_A )[ "arm" ], "rejecting" )

    def test_start_instant_is_inclusive( self ):
        at_start = datetime( 2026, 8, 4, 13, 0, tzinfo=timezone.utc )
        self.assertEqual( self.policy.assignment_at( at_start )[ "slot_id" ], "tue-09" )

    def test_end_instant_is_exclusive_and_belongs_to_the_next_slot( self ):
        """09:59:59.9→10:00:00.1 must NOT split: the boundary instant is one arm. At
        exactly 14:00 UTC the 13:00 slot has ended and the 14:00 slot owns it."""
        at_boundary = datetime( 2026, 8, 4, 14, 0, tzinfo=timezone.utc )
        self.assertEqual( self.policy.assignment_at( at_boundary )[ "arm" ], "blind" )

    def test_before_all_intervals_is_none( self ):
        self.assertIsNone( self.policy.assignment_at( datetime( 2026, 8, 4, 12, 0, tzinfo=timezone.utc ) ) )

    def test_after_all_intervals_is_none( self ):
        self.assertIsNone( self.policy.assignment_at( datetime( 2026, 8, 4, 15, 0, tzinfo=timezone.utc ) ) )

    def test_naive_datetime_raises( self ):
        """A naive instant cannot be placed on the UTC schedule without guessing a zone."""
        with self.assertRaises( ValueError ):
            self.policy.assignment_at( datetime( 2026, 8, 4, 13, 30 ) )

    def test_non_datetime_raises( self ):
        with self.assertRaises( ValueError ):
            self.policy.assignment_at( "2026-08-04T13:30:00+00:00" )

    def test_a_non_utc_zone_is_converted_not_rejected( self ):
        """09:30 EDT (UTC-4) == 13:30 UTC == inside SLOT_A."""
        edt = timezone( timedelta( hours=-4 ) )
        self.assertEqual(
            self.policy.assignment_at( datetime( 2026, 8, 4, 9, 30, tzinfo=edt ) )[ "arm" ],
            "rejecting",
        )

    def test_result_is_a_copy_caller_cannot_mutate_the_table( self ):
        got = self.policy.assignment_at( _IN_A )
        got[ "arm" ] = "tampered"
        self.assertEqual( self.policy.assignment_at( _IN_A )[ "arm" ], "rejecting" )


class TestParseSlots( unittest.TestCase ):

    def test_missing_end_utc_defaults_to_one_hour( self ):
        pol = dm_experiment.make_policy( slots=[
            { "slot_id": "x", "arm": "blind", "start_utc": "2026-08-04T13:00:00+00:00" } ] )
        self.assertEqual( pol.assignment_at( _IN_A )[ "slot_id" ], "x" )        # 13:30 inside [13,14)
        self.assertIsNone( pol.assignment_at( _IN_B ) )                         # 14:30 outside

    def test_naive_iso_start_is_read_as_utc( self ):
        """The generator writes '+00:00'; a naive string is belt-and-braces read AS UTC."""
        pol = dm_experiment.make_policy( slots=[
            { "slot_id": "x", "arm": "blind", "start_utc": "2026-08-04T13:00:00",
              "end_utc": "2026-08-04T14:00:00" } ] )
        self.assertEqual( pol.assignment_at( _IN_A )[ "slot_id" ], "x" )

    def test_missing_required_field_fails_loud( self ):
        with self.assertRaises( KeyError ):
            dm_experiment.make_policy( slots=[ { "arm": "blind", "start_utc": "2026-08-04T13:00:00+00:00" } ] )


class TestMakePolicy( unittest.TestCase ):

    def test_junk_override_is_coerced_to_none( self ):
        pol = dm_experiment.make_policy( slots=[], override_arm="graded" )
        self.assertIsNone( pol.override_arm )

    def test_valid_override_is_kept( self ):
        pol = dm_experiment.make_policy( slots=[], override_arm="rejecting" )
        self.assertEqual( pol.override_arm, "rejecting" )

    def test_inactive_policy_is_always_outside_the_window( self ):
        pol = dm_experiment.make_inactive_policy()
        self.assertIsNone( pol.assignment_at( _IN_A ) )
        self.assertIsNone( pol.experiment )

    def test_exempt_ids_accepts_an_iterable_and_strips_each( self ):
        pol = dm_experiment.make_policy( slots=[], exempt_sender_session_ids=[ "x ", " y", "" ] )
        self.assertEqual( pol.exempt_sender_session_ids, frozenset( { "x", "y" } ) )


class TestLoadSchedule( unittest.TestCase ):

    def setUp( self ):
        """
        SUSPENSION OFF for this class only (2026-08-13).

        These tests assert a property of the COMMITTED SCHEDULE FILE — that its slots
        actually resolve inside the declared windows, i.e. it is armed in fact and not
        only on paper. Rick suspended the pilot on 2026-08-13, which makes
        load_default_policy() short-circuit to an inactive policy before it ever reads
        the file, so every one of those assertions would pass vacuously by asserting
        None against None.

        Patching the switch off here keeps them testing what they were written to test.
        The suspension itself is asserted separately and explicitly by
        TestSuspension below — a test whose subject IS the switch.
        """
        patcher = patch.object( dm_experiment, "is_suspended", lambda: False )
        patcher.start()
        self.addCleanup( patcher.stop )

    def test_missing_file_is_inactive( self ):
        slots, sid, exp = dm_experiment._load_schedule( "/no/such/schedule.json" )
        self.assertEqual( ( slots, sid, exp ), ( [], None, None ) )

    def test_malformed_json_is_inactive( self ):
        path = os.path.join( tempfile.mkdtemp(), "bad.json" )
        with open( path, "w", encoding="utf-8" ) as f:
            f.write( "{ this is not json" )
        self.assertEqual( dm_experiment._load_schedule( path ), ( [], None, None ) )

    def test_valid_file_loads_slots_and_id( self ):
        path = os.path.join( tempfile.mkdtemp(), "sched.json" )
        with open( path, "w", encoding="utf-8" ) as f:
            json.dump( { "schedule_id": "test-sched", "experiment": "two-arm-v1",
                         "slots": [ SLOT_A, SLOT_B ] }, f )
        slots, sid, exp = dm_experiment._load_schedule( path )
        self.assertEqual( len( slots ), 2 )
        self.assertEqual( sid, "test-sched" )
        self.assertEqual( exp, "two-arm-v1" )

    def test_the_real_committed_schedule_has_112_slots_in_three_blocks( self ):
        """
        The pilot's actual input (Clayton's item 2). 112 slots across three declared
        windows: the original 28 (Tue/Wed 08-04..05), the 28-slot Thu/Fri/Sat
        extension (Rick, 2026-08-06), and the 56-slot week-2 block resuming
        collection 08-11..15 (Rick, 2026-08-11).

        The schedule_id and experiment tag are UNCHANGED, so the analyzer keeps
        pooling every block under `two-arm-v1` — while each block's own id lets it
        be reported standalone, which matters because the window was extended
        twice after interim results had been seen.
        """
        slots, sid, exp = dm_experiment._load_schedule( dm_experiment._DM_SCHEDULE_PATH )

        # Block ids are counted from the FILE, not from the loaded slots: the
        # loader projects a deliberately narrow public dict (arm, slot_id,
        # local_hour, start_utc) that carries no block. Rows are therefore
        # attributed to a block by timestamp, which works only because the three
        # windows are disjoint.
        with open( dm_experiment._DM_SCHEDULE_PATH ) as handle:
            blocks = collections.Counter( s[ "block" ] for s in json.load( handle )[ "slots" ] )

        self.assertEqual( len( slots ), 112 )
        self.assertEqual( blocks[ "dm-verbosity-two-arm-v1" ],       28 )
        self.assertEqual( blocks[ "dm-verbosity-two-arm-v1-ext" ],   28 )
        self.assertEqual( blocks[ "dm-verbosity-two-arm-v1-week2" ], 56 )
        self.assertEqual( sid, "dm-verbosity-two-arm-v1" )
        self.assertEqual( exp, "two-arm-v1" )

    def test_the_committed_schedule_covers_the_week2_window( self ):
        """
        Week 2 must actually resolve, else the regenerated file is armed on paper
        only — the failure mode that left three days of rows untagged. Probes one
        instant per day, including the Tuesday 15:00 open.
        """
        import datetime as _dt
        policy = dm_experiment.load_default_policy()
        for label, instant in (
            ( "Tue 15:30 EDT", _dt.datetime( 2026, 8, 11, 19, 30, tzinfo=_dt.timezone.utc ) ),
            ( "Wed 09:30 EDT", _dt.datetime( 2026, 8, 12, 13, 30, tzinfo=_dt.timezone.utc ) ),
            ( "Thu 20:30 EDT", _dt.datetime( 2026, 8, 14,  0, 30, tzinfo=_dt.timezone.utc ) ),
            ( "Fri 12:30 EDT", _dt.datetime( 2026, 8, 14, 16, 30, tzinfo=_dt.timezone.utc ) ),
            ( "Sat 13:30 EDT", _dt.datetime( 2026, 8, 15, 17, 30, tzinfo=_dt.timezone.utc ) ),
        ):
            with self.subTest( slot=label ):
                assignment = policy.assignment_at( instant )
                self.assertIsNotNone( assignment, f"{label} resolved to no slot" )
                self.assertIn( assignment[ "arm" ], ( "blind", "rejecting" ) )

    def test_the_week2_block_does_not_arm_tuesday_morning( self ):
        """
        The instruction landed at 14:36 EDT. 09:00-14:00 that day must stay
        unarmed — arming an elapsed hour would claim rows collected before the
        block existed, which is re-labelling history rather than collecting.
        """
        import datetime as _dt
        policy = dm_experiment.load_default_policy()
        self.assertIsNone( policy.assignment_at( _dt.datetime( 2026, 8, 11, 15, 30, tzinfo=_dt.timezone.utc ) ) )

    def test_the_committed_schedule_is_closed_after_week2_ends( self ):
        """Week 2 has a FIXED end — Sat 2026-08-15 15:00 EDT. Nothing resolves after it."""
        import datetime as _dt
        policy = dm_experiment.load_default_policy()
        self.assertIsNone( policy.assignment_at( _dt.datetime( 2026, 8, 15, 19, 30, tzinfo=_dt.timezone.utc ) ) )

    def test_the_committed_schedule_covers_the_extension_window( self ):
        """
        A slot must actually resolve inside the extension, else the regenerated file
        is armed on paper only. Probes one instant in each extension day.
        """
        import datetime as _dt
        policy = dm_experiment.load_default_policy()
        for label, instant in (
            ( "Thu 20:00 EDT", _dt.datetime( 2026, 8, 7, 0, 30, tzinfo=_dt.timezone.utc ) ),
            ( "Fri 12:00 EDT", _dt.datetime( 2026, 8, 7, 16, 30, tzinfo=_dt.timezone.utc ) ),
            ( "Sat 15:00 EDT", _dt.datetime( 2026, 8, 8, 19, 30, tzinfo=_dt.timezone.utc ) ),
        ):
            with self.subTest( slot=label ):
                assignment = policy.assignment_at( instant )
                self.assertIsNotNone( assignment, f"{label} resolved to no slot" )
                self.assertIn( assignment[ "arm" ], ( "blind", "rejecting" ) )

    def test_the_committed_schedule_is_closed_after_saturday_evening( self ):
        """The extension has a FIXED end — Sat 19:00 EDT. Nothing resolves after it."""
        import datetime as _dt
        policy = dm_experiment.load_default_policy()
        self.assertIsNone( policy.assignment_at( _dt.datetime( 2026, 8, 8, 23, 30, tzinfo=_dt.timezone.utc ) ) )


def _fake_cm( values ):
    class _CM:
        def __init__( self, **kwargs ): pass
        def get( self, key, default=None, return_type=None ):
            return values.get( key, default )
    return _CM


def _fake_cm_broken():
    class _CM:
        def __init__( self, **kwargs ):
            raise RuntimeError( "config unavailable" )
    return _CM


class TestLoadConfig( unittest.TestCase ):

    def _under( self, cm_class ):
        with patch( "cosa.config.configuration_manager.ConfigurationManager", cm_class ):
            return dm_experiment._load_config()

    def test_defaults_when_keys_absent( self ):
        override, reason, threshold, exempt = self._under( _fake_cm( {} ) )
        self.assertEqual( ( override, threshold, exempt ), ( None, 150, frozenset() ) )
        self.assertEqual( reason, "manual override" )

    def test_supplied_values_are_read( self ):
        override, reason, threshold, exempt = self._under( _fake_cm( {
            "dm experiment arm override"             : "REJECTING",   # case-normalized
            "dm experiment arm override reason"      : "Thursday demo",
            "dm experiment reject threshold words"   : 120,
            "dm experiment exempt sender session id" : "arbiter-sess-1",
        } ) )
        self.assertEqual( override, "rejecting" )
        self.assertEqual( reason, "Thursday demo" )
        self.assertEqual( threshold, 120 )
        self.assertEqual( exempt, frozenset( { "arbiter-sess-1" } ) )

    def test_comma_separated_exempt_becomes_a_set_of_all_ids( self ):
        """The arbiter presents under >1 identity; all three are set, blanks dropped."""
        _, _, _, exempt = self._under( _fake_cm( {
            "dm experiment exempt sender session id": "arbiter-runner, heartbeat-arbiter , , lupin-arbiter-app-8001",
        } ) )
        self.assertEqual( exempt, frozenset( { "arbiter-runner", "heartbeat-arbiter", "lupin-arbiter-app-8001" } ) )

    def test_junk_override_becomes_none( self ):
        override, _, _, _ = self._under( _fake_cm( { "dm experiment arm override": "graded" } ) )
        self.assertIsNone( override )

    def test_blank_exempt_is_empty_set( self ):
        _, _, _, exempt = self._under( _fake_cm( { "dm experiment exempt sender session id": "   " } ) )
        self.assertEqual( exempt, frozenset() )

    def test_config_read_failure_falls_back_to_safe_defaults( self ):
        self.assertEqual( self._under( _fake_cm_broken() ), ( None, "manual override", 150, frozenset() ) )


class TestSingleton( unittest.TestCase ):

    def tearDown( self ):
        dm_experiment.reset_policy()

    def test_set_policy_then_get_returns_it( self ):
        pol = dm_experiment.make_inactive_policy()
        dm_experiment.set_policy( pol )
        self.assertIs( dm_experiment.get_policy(), pol )

    def test_reset_forces_a_reload( self ):
        dm_experiment.set_policy( dm_experiment.make_inactive_policy() )
        dm_experiment.reset_policy()
        self.assertIsNone( dm_experiment._POLICY )
        reloaded = dm_experiment.get_policy()          # lazy reload from disk + ini
        self.assertIsInstance( reloaded, dm_experiment.ExperimentPolicy )

    def test_module_assignment_at_reads_the_singleton( self ):
        dm_experiment.set_policy( dm_experiment.make_policy( slots=[ SLOT_A ] ) )
        self.assertEqual( dm_experiment.assignment_at( _IN_A )[ "arm" ], "rejecting" )

    def test_load_default_policy_returns_a_policy( self ):
        self.assertIsInstance( dm_experiment.load_default_policy(), dm_experiment.ExperimentPolicy )


# ═════════════════════════════════════════════════════════════════════════════════
# In-window send path — execute_dm_send under an ACTIVE policy
# ═════════════════════════════════════════════════════════════════════════════════

def _make_send_body( **overrides ):
    from cosa.rest.routers.dm import DmSendRequest
    fields = dict(
        sender_session_id = "sender-aaaa",
        body              = "short body here.",
        recipient_persona = "mr radio",
        sender_persona    = "Rachel",
        sender_icon       = "🕊️",
        sender_project    = "lupin",
    )
    fields.update( overrides )
    return DmSendRequest( **fields )


_LONG_BODY = " ".join( [ "word" ] * 160 )   # 160 words > 150 threshold


# Row ec5cf83a: grading + the corpus row it rides on run OFF the send path, on a
# background worker. Tests that assert on the GRADE or the ROW inject this runner,
# which executes the deferred job in the caller's thread — so the assertion reads a
# finished job instead of racing one. Production's default refuses to defer under
# pytest at all (dm._submit_deferred_grade's self-guard), which is what keeps a unit
# test from ever reaching the live grader.
def _run_deferred_inline( job ):
    job()
    return True


class _ExperimentHarness( unittest.TestCase ):

    def setUp( self ):
        import cosa.rest.routers.dm as dm
        self.dm          = dm
        self.execute     = dm.execute_dm_send
        self.queue       = MagicMock()
        self.persist     = MagicMock( return_value="db-123" )
        self.spy         = MagicMock( side_effect=lambda sid, project=None: f"claude.code@{project}.deepily.ai#{sid}" )
        self.resolve     = MagicMock( return_value={
            "http_status": 200, "session_id": "abcdef1234567890", "persona_name": "mr radio" } )
        # Redirect the corpus sink to a throwaway file (never the real host corpus).
        self.corpus_path = os.path.join( tempfile.mkdtemp(), "dm_traffic.jsonl" )
        _cp = patch.object( dm, "_DM_TRAFFIC_JSONL", self.corpus_path )
        _cp.start(); self.addCleanup( _cp.stop )
        dm.reset_dm_experiment_state()
        self.addCleanup( dm.reset_dm_experiment_state )
        self.addCleanup( dm_experiment.reset_policy )

    def _set_policy( self, **kw ):
        kw.setdefault( "slots", [ SLOT_A, SLOT_B ] )
        dm_experiment.set_policy( dm_experiment.make_policy( **kw ) )

    def _run( self, body, arrival=_IN_A, grader=lambda b: None, **kw ):
        kw.setdefault( "defer_grade_fn", _run_deferred_inline )
        return self.execute(
            authenticated_user_id = "user-uuid-1",
            body                  = body,
            notification_queue    = self.queue,
            resolve_recipient_fn  = self.resolve,
            build_sender_id       = self.spy,
            persist_fn            = self.persist,
            new_id_fn             = lambda: "fixed-msg-id",
            grade_quality_fn      = grader,
            arrival_utc_fn        = lambda: arrival,
            **kw,
        )

    def _row( self ):
        return json.loads( open( self.corpus_path, encoding="utf-8" ).read().splitlines()[ 0 ] )


class TestBlindArm( _ExperimentHarness ):

    def test_blind_delivers_and_suppresses_the_quality_key( self ):
        """blind → judge runs (corpus/audit) but the quality key is ABSENT from the
        response — a present-but-empty grade would itself signal measurement."""
        self._set_policy()
        grade = { "length": { "weight": 2 }, "directness": { "weight": 1 },
                  "tone": { "weight": 1 }, "overall": { "weight": 1 } }
        result = self._run( _make_send_body(), arrival=_IN_B, grader=lambda b: grade )
        self.assertEqual( result[ "http_status" ], 201 )
        self.assertNotIn( "quality", result )

    def test_blind_corpus_row_has_effective_arm_and_no_legacy_arm( self ):
        self._set_policy()
        self._run( _make_send_body(), arrival=_IN_B )
        row = self._row()
        self.assertEqual( row[ "effective_arm" ], "blind" )
        self.assertEqual( row[ "scheduled_arm" ], "blind" )
        self.assertNotIn( "arm", row )                      # disjoint vocabulary
        self.assertEqual( row[ "length_gate" ], "passed" )
        self.assertEqual( row[ "delivery_outcome" ], "delivered" )
        self.assertEqual( row[ "experiment" ], "two-arm-v1" )
        self.assertFalse( row[ "eligible_for_rejection" ] )
        self.assertFalse( row[ "follows_rejection" ] )
        self.assertEqual( row[ "word_count_version" ], 1 )
        self.assertEqual( row[ "est_tokens" ], len( "short body here." ) // 4 )
        self.assertIsNone( row[ "override_reason" ] )
        self.assertIsNone( row[ "exemption_reason" ] )

    def test_grader_runs_on_the_delivered_path( self ):
        self._set_policy()
        seen = []
        self._run( _make_send_body(), arrival=_IN_B, grader=lambda b: seen.append( b ) )
        self.assertEqual( seen, [ "short body here." ] )    # judge runs in-window


class TestRejectingArm( _ExperimentHarness ):

    def test_under_threshold_passes( self ):
        self._set_policy()
        result = self._run( _make_send_body(), arrival=_IN_A )   # SLOT_A is rejecting
        self.assertEqual( result[ "http_status" ], 201 )
        self.assertEqual( self._row()[ "length_gate" ], "passed" )

    def test_over_threshold_is_refused_413( self ):
        self._set_policy()
        result = self._run( _make_send_body( body=_LONG_BODY ), arrival=_IN_A )
        self.assertEqual( result[ "http_status" ], 413 )

    def test_the_refusal_names_no_number( self ):
        """Undisclosed: the body states the action, never the threshold."""
        self._set_policy()
        detail = self._run( _make_send_body( body=_LONG_BODY ), arrival=_IN_A )[ "detail" ]
        self.assertFalse( any( ch.isdigit() for ch in detail ) )
        self.assertIn( "resend", detail.lower() )

    def test_a_refused_dm_is_never_delivered( self ):
        self._set_policy()
        self._run( _make_send_body( body=_LONG_BODY ), arrival=_IN_A )
        self.spy.assert_not_called()
        self.persist.assert_not_called()
        self.queue.assert_not_called()

    def test_a_refused_dm_still_writes_a_corpus_row( self ):
        """The whole point of moving the row before the gate: rejected DMs get a row."""
        self._set_policy()
        self._run( _make_send_body( body=_LONG_BODY ), arrival=_IN_A )
        row = self._row()
        self.assertEqual( row[ "length_gate" ], "rejected" )
        self.assertEqual( row[ "delivery_outcome" ], "not_attempted" )
        self.assertTrue( row[ "eligible_for_rejection" ] )

    def test_over_threshold_at_exactly_the_limit_passes( self ):
        """Strictly greater-than: 150 words passes, 151 is refused."""
        self._set_policy( reject_threshold=150 )
        exactly_150 = " ".join( [ "w" ] * 150 )
        self.assertEqual( self._run( _make_send_body( body=exactly_150 ), arrival=_IN_A )[ "http_status" ], 201 )


class TestExemption( _ExperimentHarness ):

    def test_arbiter_sender_is_never_gated( self ):
        """The one exemption: the arbiter poker, matched by session id. Over-length,
        rejecting arm, yet delivered — length_gate='exempt'."""
        self._set_policy( exempt_sender_session_ids="arbiter-sess" )
        result = self._run( _make_send_body( sender_session_id="arbiter-sess", body=_LONG_BODY ), arrival=_IN_A )
        self.assertEqual( result[ "http_status" ], 201 )
        row = self._row()
        self.assertEqual( row[ "length_gate" ], "exempt" )
        self.assertEqual( row[ "delivery_outcome" ], "delivered" )
        self.assertFalse( row[ "eligible_for_rejection" ] )
        self.assertIn( "arbiter", row[ "exemption_reason" ] )

    def test_a_non_exempt_sender_with_the_same_body_is_refused( self ):
        """CONTROL — proves the exemption is what let the arbiter through, not the body."""
        self._set_policy( exempt_sender_session_ids="arbiter-sess" )
        result = self._run( _make_send_body( sender_session_id="someone-else", body=_LONG_BODY ), arrival=_IN_A )
        self.assertEqual( result[ "http_status" ], 413 )

    def test_any_id_in_the_comma_list_is_exempt( self ):
        """The arbiter presents under >1 identity — matching ANY listed id exempts it."""
        self._set_policy( exempt_sender_session_ids="arbiter-runner, heartbeat-arbiter, lupin-arbiter-app-8001" )
        result = self._run( _make_send_body( sender_session_id="lupin-arbiter-app-8001", body=_LONG_BODY ), arrival=_IN_A )
        self.assertEqual( result[ "http_status" ], 201 )
        self.assertEqual( self._row()[ "length_gate" ], "exempt" )

    def test_every_exemption_hit_logs_the_matched_id( self ):
        """María's instrument: without the matched-id log, a working exemption and a
        silently-missed one (arbiter's real id is a fourth string) look identical."""
        import io, contextlib
        self._set_policy( exempt_sender_session_ids="arbiter-runner" )
        buf = io.StringIO()
        with contextlib.redirect_stdout( buf ):
            self._run( _make_send_body( sender_session_id="arbiter-runner", body=_LONG_BODY ), arrival=_IN_A )
        out = buf.getvalue()
        self.assertIn( "EXEMPTION HIT", out )
        self.assertIn( "arbiter-runner", out )


class TestOverride( _ExperimentHarness ):

    def test_override_beats_the_scheduled_arm( self ):
        """SLOT_B is blind; override pins rejecting → an over-length DM is refused, and
        the row records both the scheduled (blind) and effective (rejecting) arm."""
        self._set_policy( override_arm="rejecting", override_reason="Thursday demo" )
        result = self._run( _make_send_body( body=_LONG_BODY ), arrival=_IN_B )
        self.assertEqual( result[ "http_status" ], 413 )

    def test_override_reason_is_stamped_on_the_row( self ):
        self._set_policy( override_arm="rejecting", override_reason="Thursday demo" )
        self._run( _make_send_body( body=_LONG_BODY ), arrival=_IN_B )
        row = self._row()
        self.assertEqual( row[ "scheduled_arm" ], "blind" )
        self.assertEqual( row[ "effective_arm" ], "rejecting" )
        self.assertEqual( row[ "override_reason" ], "Thursday demo" )


class TestDeliveryOutcomeAndCrashSafety( _ExperimentHarness ):

    def test_successful_delivery_is_delivered( self ):
        self._set_policy()
        self._run( _make_send_body(), arrival=_IN_B )
        self.assertEqual( self._row()[ "delivery_outcome" ], "delivered" )

    def test_delivered_row_carries_a_delivered_at_stamp( self ):
        """The delivery MOMENT — for the delivery-delay secondary. Unrecoverable after
        Tuesday if not captured now (Cheech, 2026-08-03)."""
        self._set_policy()
        self._run( _make_send_body(), arrival=_IN_B )
        stamp = self._row()[ "delivered_at" ]
        self.assertIsNotNone( stamp )
        datetime.fromisoformat( stamp )                      # parses as ISO 8601

    def test_rejected_row_has_no_delivered_at( self ):
        self._set_policy()
        self._run( _make_send_body( body=_LONG_BODY ), arrival=_IN_A )
        self.assertIsNone( self._row()[ "delivered_at" ] )

    def test_failed_delivery_has_no_delivered_at( self ):
        self._set_policy()
        self.persist.side_effect = RuntimeError( "db down" )
        with self.assertRaises( RuntimeError ):
            self._run( _make_send_body(), arrival=_IN_B )
        self.assertIsNone( self._row()[ "delivered_at" ] )

    def test_crash_before_delivery_persists_not_attempted( self ):
        """Rio's gate: pass the gate, raise BEFORE delivery (sender-id build), and the
        persisted outcome is not_attempted — never null, never absent, never delivered."""
        self._set_policy()
        self.spy.side_effect = RuntimeError( "boom in prep" )
        with self.assertRaises( RuntimeError ):
            self._run( _make_send_body(), arrival=_IN_B )
        row = self._row()
        self.assertEqual( row[ "delivery_outcome" ], "not_attempted" )
        self.persist.assert_not_called()

    def test_crash_during_delivery_persists_failed( self ):
        """A persist/push raise is a delivery ATTEMPT that errored — 'failed', distinct
        from the never-tried not_attempted."""
        self._set_policy()
        self.persist.side_effect = RuntimeError( "db down" )
        with self.assertRaises( RuntimeError ):
            self._run( _make_send_body(), arrival=_IN_B )
        self.assertEqual( self._row()[ "delivery_outcome" ], "failed" )


class TestFollowsRejection( _ExperimentHarness ):

    def test_second_send_from_same_sender_same_slot_follows_a_rejection( self ):
        self._set_policy()
        self._run( _make_send_body( body=_LONG_BODY ), arrival=_IN_A )      # rejected
        self._run( _make_send_body( body="short retry." ), arrival=_IN_A )  # same sender, same slot
        rows = [ json.loads( l ) for l in open( self.corpus_path, encoding="utf-8" ).read().splitlines() ]
        self.assertFalse( rows[ 0 ][ "follows_rejection" ] )               # first attempt
        self.assertTrue( rows[ 1 ][ "follows_rejection" ] )               # after the rejection

    def test_a_different_sender_in_the_same_slot_does_not_follow( self ):
        self._set_policy()
        self._run( _make_send_body( body=_LONG_BODY ), arrival=_IN_A )                       # sender-aaaa rejected
        self._run( _make_send_body( sender_session_id="other", body="hi." ), arrival=_IN_A ) # different sender
        rows = [ json.loads( l ) for l in open( self.corpus_path, encoding="utf-8" ).read().splitlines() ]
        self.assertFalse( rows[ 1 ][ "follows_rejection" ] )

    def test_the_flag_resets_at_the_slot_boundary( self ):
        """THE TRAP: a rejection at the end of one block must NOT leak into the first
        attempt of the next — else treatment crosses the mirror's boundary."""
        self._set_policy()
        self._run( _make_send_body( body=_LONG_BODY ), arrival=_IN_A )      # rejected in SLOT_A
        self._run( _make_send_body( body="new block." ), arrival=_IN_B )    # same sender, SLOT_B
        rows = [ json.loads( l ) for l in open( self.corpus_path, encoding="utf-8" ).read().splitlines() ]
        self.assertFalse( rows[ 1 ][ "follows_rejection" ] )

    def test_reset_state_clears_the_memory( self ):
        self._set_policy()
        self._run( _make_send_body( body=_LONG_BODY ), arrival=_IN_A )      # rejected → memory holds it
        self.dm.reset_dm_experiment_state()
        self._run( _make_send_body( body="after reset." ), arrival=_IN_A )
        rows = [ json.loads( l ) for l in open( self.corpus_path, encoding="utf-8" ).read().splitlines() ]
        self.assertFalse( rows[ 1 ][ "follows_rejection" ] )


class TestOutsideWindowUnchanged( _ExperimentHarness ):
    """A send whose arrival is outside every slot takes the baseline path: legacy `arm`
    present, no experiment fields, quality appended when the grader returns one."""

    def test_outside_window_writes_the_legacy_row_shape( self ):
        self._set_policy()
        out = datetime( 2026, 8, 4, 2, 0, tzinfo=timezone.utc )   # before 09:00 ET
        grade = { "length": { "weight": 2 }, "directness": { "weight": 1 },
                  "tone": { "weight": 1 }, "overall": { "weight": 1 } }
        result = self._run( _make_send_body(), arrival=out, grader=lambda b: grade )
        self.assertEqual( result[ "http_status" ], 201 )
        # Row ec5cf83a FLIPPED THIS ASSERTION, deliberately. It read
        # `assertIn( "quality", result )` — the baseline path used to append the grade
        # to the 201. It cannot any more: the grade is computed after the send returns,
        # so the only honest response is one with no grade in it. The grade's
        # destination is the corpus row, asserted below.
        self.assertNotIn( "quality", result )
        row = self._row()
        self.assertIn( "arm", row )                              # legacy stamp present
        self.assertNotIn( "effective_arm", row )                 # no experiment fields


class TestSuspension( unittest.TestCase ):
    """
    The pilot is SUSPENDED (Rick, 2026-08-13) — the switch, not the schedule.

    Separate from TestLoadSchedule above, which patches suspension OFF to keep
    asserting that the committed schedule file is armed. The two together say the
    whole truth: the schedule remains valid AND it is deliberately not running.
    """

    def tearDown( self ):
        dm_experiment.reset_policy()

    def test_suspended_yields_an_inactive_policy_for_every_instant( self ):
        """
        The load-side behaviour that makes suspension real. A slot that WOULD resolve
        (proven live by TestLoadSchedule, same instant) must resolve to None while
        suspended — else the tutor and a rejecting hour could both be in force and no
        corpus row could say which one produced the saving.
        """
        live_instant = datetime( 2026, 8, 7, 16, 30, tzinfo=timezone.utc )   # Fri 12:00 EDT
        with patch.object( dm_experiment, "is_suspended", lambda: True ):
            policy = dm_experiment.load_default_policy()
        self.assertIsNone( policy.assignment_at( live_instant ) )
        self.assertEqual( policy._slots, [] )
        self.assertIsNone( policy.schedule_id )

    def test_not_suspended_still_resolves_that_same_instant( self ):
        """
        The CONTROL for the test above. Without it, an inactive policy caused by a
        broken schedule read would look exactly like a working suspension — the
        assertion would pass for the wrong reason and keep passing forever.
        """
        live_instant = datetime( 2026, 8, 7, 16, 30, tzinfo=timezone.utc )
        with patch.object( dm_experiment, "is_suspended", lambda: False ):
            policy = dm_experiment.load_default_policy()
        self.assertIsNotNone( policy.assignment_at( live_instant ) )

    def test_config_read_failure_suspends_rather_than_resumes( self ):
        """
        FAIL-SAFE DIRECTION. A config that cannot be read must leave the pilot OFF: a
        silent resume would gate live fleet traffic on an arm nobody chose, while a
        silent suspend costs only that the pilot stays stopped — which is the ruled
        state anyway.
        """
        with patch( "cosa.config.configuration_manager.ConfigurationManager",
                    side_effect=RuntimeError( "config unreadable" ) ):
            self.assertTrue( dm_experiment.is_suspended() )

    def test_the_shipped_config_actually_has_the_pilot_suspended( self ):
        """
        Asserts the SHIPPED value, not the mechanism. Every test above patches the
        switch, so all of them would still pass if lupin-app.ini said False and the
        pilot were quietly running in production.
        """
        self.assertTrue( dm_experiment.is_suspended() )


if __name__ == "__main__":
    unittest.main()
