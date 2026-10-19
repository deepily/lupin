"""
Unit tests for the statistics table the proxy responders print.

Twin refactor slice proxy-responder-base: the decision and notification responders each carried
a copy of the base responder's print_stats; they now differ only in the title.
"""

import pytest

from cosa.agents.utils.proxy_agents.base_responder import BaseResponder, print_stats_table
from cosa.agents.decision_proxy.responder import DecisionResponder
from cosa.agents.notification_proxy.responder import NotificationResponder

STATS = { "events_received": 3, "dry_run_hits": 0 }
RULE  = "=" * 50


def _expected( title ):
    return (
        f"\n{RULE}\n{title}\n{RULE}\n"
        f"  {'Events Received':30s} : 3\n"
        f"  {'Dry Run Hits':30s} : 0\n"
        f"{RULE}\n"
    )


def _bare( cls ):
    """An instance without running __init__, so the test needs no server, config or strategies."""
    r       = object.__new__( cls )
    r.stats = dict( STATS )
    return r


@pytest.mark.parametrize( "cls, title", [
    ( DecisionResponder,     "Decision Proxy Statistics" ),
    ( NotificationResponder, "Notification Proxy Statistics" ),
] )
def test_each_responder_prints_its_own_title_and_the_same_table( cls, title, capsys ):
    _bare( cls ).print_stats()
    assert capsys.readouterr().out == _expected( title )


class _Sub( BaseResponder ):
    async def handle_event( self, event_type, event_data ): pass


class TestBaseResponderStats:

    def test_default_title_is_the_generic_one( self, capsys ):
        r       = object.__new__( _Sub )
        r.stats = dict( STATS )
        r.print_stats()
        assert capsys.readouterr().out == _expected( "Proxy Agent Statistics" )

    def test_a_subclass_changes_only_the_title( self, capsys ):
        class _Titled( _Sub ):
            STATS_TITLE = "Custom Title"
        r       = object.__new__( _Titled )
        r.stats = dict( STATS )
        r.print_stats()
        assert capsys.readouterr().out == _expected( "Custom Title" )

    def test_an_empty_table_prints_only_the_frame( self, capsys ):
        print_stats_table( "T", {} )
        assert capsys.readouterr().out == f"\n{RULE}\nT\n{RULE}\n{RULE}\n"
