"""
Four git guard regexes take time in proportion to the command and find what they did.

Each of them took four times as long for twice as many blank lines. The fix is one
lookahead, `_NOT_A_BLANK_LINE`, after the command start. Three things are held here:

  1. each regex is linear on runs of whitespace;
  2. each regex finds the same commands as the same regex with the lookahead taken out;
  3. the whole PreToolUse hook is linear on a command of 4000 blank lines.
"""

import re
import signal
import time
from unittest.mock import patch

import pytest

from lupin_cli.claude_code.hooks import pre_tool_use as ptu
from lupin_cli.claude_code.hooks.lib import branch_lock_guard, commit_scope_guard, merge_head_guard, stash_guard

LOOKAHEAD = stash_guard._NOT_A_BLANK_LINE

REGEXES = {
    "stash_guard._GIT_STASH_RE"         : stash_guard._GIT_STASH_RE,
    "commit_scope_guard._GIT_COMMIT_RE" : commit_scope_guard._GIT_COMMIT_RE,
    "branch_lock_guard._GIT_CONFIG_RE"  : branch_lock_guard._GIT_CONFIG_RE,
    "merge_head_guard._CD_RE"           : merge_head_guard._CD_RE,
}

WHITESPACE_SHAPES = {
    "newlines"         : lambda size: "\n" * size,
    "letter+newlines"  : lambda size: "x" + "\n" * size,
    "mixed"            : lambda size: " \n\t" * ( size // 3 ),
    "crlf"             : lambda size: "\r\n" * ( size // 2 ),
    "spaces"           : lambda size: " " * size,
    "newlines then git": lambda size: "\n" * size + "git status",
    "indented blanks"  : lambda size: "    \n" * ( size // 5 ),
}


class _Expired( BaseException ):
    """Raised by the alarm, so a regex that will not finish fails the test instead of hanging it."""


def _seconds( call, seconds=20 ):
    """
    Time one call, with an alarm.

    Ensures:
        - returns the wall time of call() in seconds
        - raises _Expired when call() runs longer than `seconds`
    """
    def expired( *args ):
        raise _Expired( f"did not finish within {seconds} s" )
    previous = signal.signal( signal.SIGALRM, expired )
    try:
        signal.alarm( seconds )
        started = time.perf_counter()
        call()
        return time.perf_counter() - started
    finally:
        signal.alarm( 0 )
        signal.signal( signal.SIGALRM, previous )


def test_the_four_regexes_are_the_ones_that_carry_the_lookahead():
    """The list is the whole population: every regex in the four guards that has the lookahead."""
    carriers = set()
    for module in ( stash_guard, commit_scope_guard, branch_lock_guard, merge_head_guard ):
        for name, value in vars( module ).items():
            if isinstance( value, re.Pattern ) and LOOKAHEAD in value.pattern:
                carriers.add( f"{module.__name__.rsplit( '.', 1 )[ 1 ]}.{name}" )
    assert carriers == set( REGEXES )
    assert commit_scope_guard._NOT_A_BLANK_LINE == LOOKAHEAD


@pytest.mark.parametrize( "shape", sorted( WHITESPACE_SHAPES ) )
@pytest.mark.parametrize( "name", sorted( REGEXES ) )
def test_each_regex_is_linear_on_a_whitespace_run( name, shape ):
    """
    Four times the input must cost about four times as much, not sixteen.

    A quadratic regex reads 16 here and a linear one reads 4. The bound is 9, so a loaded
    box does not fail a linear regex and a quadratic one never passes.
    """
    regex = REGEXES[ name ]
    build = WHITESPACE_SHAPES[ shape ]
    small = min( _seconds( lambda: list( regex.finditer( build( 8000 ) ) ) ) for _ in range( 3 ) )
    large = _seconds( lambda: list( regex.finditer( build( 32000 ) ) ) )
    assert large / max( small, 0.002 ) < 9, f"{name} on {shape}: {small * 1000:.1f} ms -> {large * 1000:.1f} ms for 4x"


@pytest.mark.parametrize( "name", sorted( REGEXES ) )
def test_control_the_same_regex_without_the_lookahead_is_quadratic( name ):
    """The linear test can see the defect: without the lookahead the ratio is over the bound."""
    regex = _without_lookahead( REGEXES[ name ] )
    small = min( _seconds( lambda: list( regex.finditer( "\n" * 1000 ) ) ) for _ in range( 3 ) )
    large = _seconds( lambda: list( regex.finditer( "\n" * 4000 ) ) )
    assert large / small > 9, f"{name}: {small * 1000:.2f} ms -> {large * 1000:.2f} ms for 4x"


# ---------------------------------------------------------------------------
# The same commands are found, with and without the lookahead
# ---------------------------------------------------------------------------

def _without_lookahead( regex ):
    """The regex as it was before the fix: the one lookahead removed, same flags."""
    assert regex.pattern.count( LOOKAHEAD ) == 1, regex.pattern
    return re.compile( regex.pattern.replace( LOOKAHEAD, "" ), regex.flags )


def _found( regex, text ):
    """
    What a regex found in a text, in a form that ignores where a blank-line run was entered.

    Ensures:
        - one tuple per match: where it ends, then each named group
        - leading whitespace is stripped from the "prefix" group, the one group that starts
          at the command start and so begins later when the match starts at a later newline
    """
    rows = [ ]
    for match in regex.finditer( text ):
        groups = { key: value for key, value in match.groupdict().items() }
        if groups.get( "prefix" ) is not None: groups[ "prefix" ] = groups[ "prefix" ].lstrip()
        rows.append( ( match.end(), tuple( sorted( groups.items() ) ) ) )
    return rows


_LEADS = ( "", " ", "\n", "\n\n", "\n \n", " \n\t\n ", "\r\n\r\n", "\n\n\n\n\n", ";", ";\n\n", "&&\n \n", "(\n\n", "then\n\n", "do \n\n ", "x\n\n" )
_PREFIXES = ( "", "FOO=1 ", "FOO= ", "FOO=1\n", "FOO=1\n\n", "env ", "sudo env A=b ", "LUPIN_ALLOW_GIT_STASH=1 ", "LUPIN_ALLOW_GIT_STASH=1\n\n" )
_COMMANDS = (
    "git stash", "git stash pop", "git\nstash", "git \n\n stash list", "git -C /tmp stash push -m x",
    "git commit -m x", "git commit", "git\n\ncommit -F f -- a b", "git -c a=b commit --amend", "/usr/bin/git commit -m x",
    "git config core.hooksPath /tmp", "git\n config --global user.name x", "git -C x config a.b c",
    "cd /tmp", "cd\n/tmp", "cd  src && git commit -m x", "cd a\n\n\ncd b\ngit commit",
    "echo git stash", "gitx stash", "git stashed", "git commits", "ls", "", "\n", "git status\n\n\ngit stash drop",
)
_TAILS = ( "", "\n", "\n\n\n", " ; ls", "\n\ngit stash\n\n", " \n \n" )


def _corpus():
    return [ lead + prefix + command + tail for lead in _LEADS for prefix in _PREFIXES for command in _COMMANDS for tail in _TAILS ]


@pytest.mark.parametrize( "name", sorted( REGEXES ) )
def test_each_regex_finds_what_it_found_without_the_lookahead( name ):
    regex   = REGEXES[ name ]
    before  = _without_lookahead( regex )
    corpus  = _corpus()
    matched = 0
    for text in corpus:
        expected = _found( before, text )
        assert _found( regex, text ) == expected, repr( text )
        matched += bool( expected )
    # The comparison is not over nothing: this regex matches in many texts and misses in many.
    assert len( corpus ) == len( _LEADS ) * len( _PREFIXES ) * len( _COMMANDS ) * len( _TAILS )
    assert matched > 100, matched
    assert len( corpus ) - matched > 100, len( corpus ) - matched


def test_a_match_that_enters_a_blank_run_starts_at_its_last_newline():
    """The one thing that moves: the start. The command found, and its end, do not."""
    text   = ";\n\n\n  git stash pop"
    regex  = stash_guard._GIT_STASH_RE
    before = _without_lookahead( regex )
    assert before.search( text ).start() == 0
    assert regex.search( text ).start() == 3
    assert regex.search( text ).end() == before.search( text ).end() == len( text )


def test_the_guards_decide_the_same_on_commands_that_cross_blank_lines():
    """The decision functions too: a blank-line run hides nothing and adds nothing."""
    for lead in ( "", "\n\n\n", ";\n \n", "echo hi\n\n\n" ):
        assert stash_guard.stash_deny_reason( "Bash", { "command": lead + "git stash pop" }, env={ } ) is not None, repr( lead )
        assert stash_guard.stash_deny_reason( "Bash", { "command": lead + "git stash list" }, env={ } ) is None, repr( lead )
        assert stash_guard.stash_deny_reason( "Bash", { "command": lead + "git status" }, env={ } ) is None, repr( lead )
        assert commit_scope_guard.git_commit_match( lead + "git commit -m x" ) is not None, repr( lead )
        assert commit_scope_guard.git_commit_match( lead + "git log" ) is None, repr( lead )


# ---------------------------------------------------------------------------
# The whole hook
# ---------------------------------------------------------------------------

def _hook_seconds( command ):
    """
    Time ptu.main() on one Bash command, with the hook's I/O stubbed.

    Ensures:
        - every guard the hook runs on a Bash command runs for real
        - nothing is read from stdin, logged, drained or written to a bridge file
    """
    payload = { "tool_name": "Bash", "tool_input": { "command": command }, "session_id": "abc12345", "hook_event_name": "PreToolUse" }
    with patch.object( ptu, "read_hook_input", return_value=payload ), \
         patch.object( ptu, "log_payload" ), \
         patch.object( ptu, "get_claude_session_id", return_value="abc12345" ), \
         patch.object( ptu, "drain_and_acknowledge", return_value=[ ] ), \
         patch.object( ptu, "emit_json" ), \
         patch.object( ptu, "resolve_stable_session_id", side_effect=lambda x: x ), \
         patch.object( ptu, "touch_bridge_mtime" ):
        return _seconds( ptu.main, seconds=60 )


def test_the_whole_hook_is_linear_on_4000_blank_lines():
    """
    The hook runs before every Bash call of every seat.

    Measured before the fix: about 2.4 s for a command of 4000 newlines, four times the
    cost of 2000. After: under a tenth of a second.
    """
    small = min( _hook_seconds( "echo hi" + "\n" * 4000 ) for _ in range( 3 ) )
    large = _hook_seconds( "echo hi" + "\n" * 16000 )
    assert small < 1.0, f"4000 blank lines took {small:.2f} s"
    assert large / max( small, 0.002 ) < 9, f"{small * 1000:.1f} ms -> {large * 1000:.1f} ms for 4x"
