"""
Unit tests for the commons and DM tool surface: the `commons_enabled` kill switch,
the thin delegation wrappers, and the last few degrade-don't-raise fallbacks.

WHY THE THIN WRAPPERS ARE WORTH PINNING
Each commons tool opens with `if not _commons_enabled(): return <empty>`. That is
the defense-in-depth switch from AC12, and its two failure modes point opposite
ways: a switch that does not stop the call leaks cross-session traffic when the
operator has turned it off, and a switch stuck on refuses every call when it is
on. Neither is visible from reading the one-liner — only from exercising both
sides of it, which is what these do.

The `return []` vs `return {"status": "error"}` split is deliberate and is
asserted per tool: a READ tool answers with an empty result set, a WRITE tool
answers with an explicit error, because silently "succeeding" a post nobody
stored is the worse failure.

Venue: :7999-eligible — no server, no network, no state mutation.
"""

import pytest

import lupin_mcp.cosa_voice_mcp as cv


@pytest.fixture
def enabled( monkeypatch ):
    monkeypatch.setattr( cv, "_commons_enabled", lambda: True )
    monkeypatch.setattr( cv, "_commons_persona_fields",
                         lambda: { "persona_name": "sam", "persona_icon": "🎙️",
                                   "persona_color": "#5E35B1" } )


@pytest.fixture
def disabled( monkeypatch ):
    monkeypatch.setattr( cv, "_commons_enabled", lambda: False )


# ── the kill switch ───────────────────────────────────────────────────────────

class TestCommonsDisabledSwitch:
    """Every commons entry point must refuse when the switch is off."""

    def test_read_tools_answer_with_an_empty_result_set( self, disabled ):
        assert cv.commons_read.fn( topic="coordination" ) == []
        assert cv.commons_who.fn() == []

    @pytest.mark.parametrize( "call", [
        lambda: cv.commons_post.fn( topic="presence", body="hi" ),
        lambda: cv.commons_ask_sync.fn( topic="help-wanted", body="q" ),
        lambda: cv._commons_ask_async_dispatch( topic="help-wanted", body="q" ),
    ] )
    def test_write_tools_answer_with_an_explicit_error( self, disabled, call ):
        # A write must never look like it succeeded. An empty-but-ok return here
        # would tell the caller their post landed when nothing stored it.
        assert call() == { "status": "error", "reason": "commons disabled" }

    def test_no_store_is_even_constructed_while_disabled( self, disabled, monkeypatch ):
        def must_not_run():
            raise AssertionError( "the store must not be touched while commons is disabled" )
        monkeypatch.setattr( cv, "_get_commons_store", must_not_run )

        cv.commons_read.fn( topic="coordination" )
        cv.commons_who.fn()
        cv.commons_post.fn( topic="presence", body="hi" )


# ── delegation while enabled ──────────────────────────────────────────────────

class TestCommonsDelegation:

    def test_post_carries_this_session_s_persona_to_the_store( self, enabled, monkeypatch ):
        # The persona fields are how a reader tells WHO posted. Dropping them
        # would make every post anonymous on the commons.
        seen = {}
        class _Store:
            def post( self, **k ): seen.update( k ); return { "status": "ok" }
        monkeypatch.setattr( cv, "_get_commons_store", lambda: _Store() )

        assert cv.commons_post.fn( topic="presence", body="hi" ) == { "status": "ok" }
        assert seen[ "topic" ] == "presence"
        assert seen[ "persona_name" ] == "sam"

    def test_read_passes_its_filters_through( self, enabled, monkeypatch ):
        seen = {}
        class _Store:
            def read( self, **k ): seen.update( k ); return [ { "id": 1 } ]
        monkeypatch.setattr( cv, "_get_commons_store", lambda: _Store() )

        assert cv.commons_read.fn( topic="coordination", limit=5 ) == [ { "id": 1 } ]
        assert seen[ "topic" ] == "coordination"
        assert seen[ "limit" ] == 5

    def test_who_passes_the_retention_window_through( self, enabled, monkeypatch ):
        seen = {}
        class _Store:
            def who( self, **k ): seen.update( k ); return [ "sam" ]
        monkeypatch.setattr( cv, "_get_commons_store", lambda: _Store() )

        assert cv.commons_who.fn( retention_hours=6 ) == [ "sam" ]
        assert seen[ "retention_hours" ] == 6

    def test_ask_sync_falls_back_to_the_configured_grace_when_the_caller_omits_it( self, enabled, monkeypatch ):
        seen = {}
        monkeypatch.setattr( cv, "_get_commons_store", lambda: object() )
        monkeypatch.setattr( cv, "_commons_ask_sync_grace_default", lambda: 2.5 )
        monkeypatch.setattr( cv, "_commons_ask_sync_impl", lambda **k: seen.update( k ) or { "ok": True } )

        cv.commons_ask_sync.fn( topic="help-wanted", body="q" )
        assert seen[ "grace_seconds" ] == 2.5

    def test_ask_sync_honors_an_explicit_grace( self, enabled, monkeypatch ):
        seen = {}
        monkeypatch.setattr( cv, "_get_commons_store", lambda: object() )
        monkeypatch.setattr( cv, "_commons_ask_sync_grace_default", lambda: 2.5 )
        monkeypatch.setattr( cv, "_commons_ask_sync_impl", lambda **k: seen.update( k ) or { "ok": True } )

        cv.commons_ask_sync.fn( topic="help-wanted", body="q", grace_seconds=9.0 )
        assert seen[ "grace_seconds" ] == 9.0

    def test_ask_async_routes_through_the_shared_dispatch( self, enabled, monkeypatch ):
        seen = {}
        monkeypatch.setattr( cv, "_commons_ask_async_dispatch", lambda **k: seen.update( k ) or { "ok": True } )
        assert cv.commons_ask_async.fn( topic="help-wanted", body="q" ) == { "ok": True }
        assert seen[ "topic" ] == "help-wanted"

    def test_the_async_dispatch_carries_the_persona_to_the_impl( self, enabled, monkeypatch ):
        seen = {}
        monkeypatch.setattr( cv, "_get_commons_store", lambda: object() )
        monkeypatch.setattr( cv, "_commons_ask_async_impl", lambda **k: seen.update( k ) or { "ok": True } )

        cv._commons_ask_async_dispatch( topic="help-wanted", body="q" )
        assert seen[ "persona_name" ] == "sam"


# ── DM wrappers ───────────────────────────────────────────────────────────────

class TestDmDelegation:

    def test_dm_send_carries_this_session_s_persona_as_the_sender( self, enabled, monkeypatch ):
        # `sender_persona` is what the recipient sees as the FROM. If the wrapper
        # dropped it, a DM would arrive attributed to nobody.
        seen = {}
        monkeypatch.setattr( cv, "_dm_send_impl", lambda **k: seen.update( k ) or { "status": "sent" } )
        monkeypatch.setattr( cv, "_mcp_outbound_api_key", lambda: "k" )

        assert cv._dm_send_fn( recipient="tiberius", body="hi" ) == { "status": "sent" }
        assert seen[ "recipient" ]      == "tiberius"
        assert seen[ "sender_persona" ] == "sam"
        assert seen[ "sender_icon" ]    == "🎙️"
        assert seen[ "post_fn" ] is cv.requests.post       # HTTP injected, not imported

    def test_dm_respond_carries_the_persona_as_the_sender( self, enabled, monkeypatch ):
        seen = {}
        monkeypatch.setattr( cv, "_dm_respond_impl", lambda **k: seen.update( k ) or { "status": "sent" } )
        monkeypatch.setattr( cv, "_mcp_outbound_api_key", lambda: "k" )

        cv.dm_respond.fn( recipient="tiberius", body="hi", reply_to="m1", thread_id="t1" )
        assert seen[ "sender_persona" ] == "sam"

    def test_dm_get_delegates_with_the_resolved_api_base( self, monkeypatch ):
        seen = {}
        monkeypatch.setattr( cv, "_dm_get_impl", lambda **k: seen.update( k ) or { "status": "ok" } )
        assert cv.dm_get.fn( message_id="m1" ) == { "status": "ok" }
        assert seen[ "message_id" ] == "m1"
        assert seen[ "api_base_url" ].startswith( "http" )

    def test_dm_list_delegates_with_its_filters( self, monkeypatch ):
        seen = {}
        monkeypatch.setattr( cv, "_dm_list_impl", lambda **k: seen.update( k ) or [] )
        assert cv.dm_list.fn( thread_id="t1" ) == []
        assert seen[ "thread_id" ] == "t1"

    def test_an_unresolvable_recipient_reports_the_body_when_the_json_will_not_parse( self, monkeypatch ):
        """
        A 422 from the DM endpoint normally carries a JSON `detail`. When the body
        is not JSON, falling back to the raw text keeps SOME diagnosis rather than
        handing the caller `None` — the sender still needs to know why.

        422 specifically: it is the recipient-unresolved arm, and it is kept
        distinct from 413 (a too-long DM) so an over-long message never reports
        as a bad recipient.
        """
        class _Resp:
            status_code = 422
            text        = "upstream returned html" * 40
            def json( self ):
                raise ValueError( "not json" )

        got = cv._dm_send_impl(
            recipient            = "nobody",
            body                 = "hi",
            reply_to             = None,
            thread_id            = None,
            recipient_session_id = None,
            session_id           = "aaaaaaaa",
            sender_persona       = "sam",
            sender_icon          = "🎙️",
            sender_project       = "lupin",
            api_base_url         = "http://localhost:7999",
            api_key              = "k",
            post_fn              = lambda *a, **k: _Resp(),
        )

        assert got[ "reason" ] == "recipient_unresolved"
        assert got[ "detail" ]
        assert len( got[ "detail" ] ) <= 200                # truncated, not the whole page


# ── small fallbacks ───────────────────────────────────────────────────────────

class TestSmallFallbacks:

    def test_get_session_info_defaults_to_chorus_when_the_mode_cannot_be_read( self, monkeypatch ):
        # Chorus is the safe default: solo would suppress a sibling's audio cue.
        import cosa.utils.util as _cu
        def boom():
            raise RuntimeError( "config unavailable" )
        monkeypatch.setattr( _cu, "get_tts_interaction_mode", boom )

        assert cv.get_session_info.fn()[ "tts_interaction_mode" ] == "chorus"

    def test_get_session_info_omits_the_persona_rather_than_failing( self, monkeypatch ):
        def boom():
            raise RuntimeError( "no bridge" )
        monkeypatch.setattr( cv, "_get_cc_metadata", boom )

        info = cv.get_session_info.fn()                     # must not raise
        assert info[ "project" ] == cv.PROJECT

    def test_flip_speakerphone_without_a_session_id_says_so( self, monkeypatch ):
        def boom():
            raise RuntimeError( "no bridge" )
        monkeypatch.setattr( cv, "_get_cc_metadata", boom )
        monkeypatch.setattr( cv, "SESSION_ID", "", raising=False )

        assert cv._flip_speakerphone( True ) == {
            "status": "error", "reason": "No session_id available" }

    def test_the_outbound_api_key_delegates_to_the_loader( self, monkeypatch ):
        monkeypatch.setattr( cv, "load_outbound_api_key", lambda: "k-123" )
        assert cv._mcp_outbound_api_key() == "k-123"

    def test_sigterm_exits_zero_because_a_shutdown_is_not_a_failure( self, caplog ):
        with caplog.at_level( "INFO", logger=cv.logger.name ), pytest.raises( SystemExit ) as ei:
            cv._handle_sigterm( 15, None )
        assert ei.value.code == 0
        assert "shutting down gracefully" in caplog.text

    def test_list_spawned_sessions_asks_only_about_this_manager_s_own_crew( self, monkeypatch ):
        # Passing the wrong id here would hand back another manager's roster,
        # which the context tick would then act on.
        seen = {}
        from lupin_mcp import session_spawner
        monkeypatch.setattr( cv, "_wait_for_sender_id", lambda: "claude.code@lupin.deepily.ai#a" )
        monkeypatch.setattr( session_spawner, "resolve_manager_identity",
                             lambda meta, fallback_session_id: ( "mgr-1234", None ) )
        monkeypatch.setattr( session_spawner, "list_spawned_sessions",
                             lambda sid: seen.update( sid=sid ) or [ "worker-a" ] )

        assert cv.list_spawned_sessions.fn() == [ "worker-a" ]
        assert seen[ "sid" ] == "mgr-1234"
