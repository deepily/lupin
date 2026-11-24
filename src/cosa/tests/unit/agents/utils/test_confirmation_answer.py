"""
Unit tests for ask_confirmation_answer, which keeps the whole answer.

The notification boundary is patched, so nothing leaves the process and nothing is spent.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import cosa.agents.utils.agent_notification_dispatcher as mod
import cosa.rest.task_promotion_gate as gate
from cosa.agents.utils.agent_notification_dispatcher import AgentNotificationDispatcher, ConfirmationAnswer
from cosa.agents.test_fix_expediter.state import VoiceGateTimeoutError


STAMP = { "user_id": "u-1", "account_email": "rick@example.com", "method": "jwt" }


@pytest.fixture( autouse=True )
def _the_operators_login_maps_to_rick():
    """Map the stamp's account to the persona the gate treats as the operator."""
    real = gate.approver_persona_for_account
    with patch.object( gate, "approver_persona_for_account", side_effect=lambda email: "rick" if email == "rick@example.com" else real( email ) ):
        yield


NOBODY = object()


def _resp( exit_code=0, response_value=None, default_used=False, answered_by=NOBODY ):
    r = MagicMock()
    r.exit_code      = exit_code
    r.response_value = response_value
    r.status         = "ok"
    r.notification_id = "n-1"
    r.default_used   = default_used
    r.answered_by    = STAMP if answered_by is NOBODY else answered_by
    return r


def _run( coro ):
    return asyncio.run( coro )


# The four answer shapes, then the edge shapes. The bool column is written as literals: it is what
# ask_confirmation returned before this change, `raw.lower().strip().startswith( "yes" )`.
SHAPES = [
    ( "yes",                          "yes",     None,       True  ),
    ( "no",                           "no",      None,       False ),
    ( "neither",                      "neither", None,       False ),
    ( "yes [comment: fix the tests]", "yes",     "fix the tests", True ),
    ( "no [comment: not ready]",      "no",      "not ready",     False ),
    ( "neither [comment: re-frame]",  "neither", "re-frame",      False ),
    ( "  YES  ",                      "yes",     None,       True  ),
    ( "Yes, proceed",                 None,      None,       True  ),
    ( "yesterday",                    None,      None,       True  ),
    ( "Maybe later",                  None,      None,       False ),
]


@pytest.mark.parametrize( "raw, stance, comment, approved", SHAPES )
def test_answer_carries_stance_comment_and_raw_text( raw, stance, comment, approved ):
    d = AgentNotificationDispatcher( agent_type="test.agent" )
    with patch.object( mod, "_notify_user_sync", return_value=_resp( 0, raw ) ):
        answer = _run( d.ask_confirmation_answer( "Proceed?" ) )
    assert answer == ConfirmationAnswer( stance=stance, comment=comment, raw=raw, source="human", answered_by=STAMP )
    assert answer.approved is approved


@pytest.mark.parametrize( "raw, stance, comment, approved", SHAPES )
def test_bool_wrapper_returns_exactly_todays_value_for_every_shape( raw, stance, comment, approved ):
    d = AgentNotificationDispatcher( agent_type="test.agent" )
    with patch.object( mod, "_notify_user_sync", return_value=_resp( 0, raw ) ):
        assert _run( d.ask_confirmation( "Proceed?" ) ) is approved


def test_answer_records_the_carrying_notification_id():
    d = AgentNotificationDispatcher( agent_type="test.agent" )

    async def go():
        with patch.object( mod, "_notify_user_sync", return_value=_resp( 0, "no" ) ):
            await d.ask_confirmation_answer( "Proceed?" )
        return mod.take_last_ask_notification_id()

    assert _run( go() ) == "n-1"


def test_answer_with_no_response_raises_the_same_timeout_as_the_bool_wrapper():
    d = AgentNotificationDispatcher( agent_type="test.agent" )
    with patch.object( mod, "_notify_user_sync", return_value=_resp( 2, None ) ):
        with pytest.raises( VoiceGateTimeoutError ):
            _run( d.ask_confirmation_answer( "Proceed?" ) )
        with pytest.raises( VoiceGateTimeoutError ):
            _run( d.ask_confirmation( "Proceed?" ) )


def test_role_wrapper_forwards_to_the_dispatcher_sibling_with_the_role():
    d = MagicMock()
    d.ask_confirmation_answer = AsyncMock( return_value=ConfirmationAnswer( "neither", None, "neither" ) )
    ns = { "__name__": "fake.role_module", "_dispatcher": d, "SESSION_ID": "s", "SESSION_NAME": "n", "TARGET_USER": "u@x" }
    wrapper = mod.make_role_interface_functions( ns )[ 4 ]
    assert wrapper.__name__ == "ask_confirmation_answer"
    assert _run( wrapper( "ok?", "tester", "yes", 30, "abs" ) ) == ConfirmationAnswer( "neither", None, "neither" )
    args, kwargs = d.ask_confirmation_answer.await_args
    assert args == ( "ok?", ) and kwargs == { "default": "yes", "timeout": 30, "abstract": "abs", "role": "tester" }
    assert ( d.session_id, d.target_user ) == ( "s", "u@x" )


def _answer_to( response ):
    d = AgentNotificationDispatcher( agent_type="test.agent" )
    with patch.object( mod, "_notify_user_sync", return_value=response ):
        return _run( d.ask_confirmation_answer( "Proceed?" ) )


def test_an_answer_stamped_by_the_server_is_a_human_one():
    assert _answer_to( _resp( 0, "no" ) ).source == "human"


def test_a_default_the_server_applied_is_a_default_even_though_the_exit_code_is_zero():
    # The offline path: exit 0, status "offline", default_used True, nobody stamped.
    answer = _answer_to( _resp( 0, "no", default_used=True, answered_by=None ) )
    assert ( answer.source, answer.answered_by, answer.raw ) == ( "default", None, "no" )


def test_a_default_stays_a_default_even_if_a_stamp_is_present():
    assert _answer_to( _resp( 0, "no", default_used=True ) ).source == "default"


def test_an_answer_nobody_stamped_is_unattributed_not_human():
    # A test double, or a server that predates the stamp, looks like this.
    assert _answer_to( _resp( 0, "yes", answered_by=None ) ).source == "unattributed"


STAMPS = [
    ( STAMP,                                                                  "human" ),
    ( { "user_id": "u-2", "account_email": "rick@example.com", "method": "api_key" }, "not_operator" ),
    ( { "user_id": "u-2", "method": "api_key" },                               "not_operator" ),
    ( { "user_id": "u-3", "account_email": "someone@example.com", "method": "jwt" },  "not_operator" ),
    ( { "user_id": "u-3", "method": "jwt" },                                   "not_operator" ),
    ( { "user_id": "u-3", "account_email": "rick@example.com" },               "not_operator" ),
]


@pytest.mark.parametrize( "stamp, source", STAMPS )
def test_the_source_of_a_stamped_answer_is_decided_by_the_promotion_gates_own_predicate( stamp, source ):
    answer = _answer_to( _resp( 0, "yes", answered_by=stamp ) )
    assert answer.source == source
    assert ( answer.source == "human" ) is gate.answer_posted_by_the_operator( stamp )


def test_the_answer_source_follows_the_gate_if_the_gate_changes_its_mind():
    # If the source restated the rule instead of asking the gate, this would stay "human".
    with patch.object( mod, "answer_posted_by_the_operator", return_value=False ) as asked:
        assert _answer_to( _resp( 0, "yes" ) ).source == "not_operator"
    asked.assert_called_once_with( STAMP )
    with patch.object( mod, "answer_posted_by_the_operator", return_value=True ):
        assert _answer_to( _resp( 0, "yes", answered_by={ "method": "api_key" } ) ).source == "human"


# Row 1b3202de (F9): the open-ended and multiple-choice asks carry who answered, beside their return values.
# The slot is per task, so each test asks and reads inside one coroutine, as the orchestrator does.
MC_ANSWER = '{"answers": {"Plan": "Keep"}}'
MC_QUESTIONS = [ { "question": "Plan?", "header": "Plan", "options": [ { "label": "Keep" }, { "label": "Drop" } ] } ]


async def _ask_then_take( d, ask ):
    args = ( "Why?", ) if ask == "get_feedback" else ( MC_QUESTIONS, )
    before = mod.take_last_ask_answer_source()
    await getattr( d, ask )( *args )
    return before, mod.take_last_ask_answer_source(), mod.take_last_ask_answer_source()


@pytest.mark.parametrize( "kwargs, label", [
    ( { },                                                  "human" ),
    ( { "answered_by": { "method": "api_key", "user_id": "u-2" } }, "not_operator" ),
    ( { "answered_by": None },                              "unattributed" ),
    ( { "default_used": True },                             "default" ),
] )
@pytest.mark.parametrize( "ask", [ "get_feedback", "present_choices" ] )
def test_an_open_ended_or_multiple_choice_answer_carries_who_gave_it( ask, kwargs, label ):
    d    = AgentNotificationDispatcher( agent_type="test.agent" )
    text = "free text" if ask == "get_feedback" else MC_ANSWER
    with patch.object( mod, "_notify_user_sync", return_value=_resp( 0, text, **kwargs ) ):
        before, taken, again = _run( _ask_then_take( d, ask ) )
    assert ( before, taken, again ) == ( None, label, None )          # nothing before, the label once, then forgotten


@pytest.mark.parametrize( "ask", [ "get_feedback", "present_choices" ] )
def test_an_ask_that_raises_before_an_answer_leaves_no_source_behind( ask ):
    d = AgentNotificationDispatcher( agent_type="test.agent" )

    async def scenario():
        mod._last_ask_answer_source.set( "human" )                # a stale value from an earlier ask in this task
        with pytest.raises( VoiceGateTimeoutError ):
            await getattr( d, ask )( *( ( "Why?", ) if ask == "get_feedback" else ( MC_QUESTIONS, ) ) )
        return mod.take_last_ask_answer_source()

    with patch.object( mod, "_notify_user_sync", side_effect=ConnectionError( "down" ) ):
        assert _run( scenario() ) is None


@pytest.mark.parametrize( "ask, response", [
    ( "get_feedback",    dict( exit_code=2, response_value=None ) ),
    ( "get_feedback",    dict( exit_code=1, response_value=None ) ),
    ( "present_choices", dict( exit_code=2, response_value=None ) ),
    ( "present_choices", dict( exit_code=0, response_value='{"answers": {}}' ) ),
] )
def test_a_timeout_or_empty_answer_raises_and_leaves_no_label( ask, response ):
    d = AgentNotificationDispatcher( agent_type="test.agent" )

    async def scenario():
        with pytest.raises( VoiceGateTimeoutError ):
            await getattr( d, ask )( *( ( "Why?", ) if ask == "get_feedback" else ( MC_QUESTIONS, ) ) )
        return mod.take_last_ask_answer_source()

    with patch.object( mod, "_notify_user_sync", return_value=_resp( **response ) ):
        assert _run( scenario() ) is None
