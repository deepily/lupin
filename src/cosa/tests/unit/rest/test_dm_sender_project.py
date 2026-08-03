"""
Unit tests for CALLER-SUPPLIED project on the DM write path (row 12b5a766).

THE DEFECT UNDER TEST
---------------------
`/api/dm/send` stamps `sender_id` server-side via `build_sender_id_for_cc()`, a
HOST-shaped helper whose primary branch reads host artifacts the server
container cannot see. Server-side it degrades to `detect_project()`, which walks
up from the SERVER PROCESS's cwd and answers "lupin" — CORRECTLY, for the
question "what project am I?". The question that matters is "what project is the
CALLER?", and nobody asks it. A resolver returning a correct value for a question
nobody asked reads as healthy forever.

The caller already knows: the MCP server resolves PROJECT / CANONICAL_PROJECT at
module load, HOST-side, where the bridge and cwd are real — and then does not put
it on the wire. This suite pins the fix: when the caller SENDS its project, the
stamp uses it; when it does not, the stamp is unchanged from today AND the
absence is COUNTED so "nobody sends un-projected DMs" and "the audit is not
wired" cannot look the same.

WHAT THIS SUITE DOES NOT COVER
------------------------------
It does NOT prove any live caller's stamp is correct end-to-end — the injected
`build_sender_id` seam here is a test double, not the real helper. It proves the
CORE forwards the caller's project to whatever builder it is given, and it proves
the audit counters move. The 12 other server-side `build_sender_id_for_cc` call
sites are row 4df4215c and are UNMEASURED here.

Row: 12b5a766 (DM write path stamps @lupin for every session, any project)
"""

import unittest
from unittest.mock import MagicMock


class _SenderIdSpy:
    """
    Recording stand-in for the injected `build_sender_id` seam.

    Sensitive ON THE PROJECT AXIS by construction: the project it is handed is
    interpolated into the value it returns, so two different projects CANNOT
    produce the same stamp. That sensitivity is asserted by an explicit control
    test below rather than assumed — a spy that records while attached to
    nothing, or that ignores the argument under test, would otherwise pass every
    assertion in this file.
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
        body              = "where are we on the stamp?",
        recipient_persona = "mr radio",
        sender_persona    = "Extra 1",
        sender_icon       = "🪨",
    )
    fields.update( overrides )
    return DmSendRequest( **fields )


def _make_respond_body( **overrides ):
    from cosa.rest.routers.dm import DmRespondRequest
    fields = dict(
        sender_session_id = "asker-session-aaaa",
        body              = "threaded reply",
        recipient_persona = "mr radio",
        reply_to          = "msg-1",
        thread_id         = "thread-1",
    )
    fields.update( overrides )
    return DmRespondRequest( **fields )


class TestSenderIdSpyControl( unittest.TestCase ):
    """
    CONTROL — prove the instrument can fail ON THE AXIS THIS SUITE CLAIMS.

    Every assertion below this class rests on the spy discriminating projects.
    A spy that recorded faithfully but ignored `project` would make the whole
    suite green against an unfixed core.
    """

    def test_spy_discriminates_on_the_project_axis( self ):
        """Two projects → two different stamps. If this fails, nothing else in this file means anything."""
        spy = _SenderIdSpy()
        self.assertNotEqual( spy( "sid", project="plan" ), spy( "sid", project="lupin" ) )

    def test_spy_records_the_project_it_was_handed( self ):
        """The spy is ATTACHED to its argument, not merely counting calls."""
        spy = _SenderIdSpy()
        spy( "sid", project="cosa-voice" )
        self.assertEqual( spy.calls[ -1 ][ "project" ], "cosa-voice" )


class TestCallerSuppliedProject( unittest.TestCase ):

    def setUp( self ):
        from cosa.rest.routers.dm import execute_dm_send
        self.execute_dm_send = execute_dm_send
        self.queue           = MagicMock()
        self.persist         = MagicMock( return_value="db-123" )
        self.spy             = _SenderIdSpy()

    def _run( self, body ):
        return self.execute_dm_send(
            authenticated_user_id = "user-uuid-1",
            body                  = body,
            notification_queue    = self.queue,
            resolve_recipient_fn  = MagicMock( return_value={
                "http_status"  : 200,
                "session_id"   : "abcdef1234567890",
                "persona_name" : "mr radio",
            } ),
            build_sender_id       = self.spy,
            persist_fn            = self.persist,
            new_id_fn             = lambda: "fixed-msg-id",
        )

    def test_send_stamps_the_callers_project_not_the_servers( self ):
        """A `plan` session's DM stamps @plan — the whole point of row 12b5a766."""
        self._run( _make_send_body( sender_project="plan" ) )
        self.assertEqual(
            self.persist.call_args.kwargs[ "sender_id" ],
            "claude.code@plan.deepily.ai#asker-session-aaaa"
        )

    def test_respond_stamps_the_callers_project_too( self ):
        """The reply path shares the core, so it must share the fix — not stamp @lupin."""
        self._run( _make_respond_body( sender_project="plan" ) )
        self.assertEqual(
            self.persist.call_args.kwargs[ "sender_id" ],
            "claude.code@plan.deepily.ai#asker-session-aaaa"
        )

    def test_absent_project_is_now_rejected_step_2_shipped( self ):
        """
        ⚠️ THIS TEST WAS INVERTED 2026-07-27 WHEN STEP 2 SHIPPED. It previously
        asserted the step-1 TRANSITION contract — absent is ACCEPTED and stamped
        as before — and that contract is now superseded, so the old assertion is
        recorded here rather than deleted:

            self.assertIsNone( self.spy.calls[ -1 ][ "project" ] )
            persist sender_id == "claude.code@lupin.deepily.ai#asker-session-aaaa"

        WHY IT WAS RIGHT THEN: eleven live MCP processes were running pre-fix
        code, each resolving its project at module load, so editing the client
        could not reach a running one. A 422 then muted the fleet until respawn.

        WHY IT FLIPPED: both arms are now measured — zero live clients predate
        831e18dc, and 362 audit observations over 12h carry un_projected=0 with a
        synthetic offender proven to survive the same filter.

        The step-2 contract is pinned in the GATED tree at
        `src/tests/unit/test_dm_sender_project_required.py` — this file's tree is
        invisible to every gate (row 5bf28e07), so the regression guard cannot
        live here. This case remains only so the inversion is visible to anyone
        reading the step-1 suite.
        """
        result = self._run( _make_send_body() )
        self.assertEqual( result[ "http_status" ], 422 )
        self.assertEqual( self.spy.calls, [] )
        self.persist.assert_not_called()


class TestSenderIdBuilderAdapter( unittest.TestCase ):
    """
    `_make_sender_id_builder` is the seam that decides WHOSE question gets
    answered. Both of its branches are load-bearing and both are tested here:
    with a caller project the host helper must not be consulted at all, and
    without one it must be consulted exactly as before.
    """

    def setUp( self ):
        from cosa.rest.routers.dm import _make_sender_id_builder
        self.make  = _make_sender_id_builder
        self.calls = []
        self.host  = lambda sid: self.calls.append( sid ) or f"host-answer::{sid}"

    def test_supplied_project_bypasses_the_host_helper_entirely( self ):
        """The host-shaped resolver is the defect; a caller-supplied project must not reach it."""
        out = self.make( self.host )( "sess-1", project="plan" )
        self.assertEqual( out, "claude.code@plan.deepily.ai#sess-1" )
        self.assertEqual( self.calls, [] )

    def test_absent_project_delegates_to_the_host_helper_unchanged( self ):
        """Step-1 transition: no caller project → today's behavior, byte for byte."""
        out = self.make( self.host )( "sess-1" )
        self.assertEqual( out, "host-answer::sess-1" )
        self.assertEqual( self.calls, [ "sess-1" ] )

    def test_stamp_uses_the_shared_formatter_not_a_local_string( self ):
        """
        The sender_id FORMAT stays owned by cosa.agents.utils.sender_id. If this
        adapter formatted its own string, the two seams could drift and only one
        would be found.
        """
        from cosa.agents.utils.sender_id import build_sender_id
        self.assertEqual(
            self.make( self.host )( "sess-1", project="cosa-voice" ),
            build_sender_id( "claude.code", project="cosa-voice", suffix="sess-1" )
        )


class TestUnprojectedAudit( unittest.TestCase ):
    """
    The audit exists so step 2 is a MEASUREMENT, not a guess: before flipping
    absent→422, the log must answer "is anyone still sending without it?"
    """

    def setUp( self ):
        from cosa.rest.routers import dm
        self.dm = dm
        self.dm.reset_dm_project_audit()
        self.queue   = MagicMock()
        self.persist = MagicMock( return_value="db-123" )
        self.spy     = _SenderIdSpy()

    def _run( self, body ):
        return self.dm.execute_dm_send(
            authenticated_user_id = "user-uuid-1",
            body                  = body,
            notification_queue    = self.queue,
            resolve_recipient_fn  = MagicMock( return_value={
                "http_status"  : 200,
                "session_id"   : "abcdef1234567890",
                "persona_name" : "mr radio",
            } ),
            build_sender_id       = self.spy,
            persist_fn            = self.persist,
            new_id_fn             = lambda: "fixed-msg-id",
        )

    def test_zero_is_printed_not_merely_absent( self ):
        """
        PRINT THE LEGITIMATE ZERO. With only projected DMs, the audit line must
        still SAY un-projected=0 — otherwise "nobody sent one" and "the audit is
        not wired" are the same output.
        """
        self._run( _make_send_body( sender_project="plan" ) )
        line = self.dm.format_dm_project_audit_line()
        self.assertIn( "un_projected=0", line )
        self.assertIn( "projected=1", line )

    def test_unprojected_send_is_counted_and_named( self ):
        """An un-projected DM increments the counter and names the offending session."""
        self._run( _make_send_body() )
        counts = self.dm.get_dm_project_audit()
        self.assertEqual( counts[ "un_projected" ], 1 )
        self.assertEqual( counts[ "projected" ], 0 )
        self.assertIn( "asker-session-aaaa", counts[ "un_projected_senders" ] )

    def test_a_422_run_does_not_pollute_the_audit( self ):
        """An unresolved recipient never reached the stamp, so it is not a data point either way."""
        self.dm.execute_dm_send(
            authenticated_user_id = "user-uuid-1",
            body                  = _make_send_body(),
            notification_queue    = self.queue,
            resolve_recipient_fn  = MagicMock( return_value={
                "http_status" : 422,
                "detail"      : { "error": "recipient_not_found" },
            } ),
            build_sender_id       = self.spy,
            persist_fn            = self.persist,
            new_id_fn             = lambda: "fixed-msg-id",
        )
        counts = self.dm.get_dm_project_audit()
        self.assertEqual( counts[ "projected" ], 0 )
        self.assertEqual( counts[ "un_projected" ], 0 )


if __name__ == "__main__":
    unittest.main()
