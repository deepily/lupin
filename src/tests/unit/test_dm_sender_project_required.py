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

import unittest
from unittest.mock import MagicMock


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


if __name__ == "__main__":
    unittest.main()
