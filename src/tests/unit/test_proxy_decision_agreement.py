"""
The trust gate's two agreements stay apart.

Success is the human answer agreeing with the forecast. Rule agreement is the human answer agreeing with what the row's
action implies. They are scored apart, and neither is folded into the other.
"""
import pytest

from cosa.agents.decision_proxy.agreement import forecast_agreement, rule_agreement


def test_a_human_approving_what_the_proxy_forecast_as_approved_is_a_success():
    assert forecast_agreement( "approved", True ) is True


def test_a_human_declining_what_the_proxy_forecast_as_approved_is_not_a_success():
    assert forecast_agreement( "approved", False ) is False


def test_a_human_declining_when_the_proxy_forecast_nothing_agrees_as_the_orchestrator_has_always_scored_it():
    assert forecast_agreement( None, False ) is True
    assert forecast_agreement( "review", False ) is True


def test_a_human_approving_when_the_forecast_was_not_approved_is_not_a_success():
    assert forecast_agreement( None, True ) is False
    assert forecast_agreement( "review", True ) is False


@pytest.mark.parametrize( "action", [ "act", "suggest" ] )
def test_an_action_that_implies_approval_agrees_with_an_approving_human_and_not_with_a_declining_one( action ):
    assert rule_agreement( action, True ) is True
    assert rule_agreement( action, False ) is False


@pytest.mark.parametrize( "action", [ "shadow", "defer" ] )
def test_a_shadow_or_defer_row_has_no_rule_verdict_whatever_the_human_said( action ):
    assert rule_agreement( action, True ) is None
    assert rule_agreement( action, False ) is None


@pytest.mark.parametrize( "action", [ "act", "suggest", "shadow", "defer" ] )
def test_a_row_nobody_answered_has_no_rule_verdict( action ):
    assert rule_agreement( action, None ) is None


def test_rule_agreement_and_success_can_differ_on_one_row():
    # An act row whose forecast was not "approved": the human approved. Success is False, rule agreement is True.
    assert forecast_agreement( None, True ) is False
    assert rule_agreement( "act", True ) is True
