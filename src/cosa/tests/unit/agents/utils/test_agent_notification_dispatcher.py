"""
Unit tests for cosa/agents/utils/agent_notification_dispatcher.py.

The dispatcher wraps the blocking/async notification API. Every external seam is
boundary-mocked — `_notify_user_sync` / `_notify_user_async` (the notification
boundary) and `ConfigurationManager` (routing config) — so NO notification ever
leaves the process and there is ZERO API spend. Async methods are driven via
asyncio.run with the boundary patched.

Coverage target: 100% lines + branches + functions on production logic.
quick_smoke_test() / __main__ are excluded by the coverage config.
"""
import asyncio
from unittest.mock import MagicMock, patch

import pytest

import cosa.agents.utils.agent_notification_dispatcher as mod
from cosa.agents.utils.agent_notification_dispatcher import (
    AgentNotificationDispatcher,
    _prepend_operator_routing,
    ctx_sender_id,
    ctx_target_user,
    ctx_session_name,
)
from cosa.agents.test_fix_expediter.state import VoiceGateTimeoutError, VoiceGateUnreachableError


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _resp( exit_code=0, response_value=None, status="ok" ):
    """Build a fake NotificationResponse ( the _notify_user_sync boundary return )."""
    r = MagicMock()
    r.exit_code      = exit_code
    r.response_value = response_value
    r.status         = status
    return r


def _run( coro ):
    return asyncio.run( coro )


# =========================================================================== #
# _prepend_operator_routing
# =========================================================================== #
def test_prepend_operator_routing_no_abstract():
    out = _prepend_operator_routing( None, "svc@x.com" )
    assert out == "**Operator routing**: originally owned by `svc@x.com`"


def test_prepend_operator_routing_with_abstract():
    out = _prepend_operator_routing( "details", "svc@x.com" )
    assert out.startswith( "**Operator routing**" )
    assert out.endswith( "details" )


# =========================================================================== #
# __init__ + build_sender_id
# =========================================================================== #
def test_init_defaults():
    d = AgentNotificationDispatcher( agent_type="deep.research" )
    assert "deep.research@" in d.sender_id
    assert d.supports_role is False
    assert d.default_priority == "medium"
    assert d.target_user is None
    assert d.session_id is None


def test_build_sender_id_with_explicit_suffix():
    d = AgentNotificationDispatcher( agent_type="podcast.gen" )
    assert d.build_sender_id( suffix="jobhash" ).endswith( "#jobhash" )


def test_build_sender_id_falls_back_to_default_suffix():
    d = AgentNotificationDispatcher( agent_type="podcast.gen", default_suffix="cli" )
    # suffix arg None → 'suffix or self.default_suffix' falsy arc → default_suffix
    assert d.build_sender_id().endswith( "#cli" )


# =========================================================================== #
# _resolve_sender_id
# =========================================================================== #
def test_resolve_sender_id_role_aware_with_scoped_session_id():
    d = AgentNotificationDispatcher( agent_type="swe", supports_role=True )
    d.session_id = "abc123::user42"
    resolved = d._resolve_sender_id( "lead" )
    assert "swe.lead@" in resolved
    assert resolved.endswith( "#abc123" )   # ::user42 stripped


def test_resolve_sender_id_role_aware_with_plain_session_id():
    d = AgentNotificationDispatcher( agent_type="swe", supports_role=True )
    d.session_id = "plainhash"              # no '::' → used verbatim
    assert d._resolve_sender_id( "coder" ).endswith( "#plainhash" )


def test_resolve_sender_id_role_aware_prefers_the_per_task_session_id():
    d = AgentNotificationDispatcher( agent_type="swe", supports_role=True )
    d.session_id = "shared-instance-value"
    tokens = mod.set_dispatch_context( session_id="task-hash::user42" )
    try:
        assert d._resolve_sender_id( "lead" ).endswith( "#task-hash" )
    finally:
        mod.reset_dispatch_context( tokens )
    assert d._resolve_sender_id( "lead" ).endswith( "#shared-instance-value" )   # reset restores the instance fallback


def test_resolve_sender_id_role_aware_without_session_id():
    d = AgentNotificationDispatcher( agent_type="swe", supports_role=True )
    # session_id None → suffix stays None
    assert "swe.lead@" in d._resolve_sender_id( "lead" )


def test_resolve_sender_id_contextvar_takes_priority():
    d = AgentNotificationDispatcher( agent_type="deep.research" )
    token = ctx_sender_id.set( "ctx-sender@x#1" )
    try:
        assert d._resolve_sender_id() == "ctx-sender@x#1"
    finally:
        ctx_sender_id.reset( token )


def test_resolve_sender_id_instance_default_when_no_role_no_ctx():
    d = AgentNotificationDispatcher( agent_type="deep.research" )
    d.sender_id = "deep.research@x#fixed"
    # non-role-aware → role param ignored; no ctx → instance default
    assert d._resolve_sender_id( role="ignored" ) == "deep.research@x#fixed"


# =========================================================================== #
# _resolve_target_user / _resolve_session_name
# =========================================================================== #
def test_resolve_target_user_contextvar_priority():
    d = AgentNotificationDispatcher( agent_type="test.agent" )
    d.target_user = "instance@x.com"
    token = ctx_target_user.set( "ctx@x.com" )
    try:
        assert d._resolve_target_user() == "ctx@x.com"
    finally:
        ctx_target_user.reset( token )


def test_resolve_target_user_instance_when_no_ctx():
    d = AgentNotificationDispatcher( agent_type="test.agent" )
    d.target_user = "instance@x.com"
    assert d._resolve_target_user() == "instance@x.com"


def test_resolve_session_name_override_wins():
    d = AgentNotificationDispatcher( agent_type="test.agent" )
    d.session_name = "instance-session"
    assert d._resolve_session_name( "override" ) == "override"


def test_resolve_session_name_contextvar_when_no_override():
    d = AgentNotificationDispatcher( agent_type="test.agent" )
    d.session_name = "instance-session"
    token = ctx_session_name.set( "ctx-session" )
    try:
        assert d._resolve_session_name() == "ctx-session"
    finally:
        ctx_session_name.reset( token )


def test_resolve_session_name_instance_when_no_override_no_ctx():
    d = AgentNotificationDispatcher( agent_type="test.agent" )
    d.session_name = "instance-session"
    assert d._resolve_session_name() == "instance-session"


# =========================================================================== #
# _resolve_routing
# =========================================================================== #
def _patch_config( operator="", accounts="" ):
    """Patch ConfigurationManager so _resolve_routing reads our values."""
    cfg = MagicMock()
    cfg.get.side_effect = lambda key, default=None, return_type=None: {
        "voice gate operator email"   : operator,
        "voice gate service accounts" : accounts,
    }.get( key, default )
    return patch( "cosa.config.configuration_manager.ConfigurationManager", return_value=cfg )


def test_resolve_routing_no_target_user():
    d = AgentNotificationDispatcher( agent_type="test.agent" )
    assert d._resolve_routing( None ) == ( None, False, None )


def test_resolve_routing_config_read_raises_returns_unchanged():
    d = AgentNotificationDispatcher( agent_type="test.agent" )
    with patch( "cosa.config.configuration_manager.ConfigurationManager", side_effect=RuntimeError( "boom" ) ):
        assert d._resolve_routing( "u@x.com" ) == ( "u@x.com", False, "u@x.com" )


def test_resolve_routing_no_operator_configured():
    d = AgentNotificationDispatcher( agent_type="test.agent" )
    with _patch_config( operator="", accounts="svc@x.com" ):
        assert d._resolve_routing( "u@x.com" ) == ( "u@x.com", False, "u@x.com" )


def test_resolve_routing_service_account_redirected_to_operator():
    d = AgentNotificationDispatcher( agent_type="test.agent" )
    with _patch_config( operator="op@x.com", accounts="svc@x.com, other@x.com" ):
        eff, redirected, original = d._resolve_routing( "SVC@x.com" )  # case-insensitive match
        assert ( eff, redirected, original ) == ( "op@x.com", True, "SVC@x.com" )


def test_resolve_routing_non_service_account_not_redirected():
    d = AgentNotificationDispatcher( agent_type="test.agent" )
    with _patch_config( operator="op@x.com", accounts="svc@x.com" ):
        assert d._resolve_routing( "human@x.com" ) == ( "human@x.com", False, "human@x.com" )


# =========================================================================== #
# notify_progress
# =========================================================================== #
def test_notify_progress_success_calls_async_boundary():
    d = AgentNotificationDispatcher( agent_type="deep.research" )
    with patch.object( mod, "_notify_user_async" ) as m:
        _run( d.notify_progress( "starting", abstract="ctx", session_name="s", job_id="dr-de05b9d0" ) )
        assert m.called
        request = m.call_args[ 0 ][ 0 ]
        assert request.message == "starting"


def test_notify_progress_swallows_exception():
    d = AgentNotificationDispatcher( agent_type="deep.research" )
    with patch.object( mod, "_notify_user_async", side_effect=RuntimeError( "net down" ) ):
        # must NOT raise — fire-and-forget swallows
        assert _run( d.notify_progress( "msg" ) ) is None


# =========================================================================== #
# ask_confirmation
# =========================================================================== #
def test_ask_confirmation_yes():
    d = AgentNotificationDispatcher( agent_type="test.agent" )
    with patch.object( mod, "_notify_user_sync", return_value=_resp( 0, "Yes, proceed" ) ):
        assert _run( d.ask_confirmation( "Proceed?" ) ) is True


def test_ask_confirmation_no():
    d = AgentNotificationDispatcher( agent_type="test.agent" )
    with patch.object( mod, "_notify_user_sync", return_value=_resp( 0, "no thanks" ) ):
        assert _run( d.ask_confirmation( "Proceed?" ) ) is False


def test_ask_confirmation_redirect_prepends_routing():
    d = AgentNotificationDispatcher( agent_type="test.agent" )
    d.target_user = "svc@x.com"
    captured = {}
    def _capture( request ):
        captured[ "abstract" ] = request.abstract
        return _resp( 0, "yes" )
    with _patch_config( operator="op@x.com", accounts="svc@x.com" ), \
         patch.object( mod, "_notify_user_sync", side_effect=_capture ):
        _run( d.ask_confirmation( "Proceed?", abstract="orig" ) )
    assert "Operator routing" in captured[ "abstract" ]


def test_ask_confirmation_exit_code_2_raises_timeout():
    d = AgentNotificationDispatcher( agent_type="test.agent" )
    with patch.object( mod, "_notify_user_sync", return_value=_resp( 2 ) ):
        with pytest.raises( VoiceGateTimeoutError ):
            _run( d.ask_confirmation( "Proceed?", timeout=5 ) )


def test_ask_confirmation_other_exit_code_raises_timeout():
    d = AgentNotificationDispatcher( agent_type="test.agent" )
    with patch.object( mod, "_notify_user_sync", return_value=_resp( 1, None, status="503" ) ):
        with pytest.raises( VoiceGateTimeoutError ):
            _run( d.ask_confirmation( "Proceed?" ) )


def test_ask_confirmation_connection_error_raises_timeout():
    d = AgentNotificationDispatcher( agent_type="test.agent" )
    with patch.object( mod, "_notify_user_sync", side_effect=ConnectionError( "refused" ) ):
        with pytest.raises( VoiceGateTimeoutError ):
            _run( d.ask_confirmation( "Proceed?" ) )


@pytest.mark.parametrize( "default", [ "yes", "no" ] )
def test_ask_confirmation_unexpected_error_raises_unreachable_not_the_default( default ):
    # An unexpected error means the asking broke and nobody answered. Returning
    # `default` would hand the caller "yes" or "no" as if a person had said it.
    # It is not a timeout either: the question may never have been asked.
    d = AgentNotificationDispatcher( agent_type="test.agent" )
    boom = RuntimeError( "weird" )
    with patch.object( mod, "_notify_user_sync", side_effect=boom ):
        with pytest.raises( VoiceGateUnreachableError ) as ctx:
            _run( d.ask_confirmation( "Proceed?", default=default ) )
    assert not isinstance( ctx.value, VoiceGateTimeoutError )
    assert ctx.value.phase == "confirmation"
    assert ctx.value.cause is boom


# =========================================================================== #
# get_feedback
# =========================================================================== #
def test_get_feedback_success():
    d = AgentNotificationDispatcher( agent_type="test.agent" )
    with patch.object( mod, "_notify_user_sync", return_value=_resp( 0, "my answer" ) ):
        assert _run( d.get_feedback( "Preferences?" ) ) == "my answer"


def test_get_feedback_exit_code_2_raises_timeout():
    d = AgentNotificationDispatcher( agent_type="test.agent" )
    with patch.object( mod, "_notify_user_sync", return_value=_resp( 2 ) ):
        with pytest.raises( VoiceGateTimeoutError ):
            _run( d.get_feedback( "Preferences?", timeout=7 ) )


def test_get_feedback_other_exit_code_raises_timeout():
    d = AgentNotificationDispatcher( agent_type="test.agent" )
    with patch.object( mod, "_notify_user_sync", return_value=_resp( 1, None, status="503" ) ):
        with pytest.raises( VoiceGateTimeoutError ):
            _run( d.get_feedback( "Preferences?" ) )


def test_get_feedback_connection_error_raises_timeout():
    d = AgentNotificationDispatcher( agent_type="test.agent" )
    with patch.object( mod, "_notify_user_sync", side_effect=ConnectionError( "x" ) ):
        with pytest.raises( VoiceGateTimeoutError ):
            _run( d.get_feedback( "Preferences?" ) )


def test_get_feedback_generic_error_returns_none():
    d = AgentNotificationDispatcher( agent_type="test.agent" )
    with patch.object( mod, "_notify_user_sync", side_effect=RuntimeError( "weird" ) ):
        assert _run( d.get_feedback( "Preferences?" ) ) is None


# =========================================================================== #
# present_choices
# =========================================================================== #
_QUESTIONS = [ { "header": "Pick", "question": "Which?", "options": [ { "label": "a" }, { "label": "b" } ] } ]


def test_present_choices_success_parses_answers():
    d = AgentNotificationDispatcher( agent_type="test.agent" )
    payload = '{"answers": {"Pick": "a"}}'
    with patch.object( mod, "_notify_user_sync", return_value=_resp( 0, payload ) ):
        out = _run( d.present_choices( _QUESTIONS ) )
    assert out == { "answers": { "Pick": "a" } }


def test_present_choices_non_json_response_wraps_raw():
    d = AgentNotificationDispatcher( agent_type="test.agent" )
    with patch.object( mod, "_notify_user_sync", return_value=_resp( 0, "plain text not json" ) ):
        out = _run( d.present_choices( _QUESTIONS ) )
    assert out == { "answers": { "response": "plain text not json" } }


def test_present_choices_empty_answers_raises_timeout():
    d = AgentNotificationDispatcher( agent_type="test.agent" )
    with patch.object( mod, "_notify_user_sync", return_value=_resp( 0, '{"answers": {}}' ) ):
        with pytest.raises( VoiceGateTimeoutError ):
            _run( d.present_choices( _QUESTIONS, timeout=3 ) )


def test_present_choices_all_blank_answers_raises_timeout():
    d = AgentNotificationDispatcher( agent_type="test.agent" )
    with patch.object( mod, "_notify_user_sync", return_value=_resp( 0, '{"answers": {"Pick": ""}}' ) ):
        with pytest.raises( VoiceGateTimeoutError ):
            _run( d.present_choices( _QUESTIONS ) )


def test_present_choices_non_dict_parsed_treated_as_empty():
    # parsed is a list (valid JSON, not a dict) → answers={} → timeout
    d = AgentNotificationDispatcher( agent_type="test.agent" )
    with patch.object( mod, "_notify_user_sync", return_value=_resp( 0, '[1, 2, 3]' ) ):
        with pytest.raises( VoiceGateTimeoutError ):
            _run( d.present_choices( _QUESTIONS ) )


def test_present_choices_redirect_prepends_routing():
    d = AgentNotificationDispatcher( agent_type="test.agent" )
    d.target_user = "svc@x.com"
    captured = {}
    def _capture( request ):
        captured[ "abstract" ] = request.abstract
        return _resp( 0, '{"answers": {"Pick": "a"}}' )
    with _patch_config( operator="op@x.com", accounts="svc@x.com" ), \
         patch.object( mod, "_notify_user_sync", side_effect=_capture ):
        _run( d.present_choices( _QUESTIONS, abstract="orig" ) )
    assert "Operator routing" in captured[ "abstract" ]


def test_present_choices_exit_code_2_raises_timeout():
    d = AgentNotificationDispatcher( agent_type="test.agent" )
    with patch.object( mod, "_notify_user_sync", return_value=_resp( 2 ) ):
        with pytest.raises( VoiceGateTimeoutError ):
            _run( d.present_choices( _QUESTIONS, timeout=9 ) )


def test_present_choices_catch_all_no_response_raises_timeout():
    # exit_code 0 but response_value falsy → skip success block → catch-all timeout
    d = AgentNotificationDispatcher( agent_type="test.agent" )
    with patch.object( mod, "_notify_user_sync", return_value=_resp( 0, None ) ):
        with pytest.raises( VoiceGateTimeoutError ):
            _run( d.present_choices( _QUESTIONS ) )


def test_present_choices_connection_error_raises_timeout():
    d = AgentNotificationDispatcher( agent_type="test.agent" )
    with patch.object( mod, "_notify_user_sync", side_effect=ConnectionError( "x" ) ):
        with pytest.raises( VoiceGateTimeoutError ):
            _run( d.present_choices( _QUESTIONS ) )


def test_present_choices_generic_error_returns_empty_answers():
    d = AgentNotificationDispatcher( agent_type="test.agent" )
    with patch.object( mod, "_notify_user_sync", side_effect=RuntimeError( "weird" ) ):
        assert _run( d.present_choices( _QUESTIONS ) ) == { "answers": {} }


# ---------------------------------------------------------------------------
# make_role_interface_functions: the role-aware wrappers the SWE team module is built from
# ---------------------------------------------------------------------------

def _role_namespace():
    from unittest.mock import AsyncMock
    d = MagicMock()
    d.notify_progress = AsyncMock( return_value=None )
    d.ask_confirmation = AsyncMock( return_value=True )
    d.present_choices = AsyncMock( return_value={ "answers": { "h": "v" } } )
    d.get_feedback = AsyncMock( return_value="fb" )
    return { "__name__": "fake.role_module", "_dispatcher": d, "SESSION_ID": "sess-1", "SESSION_NAME": "name-1", "TARGET_USER": "u@x" }, d


def test_role_wrappers_have_the_four_names_the_module_exposes():
    ns, _ = _role_namespace()
    notify_progress, ask_confirmation, request_decision, get_feedback = mod.make_role_interface_functions( ns )
    assert [ f.__name__ for f in ( notify_progress, ask_confirmation, request_decision, get_feedback ) ] == [ "notify_progress", "ask_confirmation", "request_decision", "get_feedback" ]
    assert all( f.__module__ == "fake.role_module" for f in ( notify_progress, ask_confirmation, request_decision, get_feedback ) )


def test_role_notify_progress_pushes_session_identity_and_forwards_the_role():
    ns, d = _role_namespace()
    notify_progress = mod.make_role_interface_functions( ns )[ 0 ]
    _run( notify_progress( "hi", "coder", "low", job_id="j1", progress_group_id="pg-1" ) )
    assert ( d.session_id, d.session_name, d.target_user ) == ( "sess-1", "name-1", "u@x" )
    args, kwargs = d.notify_progress.await_args
    assert args == ( "hi", )
    assert kwargs[ "role" ] == "coder" and kwargs[ "priority" ] == "low" and kwargs[ "job_id" ] == "j1" and kwargs[ "progress_group_id" ] == "pg-1"


def test_role_ask_confirmation_keeps_the_positional_order_the_orchestrator_uses():
    ns, d = _role_namespace()
    ask_confirmation = mod.make_role_interface_functions( ns )[ 1 ]
    assert _run( ask_confirmation( "ok?", "tester", "yes", 30, "abs" ) ) is True
    args, kwargs = d.ask_confirmation.await_args
    assert args == ( "ok?", ) and kwargs == { "default": "yes", "timeout": 30, "abstract": "abs", "role": "tester" }
    assert ( d.session_id, d.target_user ) == ( "sess-1", "u@x" )
    assert not isinstance( d.session_name, str )          # only notify_progress copies the session name


def test_role_request_decision_awaits_present_choices_with_the_options():
    ns, d = _role_namespace()
    request_decision = mod.make_role_interface_functions( ns )[ 2 ]
    assert _run( request_decision( "q", [ { "x": 1 } ], "lead", 60, "abs" ) ) == { "answers": { "h": "v" } }
    args, kwargs = d.present_choices.await_args
    assert args == ( [ { "x": 1 } ], ) and kwargs == { "timeout": 60, "abstract": "abs", "role": "lead" }


def test_role_get_feedback_forwards_prompt_timeout_and_role():
    ns, d = _role_namespace()
    get_feedback = mod.make_role_interface_functions( ns )[ 3 ]
    assert _run( get_feedback( "prompt", "tester", 9 ) ) == "fb"
    args, kwargs = d.get_feedback.await_args
    assert args == ( "prompt", ) and kwargs == { "timeout": 9, "role": "tester" }


def test_role_wrappers_read_the_namespace_on_every_call():
    ns, d = _role_namespace()
    ask_confirmation = mod.make_role_interface_functions( ns )[ 1 ]
    ns[ "SESSION_ID" ] = "sess-2"
    _run( ask_confirmation( "again?" ) )
    assert d.session_id == "sess-2"
