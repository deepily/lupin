"""
Unit tests for cosa_voice_mcp's project-detection and repo-account-validation
paths — exercising the REAL functions.

WHY A NEW FILE RATHER THAN EXTENDING test_mcp_account_validation.py
==================================================================
That file does not call `_validate_repo_account`. It rebuilds a hand-written
copy inside the test ("The function logic mirrors cosa_voice_mcp.
_validate_repo_account exactly") and exercises the copy. Coverage therefore
reported the real function at 0% while six tests named after it passed.

The copy has since DRIFTED from the original, measured 2026-08-25:

  1. It catches `requests.ConnectionError` only. The real function catches
     `( requests.ConnectionError, requests.Timeout )`, and carries a comment
     saying why: without the Timeout arm a slow server propagates
     `requests.ReadTimeout` out of module-import scope and breaks every test
     that imports cosa_voice_mcp. `ReadTimeout` is NOT a subclass of
     `ConnectionError` (verified: issubclass(...) is False), so the copy
     encodes the PRE-FIX behavior and its
     `test_connection_error_sends_server_down_notification` passes anyway.
  2. It has no final `except Exception` arm, so the "never let validation
     explode at import time" guarantee is untested.
  3. It never touches `_ACCOUNT_VALIDATED` — the module-level flag that IS the
     function's observable output — so nothing asserted it at all.

A replica that must be kept in step by hand is only as good as the last person
who remembered. These tests call the real thing, so drift is impossible by
construction.

Venue: :7999-eligible — pure unit, no server, no state mutation. Every network
call and credential read is injected.
"""

import pytest
import requests

import lupin_mcp.cosa_voice_mcp as cv


@pytest.fixture( autouse=True )
def _restore_module_globals( monkeypatch ):
    """
    `_validate_repo_account` and `_get_project` write MODULE-LEVEL globals
    (`_ACCOUNT_VALIDATED`, `_PROJECT_SOURCE`). Left dirty they leak into every
    later test in the same interpreter, so both are restored around each test.
    """
    monkeypatch.setattr( cv, "_ACCOUNT_VALIDATED", None, raising=False )
    monkeypatch.setattr( cv, "_PROJECT_SOURCE", "unknown", raising=False )


def _creds_ok( project ):
    return ( f"claude.code@{project}.deepily.ai", "hunter2" )


def _resp( status ):
    class _R:
        status_code = status
    return _R()


# ── project detection ─────────────────────────────────────────────────────────

class TestDetectProjectFromCwd:
    def test_delegates_to_the_shared_detector( self, monkeypatch ):
        monkeypatch.setattr( cv, "_detect_project_shared", lambda: "lupin" )
        assert cv._detect_project_from_cwd() == "lupin"

    def test_a_raising_detector_degrades_to_none_rather_than_propagating( self, monkeypatch ):
        # This runs at import time. Propagating here would take down every
        # consumer of the module.
        def boom():
            raise RuntimeError( "no git ancestor" )
        monkeypatch.setattr( cv, "_detect_project_shared", boom )
        assert cv._detect_project_from_cwd() is None


class TestGetProject:
    """
    The three-tier priority, and the SOURCE each tier records. `_PROJECT_SOURCE`
    is not decoration — it is how a reader tells an auto-detected project from a
    basename guess, and a wrong project routes notifications to the wrong repo.
    """

    def test_a_known_detected_project_is_sourced_known( self, monkeypatch ):
        monkeypatch.setattr( cv, "_detect_project_from_cwd", lambda: "lupin" )
        monkeypatch.setattr( cv, "is_known_project", lambda p: True )
        assert cv._get_project() == "lupin"
        assert cv._PROJECT_SOURCE == "known"

    def test_an_unregistered_detected_project_is_sourced_basename( self, monkeypatch ):
        monkeypatch.setattr( cv, "_detect_project_from_cwd", lambda: "some-repo" )
        monkeypatch.setattr( cv, "is_known_project", lambda p: False )
        assert cv._get_project() == "some-repo"
        assert cv._PROJECT_SOURCE == "basename"

    def test_the_env_var_is_used_only_when_detection_finds_nothing( self, monkeypatch ):
        monkeypatch.setattr( cv, "_detect_project_from_cwd", lambda: None )
        monkeypatch.setenv( "MCP_PROJECT", "  MyProject  " )
        assert cv._get_project() == "myproject"             # trimmed AND lowercased
        assert cv._PROJECT_SOURCE == "env_var"

    def test_detection_beats_the_env_var( self, monkeypatch ):
        # Dynamic detection takes precedence so one env default cannot pin a
        # multi-repo session to the wrong project.
        monkeypatch.setattr( cv, "_detect_project_from_cwd", lambda: "lupin" )
        monkeypatch.setattr( cv, "is_known_project", lambda p: True )
        monkeypatch.setenv( "MCP_PROJECT", "somethingelse" )
        assert cv._get_project() == "lupin"

    def test_a_blank_env_var_falls_through_to_the_cwd_basename( self, monkeypatch, tmp_path ):
        target = tmp_path / "FallbackRepo"
        target.mkdir()
        monkeypatch.setattr( cv, "_detect_project_from_cwd", lambda: None )
        monkeypatch.setenv( "MCP_PROJECT", "   " )
        monkeypatch.chdir( target )
        assert cv._get_project() == "fallbackrepo"
        assert cv._PROJECT_SOURCE == "basename"

    def test_the_fallback_warns_loudly_because_routing_may_be_wrong( self, monkeypatch, tmp_path, caplog ):
        target = tmp_path / "Unregistered"
        target.mkdir()
        monkeypatch.setattr( cv, "_detect_project_from_cwd", lambda: None )
        monkeypatch.delenv( "MCP_PROJECT", raising=False )
        monkeypatch.chdir( target )
        with caplog.at_level( "WARNING", logger=cv.logger.name ):
            cv._get_project()
        assert "PROJECT DETECTION FALLBACK" in caplog.text
        assert "may route incorrectly" in caplog.text


class TestResolveCanonicalProject:
    """
    The cwd name and the account identity can differ (e.g. `ampe-to-meridian` on
    disk, `ampe2meridian` in the account email). sender_id must carry the
    CANONICAL one, so this resolves it from the config email.
    """

    def test_maps_a_detected_name_to_the_canonical_identifier( self, monkeypatch ):
        import lupin_cli.claude_code.hooks.lib.hook_credentials as hc
        monkeypatch.setattr( hc, "get_hook_credentials",
                             lambda p: ( "claude.code@ampe2meridian.deepily.ai", "pw" ) )
        assert cv._resolve_canonical_project( "ampe-to-meridian" ) == "ampe2meridian"

    def test_an_already_canonical_name_passes_through_unchanged( self, monkeypatch ):
        import lupin_cli.claude_code.hooks.lib.hook_credentials as hc
        monkeypatch.setattr( hc, "get_hook_credentials",
                             lambda p: ( "claude.code@lupin.deepily.ai", "pw" ) )
        assert cv._resolve_canonical_project( "lupin" ) == "lupin"

    def test_an_unparseable_email_leaves_the_detected_name_alone( self, monkeypatch, caplog ):
        import lupin_cli.claude_code.hooks.lib.hook_credentials as hc
        monkeypatch.setattr( hc, "get_hook_credentials",
                             lambda p: ( "not-an-email", "pw" ) )
        with caplog.at_level( "WARNING", logger=cv.logger.name ):
            assert cv._resolve_canonical_project( "lupin" ) == "lupin"
        assert "does not match expected format" in caplog.text

    @pytest.mark.parametrize( "exc", [ FileNotFoundError( "no config" ), ValueError( "no section" ) ] )
    def test_a_missing_config_is_not_an_error_just_no_mapping( self, monkeypatch, exc ):
        import lupin_cli.claude_code.hooks.lib.hook_credentials as hc
        def boom( p ):
            raise exc
        monkeypatch.setattr( hc, "get_hook_credentials", boom )
        assert cv._resolve_canonical_project( "lupin" ) == "lupin"

    def test_an_unexpected_error_still_returns_the_detected_name( self, monkeypatch, caplog ):
        # Best-effort by contract — this must never raise into sender_id building.
        import lupin_cli.claude_code.hooks.lib.hook_credentials as hc
        def boom( p ):
            raise RuntimeError( "config parser exploded" )
        monkeypatch.setattr( hc, "get_hook_credentials", boom )
        with caplog.at_level( "WARNING", logger=cv.logger.name ):
            assert cv._resolve_canonical_project( "lupin" ) == "lupin"
        assert "Unexpected error resolving canonical project" in caplog.text


# ── validation-error notification ─────────────────────────────────────────────

class TestSendValidationError:
    def test_sends_an_urgent_task_notification_from_the_error_sender( self, monkeypatch ):
        sent = {}
        monkeypatch.setattr( cv, "notify_user_async",
                             lambda request, debug: sent.update( req=request, debug=debug ) )
        cv._send_validation_error( "something is wrong" )

        assert sent[ "req" ].sender_id == cv.ERROR_SENDER_ID
        assert sent[ "req" ].priority.value == "urgent"
        assert "COSA-VOICE MCP VALIDATION FAILED" in sent[ "req" ].message
        assert "something is wrong" in sent[ "req" ].message

    def test_logs_critical_even_when_the_notification_cannot_be_sent( self, monkeypatch, caplog ):
        # The log is the floor. If the server is the very thing that is down,
        # the notification cannot arrive and the log is all that remains.
        def boom( request, debug ):
            raise RuntimeError( "server unreachable" )
        monkeypatch.setattr( cv, "notify_user_async", boom )

        with caplog.at_level( "DEBUG", logger=cv.logger.name ):
            cv._send_validation_error( "detail here" )      # must not raise

        assert "COSA-VOICE MCP VALIDATION FAILED" in caplog.text
        assert "Could not send validation error notification" in caplog.text


# ── repo account validation (the REAL function) ───────────────────────────────

class TestValidateRepoAccount:

    def test_valid_credentials_and_a_200_login_validate_silently( self, monkeypatch ):
        import lupin_cli.claude_code.hooks.lib.hook_credentials as hc
        sent = []
        monkeypatch.setattr( hc, "get_hook_credentials", _creds_ok )
        monkeypatch.setattr( cv.requests, "post", lambda *a, **k: _resp( 200 ) )
        monkeypatch.setattr( cv, "_send_validation_error", lambda d: sent.append( d ) )

        cv._validate_repo_account( "lupin" )

        assert sent == []
        assert cv._ACCOUNT_VALIDATED is True

    @pytest.mark.parametrize( "exc", [ FileNotFoundError( "no config" ), ValueError( "no [lupin] section" ) ] )
    def test_missing_credentials_notify_with_setup_steps_and_mark_invalid( self, monkeypatch, exc ):
        import lupin_cli.claude_code.hooks.lib.hook_credentials as hc
        sent = []
        def boom( p ):
            raise exc
        monkeypatch.setattr( hc, "get_hook_credentials", boom )
        monkeypatch.setattr( cv, "_send_validation_error", lambda d: sent.append( d ) )

        cv._validate_repo_account( "lupin" )

        assert cv._ACCOUNT_VALIDATED is False
        assert len( sent ) == 1
        assert "No credentials for project 'lupin'" in sent[ 0 ]
        assert "claude.code@lupin.deepily.ai" in sent[ 0 ]   # the email to create
        assert "/app/admin/users" in sent[ 0 ]               # where to create it

    def test_a_non_200_login_reports_the_status_code( self, monkeypatch ):
        import lupin_cli.claude_code.hooks.lib.hook_credentials as hc
        sent = []
        monkeypatch.setattr( hc, "get_hook_credentials", _creds_ok )
        monkeypatch.setattr( cv.requests, "post", lambda *a, **k: _resp( 401 ) )
        monkeypatch.setattr( cv, "_send_validation_error", lambda d: sent.append( d ) )

        cv._validate_repo_account( "lupin" )

        assert cv._ACCOUNT_VALIDATED is False
        assert "HTTP 401" in sent[ 0 ]

    @pytest.mark.parametrize( "exc_cls", [
        requests.ConnectionError,
        requests.Timeout,
        requests.exceptions.ReadTimeout,                    # NOT a ConnectionError
        requests.exceptions.ConnectTimeout,
    ] )
    def test_every_transport_failure_is_caught_including_read_timeout( self, monkeypatch, exc_cls ):
        """
        THE DRIFT THIS FILE EXISTS FOR. The replica in
        test_mcp_account_validation.py catches ConnectionError only, and
        `ReadTimeout` is not one — so a slow-but-up server would propagate out of
        module-import scope and break every importer. The real function catches
        `( ConnectionError, Timeout )`; this parametrization is what keeps that
        true rather than a comment saying it is.
        """
        import lupin_cli.claude_code.hooks.lib.hook_credentials as hc
        sent = []
        def boom( *a, **k ):
            raise exc_cls( "transport" )
        monkeypatch.setattr( hc, "get_hook_credentials", _creds_ok )
        monkeypatch.setattr( cv.requests, "post", boom )
        monkeypatch.setattr( cv, "_send_validation_error", lambda d: sent.append( d ) )

        cv._validate_repo_account( "lupin" )                # must not raise

        assert cv._ACCOUNT_VALIDATED is False
        assert len( sent ) == 1
        assert "Cannot reach Lupin server" in sent[ 0 ]
        assert exc_cls.__name__ in sent[ 0 ]                # names WHICH failure

    def test_an_unexpected_error_aborts_validation_without_exploding_at_import( self, monkeypatch, caplog ):
        """
        The final fallback. This function runs at module import, so ANY escaping
        exception takes down every consumer — which is a far worse outcome than
        running unvalidated.
        """
        import lupin_cli.claude_code.hooks.lib.hook_credentials as hc
        def boom( *a, **k ):
            raise RuntimeError( "something nobody predicted" )
        monkeypatch.setattr( hc, "get_hook_credentials", _creds_ok )
        monkeypatch.setattr( cv.requests, "post", boom )

        with caplog.at_level( "WARNING", logger=cv.logger.name ):
            cv._validate_repo_account( "lupin" )            # must not raise

        assert cv._ACCOUNT_VALIDATED is False
        assert "Repo account validation aborted" in caplog.text

    def test_the_login_call_targets_the_configured_server_with_the_config_credentials( self, monkeypatch ):
        import lupin_cli.claude_code.hooks.lib.hook_credentials as hc
        seen = {}
        def capture( url, json=None, timeout=None ):
            seen.update( url=url, json=json, timeout=timeout )
            return _resp( 200 )
        monkeypatch.setattr( hc, "get_hook_credentials", _creds_ok )
        monkeypatch.setattr( cv.requests, "post", capture )

        cv._validate_repo_account( "lupin" )

        assert seen[ "url" ] == f"{cv.SERVER_URL}/auth/login"
        assert seen[ "json" ] == { "email": "claude.code@lupin.deepily.ai", "password": "hunter2" }
        assert seen[ "timeout" ] == cv._SERVER_TRANSPORT_TIMEOUT_SECONDS


class TestGetSenderId:
    def test_builds_the_bare_sender_id( self ):
        assert cv._get_sender_id( "lupin" ) == "claude.code@lupin.deepily.ai"

    def test_appends_the_session_suffix( self ):
        assert cv._get_sender_id( "lupin", "a1b2c3d4" ) == "claude.code@lupin.deepily.ai#a1b2c3d4"
