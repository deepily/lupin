"""
Unit tests for purpose lines: what is sent, what is stored, and what is dropped.

The writer is a fake that records the ids it receives. The screen is the index's real
sendable and c1_hits, so the five sensitive shapes are tested against the real patterns.
"""
import json

import pytest

from cosa.repo.symindex.candidates import purpose_lines as pl


@pytest.fixture( scope="module" )
def screen():
    return pl.default_screen()


def entry( name, pin, sig="()", doc="", file="src/a.py" ):
    return { "id": f"a.{name}", "name": name, "file": file, "sig": sig, "doc": doc, "pin": pin, "lang": "py", "kind": "function", "line": 1, "public": True }


class FakeWriter:
    def __init__( self, answers=None ):
        self.answers = answers if answers is not None else {}
        self.calls   = []

    def __call__( self, ids ):
        self.calls.append( list( ids ) )
        return { i: self.answers.get( i, f"Return the {i} value." ) for i in ids if i not in self.answers or self.answers[ i ] is not None }


def test_default_screen_is_the_index_functions( screen ):
    from lupin_mcp import reuse_tools
    assert screen.sendable is reuse_tools.sendable
    assert screen.hits is reuse_tools.c1_hits


def test_prompt_hash_changes_with_the_prompt( monkeypatch ):
    first = pl.prompt_hash()
    assert len( first ) == 16
    assert pl.prompt_hash() == first
    monkeypatch.setattr( pl, "PROMPT_TEXT", pl.PROMPT_TEXT + " Also be brief." )
    assert pl.prompt_hash() != first


def test_load_lines_of_a_missing_file_is_empty( tmp_path ):
    assert pl.load_lines( tmp_path / "none.jsonl" ) == {}


def test_load_lines_skips_blank_lines_and_keeps_the_first_row_of_a_pin( tmp_path ):
    p = tmp_path / "purpose.jsonl"
    p.write_text( json.dumps( { "pin": "p1", "purpose": "First." } ) + "\n\n" + json.dumps( { "pin": "p1", "purpose": "Second." } ) + "\n" )
    assert pl.load_lines( p ) == { "p1": { "pin": "p1", "purpose": "First." } }


def test_missing_pins_are_written_and_stored_pins_are_not_sent( tmp_path, screen ):
    store  = tmp_path / "p" / "purpose.jsonl"
    writer = FakeWriter()
    r1 = pl.write_purpose_lines( [ entry( "f", "p1" ), entry( "g", "p2" ) ], writer, store, "w1", screen )
    assert r1 == { "written": 2, "kept": 0, "dropped_screen": [], "dropped_output": [], "missing": [] }
    assert writer.calls == [ [ "a.f", "a.g" ] ]

    r2 = pl.write_purpose_lines( [ entry( "f", "p1" ), entry( "g", "p2" ) ], writer, store, "w1", screen )
    assert r2[ "written" ] == 0 and r2[ "kept" ] == 2
    assert len( writer.calls ) == 1

    rows = pl.load_lines( store )
    assert set( rows ) == { "p1", "p2" }
    assert rows[ "p1" ] == { "pin": "p1", "purpose": "Return the a.f value.", "prompt_hash": pl.prompt_hash(), "writer_version": "w1" }


def test_a_changed_pin_is_rewritten_as_a_new_row_and_the_old_row_stays( tmp_path, screen ):
    store  = tmp_path / "purpose.jsonl"
    writer = FakeWriter()
    pl.write_purpose_lines( [ entry( "f", "p1" ) ], writer, store, "w1", screen )
    pl.write_purpose_lines( [ entry( "f", "p1b" ) ], writer, store, "w1", screen )
    assert writer.calls == [ [ "a.f" ], [ "a.f" ] ]
    assert set( pl.load_lines( store ) ) == { "p1", "p1b" }


def test_two_entries_with_one_pin_are_sent_once( tmp_path, screen ):
    writer = FakeWriter()
    r = pl.write_purpose_lines( [ entry( "f", "same" ), entry( "g", "same" ) ], writer, tmp_path / "p.jsonl", "w1", screen )
    assert writer.calls == [ [ "a.f" ] ]
    assert r[ "written" ] == 1


def test_the_writer_gets_ids_only_never_source_text( tmp_path, screen ):
    writer = FakeWriter()
    pl.write_purpose_lines( [ entry( "f", "p1", sig="(x)", doc="Secret docstring text." ) ], writer, tmp_path / "p.jsonl", "w1", screen )
    assert writer.calls == [ [ "a.f" ] ]
    assert all( isinstance( i, str ) and "Secret" not in i for call in writer.calls for i in call )


@pytest.mark.parametrize( "kind, doc", [
    ( "email",      "Mail alice@example.com about it." ),
    ( "url",        "See https://example.com/x for it." ),
    ( "ip",         "Connect to 10.1.2.3 now." ),
    ( "path",       "Reads /home/rick/secrets.txt." ),
    ( "credential", "Uses sk-abcdefghijklmnop as key." )
] )
def test_an_entry_with_a_sensitive_shape_is_never_sent_and_is_listed( tmp_path, screen, kind, doc ):
    writer = FakeWriter()
    r = pl.write_purpose_lines( [ entry( "ok", "p1" ), entry( "bad", "p2", doc=doc ) ], writer, tmp_path / "p.jsonl", "w1", screen )
    assert writer.calls == [ [ "a.ok" ] ]
    assert r[ "dropped_screen" ] == [ "a.bad" ]
    assert set( pl.load_lines( tmp_path / "p.jsonl" ) ) == { "p1" }


@pytest.mark.parametrize( "kind, purpose", [
    ( "email",      "Mail the report to alice@example.com." ),
    ( "url",        "Fetch the page at https://example.com/x." ),
    ( "ip",         "Connect to 10.1.2.3 and report." ),
    ( "path",       "Read the file /home/rick/notes.txt." ),
    ( "credential", "Check the key sk-abcdefghijklmnop." )
] )
def test_an_output_line_with_a_sensitive_shape_is_dropped_and_listed( tmp_path, screen, kind, purpose ):
    writer = FakeWriter( { "a.f": purpose } )
    r = pl.write_purpose_lines( [ entry( "f", "p1" ), entry( "g", "p2" ) ], writer, tmp_path / "p.jsonl", "w1", screen )
    assert r[ "dropped_output" ] == [ { "id": "a.f", "reason": f"screen:{kind}" } ]
    assert r[ "written" ] == 1
    assert set( pl.load_lines( tmp_path / "p.jsonl" ) ) == { "p2" }


def test_judge_purpose_rules( screen ):
    assert pl.judge_purpose( "Return the value of the setting.", screen.hits ) is None
    assert pl.judge_purpose( 7, screen.hits ) == "not_text"
    assert pl.judge_purpose( "   ", screen.hits ) == "empty"
    assert pl.judge_purpose( "word " * 25, screen.hits ) is None
    assert pl.judge_purpose( "word " * 26, screen.hits ) == "too_long"


def test_a_missing_answer_is_listed_and_a_bad_line_does_not_stop_the_batch( tmp_path, screen ):
    writer = FakeWriter( { "a.f": None, "a.g": "", "a.h": "Count the rows." } )
    r = pl.write_purpose_lines( [ entry( "f", "p1" ), entry( "g", "p2" ), entry( "h", "p3" ) ], writer, tmp_path / "p.jsonl", "w1", screen )
    assert r[ "missing" ] == [ "a.f" ]
    assert r[ "dropped_output" ] == [ { "id": "a.g", "reason": "empty" } ]
    assert r[ "written" ] == 1


def test_batches_are_cut_at_the_batch_size( tmp_path, screen ):
    writer  = FakeWriter()
    entries = [ entry( f"f{i}", f"p{i}" ) for i in range( 5 ) ]
    pl.write_purpose_lines( entries, writer, tmp_path / "p.jsonl", "w1", screen, batch_size=2 )
    assert [ len( c ) for c in writer.calls ] == [ 2, 2, 1 ]


def test_a_batch_with_no_valid_line_writes_no_file_content( tmp_path, screen ):
    writer = FakeWriter( { "a.f": "" } )
    pl.write_purpose_lines( [ entry( "f", "p1" ) ], writer, tmp_path / "p.jsonl", "w1", screen )
    assert not ( tmp_path / "p.jsonl" ).exists()
