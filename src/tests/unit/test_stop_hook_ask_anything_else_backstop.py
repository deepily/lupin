"""
Fixture suite for stop.py::_ask_anything_else's exception backstop — row e3dd1df2.

WHAT WAS RULED AND WHY THESE CASES. The handler's comment used to say it caught "server
down, network error, import error". Two of those three are false, and the false sentence
is what led a reviewer to price a fix at "work at every raise site". Rick's ruling: keep
the one announcement, narrow the catch, fix the comment, and put the session and the hook
phase INTO the card.

The load-bearing cases are the two halves of that:

  · A DEAD SERVER MUST PRODUCE NO CARD. notify_user_sync is total — it returns a
    NotificationResponse rather than raising — so an outage falls out of the ordinary
    "no" path. A test that asserts a card on a dead server would be encoding the bug
    the comment described.
  · A DEFECT MUST PRODUCE A CARD THAT NAMES THE PHASE. A bare exception string is what
    made 212 cards unactionable; the phase and the session id are the fix.

`send_tts` is monkeypatched in every case — a test's simulated failure must never reach
the live transport (the leak ebb2c061 closed at src/conftest.py:225).
"""

import pytest

from lupin_cli.claude_code.hooks import stop


class _Response:
    """Stand-in for NotificationResponse — only the fields the handler reads."""
    def __init__( self, response_value=None, exit_code=1, status="connection_error" ):
        self.response_value = response_value
        self.exit_code      = exit_code
        self.status         = status


@pytest.fixture
def cards( monkeypatch ):
    """Capture every send_tts call instead of letting one reach the transport."""
    sent = [ ]
    monkeypatch.setattr( stop, "send_tts",
                         lambda message, **kwargs: sent.append( { "message": message, **kwargs } ) )
    monkeypatch.setattr( stop, "log_to_stream", lambda *a, **k: None )
    monkeypatch.setattr( stop, "build_sender_id_for_cc", lambda sid=None: "claude.code@lupin.deepily.ai#abc12345" )
    monkeypatch.setattr( stop, "_summarize_task", lambda msg: "did the thing" )
    monkeypatch.setattr( stop, "_get_session_context", lambda cwd: ( "a topic", "a-branch" ) )
    return sent


# ── the half that must stay SILENT ────────────────────────────────────────────────

def test_a_dead_server_produces_no_card( cards, monkeypatch ):
    """THE load-bearing negative. notify_user_sync is total: on a dead :7999 it RETURNS
    response_value=None. That must fall out of the ordinary allow-stop path with no
    announcement — the handler's old comment claimed the opposite."""
    monkeypatch.setattr( stop, "notify_user_sync", lambda request: _Response() )

    result = stop._ask_anything_else( "abc12345-full", "I fixed the bug", cwd=None )

    assert result == { }        # allow stop
    assert cards == [ ]         # and say nothing


def test_a_plain_no_produces_no_card( cards, monkeypatch ):
    monkeypatch.setattr( stop, "notify_user_sync",
                         lambda request: _Response( "no", exit_code=0, status="responded" ) )

    assert stop._ask_anything_else( "abc12345-full", "work", cwd=None ) == { }
    assert cards == [ ]


def test_a_timeout_produces_no_card( cards, monkeypatch ):
    monkeypatch.setattr( stop, "notify_user_sync",
                         lambda request: _Response( None, exit_code=2, status="request_timeout" ) )

    assert stop._ask_anything_else( "abc12345-full", "work", cwd=None ) == { }
    assert cards == [ ]


# ── the half that must SPEAK, and name where it broke ─────────────────────────────

def test_a_defect_produces_one_card_naming_the_phase_and_session( cards, monkeypatch ):
    def boom( request ): raise AttributeError( "response object has no attribute" )
    monkeypatch.setattr( stop, "notify_user_sync", boom )

    result = stop._ask_anything_else( "abc12345-full", "I fixed the bug", cwd=None )

    assert result == { }                     # still allows the stop — never blocks
    assert len( cards ) == 1
    message = cards[ 0 ][ "message" ]
    assert "notify_sync" in message          # the PHASE
    assert "abc12345"    in message          # the SESSION
    assert "AttributeError" in message       # the TYPE, not just the string
    assert cards[ 0 ][ "sender_id" ] == "claude.code@lupin.deepily.ai#abc12345"


@pytest.mark.parametrize( "target,expected_phase", [
    ( "build_sender_id_for_cc", "build_sender_id" ),
    ( "_summarize_task",        "summarize_task" ),
    ( "_get_session_context",   "session_context" ),
    ( "notify_user_sync",       "notify_sync" ),
] )
def test_each_step_reports_its_own_phase( cards, monkeypatch, target, expected_phase ):
    """A card that cannot say WHICH step broke is the unactionable card this fix exists
    to replace. Every phase boundary gets a case so a future reorder cannot silently
    collapse two steps into one label."""
    def boom( *args, **kwargs ): raise RuntimeError( "kaboom" )
    monkeypatch.setattr( stop, target, boom )
    monkeypatch.setattr( stop, "notify_user_sync",
                         boom if target == "notify_user_sync" else ( lambda request: _Response( "no", 0, "responded" ) ) )

    stop._ask_anything_else( "abc12345-full", "work", cwd="/tmp" )

    assert len( cards ) == 1
    assert expected_phase in cards[ 0 ][ "message" ]


def test_a_throw_in_the_first_step_does_not_make_the_backstop_itself_raise( cards, monkeypatch ):
    """sender_id is bound BEFORE the try for exactly this case — a backstop that raises
    NameError while reporting someone else's failure is no backstop."""
    def boom( sid=None ): raise ImportError( "session_bridge gone" )
    monkeypatch.setattr( stop, "build_sender_id_for_cc", boom )

    result = stop._ask_anything_else( "abc12345-full", "work", cwd=None )

    assert result == { }
    assert cards[ 0 ][ "sender_id" ] is None
    assert "build_sender_id" in cards[ 0 ][ "message" ]


def test_a_missing_session_id_still_renders_a_card( cards, monkeypatch ):
    """`(session_id or "")[:8]` — a None session must not turn the announcement into a
    second exception inside the handler."""
    def boom( request ): raise ValueError( "bad request" )
    monkeypatch.setattr( stop, "notify_user_sync", boom )

    assert stop._ask_anything_else( None, "work", cwd=None ) == { }
    assert len( cards ) == 1
    assert "ValueError" in cards[ 0 ][ "message" ]


def test_the_defect_is_also_written_to_the_hook_event_stream( monkeypatch ):
    """The card is for the human; the stream line is for whoever debugs it later. Both,
    not either — a card nobody kept is the state this row started in."""
    logged = [ ]
    monkeypatch.setattr( stop, "send_tts", lambda *a, **k: None )
    monkeypatch.setattr( stop, "log_to_stream",
                         lambda hook, payload, extra=None: logged.append( extra ) )
    monkeypatch.setattr( stop, "build_sender_id_for_cc", lambda sid=None: "claude.code@lupin.deepily.ai#abc12345" )
    monkeypatch.setattr( stop, "_summarize_task", lambda msg: None )
    monkeypatch.setattr( stop, "_get_session_context", lambda cwd: ( None, None ) )
    def boom( request ): raise TypeError( "nope" )
    monkeypatch.setattr( stop, "notify_user_sync", boom )

    stop._ask_anything_else( "abc12345-full", "work", cwd=None )

    entry = logged[ -1 ]
    assert entry[ "phase" ]      == "ask_anything_else_error"
    assert entry[ "failed_at" ]  == "notify_sync"
    assert entry[ "error_type" ] == "TypeError"
    assert entry[ "session_id" ] == "abc12345"


# ── the success paths must be untouched by the phase tracking ─────────────────────

def test_a_yes_still_blocks_the_stop( cards, monkeypatch ):
    monkeypatch.setattr( stop, "notify_user_sync",
                         lambda request: _Response( "yes", 0, "responded" ) )

    result = stop._ask_anything_else( "abc12345-full", "work", cwd=None )

    assert result != { }
    assert cards == [ ]


def test_a_qualifier_still_injects_and_blocks( cards, monkeypatch ):
    injected = [ ]
    monkeypatch.setattr( stop, "inject_qualifier_via_tmux",
                         lambda sid, text: injected.append( text ) )
    monkeypatch.setattr( stop, "notify_user_sync",
                         lambda request: _Response( "no [comment: keep going]", 0, "responded" ) )

    result = stop._ask_anything_else( "abc12345-full", "work", cwd=None )

    assert result != { }
    assert injected == [ "keep going" ]
    assert cards == [ ]
