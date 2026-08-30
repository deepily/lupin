"""
Coverage ramp for `src/scripts/debug/debug_crud_llm_call.py` — 108 statements, previously a
flat 0.0% (assigned by Mr Radio 🦉 2026-08-30 for the 96% push).

🔴 WHAT THIS FILE IS, STATED PLAINLY. The script under test is a debug one-shot that nothing
imports. These tests were written to move a coverage number, not because the script earned
tests on merit. Every branch below is really executed and really asserted, but nobody should
read this suite as evidence the script is well-covered infrastructure.

🔴 IMPORTING THIS SCRIPT *IS* RUNNING IT — that is the whole difficulty. It has ZERO function
definitions and NO `if __name__ == "__main__"` guard: all 108 statements sit at module level,
and they read a prompt template off disk, build a DataFrameStorage, and POST twice to a vLLM
endpoint at 192.168.1.21:3001. A bare `import` in a unit test would be a live network call.

So every patch must be in place BEFORE the import, and the patch target is the SOURCE module,
not the script:
  · `DataFrameStorage` and `PromptTemplateProcessor` are bound by `from … import …`, which
    copies the reference at import time — patching them on the script afterwards would be too
    late, and patching them at all afterwards would be patching a module that already ran.
  · `requests.post` is reached as an attribute at CALL time, so patching the real `requests`
    module works — and is scoped by monkeypatch, so it does not leak to other importers.

Each test re-imports the module from a clean `sys.modules` so the top-level code runs again
under that test's own scripted responses. `_fresh_import` also purges the module's `__pycache__`
entry: a mutation-free re-import is normally fine, but this suite is exactly the shape
(same-size edits, sub-second) that CLAUDE.md's stale-pyc rule warns about, and purging costs
nothing.
"""

import importlib
import json
import os
import sys

import pytest
import requests

_ROOT = os.environ.get( "LUPIN_ROOT", os.getcwd() )
for _p in ( os.path.join( _ROOT, "src", "scripts", "debug" ), os.path.join( _ROOT, "src" ) ):
    if _p not in sys.path:
        sys.path.insert( 0, _p )

MODULE_NAME = "debug_crud_llm_call"
ENDPOINT    = "http://192.168.1.21:3001/v1/completions"


class _FakeStorage:
    """
    Stands in for DataFrameStorage so no `io/dfs` state is read or written.

    Requires:
        - metadata is a list of dicts carrying list_name / schema_type / item_count
    """

    def __init__( self, metadata ):
        self._metadata = metadata

    def __call__( self, *args, **kwargs ):
        return self

    def get_all_lists_metadata( self ):
        return self._metadata


class _FakeProcessor:
    """Stands in for PromptTemplateProcessor — returns the template untouched."""

    def __init__( self, *args, **kwargs ):
        pass

    def process_template( self, template, routing_command ):
        return template


class _FakeResponse:
    """
    Stands in for a `requests` response, for both the streaming and non-streaming calls.

    Requires:
        - status_code is an int
        - lines is a list of bytes for iter_lines(), used only on the streaming call
    """

    def __init__( self, status_code=200, body="ok", payload=None, lines=None ):
        self.status_code = status_code
        self.text        = body
        self.headers     = { "Content-Type": "application/json" }
        self._payload    = payload if payload is not None else { "choices": [ { "text": "parsed-text" } ] }
        self._lines      = lines or []

    def json( self ):
        return self._payload

    def iter_lines( self ):
        return iter( self._lines )


def _sse( text ):
    """Build one `data:` server-sent-event line the way vLLM emits it."""
    return ( "data: " + json.dumps( { "choices": [ { "text": text } ] } ) ).encode( "utf-8" )


def _fresh_import( monkeypatch, post_results, metadata=None ):
    """
    Import the script from scratch with every side effect stubbed.

    Requires:
        - post_results is a list of len 2: the non-streaming then the streaming outcome.
          An entry that is an Exception is raised instead of returned.

    Ensures:
        - returns ( module, calls ) where calls records each requests.post invocation
        - no network call is made and no DataFrame state is touched
        - the module is removed from sys.modules afterwards, so tests do not leak into
          each other through a cached module object
    """
    calls = []

    def fake_post( url, **kwargs ):
        # 🔴 SNAPSHOT THE PAYLOAD — the script builds ONE `payload` dict and mutates it
        # (`payload["stream"] = True`) between the two calls. Recording the dict by reference
        # makes both entries read `stream: True`, so a test asserting the two calls differ
        # would measure the shared object rather than what was sent, and fail against correct
        # code. Measured here on the first run.
        recorded = dict( kwargs )
        if "json" in recorded: recorded[ "json" ] = dict( recorded[ "json" ] )
        calls.append( { "url": url, **recorded } )

        outcome = post_results[ len( calls ) - 1 ]
        if isinstance( outcome, BaseException ): raise outcome
        return outcome

    monkeypatch.setattr( requests, "post", fake_post )
    monkeypatch.setattr(
        "cosa.crud_for_dataframes.storage.DataFrameStorage",
        _FakeStorage( metadata if metadata is not None else [] ),
    )
    monkeypatch.setattr(
        "cosa.agents.io_models.utils.prompt_template_processor.PromptTemplateProcessor",
        _FakeProcessor,
    )

    sys.modules.pop( MODULE_NAME, None )
    module = importlib.import_module( MODULE_NAME )
    sys.modules.pop( MODULE_NAME, None )
    return module, calls


def test_both_calls_succeed_and_hit_the_configured_endpoint( monkeypatch, capsys ):
    """The clean path: a 200 on the plain call and a streamed 200 carrying two chunks."""
    streaming = _FakeResponse( lines=[ _sse( "hello " ), _sse( "world" ), b"data: [DONE]" ] )
    _, calls  = _fresh_import( monkeypatch, [ _FakeResponse(), streaming ] )

    assert len( calls ) == 2
    assert [ c[ "url" ] for c in calls ] == [ ENDPOINT, ENDPOINT ]

    # The two calls differ in exactly one field, and that is the point of the script.
    assert calls[ 0 ][ "json" ][ "stream" ] is False
    assert calls[ 1 ][ "json" ][ "stream" ] is True

    out = capsys.readouterr().out
    assert "DIAGNOSTIC COMPLETE" in out
    assert "hello world" in out


def test_available_lists_are_rendered_into_the_prompt( monkeypatch, capsys ):
    """
    With lists present, the script formats them into the prompt.

    Reads the prompt actually SENT rather than the console banner: an empty and a populated
    list both print a prompt, so only the payload distinguishes them.
    """
    metadata = [
        { "list_name": "grocery", "schema_type": "todo", "item_count": 3 },
        { "list_name": "books",   "schema_type": "todo", "item_count": 7 },
    ]
    streaming = _FakeResponse( lines=[ b"data: [DONE]" ] )
    _, calls  = _fresh_import( monkeypatch, [ _FakeResponse(), streaming ], metadata=metadata )

    prompt = calls[ 0 ][ "json" ][ "prompt" ]
    assert "- grocery (todo, 3 items)" in prompt
    assert "- books (todo, 7 items)" in prompt
    assert "No lists created yet." not in prompt


def test_no_available_lists_renders_the_empty_placeholder( monkeypatch ):
    """The other arm of the same branch — asserted on the payload, for the same reason."""
    streaming = _FakeResponse( lines=[ b"data: [DONE]" ] )
    _, calls  = _fresh_import( monkeypatch, [ _FakeResponse(), streaming ], metadata=[] )

    assert "No lists created yet." in calls[ 0 ][ "json" ][ "prompt" ]


def test_non_200_on_both_calls_is_reported_not_raised( monkeypatch, capsys ):
    """A refused request is a diagnostic result, so the script prints and carries on."""
    bad = _FakeResponse( status_code=500, body="upstream exploded" )
    _fresh_import( monkeypatch, [ bad, bad ] )

    out = capsys.readouterr().out
    assert out.count( "ERROR: Non-200 status code" ) == 2
    assert "DIAGNOSTIC COMPLETE" in out


def test_connection_error_on_both_calls_names_the_endpoint( monkeypatch, capsys ):
    """The failure this script was written to diagnose — vLLM not reachable."""
    boom = requests.exceptions.ConnectionError( "no route to host" )
    _fresh_import( monkeypatch, [ boom, boom ] )

    out = capsys.readouterr().out
    assert out.count( "CONNECTION ERROR" ) == 2
    assert "Is the vLLM server running on 192.168.1.21:3001?" in out


def test_timeout_on_both_calls_is_reported( monkeypatch, capsys ):
    """Separate arm from ConnectionError, and it prints a different line."""
    _fresh_import( monkeypatch, [ requests.exceptions.Timeout(), requests.exceptions.Timeout() ] )

    out = capsys.readouterr().out
    assert out.count( "TIMEOUT: No response within 60s" ) == 2


def test_unexpected_error_on_both_calls_reports_the_exception_type( monkeypatch, capsys ):
    """The catch-all arm — it names the exception class, so assert on that."""
    _fresh_import( monkeypatch, [ ValueError( "weird" ), KeyError( "odd" ) ] )

    out = capsys.readouterr().out
    assert "UNEXPECTED ERROR: ValueError: weird" in out
    assert "UNEXPECTED ERROR: KeyError:" in out


def test_streaming_handles_malformed_chunk_and_non_data_lines( monkeypatch, capsys ):
    """
    The stream carries three shapes the parser must survive: a good chunk, a `data:` line
    whose body is not JSON, and a line that is not a `data:` line at all.
    """
    lines = [
        _sse( "good" ),
        b"data: {not json",
        b": keep-alive comment",
        b"data: [DONE]",
    ]
    _fresh_import( monkeypatch, [ _FakeResponse(), _FakeResponse( lines=lines ) ] )

    out = capsys.readouterr().out
    assert "PARSE ERROR" in out
    assert "Line 2: : keep-alive comment" in out
    assert "Reconstructed text:\ngood" in out


def test_streaming_prints_early_chunks_and_every_twentieth( monkeypatch, capsys ):
    """
    Covers the `if i < 5 or i % 20 == 0` arm in both directions.

    25 chunks means indices 0-4 print by the first clause, index 20 prints by the second, and
    the rest are silent — so the printed set is the assertion, not the chunk count.
    """
    lines = [ _sse( f"c{i}" ) for i in range( 25 ) ] + [ b"data: [DONE]" ]
    _fresh_import( monkeypatch, [ _FakeResponse(), _FakeResponse( lines=lines ) ] )

    out = capsys.readouterr().out
    assert "Chunk 0: 'c0'" in out
    assert "Chunk 4: 'c4'" in out
    assert "Chunk 20: 'c20'" in out
    assert "Chunk 21: 'c21'" not in out
    assert "Total chunks: 25" in out


def test_streaming_non_200_prints_the_body( monkeypatch, capsys ):
    """A refused stream reports its body, which is the only diagnostic available."""
    bad = _FakeResponse( status_code=503, body="service unavailable" )
    _fresh_import( monkeypatch, [ _FakeResponse(), bad ] )

    out = capsys.readouterr().out
    assert "service unavailable" in out


def test_empty_stream_reconstructs_nothing( monkeypatch, capsys ):
    """
    A 200 that carries no chunks at all — the empty-response symptom the script's docstring
    says it exists to isolate.
    """
    _fresh_import( monkeypatch, [ _FakeResponse(), _FakeResponse( lines=[] ) ] )

    out = capsys.readouterr().out
    assert "Total chunks: 0" in out
    assert "Reconstructed text length: 0" in out


def test_late_non_data_lines_are_not_printed( monkeypatch, capsys ):
    """
    Covers the FALSE arm of the stream's `if i < 5` guard on non-`data:` lines, and with it
    the loop's back-edge from that branch.

    Six keep-alive comments: the first five print, the sixth does not, and the loop still
    reaches the terminator after it.
    """
    lines = [ b": keep-alive" ] * 6 + [ _sse( "tail" ), b"data: [DONE]" ]
    _fresh_import( monkeypatch, [ _FakeResponse(), _FakeResponse( lines=lines ) ] )

    out = capsys.readouterr().out
    assert "Line 4: : keep-alive" in out
    assert "Line 5: : keep-alive" not in out
    assert "Reconstructed text:\ntail" in out


def test_import_inserts_src_on_a_path_that_lacks_it( monkeypatch, capsys ):
    """
    Covers the bootstrap's `sys.path.insert` arm, which every other test skips because the
    conftest has already put `src` on the path.

    Removing that exact entry first makes the script take the other branch; it re-inserts the
    path itself before importing cosa, so nothing downstream is disturbed.
    """
    src_path = os.path.join( _ROOT, "src" )
    monkeypatch.setattr( sys, "path", [ p for p in sys.path if p != src_path ] )
    assert src_path not in sys.path

    _fresh_import( monkeypatch, [ _FakeResponse(), _FakeResponse( lines=[ b"data: [DONE]" ] ) ] )

    assert src_path in sys.path
    assert "DIAGNOSTIC COMPLETE" in capsys.readouterr().out


def test_blank_lines_in_the_stream_are_skipped( monkeypatch, capsys ):
    """`if line:` — a keep-alive empty line must not be treated as a chunk."""
    lines = [ b"", _sse( "only" ), b"", b"data: [DONE]" ]
    _fresh_import( monkeypatch, [ _FakeResponse(), _FakeResponse( lines=lines ) ] )

    out = capsys.readouterr().out
    assert "Total chunks: 1" in out
    assert "Reconstructed text:\nonly" in out
