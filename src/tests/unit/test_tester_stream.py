#!/usr/bin/env python3
"""
tester_stream.verify_with_tester: the Tester loop both fix expediters share.

Venue: :7999-eligible / local, pure; fakes stand in for the SDK's message classes and for pytest.
"""
import asyncio
import os
import sys

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.agents.shared.tester_stream import verify_with_tester


class Text:
    def __init__( self, text ): self.text = text

class ToolUse:
    def __init__( self, name, input ): self.name, self.input = name, input

class Assistant:
    def __init__( self, content ): self.content = content

class Result:
    def __init__( self, is_error=False, text="done" ):
        self.is_error, self.text = is_error, text
        self.result, self.errors, self.subtype = text, [], "error_during_execution"

class Rate:
    retry_after = 7

class Guard:
    def __init__( self ): self.timeouts = 0
    def check_timeout( self ): self.timeouts += 1

class Log:
    def __init__( self ): self.warnings, self.errors = [], []
    def warning( self, text ): self.warnings.append( text )
    def error( self, text ): self.errors.append( text )

class Stop( Exception ):
    """Stands in for the safety-limit class the caller owns."""

class Ran:
    def __init__( self, passed ): self.passed, self.passed_count, self.total_tests = passed, 1 if passed else 0, 1

TYPES = ( Assistant, Text, ToolUse, Result, Rate )


def _verify( messages, pytest_passes=True, error_label=None, guard=None, log=None, notes=None, hooks=None, ran=None, debug=False, open_raises=None, hook_raises=None ):
    notes = [] if notes is None else notes
    ran   = [] if ran is None else ran
    hooks = [] if hooks is None else hooks

    def open_stream():
        if open_raises is not None: raise open_raises
        async def stream():
            for m in messages: yield m
        return stream()

    async def notify( text, priority="low" ): notes.append( ( text, priority ) )
    async def hook( name, input, g ):
        if hook_raises is not None: raise hook_raises
        hooks.append( ( name, input ) )
    async def run_pytest( path, timeout_secs=60 ):
        ran.append( ( path, timeout_secs ) )
        return Ran( pytest_passes )

    return asyncio.run( verify_with_tester( open_stream, guard or Guard(), notify, "Lbl", log or Log(), TYPES, hook, run_pytest, Stop, debug, error_label ) )


def test_the_testers_own_report_decides_when_it_wrote_no_test_file():
    assert _verify( [ Text( "all good, tests pass" ) ] ) == ( True, "all good, tests pass" )
    assert _verify( [ Text( "2 pass, 1 fail" ) ] ) == ( False, "2 pass, 1 fail" )
    assert _verify( [ Text( "nothing to say" ) ] ) == ( False, "nothing to say" )


def test_all_tests_pass_wins_even_when_the_word_fail_appears():
    assert _verify( [ Text( "no fail seen: all tests pass" ) ] )[ 0 ] is True


def test_text_blocks_and_bare_text_messages_are_joined_and_stripped():
    assert _verify( [ Assistant( [ Text( "a " ) ] ), Text( "pass " ) ] )[ 1 ] == "a pass"


def test_each_tool_use_is_announced_and_each_edit_or_write_runs_the_hook():
    notes, hooks = [], []
    _verify( [ Assistant( [ ToolUse( "Edit", { "file_path": "t.py" } ), ToolUse( "Read", { } ), ToolUse( "Write", { } ) ] ) ], notes=notes, hooks=hooks )
    assert notes == [ ( "Tester: Edit", "low" ), ( "Tester: Read", "low" ), ( "Tester: Write", "low" ) ]
    assert [ h[ 0 ] for h in hooks ] == [ "Edit", "Write" ]


def test_the_first_test_file_is_run_and_its_failure_overrides_a_passing_report():
    ran  = []
    msgs = [ Text( "all tests pass" ), Assistant( [ ToolUse( "Write", { "file_path": "a_test.py" } ), ToolUse( "Write", { "file_path": "a_test.py" } ), ToolUse( "Write", { "file_path": "b_test.py" } ) ] ) ]
    passed, _ = _verify( msgs, pytest_passes=False, ran=ran )
    assert passed is False
    assert ran == [ ( "a_test.py", 60 ) ]


def test_a_passing_run_leaves_the_report_alone():
    assert _verify( [ Text( "pass" ), Assistant( [ ToolUse( "Edit", { "file_path": "x_test.py" } ) ] ) ], pytest_passes=True )[ 0 ] is True


def test_files_that_are_not_python_tests_are_skipped_until_one_is_found():
    ran  = []
    msgs = [ Assistant( [ ToolUse( "Edit", { "file_path": "notes.md" } ), ToolUse( "Edit", { "file_path": "helper.py" } ), ToolUse( "Edit", { "file_path": "src/Test_It.py" } ) ] ) ]
    _verify( msgs, ran=ran )
    assert ran == [ ( "src/Test_It.py", 60 ) ]


def test_no_test_file_means_no_pytest_run():
    ran = []
    _verify( [ Assistant( [ ToolUse( "Edit", { "file_path": "helper.py" } ), ToolUse( "Edit", { } ) ] ) ], ran=ran )
    assert ran == []


def test_a_block_or_message_of_another_kind_is_skipped():
    class Other: pass
    assert _verify( [ Assistant( [ Other(), Text( "pass" ) ] ), Other() ] ) == ( True, "pass" )


def test_the_guard_is_checked_on_every_message():
    guard = Guard()
    _verify( [ Text( "a" ), Text( "b" ), Result() ], guard=guard )
    assert guard.timeouts == 3


def test_a_rate_limit_event_is_logged_and_the_read_goes_on():
    log = Log()
    assert _verify( [ Rate(), Text( "pass" ) ], log=log ) == ( True, "pass" )
    assert log.warnings == [ "Rate limited: retry_after=7s" ]


def test_an_error_result_is_ignored_without_an_error_label():
    assert _verify( [ Result( is_error=True ), Text( "pass" ) ] ) == ( True, "pass" )


def test_a_clean_result_is_ignored_with_an_error_label():
    assert _verify( [ Result(), Text( "pass" ) ], error_label="X tester" )[ 0 ] is True


def test_an_error_result_with_an_error_label_fails_the_verification_and_logs_it():
    log = Log()
    passed, out = _verify( [ Result( is_error=True, text="boom" ) ], error_label="X tester", log=log )
    assert passed is False and out.startswith( "Verification error:" )
    assert any( "[X tester]" in e for e in log.errors ) and any( e.startswith( "Verification failed" ) for e in log.errors )


def test_a_failure_to_open_the_stream_is_caught_like_a_failure_to_read():
    log = Log()
    assert _verify( [ ], open_raises=ValueError( "no sdk" ), log=log ) == ( False, "Verification error: no sdk" )
    assert log.errors == [ "Verification failed: no sdk" ]


def test_the_safety_stop_is_raised_and_never_swallowed():
    import pytest
    with pytest.raises( Stop ):
        _verify( [ Assistant( [ ToolUse( "Edit", { "file_path": "a_test.py" } ) ] ) ], hook_raises=Stop( "limit" ) )


def test_debug_prints_the_pytest_result_and_the_verdict_under_the_label( capsys ):
    _verify( [ Text( "pass" ), Assistant( [ ToolUse( "Edit", { "file_path": "a_test.py" } ) ] ) ], debug=True )
    out = capsys.readouterr().out
    assert "[Lbl] pytest a_test.py: PASS (1/1)" in out and "[Lbl] Verification: PASS" in out
    _verify( [ Text( "pass" ), Assistant( [ ToolUse( "Edit", { "file_path": "a_test.py" } ) ] ) ], pytest_passes=False, debug=True )
    out = capsys.readouterr().out
    assert "[Lbl] pytest a_test.py: FAIL (0/1)" in out and "[Lbl] Verification: FAIL" in out


def test_debug_off_prints_nothing( capsys ):
    _verify( [ Text( "pass" ) ] )
    assert capsys.readouterr().out == ""
