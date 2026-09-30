"""
Row 97c5bd94 — the arbiter's DM push must actually get PAST the server's DM write path.

WHAT WENT WRONG. Since row 12b5a766 step 2 (2026-07-27) `execute_dm_send` refuses any DM that
carries no `sender_project`. The arbiter's payload never carried one, so every DM it pushed —
the `manager_stale_poke` wake-ups and the stale-MCP tells alike — was answered 422 and dropped
before it was stored or pushed. The journal recorded `push_unavailable` and nothing more: urllib
raised on the 422, so the status text survived and the reason (the response body) did not.

WHY THESE TESTS IMPORT THE SERVER'S OWN CORE. The rule "a DM needs a sender_project" lives in
`cosa.rest.routers.dm.execute_dm_send`. Restating it here would pass against today's rule and
keep passing after the server changed it. So the payload the arbiter really builds is fed to the
real `DmSendRequest` model and the real `execute_dm_send`, and the assertion is the server's own
verdict (201), not a re-derivation of why it would say yes.

THE CONTROL. The same payload with `sender_project` removed must come back 422. Without it a
green run could just mean the harness accepts anything.
"""
import io
import json
import urllib.error

import pytest

import lupin_arbiter_app.arbiter_live_notify as aln


ARGS = dict( base_url="http://x:7999", api_key="k", sender_session_id="lupin-arbiter-app-8001",
             sender_project="lupin" )


@pytest.fixture
def server_core( monkeypatch, tmp_path ):
    """
    The real `execute_dm_send`, with only its slow/persistent edges pinned: the traffic corpus
    goes to a throwaway file, the model judge is off, and the two-arm pilot is inactive so the
    wall clock cannot flip it onto the experiment path. Same pins as
    test_dm_sender_project_required, which owns the reasons.
    """
    import cosa.rest.dm_experiment as dm_experiment
    import cosa.rest.routers.dm as dm
    from unittest.mock import MagicMock
    monkeypatch.setattr( dm, "_DM_TRAFFIC_JSONL", str( tmp_path / "dm_traffic.jsonl" ) )
    monkeypatch.setattr( dm, "get_dm_quality_judgment_enabled", lambda: False )
    dm_experiment.set_policy( dm_experiment.make_inactive_policy() )
    dm.reset_dm_project_audit()

    def send( payload ):
        return dm.execute_dm_send(
            authenticated_user_id = "user-uuid-1",
            body                  = dm.DmSendRequest( **payload ),
            notification_queue    = MagicMock(),
            resolve_recipient_fn  = lambda **kw: { "http_status": 200, "session_id": "abcdef1234567890",
                                                   "persona_name": "mr radio" },
            build_sender_id       = lambda session_id, project=None: f"claude.code@{project}#{session_id}",
            persist_fn            = MagicMock( return_value="db-123" ),
            new_id_fn             = lambda: "fixed-msg-id",
        )
    yield send
    dm_experiment.reset_policy()


def _payload_the_arbiter_really_sends():
    """Capture the payload off the real dm_push closure — the exact dict it would POST."""
    seen = []
    push = aln.make_dm_push_fn( http_post_json_fn=lambda u, h, p, t: seen.append( p ) or ( 201, {} ),
                                log_fn=lambda e, **f: None, **ARGS )
    push( "mr radio", "stale-mcp-1", "STALE MCP — restart the seat" )
    return seen[ 0 ]


def test_the_payload_the_arbiter_sends_is_accepted_by_the_servers_own_core( server_core ):
    result = server_core( _payload_the_arbiter_really_sends() )
    assert result[ "http_status" ] == 201, result


def test_control_the_same_payload_without_a_project_is_refused( server_core ):
    payload = _payload_the_arbiter_really_sends()
    del payload[ "sender_project" ]
    result = server_core( payload )
    assert result[ "http_status" ] == 422 and "sender_project" in result[ "detail" ]


def test_the_project_is_the_callers_not_a_constant( server_core ):
    seen = []
    push = aln.make_dm_push_fn( http_post_json_fn=lambda u, h, p, t: seen.append( p ) or ( 201, {} ),
                                log_fn=lambda e, **f: None, **{ **ARGS, "sender_project": "other-repo" } )
    push( "mr radio", "t", "b" )
    assert seen[ 0 ][ "sender_project" ] == "other-repo"


# --- the reason for a refusal must survive into the log -------------------------------------------

def _push_logging( status_and_body ):
    logged = []
    push = aln.make_dm_push_fn( http_post_json_fn=lambda u, h, p, t: status_and_body,
                                log_fn=lambda e, **f: logged.append( ( e, f ) ), **ARGS )
    return push( "mr radio", "t-1", "b" ), logged


def test_a_refused_push_logs_its_status_and_body():
    outcome, logged = _push_logging( ( 422, { "detail": "sender_project is REQUIRED" } ) )
    assert outcome[ "outcome" ] == "push_unavailable"
    event, fields = logged[ 0 ]
    assert event == "dm_push_attempted" and fields[ "http_status" ] == 422
    assert "sender_project is REQUIRED" in fields[ "detail" ]


def test_a_dispatched_push_logs_no_failure_fields():
    outcome, logged = _push_logging( ( 201, {} ) )
    assert outcome[ "outcome" ] == "dispatched"
    assert "http_status" not in logged[ 0 ][ 1 ] and "detail" not in logged[ 0 ][ 1 ]


def test_a_push_that_raised_logs_its_detail_without_a_status():
    logged = []
    def boom( *a ): raise ConnectionError( "refused" )
    push = aln.make_dm_push_fn( http_post_json_fn=boom, log_fn=lambda e, **f: logged.append( f ), **ARGS )
    assert push( "mr radio", "t", "b" )[ "outcome" ] == "push_unavailable"
    assert "refused" in logged[ 0 ][ "detail" ] and "http_status" not in logged[ 0 ]


# --- _http_post_json: urllib RAISES on a 4xx, which is how the body got lost ----------------------

class _Resp:
    def __init__( self, status, raw ): self.status, self._raw = status, raw
    def read( self ): return self._raw
    def __enter__( self ): return self
    def __exit__( self, *a ): return False


def test_a_201_returns_its_status_and_parsed_body( monkeypatch ):
    monkeypatch.setattr( "urllib.request.urlopen", lambda req, timeout: _Resp( 201, b'{"dispatched": true}' ) )
    assert aln._http_post_json( "http://x", {}, { "a": 1 } ) == ( 201, { "dispatched": True } )


def test_an_empty_or_non_json_success_body_is_none( monkeypatch ):
    for raw in ( b"", b"not json" ):
        monkeypatch.setattr( "urllib.request.urlopen", lambda req, timeout, raw=raw: _Resp( 200, raw ) )
        assert aln._http_post_json( "http://x", {}, {} ) == ( 200, None )


def test_a_4xx_returns_the_status_and_the_reason_instead_of_raising( monkeypatch ):
    def refuse( req, timeout ):
        raise urllib.error.HTTPError( "http://x", 422, "Unprocessable Content", {},
                                      io.BytesIO( json.dumps( { "detail": "sender_project is REQUIRED" } ).encode() ) )
    monkeypatch.setattr( "urllib.request.urlopen", refuse )
    assert aln._http_post_json( "http://x", {}, {} ) == ( 422, { "detail": "sender_project is REQUIRED" } )


def test_a_4xx_with_an_unreadable_body_still_returns_its_status( monkeypatch ):
    def refuse( req, timeout ):
        raise urllib.error.HTTPError( "http://x", 500, "Server Error", {}, io.BytesIO( b"<html>" ) )
    monkeypatch.setattr( "urllib.request.urlopen", refuse )
    assert aln._http_post_json( "http://x", {}, {} ) == ( 500, None )


# --- the arbiter's own construction of the hop (app.py), the part that used to pass no project -----

class _DmCfg:
    def __init__( self, enabled=True ): self._enabled = enabled
    def get( self, key, default=None, return_type=None ):
        return self._enabled if key == "arbiter outreach dm push enabled" else default


def test_the_arbiters_dm_hop_posts_its_own_project( monkeypatch, server_core ):
    import lupin_arbiter_app.app as app_module
    seen = []
    monkeypatch.setattr( aln, "_http_post_json", lambda u, h, p, t: seen.append( p ) or ( 201, {} ) )
    monkeypatch.setattr( app_module, "resolve_arbiter_project", lambda: "lupin" )
    push = app_module.build_dm_push_fn( _DmCfg(), base_url="http://x:7999", api_key="k", timeout=5 )
    assert push( "mr radio", "stale-mcp-9", "STALE MCP" )[ "outcome" ] == "dispatched"
    assert seen[ 0 ][ "sender_project" ] == "lupin"
    assert server_core( seen[ 0 ] )[ "http_status" ] == 201          # and the server's own core accepts what it built


def test_the_dm_hop_is_none_when_its_flag_is_off():
    import lupin_arbiter_app.app as app_module
    assert app_module.build_dm_push_fn( _DmCfg( enabled=False ), base_url="http://x", api_key="k", timeout=5 ) is None


def test_the_arbiter_project_is_detected_and_degrades_to_lupin( monkeypatch ):
    import lupin_arbiter_app.app as app_module
    monkeypatch.setattr( "cosa.agents.utils.sender_id.detect_project", lambda: "other-repo" )
    assert app_module.resolve_arbiter_project() == "other-repo"
    def boom(): raise OSError( "no git" )
    monkeypatch.setattr( "cosa.agents.utils.sender_id.detect_project", boom )
    assert app_module.resolve_arbiter_project() == "lupin"
