"""
Step 2 of row 12b5a766 — an ABSENT `sender_project` on the DM write path is a
REJECT, not a fallback.

WHY THIS FILE LIVES IN `src/tests/unit/` AND NOT NEXT TO ITS SIBLING
--------------------------------------------------------------------
The step-1 suite is `src/cosa/tests/unit/rest/test_dm_sender_project.py`. That
whole tree is INVISIBLE to every gate (row 5bf28e07 — ~410 files, unresolved:
Rick's standing ruling is to first research whether the CoSA tree was superseded
by / migrated into this harness, rather than wire a possible second copy). A
regression guard on the fleet DM write path must not land somewhere no gate
runs, so the step-2 tests go in the gated tree even though it splits the row's
coverage across two files. The split is deliberate and is named here so the next
reader does not "tidy" it back.

WHAT STEP 2 CHANGES
-------------------
Step 1 (831e18dc) made `sender_project` optional-by-transition: supplied → stamp
from it; absent → stamp as before AND count the omission. The absence was
accepted because editing the MCP client does not reach an ALREADY-RUNNING one
(`PROJECT`/`CANONICAL_PROJECT` resolve at import), so a 422 then would have muted
every live seat until respawn — the correct fix, muting the fleet.

The flip is now a MEASUREMENT rather than a judgement:
    negative arm  zero live cosa_voice_mcp.py clients predate 831e18dc
    positive arm  362 [dm-project-audit] observations over 12h, un_projected=0
                  on every line, with a synthetic un_projected=7 proven to
                  survive the same filter (so the filter discriminates)

⚠️ THE AUDIT COUNTS AT THE ENDPOINT, which is what retires the standing caveat
that "a grep cannot see a caller on another machine": the grep is bounded to this
filesystem, the audit is not. Any off-box caller omitting the field would land in
`un_projected` regardless of origin.

WHAT THIS SUITE DOES NOT COVER
------------------------------
It does not prove any LIVE caller's stamp is correct end-to-end — the injected
`build_sender_id` seam is a test double. It pins the CORE's reject contract and
that the audit still observes a rejected DM. The 12 other server-side
`build_sender_id_for_cc` call sites are row 4df4215c and are UNMEASURED here.

Row: 12b5a766
"""

import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import cosa.utils.util as cu


class _SenderIdSpy:
    """
    Recording stand-in for the injected `build_sender_id` seam.

    Sensitive ON THE PROJECT AXIS by construction — the project is interpolated
    into the returned value, so two projects cannot produce one stamp. Asserted
    by an explicit control below rather than assumed.
    """

    def __init__( self ):
        self.calls = []

    def __call__( self, session_id, project=None ):
        self.calls.append( { "session_id": session_id, "project": project } )
        return f"claude.code@{project or 'lupin'}.deepily.ai#{session_id}"


def _make_send_body( **overrides ):
    from cosa.rest.routers.dm import DmSendRequest
    fields = dict(
        sender_session_id = "asker-session-aaaa",
        body              = "does this still get through?",
        recipient_persona = "mr radio",
        sender_persona    = "María",
        sender_icon       = "🌸",
    )
    fields.update( overrides )
    return DmSendRequest( **fields )


class TestSpyControl( unittest.TestCase ):
    """
    CONTROL — the instrument must be able to fail on the axis this suite claims.
    A spy that ignored `project` would make every assertion below green against
    unfixed code.
    """

    def test_spy_discriminates_on_the_project_axis( self ):
        spy = _SenderIdSpy()
        self.assertNotEqual( spy( "sid", project="plan" ), spy( "sid", project="lupin" ) )


class _CoreHarness( unittest.TestCase ):

    def setUp( self ):
        import cosa.rest.routers.dm as dm
        from cosa.rest.routers.dm import execute_dm_send, reset_dm_project_audit
        self.execute_dm_send = execute_dm_send
        self.reset_audit     = reset_dm_project_audit
        self.queue           = MagicMock()
        self.persist         = MagicMock( return_value="db-123" )
        self.spy             = _SenderIdSpy()
        self.resolve         = MagicMock( return_value={
            "http_status"  : 200,
            "session_id"   : "abcdef1234567890",
            "persona_name" : "mr radio",
        } )
        self.reset_audit()
        # Row 334569d6: execute_dm_send now appends a JSONL row to _DM_TRAFFIC_JSONL on
        # every ACCEPTED (201) send. Under test that path resolves via
        # cu.get_project_root() to the REAL host corpus — so a send-path test would
        # silently write fixture rows ("does this still get through?" etc.) into Rick's
        # four-day dataset. Redirect the sink to a throwaway file for EVERY test built on
        # this harness; a guard below proves the real corpus is never touched.
        self.corpus_path = os.path.join( tempfile.mkdtemp(), "dm_traffic.jsonl" )
        _corpus_patch = patch.object( dm, "_DM_TRAFFIC_JSONL", self.corpus_path )
        _corpus_patch.start()
        self.addCleanup( _corpus_patch.stop )

    def _run( self, body ):
        return self.execute_dm_send(
            authenticated_user_id = "user-uuid-1",
            body                  = body,
            notification_queue    = self.queue,
            resolve_recipient_fn  = self.resolve,
            build_sender_id       = self.spy,
            persist_fn            = self.persist,
            new_id_fn             = lambda: "fixed-msg-id",
        )


class TestAbsentProjectIsRejected( _CoreHarness ):

    def test_absent_project_returns_422( self ):
        """The flip: what step 1 accepted-and-warned, step 2 refuses."""
        result = self._run( _make_send_body() )
        self.assertEqual( result[ "http_status" ], 422 )

    def test_the_rejection_names_the_session_and_the_remedy( self ):
        """
        An operator reading this must learn WHICH seat is at fault and WHAT to do.
        A 422 saying only "sender_project is required" would make the reader go
        find the row to discover a respawn is the fix.
        """
        detail = self._run( _make_send_body() )[ "detail" ]
        self.assertIn( "asker-session-aaaa", detail )
        self.assertIn( "12b5a766", detail )
        self.assertIn( "respawn", detail.lower() )

    def test_a_rejected_dm_is_never_stamped_or_persisted( self ):
        """
        The reject must happen BEFORE the stamp and the write. A 422 that still
        persisted the DM under a wrong sender_id would be worse than the defect
        it replaces — a wrong stamp AND a lost message.
        """
        self._run( _make_send_body() )
        self.assertEqual( self.spy.calls, [] )
        self.persist.assert_not_called()
        self.queue.assert_not_called()


class TestRejectionIsStillObserved( _CoreHarness ):
    """
    ⚠️ THE FAILURE THIS PREVENTS. If the reject returned before `_record_dm_project`,
    a fleet that started omitting the field would go SILENT in the audit at exactly
    the moment the audit mattered — `un_projected` would stay 0 while every DM was
    being refused, and the counter that exists to detect the problem would report
    health. The order (count, THEN reject) is load-bearing.
    """

    def test_a_rejected_dm_increments_un_projected( self ):
        from cosa.rest.routers.dm import get_dm_project_audit
        self._run( _make_send_body() )
        self.assertEqual( get_dm_project_audit()[ "un_projected" ], 1 )

    def test_a_rejected_dm_names_its_offending_session( self ):
        from cosa.rest.routers.dm import get_dm_project_audit
        self._run( _make_send_body() )
        self.assertIn( "asker-session-aaaa", get_dm_project_audit()[ "un_projected_senders" ] )


class TestSuppliedProjectStillWorks( _CoreHarness ):
    """
    The other arm. A suite that only proved the reject would pass against a core
    that rejected EVERYTHING — the fleet-mute outcome, green.
    """

    def test_supplied_project_is_accepted( self ):
        result = self._run( _make_send_body( sender_project="plan" ) )
        self.assertNotEqual( result[ "http_status" ], 422 )

    def test_supplied_project_reaches_the_builder_and_the_persist( self ):
        self._run( _make_send_body( sender_project="plan" ) )
        self.assertEqual( self.spy.calls[ -1 ][ "project" ], "plan" )
        self.assertEqual(
            self.persist.call_args.kwargs[ "sender_id" ],
            "claude.code@plan.deepily.ai#asker-session-aaaa"
        )

    def test_supplied_project_counts_as_projected_not_un_projected( self ):
        from cosa.rest.routers.dm import get_dm_project_audit
        self._run( _make_send_body( sender_project="plan" ) )
        audit = get_dm_project_audit()
        self.assertEqual( audit[ "projected" ], 1 )
        self.assertEqual( audit[ "un_projected" ], 0 )


class TestAuditEndpointIsWired( unittest.TestCase ):
    """
    Row 67fe3be1, fifth instance — the audit was generated correctly from
    2026-07-21 and readable ONLY by grepping `docker logs`, so the gate it
    existed to inform sat four days unread. A disclosure nobody can consume is
    not a disclosure. This pins that a route now exposes it.
    """

    def test_a_route_exists_on_the_dm_router_for_the_audit( self ):
        from cosa.rest.routers.dm import router
        paths = { getattr( r, "path", None ) for r in router.routes }
        self.assertIn( "/api/dm/project-audit", paths )

    def test_the_endpoint_returns_the_live_counters( self ):
        from cosa.rest.routers.dm import get_dm_project_audit, reset_dm_project_audit
        reset_dm_project_audit()
        snapshot = get_dm_project_audit()
        for key in ( "projected", "un_projected", "un_projected_senders", "since" ):
            self.assertIn( key, snapshot )

    def test_the_snapshot_is_a_copy_a_reader_cannot_mutate_the_counters( self ):
        """Handing out the live dict would let any reader corrupt the gate's own evidence."""
        from cosa.rest.routers.dm import get_dm_project_audit, reset_dm_project_audit
        reset_dm_project_audit()
        got = get_dm_project_audit()
        got[ "projected" ] = 999
        got[ "un_projected_senders" ].append( "not-a-real-session" )
        fresh = get_dm_project_audit()
        self.assertEqual( fresh[ "projected" ], 0 )
        self.assertEqual( fresh[ "un_projected_senders" ], [] )


class TestCountSentences( unittest.TestCase ):
    """
    _count_sentences() — deliberately a simple .!? splitter, not an NLP-grade
    sentence boundary detector. It exists to give the length audit a verbosity
    SIGNAL (multi-topic DMs tend to run more sentences), not to be linguistically
    exact.
    """

    def test_single_sentence_with_period( self ):
        from cosa.rest.routers.dm import _count_sentences
        self.assertEqual( _count_sentences( "Commit landed." ), 1 )

    def test_two_sentences( self ):
        from cosa.rest.routers.dm import _count_sentences
        self.assertEqual( _count_sentences( "Does this still get through? Yes it does." ), 2 )

    def test_fragment_with_no_terminal_punctuation_counts_as_one( self ):
        """A bare fragment ("status?") is still 1 sentence, never 0."""
        from cosa.rest.routers.dm import _count_sentences
        self.assertEqual( _count_sentences( "no terminal punctuation here" ), 1 )

    def test_blank_string_counts_as_zero( self ):
        from cosa.rest.routers.dm import _count_sentences
        self.assertEqual( _count_sentences( "   " ), 0 )

    def test_exclamation_and_question_marks_both_count( self ):
        from cosa.rest.routers.dm import _count_sentences
        self.assertEqual( _count_sentences( "Stop! Why? Because." ), 3 )


class TestDmLengthAuditIsWired( unittest.TestCase ):
    """
    Phase 1 of the DM Verbosity Reduction plan (Rick, 2026-07-31 —
    src/rnd/v0.1.9/2026.07.31-dm-verbosity-reduction/). Mirrors
    TestAuditEndpointIsWired's three assertions for the sibling length-audit
    counter: a route exists, the endpoint returns live counters, and the
    snapshot is a defensive copy.
    """

    def test_a_route_exists_on_the_dm_router_for_the_length_audit( self ):
        from cosa.rest.routers.dm import router
        paths = { getattr( r, "path", None ) for r in router.routes }
        self.assertIn( "/api/dm/length-audit", paths )

    def test_the_endpoint_returns_the_live_counters( self ):
        from cosa.rest.routers.dm import get_dm_length_audit, reset_dm_length_audit
        reset_dm_length_audit()
        snapshot = get_dm_length_audit()
        for key in ( "count", "total_chars", "total_words", "total_sentences", "since", "avg_chars", "avg_words", "avg_sentences" ):
            self.assertIn( key, snapshot )

    def test_the_snapshot_is_a_copy_a_reader_cannot_mutate_the_counters( self ):
        """Same defensive-copy contract as the project-audit's equivalent test."""
        from cosa.rest.routers.dm import get_dm_length_audit, reset_dm_length_audit
        reset_dm_length_audit()
        got = get_dm_length_audit()
        got[ "count" ] = 999
        fresh = get_dm_length_audit()
        self.assertEqual( fresh[ "count" ], 0 )


class TestDmLengthAuditIsRecordedOnSend( _CoreHarness ):
    """
    A rejected (un-projected) DM still gets its length counted — same
    count-then-reject ordering discipline as TestRejectionIsStillObserved,
    so a fleet that starts offending on the project axis doesn't ALSO go
    invisible on the length axis.
    """

    def setUp( self ):
        super().setUp()
        from cosa.rest.routers.dm import reset_dm_length_audit
        reset_dm_length_audit()

    def test_an_accepted_dm_is_counted_in_the_length_audit( self ):
        from cosa.rest.routers.dm import get_dm_length_audit
        self._run( _make_send_body( sender_project="plan" ) )
        audit = get_dm_length_audit()
        self.assertEqual( audit[ "count" ], 1 )
        self.assertEqual( audit[ "total_words" ], 5 )   # "does this still get through?"
        self.assertEqual( audit[ "total_chars" ], 28 )
        self.assertEqual( audit[ "total_sentences" ], 1 )   # one question, no other terminal punctuation

    def test_a_rejected_dm_is_still_counted_in_the_length_audit( self ):
        from cosa.rest.routers.dm import get_dm_length_audit
        self._run( _make_send_body() )   # no sender_project → 422, per TestAbsentProjectIsRejected
        self.assertEqual( get_dm_length_audit()[ "count" ], 1 )


class TestDmQualityAuditIsWired( unittest.TestCase ):
    """
    Phase 2 of the DM Verbosity Reduction plan (Rick, 2026-07-31). Mirrors the
    length-audit's three wiring assertions for the sibling quality-audit counter:
    a route exists, the endpoint returns live counters (count + all four running
    weight totals + their derived averages), and the snapshot is a defensive copy.
    """

    def test_a_route_exists_on_the_dm_router_for_the_quality_audit( self ):
        from cosa.rest.routers.dm import router
        paths = { getattr( r, "path", None ) for r in router.routes }
        self.assertIn( "/api/dm/quality-audit", paths )

    def test_the_endpoint_returns_the_live_counters( self ):
        from cosa.rest.routers.dm import get_dm_quality_audit, reset_dm_quality_audit
        reset_dm_quality_audit()
        snapshot = get_dm_quality_audit()
        for key in (
            "count", "since",
            "total_length_weight", "total_directness_weight",
            "total_tone_weight", "total_overall_weight",
            "avg_length", "avg_directness", "avg_tone", "avg_overall",
        ):
            self.assertIn( key, snapshot )

    def test_zero_count_averages_are_guarded_against_divide_by_zero( self ):
        """The same `if count else 0.0` guard as the length-audit — a fresh window
        reports 0.0 averages, never raises ZeroDivisionError."""
        from cosa.rest.routers.dm import get_dm_quality_audit, reset_dm_quality_audit
        reset_dm_quality_audit()
        snapshot = get_dm_quality_audit()
        self.assertEqual( snapshot[ "count" ], 0 )
        for avg in ( "avg_length", "avg_directness", "avg_tone", "avg_overall" ):
            self.assertEqual( snapshot[ avg ], 0.0 )

    def test_the_snapshot_is_a_copy_a_reader_cannot_mutate_the_counters( self ):
        """Same defensive-copy contract as the other two audits."""
        from cosa.rest.routers.dm import get_dm_quality_audit, reset_dm_quality_audit
        reset_dm_quality_audit()
        got = get_dm_quality_audit()
        got[ "count" ] = 999
        fresh = get_dm_quality_audit()
        self.assertEqual( fresh[ "count" ], 0 )

    def test_record_tallies_all_four_weights( self ):
        from cosa.rest.routers.dm import get_dm_quality_audit, reset_dm_quality_audit, _record_dm_quality
        reset_dm_quality_audit()
        _record_dm_quality( {
            "length"     : { "weight":  2 },
            "directness" : { "weight":  1 },
            "tone"       : { "weight": -1 },
            "overall"    : { "weight":  1 },
        } )
        audit = get_dm_quality_audit()
        self.assertEqual( audit[ "count" ], 1 )
        self.assertEqual( audit[ "total_length_weight" ], 2 )
        self.assertEqual( audit[ "total_directness_weight" ], 1 )
        self.assertEqual( audit[ "total_tone_weight" ], -1 )
        self.assertEqual( audit[ "total_overall_weight" ], 1 )
        self.assertEqual( audit[ "avg_tone" ], -1.0 )

    def test_length_only_mode_does_not_crash_the_audit_on_a_none_weight( self ):
        """REGRESSION. LENGTH-ONLY mode (Rick, 2026-08-01, row ca7a2cbf) returns
        weight None for Directness/Tone. The tally did `int += None` and threw
        TypeError, which surfaced as a 500 on EVERY DM send the moment the ruling
        reached a running server. A None must be skipped, never summed."""
        from cosa.rest.routers.dm import get_dm_quality_audit, reset_dm_quality_audit, _record_dm_quality
        reset_dm_quality_audit()
        _record_dm_quality( {
            "length"     : { "weight":  2 },
            "directness" : { "weight": None },
            "tone"       : { "weight": None },
            "overall"    : { "weight":  2 },
        } )
        audit = get_dm_quality_audit()
        self.assertEqual( audit[ "count" ], 1 )
        self.assertEqual( audit[ "total_length_weight" ], 2 )
        self.assertEqual( audit[ "total_overall_weight" ], 2 )

    def test_a_withheld_grade_does_not_count_toward_the_qualitative_average( self ):
        """A withheld dimension is NOT a zero. Averaging it as one would drag
        avg_directness toward 0 and publish that as a considered score — the exact
        non-answer-in-the-answer's-value-space defect row ca7a2cbf is about, moved
        into the audit counter. qualitative_count is what keeps them separable."""
        from cosa.rest.routers.dm import get_dm_quality_audit, reset_dm_quality_audit, _record_dm_quality
        reset_dm_quality_audit()
        _record_dm_quality( {                                    # withheld — must not dilute
            "length": { "weight": 0 }, "directness": { "weight": None },
            "tone"  : { "weight": None }, "overall": { "weight": 0 },
        } )
        _record_dm_quality( {                                    # a real grade
            "length": { "weight": 0 }, "directness": { "weight": 2 },
            "tone"  : { "weight": 2 }, "overall": { "weight": 1 },
        } )
        audit = get_dm_quality_audit()
        self.assertEqual( audit[ "count" ], 2 )
        self.assertEqual( audit[ "qualitative_count" ], 1 )
        # 2/1, NOT 2/2 — the withheld row is absent from the denominator
        self.assertEqual( audit[ "avg_directness" ], 2.0 )
        self.assertEqual( audit[ "avg_tone" ], 2.0 )

    def test_qualitative_count_is_zero_in_pure_length_only_mode( self ):
        """The tell a reader needs: avg_directness == 0.0 with qualitative_count == 0
        means NOTHING was graded, which is a different fact from an average of zero."""
        from cosa.rest.routers.dm import get_dm_quality_audit, reset_dm_quality_audit, _record_dm_quality
        reset_dm_quality_audit()
        for _ in range( 3 ):
            _record_dm_quality( {
                "length": { "weight": 1 }, "directness": { "weight": None },
                "tone"  : { "weight": None }, "overall": { "weight": 1 },
            } )
        audit = get_dm_quality_audit()
        self.assertEqual( audit[ "count" ], 3 )
        self.assertEqual( audit[ "qualitative_count" ], 0 )
        self.assertEqual( audit[ "avg_directness" ], 0.0 )
        self.assertEqual( audit[ "avg_tone" ], 0.0 )
        self.assertEqual( audit[ "avg_length" ], 1.0 )

    def test_reset_clears_the_qualitative_counter_too( self ):
        """A counter that survives a reset silently poisons the next window."""
        from cosa.rest.routers.dm import get_dm_quality_audit, reset_dm_quality_audit, _record_dm_quality
        reset_dm_quality_audit()
        _record_dm_quality( {
            "length": { "weight": 1 }, "directness": { "weight": 1 },
            "tone"  : { "weight": 1 }, "overall": { "weight": 1 },
        } )
        self.assertEqual( get_dm_quality_audit()[ "qualitative_count" ], 1 )
        reset_dm_quality_audit()
        self.assertEqual( get_dm_quality_audit()[ "qualitative_count" ], 0 )


class TestDmQualityJudgeMergedIntoSend( _CoreHarness ):
    """
    Phase 2: the injected grade_quality_fn seam decides whether execute_dm_send's
    201 result carries a `quality` field. Control (grader returns None) → no field,
    the Phase 1 baseline shape. Treatment (grader returns a grade) → the grade is
    appended verbatim. The grader is only reached on the ACCEPTED (201) path.
    """

    def _run_with_grader( self, body, grader ):
        return self.execute_dm_send(
            authenticated_user_id = "user-uuid-1",
            body                  = body,
            notification_queue    = self.queue,
            resolve_recipient_fn  = self.resolve,
            build_sender_id       = self.spy,
            persist_fn            = self.persist,
            new_id_fn             = lambda: "fixed-msg-id",
            grade_quality_fn      = grader,
        )

    def test_control_grader_none_appends_no_quality_field( self ):
        result = self._run_with_grader( _make_send_body( sender_project="plan" ), lambda body: None )
        self.assertEqual( result[ "http_status" ], 201 )
        self.assertNotIn( "quality", result )

    def test_treatment_grade_is_appended_verbatim( self ):
        grade = {
            "length"     : { "emoji": "⭐", "weight":  2, "detail": "12 words, target ~60" },
            "directness" : { "emoji": "👍", "weight":  1, "detail": "leads with the result" },
            "tone"       : { "emoji": "⭐", "weight":  2, "detail": "plain colleague voice" },
            "overall"    : { "emoji": "⭐", "weight":  2, "note": "Tight and direct." },
        }
        result = self._run_with_grader( _make_send_body( sender_project="plan" ), lambda body: grade )
        self.assertEqual( result[ "http_status" ], 201 )
        self.assertEqual( result[ "quality" ], grade )

    def test_grader_receives_the_raw_body_not_the_stamped_one( self ):
        seen = {}
        def grader( body_text ):
            seen[ "body" ] = body_text
            return None
        self._run_with_grader( _make_send_body( sender_project="plan", body="crisp verdict here." ), grader )
        self.assertEqual( seen[ "body" ], "crisp verdict here." )   # no EDT "[...]" prefix

    def test_a_rejected_dm_never_reaches_the_grader( self ):
        """The grader runs only on the 201 path — a 422 (no sender_project) must not
        pay for a judge call."""
        calls = []
        self._run_with_grader( _make_send_body(), lambda body: calls.append( body ) )
        self.assertEqual( calls, [] )


class TestDmTrafficJsonlCorpus( _CoreHarness ):
    """
    Row 334569d6 — the per-DM JSONL corpus that stops discarding rows the running
    counter can only sum. The write lands at execute_dm_send's tail (after the DM is
    persisted + pushed) so a corpus failure cannot cost a message; grades ride along
    from the same 726 call. These tests point the module's sink path at a temp file.
    """

    def _run_with_grader( self, body, grader ):
        return self.execute_dm_send(
            authenticated_user_id = "user-uuid-1",
            body                  = body,
            notification_queue    = self.queue,
            resolve_recipient_fn  = self.resolve,
            build_sender_id       = self.spy,
            persist_fn            = self.persist,
            new_id_fn             = lambda: "fixed-msg-id",
            grade_quality_fn      = grader,
        )

    _GRADE = {
        "length"     : { "emoji": "⭐", "weight":  2, "detail": "3 words, target ~60" },
        "directness" : { "emoji": "👍", "weight":  1, "detail": "leads with the result" },
        "tone"       : { "emoji": "😞", "weight": -2, "detail": "curt" },
        "overall"    : { "emoji": "👍", "weight":  1, "note": "ok" },
    }

    def test_accepted_dm_appends_one_row_with_fields_and_grades( self ):
        self._run_with_grader(
            _make_send_body( sender_project="plan", body="crisp verdict here." ),
            lambda b: self._GRADE,
        )
        lines = open( self.corpus_path, encoding="utf-8" ).read().splitlines()
        self.assertEqual( len( lines ), 1 )
        row = json.loads( lines[ 0 ] )
        self.assertEqual( row[ "from" ],         "María" )
        self.assertEqual( row[ "from_project" ], "plan" )
        self.assertEqual( row[ "to" ],           "mr radio" )
        self.assertEqual( row[ "words" ],        3 )
        self.assertEqual( row[ "sentences" ],    1 )
        self.assertEqual( row[ "body" ],         "crisp verdict here." )
        # written from within pytest → stamped as a test row (row f5d6dc5e)
        self.assertEqual( row[ "origin" ],       "test" )
        # experiment arm stamped from config; the test ini has `dm reject on overage`
        # False → arm A (row f4bb1cdb)
        self.assertEqual( row[ "arm" ],          "signal_only" )
        # grades ride along as integer weights
        self.assertEqual( row[ "len_grade" ],  2 )
        self.assertEqual( row[ "directness" ], 1 )
        self.assertEqual( row[ "tone" ],       -2 )
        self.assertEqual( row[ "overall" ],    1 )

    def test_control_grader_none_still_writes_row_with_null_grades( self ):
        """Judge OFF → quality is None → the row is STILL written (measurements +
        body), with grade fields null. A corpus that logged nothing when the judge
        is off would collect nothing in the control arm."""
        self._run_with_grader( _make_send_body( sender_project="plan", body="short one." ), lambda b: None )
        row = json.loads( open( self.corpus_path, encoding="utf-8" ).read().splitlines()[ 0 ] )
        self.assertEqual( row[ "words" ], 2 )
        self.assertIsNone( row[ "len_grade" ] )
        self.assertIsNone( row[ "directness" ] )
        self.assertIsNone( row[ "tone" ] )
        self.assertIsNone( row[ "overall" ] )

    def test_a_rejected_dm_writes_no_corpus_row( self ):
        """A 422 (no sender_project) returns before the tail write, so the corpus is
        the SENT-traffic population — a rejected DM never sent and must not appear."""
        result = self._run_with_grader( _make_send_body(), lambda b: None )   # no project → 422
        self.assertEqual( result[ "http_status" ], 422 )
        self.assertFalse( os.path.exists( self.corpus_path ) )

    def test_write_failure_is_fail_soft_and_the_dm_still_sends( self ):
        """GATE (c) — FORCE the except arm. The sink path points into a directory that
        does not exist, so the append raises FileNotFoundError inside the writer. The
        DM must still return 201 dispatched=True, and no file may appear (proving the
        write genuinely threw and was swallowed, not silently succeeded)."""
        import cosa.rest.routers.dm as dm
        missing = os.path.join( tempfile.mkdtemp(), "no_such_dir", "dm.jsonl" )
        with patch.object( dm, "_DM_TRAFFIC_JSONL", missing ):
            result = self._run_with_grader( _make_send_body( sender_project="plan" ), lambda b: self._GRADE )
        self.assertEqual( result[ "http_status" ], 201 )
        self.assertTrue( result[ "dispatched" ] )
        self.assertFalse( os.path.exists( missing ) )

    def test_a_send_path_test_never_writes_the_real_production_corpus( self ):
        """GUARD (row 334569d6 CHANGES-REQUESTED). The harness MUST redirect the sink
        away from the real host corpus, else every send-path test silently pollutes
        Rick's four-day dataset. Proves (1) the active sink is not the production path
        and (2) a real send under test leaves the production file byte-for-byte
        untouched."""
        import cosa.rest.routers.dm as dm
        real = cu.get_project_root() + "/src/tmp/dm_traffic.jsonl"
        self.assertNotEqual( dm._DM_TRAFFIC_JSONL, real )
        before = os.path.getsize( real ) if os.path.exists( real ) else None
        self._run_with_grader( _make_send_body( sender_project="plan" ), lambda b: self._GRADE )
        after = os.path.getsize( real ) if os.path.exists( real ) else None
        self.assertEqual( before, after )

    def test_writer_refuses_the_production_corpus_from_a_pytest_process( self ):
        """GATE (a), row f5d6dc5e — the case the conftest fixture does NOT cover. Point
        the sink back at the LITERAL production constant (simulating the fixture not in
        play, e.g. a send-path test written outside its reach) and call the writer
        directly under pytest. The self-guard must refuse: the production corpus stays
        byte-for-byte unchanged.

        Compares against dm._DM_TRAFFIC_PRODUCTION_PATH — the immutable constant the
        fixture never patches — NOT the patched _DM_TRAFFIC_JSONL read back, which would
        be a control comparing a value to itself."""
        import cosa.rest.routers.dm as dm
        prod = dm._DM_TRAFFIC_PRODUCTION_PATH
        before = open( prod, "rb" ).read() if os.path.exists( prod ) else None
        # Override the conftest redirect: aim the live sink at the real production path.
        with patch.object( dm, "_DM_TRAFFIC_JSONL", prod ):
            dm._persist_dm_row(
                body_text="a test that slipped the fixture would land HERE",
                from_persona="Fixture-Escapee", from_session="sess-x", from_project="lupin",
                to_persona="victim", to_session="sess-y", quality=None,
            )
        after = open( prod, "rb" ).read() if os.path.exists( prod ) else None
        self.assertEqual( before, after, "self-guard failed: a pytest write reached the real corpus" )

    def test_row_is_stamped_origin_test_when_written_under_pytest( self ):
        """The audit stamp (row f5d6dc5e): a row written from within pytest carries
        origin='test', so a reader filters contaminants on the field instead of
        inferring them from a timezone."""
        self._run_with_grader( _make_send_body( sender_project="plan", body="short one." ), lambda b: None )
        row = json.loads( open( self.corpus_path, encoding="utf-8" ).read().splitlines()[ 0 ] )
        self.assertEqual( row[ "origin" ], "test" )


def _fake_cm( values ):
    """A ConfigurationManager stand-in whose .get returns the stored value, or the
    passed default when the key is ABSENT — mirroring the real manager's missing-key
    behaviour, which is the case row f4bb1cdb turns on."""
    class _CM:
        def __init__( self, **kwargs ):   # constructed as ConfigurationManager(env_var_name=...)
            pass
        def get( self, key, default=None, return_type=None ):
            return values.get( key, default )
    return _CM


def _fake_cm_that_cannot_construct():
    class _CM:
        def __init__( self, **kwargs ):
            raise RuntimeError( "config unavailable" )
    return _CM


class TestDmFeedbackArm( unittest.TestCase ):
    """Row f4bb1cdb — get_dm_feedback_arm() derives the experiment arm from the
    `dm reject on overage` config key. False/absent → "signal_only" (arm A), True →
    "reject_on_overage" (arm B). A MISSING key or a read error is arm A, NEVER an error
    (no fail-closed): the corpus must name its arm before arm B is built."""

    def _arm_under( self, cm_class ):
        import cosa.rest.routers.dm as dm
        with patch( "cosa.config.configuration_manager.ConfigurationManager", cm_class ):
            return dm.get_dm_feedback_arm()

    def test_false_key_is_signal_only( self ):
        self.assertEqual( self._arm_under( _fake_cm( { "dm reject on overage": False } ) ), "signal_only" )

    def test_true_key_is_reject_on_overage( self ):
        self.assertEqual( self._arm_under( _fake_cm( { "dm reject on overage": True } ) ), "reject_on_overage" )

    def test_absent_key_is_signal_only_not_an_error( self ):
        """María's required case: a default nobody has run with the key DELETED is a
        default nobody has tested. Missing key → arm A, no exception."""
        self.assertEqual( self._arm_under( _fake_cm( {} ) ), "signal_only" )

    def test_config_read_failure_falls_back_to_signal_only( self ):
        """A broken config read is arm A, not fail-closed — same posture as the missing
        key. Stamping nothing, or raising into the send path, would both be worse."""
        self.assertEqual( self._arm_under( _fake_cm_that_cannot_construct() ), "signal_only" )


if __name__ == "__main__":
    unittest.main()
