"""
A hook's stdout is its RETURN CHANNEL, not a log (row 298af249).

`ConfigurationManager.__init__` prints a banner and a section table to stdout
(configuration_manager.py:164). In a terminal that is useful; inside a hook it is
prepended to the only channel the harness reads an answer from. The harness
truncates a large payload to a ~2 KB preview and writes the rest to a file
nothing reads.

MEASURED across 505 saved payloads in this project: that noise averaged 1,660
bytes and filled the entire preview BY ITSELF in 391 of them — so in 77% of
truncated turns the reader's whole budget was spent on our own banner before the
peer DM had started. End-to-end two-arm control on the live hook: fix off →
2,997 bytes led by the banner; fix on → 791 bytes starting at `{`.

🔴 THE PAYLOAD-POSITION TEST IS THE ONE THAT MATTERS. Cleanliness is not the
property under test — POSITION is. The harness keeps a LEADING preview, so
anything ahead of the JSON is what gets kept instead of the JSON.
"""

import io
import sys

import pytest

from lupin_cli.claude_code.hooks.lib import hook_common


# ── quiet_stdout ─────────────────────────────────────────────────────────────

def test_stdout_written_during_the_call_is_discarded( capsys ):
    hook_common.quiet_stdout( lambda: print( "banner noise" ) )
    assert capsys.readouterr().out == ""


def test_the_return_value_is_passed_through_untouched():
    assert hook_common.quiet_stdout( lambda: 1234 ) == 1234


def test_arguments_reach_the_callable():
    assert hook_common.quiet_stdout( lambda a, b=0: a + b, 40, b=2 ) == 42


def test_stderr_is_NOT_suppressed( capsys ):
    """
    Only stdout is the return channel. Silencing stderr too would hide real
    diagnostics to fix a formatting problem.
    """
    hook_common.quiet_stdout( lambda: print( "a real problem", file=sys.stderr ) )
    assert "a real problem" in capsys.readouterr().err


def test_an_exception_PROPAGATES_rather_than_being_swallowed():
    """
    A config failure must not be converted into a quiet hook. This helper hides
    output, never errors.
    """
    def _boom():
        raise RuntimeError( "config is broken" )

    with pytest.raises( RuntimeError, match="config is broken" ):
        hook_common.quiet_stdout( _boom )


def test_stdout_is_restored_after_a_RAISING_call( capsys ):
    """
    The load-bearing failure arm. If a raising call left sys.stdout pointed at
    the discard buffer, every later emit_json would vanish — a far worse defect
    than the banner this fixes.
    """
    with pytest.raises( ValueError ):
        hook_common.quiet_stdout( lambda: ( _ for _ in () ).throw( ValueError( "x" ) ) )

    print( "this must still reach stdout" )
    assert "this must still reach stdout" in capsys.readouterr().out


def test_nothing_outside_the_call_is_suppressed( capsys ):
    print( "before" )
    hook_common.quiet_stdout( lambda: print( "swallowed" ) )
    print( "after" )
    out = capsys.readouterr().out
    assert "before" in out and "after" in out and "swallowed" not in out


# ── the reminder body, which is where the banner actually came from ──────────

def test_building_the_speakerphone_rider_prints_NOTHING_to_stdout( capsys ):
    """
    The regression control for the shipped defect. `_speakerphone_reminder_body`
    calls get_spoken_char_cap(), which builds a ConfigurationManager and printed
    its banner straight onto the hook's return channel on EVERY turn.

    A stack trace, not a guess, put the print here: an earlier fix wrapped the
    hook's IMPORTS instead and changed nothing (2,997 bytes either way), because
    the config is built during main().
    """
    body = hook_common._speakerphone_reminder_body( "typed" )
    assert capsys.readouterr().out == ""
    assert "[turn-state]" in body


def test_the_rider_still_reports_the_configured_word_budget():
    """
    Silencing the call must not silence its ANSWER. A rider quoting a budget of
    None would be a quiet hook delivering a broken contract.
    """
    body = hook_common._speakerphone_reminder_body( "typed" )
    assert "words" in body
    assert "None" not in body
