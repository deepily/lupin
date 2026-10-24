"""
The leak check reads TypeScript parameter names, and never their types.
"""
import pathlib
import subprocess

import pytest

from cosa.repo.symindex import js_index
from lupin_mcp import reuse_need_check as nc

ROOT = pathlib.Path( __file__ ).resolve().parents[ 3 ]

# The record measured in the Stage 1 review: a TypeScript member whose Python-style parse failed.
MEASURED = { "id": "lupin_app.static.js.formatTime", "lang": "ts", "file": "src/lupin_app/static/js/x.ts",
             "sig": "(ms: number, label?: string): string", "doc": "", "name": "formatTime" }


def test_the_python_parse_of_the_measured_signature_returns_the_type_words():
    assert { "number", "string" } <= nc._argument_names( MEASURED[ "sig" ] )


def test_the_measured_typescript_record_gives_names_and_no_type_words():
    tokens = nc.identifier_tokens( MEASURED )
    assert { "ms", "label", "formattime", "x" } <= tokens
    assert not tokens & { "number", "string" }


@pytest.mark.parametrize( "sig, names", [
    ( "(ms: number, label?: string): string",                   { "ms", "label" } ),
    ( "({ a, b }: Opts)",                                       { "a", "b" } ),
    ( "({ a: { b }, c }: Opts)",                                { "a", "b", "c" } ),
    ( "([x, y]: Pair, z = (1, 2))",                             { "x", "y", "z" } ),
    ( "(...xs: number[])",                                      { "xs" } ),
    ( "<T>(m: Map<string, number>, k: string): T",              { "m", "k" } ),
    ( "(n = 3)",                                                { "n" } ),
    ( "(cb: (x: number) => void, n: number)",                   { "cb", "n" } ),
    ( "(private readonly svc: Service, this: Foo)",             { "svc" } ),
    ( "(handler: (a: string) => Promise<void>, $el: Element)",  { "handler", "$el" } ),
    ( "()",                                                     set() ),
    ( "",                                                       set() ),
    ( "({ a",                                                   { "a" } ),
    ( "(a, b",                                                  { "a", "b" } ),
] )
def test_typescript_signatures_give_only_parameter_names(sig, names):
    assert nc._ts_argument_names( sig ) == names


def test_a_type_word_used_as_a_parameter_name_is_still_not_a_token():
    assert nc._ts_argument_names( "(string: string, any: any)" ) == set()


def test_a_record_without_a_lang_or_with_python_reads_the_signature_as_python():
    base = { "id": "p.f", "file": "p/x.py", "sig": "(string, n)", "doc": "" }
    assert "string" in nc.identifier_tokens( base )
    assert "string" in nc.identifier_tokens( dict( base, lang="py" ) )
    assert "string" not in nc.identifier_tokens( dict( base, lang="ts" ) )


def test_a_need_that_says_string_passes_the_identifier_check_for_the_measured_record():
    tokens = nc.identifier_tokens( MEASURED )
    assert "string" not in tokens and "number" not in tokens
    assert nc.shared_run( "A function that turns a number of milliseconds into a string for display.", "turns a count into text" ) is None


def real_typescript_records():
    """Return the symbol records the real extractor makes for the tracked multiplexer sources."""
    listed = subprocess.run( [ "git", "ls-files", "src/lupin_app/static/js/multiplexer" ], cwd=ROOT, capture_output=True, text=True, check=True ).stdout.split()
    files  = [ ROOT / f for f in listed if f.endswith( ".ts" ) and not f.endswith( ".d.ts" ) ]
    records = js_index.extract_js( ROOT, files )
    for rec in records: rec[ "id" ] = rec[ "file" ].rsplit( ".", 1 )[ 0 ].replace( "/", "." ) + "." + rec[ "name" ]
    return records


def test_real_typescript_records_never_yield_a_type_word_as_a_token():
    records = real_typescript_records()
    assert len( records ) > 100, "the extractor returned too few records to mean anything"
    with_types = [ r for r in records if any( w in r[ "sig" ] for w in ( ": string", ": number", ": boolean" ) ) ]
    assert len( with_types ) > 20, "the corpus holds too few typed signatures to test the filter"
    leaked = [ ( r[ "id" ], sorted( nc.identifier_tokens( r ) & nc.TS_TYPE_WORDS ) ) for r in with_types if nc.identifier_tokens( r ) & nc.TS_TYPE_WORDS ]
    assert leaked == []
    assert any( nc._argument_names( r[ "sig" ] ) & nc.TS_TYPE_WORDS for r in with_types ), "the Python parse should show the defect on this corpus"
