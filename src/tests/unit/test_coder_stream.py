#!/usr/bin/env python3
"""
coder_stream.read_coder_stream: the loop both fix expediters use to read a Coder stream.

Venue: :7999-eligible / local, pure; fakes stand in for the SDK's message classes.
"""
import asyncio
import os
import sys

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

import pytest

from cosa.agents.shared.coder_stream import read_coder_stream


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
    def __init__( self ): self.timeouts, self.iterations = 0, 0
    def check_timeout( self ): self.timeouts += 1
    def check_iteration( self ): self.iterations += 1

class Log:
    def __init__( self ): self.warnings, self.errors = [], []
    def warning( self, text ): self.warnings.append( text )
    def error( self, text ): self.errors.append( text )

TYPES = ( Assistant, Text, ToolUse, Result, Rate )


def _run( messages, cancel_after=None, hook_calls=None, notes=None, guard=None, log=None ):
    notes = [] if notes is None else notes
    seen  = { "n": 0 }

    async def stream():
        for m in messages:
            seen[ "n" ] += 1
            yield m

    async def notify( text, priority="low" ): notes.append( ( text, priority ) )
    async def hook( name, input, g ): ( [] if hook_calls is None else hook_calls ).append( ( name, input ) )
    def cancelled(): return cancel_after is not None and seen[ "n" ] > cancel_after

    return asyncio.run( read_coder_stream( stream(), guard or Guard(), notify, cancelled, "Label", log or Log(), TYPES, hook ) )


def test_text_and_each_edited_file_are_collected_once_in_order():
    hooks = []
    msgs  = [
        Assistant( [ Text( "a " ), ToolUse( "Edit", { "file_path": "x.py" } ), ToolUse( "Write", { "file_path": "y.py" } ), ToolUse( "Edit", { "file_path": "x.py" } ), ToolUse( "Read", { "file_path": "z.py" } ), ToolUse( "Edit", { } ) ] ),
        Text( "b " ),
        Result( text="r" * 300 ),
    ]
    notes = []
    out, files = _run( msgs, hook_calls=hooks, notes=notes )
    assert out == "a b"
    assert files == [ "x.py", "y.py" ]
    assert [ h[ 0 ] for h in hooks ] == [ "Edit", "Write", "Edit", "Edit" ]
    assert len( notes ) == 6 and notes[ -1 ] == ( "r" * 200, "low" )


def test_the_guard_is_checked_per_message_and_once_at_the_end():
    guard = Guard()
    _run( [ Text( "a" ), Text( "b" ) ], guard=guard )
    assert ( guard.timeouts, guard.iterations ) == ( 2, 1 )


def test_a_cancel_stops_the_read():
    out, _ = _run( [ Text( "a" ), Text( "b" ), Text( "c" ) ], cancel_after=1 )
    assert out == "a"


def test_an_error_result_raises_and_logs_under_the_label():
    log = Log()
    with pytest.raises( RuntimeError ):
        _run( [ Result( is_error=True, text="boom" ) ], log=log )
    assert log.errors and "[Label]" in log.errors[ 0 ]


def test_a_rate_limit_event_is_logged_and_the_read_goes_on():
    log = Log()
    out, _ = _run( [ Rate(), Text( "ok" ) ], log=log )
    assert out == "ok" and log.warnings == [ "Rate limited: retry_after=7s" ]
