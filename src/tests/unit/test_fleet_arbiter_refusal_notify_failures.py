"""
Unit tests for the janitor refusal notice when its durable or live channel fails.

The gateway and live push are fakes. Each failure becomes an outcome value and a log line;
nothing is raised, so one bad channel cannot hide the other.
"""

from lupin_arbiter_app.fleet_arbiter_loop import ESCALATION_TOPIC, make_refusal_notify_fn


class _Gateway:
    """Records posts; raises when told to."""
    def __init__( self, error=None ):
        self.error, self.posts = error, []

    def post( self, topic, body ):
        if self.error is not None: raise self.error
        self.posts.append( ( topic, body ) )


def test_both_channels_succeed_and_the_abstract_rides_the_live_push():
    """Durable post carries message and abstract; the live push gets the abstract as detail."""
    gateway, live = _Gateway(), []
    notify = make_refusal_notify_fn( gateway, live_notify_fn=lambda m, abstract=None: live.append( ( m, abstract ) ) or { "channel": "live", "outcome": "queued" } )
    got = notify( "msg", "blockers" )
    assert gateway.posts == [ ( ESCALATION_TOPIC, "msg\n\nblockers" ) ]
    assert live == [ ( "msg", "blockers" ) ]
    assert got == [ { "channel": "durable", "outcome": "posted" }, { "channel": "live", "outcome": "queued" } ]


def test_a_durable_post_failure_is_an_outcome_and_a_log_line_and_the_live_push_still_runs():
    """The gateway raising gives post_error and a log line; the live channel still reports."""
    logs = []
    notify = make_refusal_notify_fn( _Gateway( RuntimeError( "x" * 300 ) ), live_notify_fn=lambda m, abstract=None: { "channel": "live", "outcome": "queued" },
                                     log_fn=lambda event, **kw: logs.append( ( event, kw ) ) )
    got = notify( "m", "a" )
    assert got[ 0 ][ "outcome" ] == "post_error" and got[ 0 ][ "detail" ] == "x" * 160
    assert got[ 1 ] == { "channel": "live", "outcome": "queued" }
    assert logs[ 0 ][ 0 ] == "worktree_refusal_post_error" and logs[ 0 ][ 1 ][ "error" ] == "x" * 300


def test_a_live_push_failure_is_an_http_error_outcome_and_a_log_line():
    """The live push raising gives http_error; the durable post is unaffected."""
    logs = []
    def boom( message, abstract=None ): raise ConnectionError( "down" )
    got = make_refusal_notify_fn( _Gateway(), live_notify_fn=boom, log_fn=lambda event, **kw: logs.append( event ) )( "m", "a" )
    assert got[ 0 ] == { "channel": "durable", "outcome": "posted" }
    assert got[ 1 ] == { "channel": "live", "outcome": "http_error", "detail": "down" }
    assert logs == [ "worktree_refusal_live_notify_error" ]


def test_without_a_live_push_the_live_channel_reads_disabled():
    """No live_notify_fn: the live outcome is disabled, and the durable post still happens."""
    gateway = _Gateway()
    got = make_refusal_notify_fn( gateway )( "m", "a" )
    assert got[ 1 ] == { "channel": "live", "outcome": "disabled" } and len( gateway.posts ) == 1
