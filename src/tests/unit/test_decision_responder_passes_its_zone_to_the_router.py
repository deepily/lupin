"""
Unit test: the decision responder hands the zone it was given to its smart router.

Production builds the responder with the configured zone, so a responder that dropped the argument
would still answer correctly there. This test gives it a zone that differs from the configured one.
"""
from cosa.agents.decision_proxy.responder import DecisionResponder


def test_the_responder_passes_the_zone_it_was_given_to_the_smart_router( monkeypatch ):
    monkeypatch.setattr( "cosa.agents.decision_proxy.smart_router.read_decision_proxy_timezone", lambda: "Asia/Tokyo" )

    responder = DecisionResponder( timezone="Pacific/Auckland" )

    assert responder.smart_router.timezone == "Pacific/Auckland"
