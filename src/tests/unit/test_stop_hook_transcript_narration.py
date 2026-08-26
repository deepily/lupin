"""
Transcript reading and the auto-narrate decision in `stop.py` — row `e2099400`.

WHY THESE THREE. `_read_last_assistant_message`, `_turn_has_notify_call` and
`_extract_narratable_text` are what the stop hook uses to decide whether to
speak a turn out loud. Their dark lines (1035-1036, 1067-1068, 1106-1107,
1109-1110) were all failure paths, and the failure value of each is the same
shape as a legitimate one: None, False, "".

WHAT THAT COSTS WHEN IT IS WRONG, in both directions. Read the transcript
wrongly and the hook narrates a turn Claude already narrated itself — the user
hears the same thing twice. Fail to read it and the hook stays silent on a turn
that needed speaking, and nothing anywhere reports that it happened. Neither
direction raises, so a test is the only place either can be seen.

WHAT IS PINPOINTED:

· **The LAST assistant message wins, not the first.** The reader walks the whole
  file and keeps overwriting. Reversing that would narrate a stale turn — which
  would look entirely normal to anyone reading the code.

· **User messages are never mistaken for assistant ones.** The transcript
  interleaves both, and the type check is the only thing separating them.

· **A malformed line is skipped and the walk continues.** A half-written last
  line is the NORMAL state of a live transcript — it is being appended to while
  the hook reads it. Aborting on it would silence exactly the turn being spoken.

· **A missing file, a directory, an empty path and an unreadable file all yield
  None** rather than raising on the stop path.

· **`_turn_has_notify_call` finds the notify block wherever it sits** in the
  content list, and returns False — never raises — on every malformed shape it
  can be handed. It is the pass-through switch: a False here means the hook
  speaks, so a shape mismatch that threw would be worse than one that returned
  the wrong answer.

· **Only `text` blocks are narratable.** Tool-use blocks and their results must
  never be read aloud; blocks are filtered by type, not merely by having a
  `text` key.

· **Fenced code is stripped, and a failure to strip is not a failure to
  narrate** — the strip is best-effort and its import is guarded, so a broken
  stripper degrades to speaking the raw text rather than to silence.

See: row e2099400
"""

import json

import pytest

from lupin_cli.claude_code.hooks.stop import (
    _extract_narratable_text,
    _read_last_assistant_message,
    _turn_has_notify_call,
)


MODULE = "lupin_cli.claude_code.hooks.stop"


def _assistant( *blocks ):
    return { "type": "assistant", "message": { "content": list( blocks ) } }


def _text( s ):
    return { "type": "text", "text": s }


def _notify_call():
    return { "type": "tool_use", "name": "mcp__cosa-voice__notify", "input": {} }


def _transcript( tmp_path, *rows ):
    p = tmp_path / "transcript.jsonl"
    p.write_text( "".join( json.dumps( r ) + "\n" for r in rows ) )
    return str( p )


class TestReadingTheTranscript:

    def test_the_last_assistant_message_wins( self, tmp_path ):
        """The walk overwrites rather than returning early. Reversed, the hook
        narrates a stale turn — and the code would read as correct."""
        path = _transcript( tmp_path,
                            _assistant( _text( "first" ) ),
                            _assistant( _text( "second" ) ) )
        msg = _read_last_assistant_message( path )
        assert _extract_narratable_text( msg ) == "second"

    def test_a_trailing_user_message_does_not_displace_it( self, tmp_path ):
        """The transcript interleaves both roles; the type check is the only
        thing separating them."""
        path = _transcript( tmp_path,
                            _assistant( _text( "assistant text" ) ),
                            { "type": "user", "message": { "content": [ _text( "user text" ) ] } } )
        assert _extract_narratable_text( _read_last_assistant_message( path ) ) == "assistant text"

    def test_a_transcript_with_no_assistant_turn_yields_none( self, tmp_path ):
        path = _transcript( tmp_path, { "type": "user", "message": { "content": [] } } )
        assert _read_last_assistant_message( path ) is None

    def test_a_half_written_trailing_line_does_not_lose_the_turn( self, tmp_path ):
        """A half-written LAST line is the normal state of a live transcript —
        it is being appended to while the hook reads it."""
        p = tmp_path / "t.jsonl"
        p.write_text( json.dumps( _assistant( _text( "good" ) ) ) + "\n{ half-writ" )
        assert _extract_narratable_text( _read_last_assistant_message( str( p ) ) ) == "good"

    def test_a_malformed_line_MIDWAY_does_not_abort_the_walk( self, tmp_path ):
        """⚠️ THIS IS THE TEST THAT HAS TEETH, and the trailing-line one above
        does not. With the bad line last, `continue` and `break` behave
        identically — the answer was already found. Only a bad line BEFORE a
        later assistant turn distinguishes skipping from aborting, and aborting
        would narrate a stale turn while the real one sat unread two lines down.
        Found by mutating `continue` to `break` and watching the first version
        of this test stay green."""
        p = tmp_path / "t.jsonl"
        p.write_text( json.dumps( _assistant( _text( "stale" ) ) ) + "\n"
                      + "{ corrupt line\n"
                      + json.dumps( _assistant( _text( "current" ) ) ) + "\n" )
        assert _extract_narratable_text( _read_last_assistant_message( str( p ) ) ) == "current"

    def test_blank_lines_are_skipped( self, tmp_path ):
        p = tmp_path / "t.jsonl"
        p.write_text( "\n" + json.dumps( _assistant( _text( "x" ) ) ) + "\n\n" )
        assert _read_last_assistant_message( str( p ) ) is not None

    def test_a_missing_file_yields_none( self, tmp_path ):
        assert _read_last_assistant_message( str( tmp_path / "nope.jsonl" ) ) is None

    def test_an_empty_path_yields_none( self ):
        assert _read_last_assistant_message( "" ) is None

    def test_none_as_a_path_yields_none( self ):
        assert _read_last_assistant_message( None ) is None

    def test_a_directory_yields_none_rather_than_raising( self, tmp_path ):
        assert _read_last_assistant_message( str( tmp_path ) ) is None

    def test_an_unreadable_file_yields_none( self, tmp_path, monkeypatch ):
        path = _transcript( tmp_path, _assistant( _text( "x" ) ) )
        import builtins
        real_open = builtins.open
        def boom( *a, **k ): raise OSError( "permission denied" )
        monkeypatch.setattr( builtins, "open", boom )
        assert _read_last_assistant_message( path ) is None
        monkeypatch.setattr( builtins, "open", real_open )

    def test_an_empty_transcript_yields_none( self, tmp_path ):
        p = tmp_path / "t.jsonl"
        p.write_text( "" )
        assert _read_last_assistant_message( str( p ) ) is None


class TestTheSelfNarrationSwitch:
    """A False here means the hook speaks; it must never raise."""

    def test_a_notify_tool_use_is_found( self ):
        assert _turn_has_notify_call( _assistant( _notify_call() ) ) is True

    def test_it_is_found_among_other_blocks( self ):
        assert _turn_has_notify_call(
            _assistant( _text( "some prose" ), _notify_call(), _text( "more" ) ) ) is True

    def test_a_turn_without_it_returns_false( self ):
        assert _turn_has_notify_call( _assistant( _text( "just prose" ) ) ) is False

    def test_a_different_tool_is_not_a_notify( self ):
        """Otherwise every turn that used any tool would suppress narration."""
        assert _turn_has_notify_call( _assistant(
            { "type": "tool_use", "name": "mcp__cosa-voice__ask_yes_no" } ) ) is False

    def test_a_text_block_merely_naming_notify_is_not_a_call( self ):
        assert _turn_has_notify_call(
            _assistant( _text( "I will call mcp__cosa-voice__notify next" ) ) ) is False

    @pytest.mark.parametrize( "junk", [
        None, {}, { "message": None }, { "message": {} },
        { "message": { "content": None } },
        { "message": { "content": "not a list" } },
        { "message": { "content": [ None, "string", 42 ] } },
    ] )
    def test_every_malformed_shape_returns_false_rather_than_raising( self, junk ):
        assert _turn_has_notify_call( junk ) is False


class TestExtractingNarratableText:

    def test_a_single_text_block_comes_back( self ):
        assert _extract_narratable_text( _assistant( _text( "hello" ) ) ) == "hello"

    def test_multiple_text_blocks_are_joined_with_a_blank_line( self ):
        assert _extract_narratable_text(
            _assistant( _text( "one" ), _text( "two" ) ) ) == "one\n\ntwo"

    def test_tool_use_blocks_are_never_narrated( self ):
        """Reading a tool call aloud is the failure this filter prevents."""
        assert _extract_narratable_text(
            _assistant( _notify_call(), _text( "spoken" ) ) ) == "spoken"

    def test_a_block_with_a_text_key_but_the_wrong_type_is_skipped( self ):
        """Filtered by type, not by merely having a `text` key — a tool result
        carrying one would otherwise be read out."""
        assert _extract_narratable_text( _assistant(
            { "type": "tool_result", "text": "internal detail" },
            _text( "spoken" ) ) ) == "spoken"

    def test_empty_text_blocks_contribute_nothing( self ):
        assert _extract_narratable_text(
            _assistant( _text( "" ), _text( "real" ) ) ) == "real"

    def test_a_turn_with_no_text_yields_an_empty_string( self ):
        assert _extract_narratable_text( _assistant( _notify_call() ) ) == ""

    def test_fenced_code_is_stripped( self ):
        spoken = _extract_narratable_text( _assistant(
            _text( "Here it is:\n\n```python\nprint( 'x' )\n```\n\nThat is all." ) ) )
        assert "print" not in spoken
        assert "That is all." in spoken

    def test_a_broken_stripper_degrades_to_the_raw_text_not_to_silence( self, monkeypatch ):
        """The strip is best-effort and its import is guarded. Losing code
        removal is a cosmetic problem; losing the turn is not."""
        import lupin_mcp.cosa_voice_mcp as mcp
        def boom( text ): raise RuntimeError( "stripper broken" )
        monkeypatch.setattr( mcp, "strip_fenced_code_blocks", boom )
        assert "spoken" in _extract_narratable_text( _assistant( _text( "spoken" ) ) )

    @pytest.mark.parametrize( "junk", [
        None, {}, { "message": None }, { "message": { "content": None } },
        { "message": { "content": "not a list" } },
        { "message": { "content": [ None, 42 ] } },
    ] )
    def test_every_malformed_shape_yields_an_empty_string_rather_than_raising( self, junk ):
        assert _extract_narratable_text( junk ) == ""

    def test_surrounding_whitespace_is_trimmed( self ):
        assert _extract_narratable_text( _assistant( _text( "  spaced  \n\n" ) ) ) == "spaced"
