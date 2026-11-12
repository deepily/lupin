"""
Tests for print_job_state_transition, the job state line both proxy responders print.

Each test pins one behaviour. Both responders are driven through handle_event so the line
is checked where a caller meets it.
"""

import asyncio

import pytest

from cosa.agents.utils.proxy_agents.base_responder import print_job_state_transition


EVENT = { "job_id": "j1", "from_state": "queued", "to_state": "running" }


def test_line_names_prefix_job_and_both_states_in_order( capsys ):
    print_job_state_transition( EVENT, "[Tag]" )
    assert capsys.readouterr().out == "[Tag] Job state: j1 queued -> running\n"


def test_arrow_is_the_caller_choice( capsys ):
    print_job_state_transition( EVENT, "[Tag]", arrow="→" )
    assert capsys.readouterr().out == "[Tag] Job state: j1 queued → running\n"


def test_states_are_not_swapped( capsys ):
    print_job_state_transition( { "job_id": "j", "from_state": "A", "to_state": "B" }, "[T]" )
    assert "A -> B" in capsys.readouterr().out


@pytest.mark.parametrize( "event, line", [
    ( {},                                          "[T] Job state: ? ? -> ?" ),
    ( { "job_id": "j" },                           "[T] Job state: j ? -> ?" ),
    ( { "from_state": "queued" },                  "[T] Job state: ? queued -> ?" ),
    ( { "to_state": "done" },                      "[T] Job state: ? ? -> done" ),
    ( { "from_queue": "todo", "to_queue": "run" }, "[T] Job state: ? ? -> ?" ),
] )
def test_each_missing_key_prints_a_question_mark( capsys, event, line ):
    print_job_state_transition( event, "[T]" )
    assert capsys.readouterr().out.strip() == line


def test_nothing_is_returned():
    assert print_job_state_transition( EVENT, "[T]" ) is None


def test_decision_responder_prints_it_with_its_own_tag_and_arrow( capsys ):
    from cosa.agents.decision_proxy.responder import DecisionResponder
    responder = DecisionResponder.__new__( DecisionResponder )
    responder.verbose = True
    responder.stats   = { "events_received": 0 }
    asyncio.run( responder.handle_event( "job_state_transition", EVENT ) )
    assert capsys.readouterr().out == f"{DecisionResponder.LOG_PREFIX} Job state: j1 queued -> running\n"


def test_notification_responder_prints_it_with_its_own_tag_and_arrow( capsys ):
    from cosa.agents.notification_proxy.responder import NotificationResponder
    responder = NotificationResponder.__new__( NotificationResponder )
    responder.verbose = True
    asyncio.run( responder.handle_event( "job_state_transition", EVENT ) )
    assert capsys.readouterr().out == "[Responder] Job state: j1 queued → running\n"


def test_both_responders_stay_silent_when_not_verbose( capsys ):
    from cosa.agents.decision_proxy.responder import DecisionResponder
    from cosa.agents.notification_proxy.responder import NotificationResponder
    d = DecisionResponder.__new__( DecisionResponder ); d.verbose = False; d.stats = { "events_received": 0 }
    n = NotificationResponder.__new__( NotificationResponder ); n.verbose = False
    asyncio.run( d.handle_event( "job_state_transition", EVENT ) )
    asyncio.run( n.handle_event( "job_state_transition", EVENT ) )
    assert capsys.readouterr().out == ""
