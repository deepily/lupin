"""
Tests for the shared stream-text loop in cosa.agents.base_llm_client.

The stream is a fake async context manager, so no model or socket is touched.
"""
import asyncio

from cosa.agents.base_llm_client import collect_stream_text


class _Result:
    def __init__( self, chunks ): self._chunks = chunks

    async def stream_text( self, delta=False ):
        assert delta is True
        for c in self._chunks: yield c


class _Stream:
    def __init__( self, chunks ):
        self._chunks = chunks
        self.exited  = False

    async def __aenter__( self ): return _Result( self._chunks )

    async def __aexit__( self, *exc ): self.exited = True


def _run( chunks, debug, verbose, newline_after=False ):
    stream = _Stream( chunks )
    out    = asyncio.run( collect_stream_text( stream, debug, verbose, newline_after ) )
    return out, stream


def test_deltas_join_in_arrival_order_and_the_stream_is_closed():
    out, stream = _run( [ "a", "b", "c" ], False, False )
    assert out == "abc" and stream.exited is True


def test_debug_and_verbose_echo_each_delta_and_print_no_dots( capsys ):
    _run( [ "Hel", "lo" ], True, True )
    assert capsys.readouterr().out == "Hello"


def test_debug_without_verbose_prints_dots_not_deltas( capsys ):
    _run( [ "x", "y" ], True, False )
    assert capsys.readouterr().out == ".."


def test_quiet_run_prints_one_dot_per_delta_and_a_break_after_the_128th( capsys ):
    _run( [ "z" ] * 130, False, False )
    assert capsys.readouterr().out == "." * 127 + "\n" + "." * 3


def test_newline_after_adds_one_break_once_the_stream_ends( capsys ):
    _run( [ "z" ], False, False, newline_after=True )
    assert capsys.readouterr().out == ".\n"


def test_an_empty_stream_returns_an_empty_string_and_prints_nothing( capsys ):
    out, _ = _run( [], False, False )
    assert out == "" and capsys.readouterr().out == ""
