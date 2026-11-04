"""
Unit tests for build_notify_kwargs, the argument builder behind the proxy notifiers.

Twin refactor slice proxy-voice-io: the decision and notification proxies each carried a copy.
"""

from cosa.agents.utils.sync_notify import build_notify_kwargs


def test_required_keys_only_when_options_are_none():
    assert build_notify_kwargs( "hi", "proxy@x" ) == {
        "message": "hi", "sender_id": "proxy@x", "priority": "low", "debug": False }


def test_every_option_is_forwarded_when_given():
    assert build_notify_kwargs( "hi", "s", "high", "h.example", 7999, "u@x", True ) == {
        "message": "hi", "sender_id": "s", "priority": "high", "debug": True,
        "host": "h.example", "port": 7999, "target_user": "u@x" }


def test_a_falsy_but_not_none_value_is_still_forwarded():
    """Port 0 and an empty host are not None, so they pass through as the old code did."""
    kw = build_notify_kwargs( "hi", "s", host = "", port = 0 )
    assert kw[ "host" ] == "" and kw[ "port" ] == 0
