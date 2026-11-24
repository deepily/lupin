"""
Tests for src/scripts/answer_attrition_table.py.

The positive control plants one answer of each unit in a fixture database the test builds. It never touches the live one.
The survive-or-drop matrix below was written before the code ran. The read-only tests show a write fails.
That write is made inside the script's own transaction, and the fixture is unchanged afterwards.
"""

import contextlib
import hashlib
import json
import sqlite3
import subprocess
import sys
import types
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

import cosa.utils.util as cu

sys.path.insert( 0, cu.get_project_root() + "/src/scripts" )
import answer_attrition_table as aat   # noqa: E402

ME      = "00000000-0000-0000-0000-00000000aaaa"
OPTIONS = { "questions": [ { "header": "Pick", "multi_select": False, "options": [ { "label": "Alpha" }, { "label": "Beta (Recommended)" } ] },
                           { "header": "Tags", "multi_select": True,  "options": [ { "label": "x" }, { "label": "y" } ] } ] }
STEPS   = list( aat.STEP_SYMBOLS )

# The literal matrix: one row per unit, one column per step, in STEPS order. Written before the first run.
#          1p 1c  2  3 3g  4 4n 5a vote 5b  6 cmt miss left
MATRIX = {
    "stance:yes"        : [ 1, 2, 1, 1, 1, 0, 1, 1, 1, 0, 1, 0, 0, 0 ],   # the plain reader also reads "yes, but later" as a yes
    "stance:no"         : [ 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 1, 0, 0, 0 ],
    "stance:neither"    : [ 1, 1, 1, 1, 1, 0, 1, 1, 1, 0, 1, 0, 0, 0 ],
    "stance:none"       : [ 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0 ],   # "yes, but later" is unread from step 2 on
    "comment"           : [ 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 1, 0, 0 ],   # stored, never a vote, never moves the score
    "typed_other"       : [ 1, 1, 1, 1, 1, 1, 0, 1, 0, 0, 1, 0, 1, 1 ],
    "multi_pick"        : [ 1, 1, 1, 1, 1, 0, 0, 1, 1, 0, 1, 0, 0, 0 ],
    "single_listed_pick": [ 1, 1, 1, 1, 1, 0, 0, 1, 1, 0, 1, 0, 0, 0 ],
    "empty_selection"   : [ 1, 1, 1, 1, 1, 0, 0, 1, 0, 0, 1, 0, 0, 0 ],
    "open_text"         : [ 1, 1, 1, 1, 1, 0, 0, 1, 0, 0, 1, 0, 0, 0 ],
    "batch_field"       : [ 1, 1, 1, 1, 1, 0, 0, 1, 0, 0, 1, 0, 0, 0 ],
    "timeout"           : [ 1, 1, 0, 0, 0, 0, 1, 1, 1, 0, 1, 0, 0, 0 ],   # a timeout default is stored and voted as an answer
}


def person( value, source="ui" ):
    """A stored answer as the on-screen route writes it."""
    return { "value": value, "source": source, "answered_by": { "user_id": ME } }


PLANTS = [
    ( "p1", "yes_no",           person( "yes" ),                                                None ),
    ( "p2", "yes_no",           person( "no [comment: not ready]" ),                            None ),
    ( "p3", "yes_no",           person( "neither" ),                                            None ),
    ( "p4", "yes_no",           person( "yes, but later" ),                                     None ),
    ( "p5", "multiple_choice",  person( json.dumps( { "answers": { "Pick": "Neither, ask me tomorrow", "Tags": [ "x" ] } } ) ), OPTIONS ),
    ( "p6", "multiple_choice",  person( json.dumps( { "answers": { "Pick": "Alpha", "Tags": [] } } ) ),                       OPTIONS ),
    ( "p7", "open_ended",       person( "free words" ),                                         None ),
    ( "p8", "open_ended_batch", person( json.dumps( { "answers": { "Why": "because" } } ) ),    None ),
    ( "p9", "yes_no",           { "value": "yes", "source": "timeout_default" },                None ),
]
IDS = { name: f"{i:032x}" for i, ( name, *_ ) in enumerate( PLANTS, start=1 ) }


def build_fixture( path, with_log=True ):
    """Build the fixture file: one planted answer per unit, evidence for two, and some reveals."""
    con = sqlite3.connect( path )
    con.execute( "CREATE TABLE notifications ( id TEXT, recipient_id TEXT, response_type TEXT, response_value TEXT, response_options TEXT, created_at TEXT, responded_at TEXT, sender_id TEXT )" )
    con.execute( "CREATE TABLE preference_evidence ( notification_id TEXT, field_key TEXT, retracted_at TEXT )" )
    con.execute( "CREATE TABLE prediction_log ( notification_id TEXT, fold_opened_at TEXT, draft_at_reveal TEXT )" )
    for name, kind, value, options in PLANTS:
        con.execute( "INSERT INTO notifications VALUES ( ?, ?, ?, ?, ?, ?, ?, ? )",
                     ( IDS[ name ], ME.replace( "-", "" ), kind, json.dumps( value ), None if options is None else json.dumps( options ),
                       "2026-10-01T10:00:00+00:00", "2026-10-01T10:05:00+00:00", "x@lupin.deepily.ai#1" ) )
    con.execute( "INSERT INTO preference_evidence VALUES ( ?, ?, NULL )", ( IDS[ "p2" ], aat.WHOLE ) )
    con.execute( "INSERT INTO preference_evidence VALUES ( ?, ?, NULL )", ( IDS[ "p5" ], "Pick" ) )
    con.execute( "INSERT INTO preference_evidence VALUES ( ?, ?, '2026-10-02T00:00:00+00:00' )", ( IDS[ "p1" ], aat.WHOLE ) )   # retracted: never counts
    if with_log:
        con.execute( "INSERT INTO prediction_log VALUES ( ?, '2026-10-01T10:01:00+00:00', ? )", ( IDS[ "p1" ], json.dumps( { "value": "no" } ) ) )   # a draft that differs
        con.execute( "INSERT INTO prediction_log VALUES ( ?, '2026-10-01T10:09:00+00:00', NULL )", ( IDS[ "p3" ], ) )                                  # revealed after the answer
        con.execute( "INSERT INTO prediction_log VALUES ( ?, '2026-10-01T10:01:00+00:00', NULL )", ( "ffffffffffffffffffffffffffffffff", ) )         # not an answered row
    con.commit()
    con.close()


@pytest.fixture
def fixture_path( tmp_path ):
    """A fixture database file."""
    path = str( tmp_path / "fixture.sqlite" )
    build_fixture( path )
    return path


def file_digest( path ):
    """The sha256 of a file."""
    with open( path, "rb" ) as handle: return hashlib.sha256( handle.read() ).hexdigest()


def measured( path ):
    """Measure the fixture through the script's own loaders."""
    with aat.open_archive_session( path ) as session: rows, evidence, log = aat.read_tables( session )
    return aat.measure( rows, evidence, log, "fixture" ), rows, evidence, log


# ---------------------------------------------------------------- the positive control

def test_survive_or_drop_matrix_matches_the_literal_matrix( fixture_path ):
    """Every unit's count at every step equals the literal matrix."""
    result, *_ = measured( fixture_path )
    actual = { tag: [ result[ "units" ][ tag ].get( step, 0 ) for step in STEPS ] for tag in MATRIX }
    assert actual == MATRIX
    assert all( aat.STEP_SYMBOLS[ step ] for step in STEPS )
    assert set( result[ "units" ] ) == set( MATRIX )


def test_the_planted_populations_are_counted_by_unit( fixture_path ):
    """The planted populations, denominators, unread shape and label equality."""
    result, *_ = measured( fixture_path )
    assert result[ "answers" ] == { "yes_no": 4, "multiple_choice": 2, "open_ended": 1, "open_ended_batch": 1 }
    assert result[ "timeouts" ] == { "yes_no": 1 }
    assert result[ "unread_shapes" ] == { "first word is a stance, rest not read": 1 }
    assert result[ "label_equality" ] == { "matches no label": 1, "equals a label character for character (a click cannot be told from typing)": 1 }
    assert result[ "typed_denominators" ] == { "typed fields": 1, "cards holding a typed field": 1, "distinct ( card, header ) pairs": 1,
                                               "distinct ( header, text ) pairs": 1, "typed fields on multiple_choice": 1 }
    assert result[ "evidence_rows" ] == 2   # the retracted row is not counted


def test_step_one_two_columns_differ_where_production_reading_loses_something( fixture_path ):
    """The plain reader reads "yes, but later" as yes and the production reader does not."""
    result, *_ = measured( fixture_path )
    assert result[ "units" ][ "stance:yes" ][ "1p_production_readers" ] == 1
    assert result[ "units" ][ "stance:yes" ][ "1c_plain_first_word_reader" ] == 2
    assert result[ "units" ][ "stance:none" ][ "1c_plain_first_word_reader" ] if "1c_plain_first_word_reader" in result[ "units" ][ "stance:none" ] else True


def test_the_draft_summary_counts_reveals_and_drafts( fixture_path ):
    """One reveal before the answer, one after it, and one log row on no answered row."""
    result, *_ = measured( fixture_path )
    assert result[ "drafts" ] == { "reveals on answered rows": 2, "reveals before the answer": 1, "stored drafts": 1, "draft outcome: switched": 1 }


def test_the_prompt_probe_finds_an_answer_when_the_builder_carries_it( fixture_path ):
    """A builder that prints the answer makes units survive the probe; the real one drops all."""
    _, rows, *_ = measured( fixture_path )
    row   = next( r for r in rows if r[ "id" ] == IDS[ "p1" ] )
    units = aat.production_units( row )
    leaky = lambda episode, layers=None: "Q " + str( episode.get( "answer", "" ) )
    assert aat.prompt_units( row, units, leaky ) == units
    assert aat.prompt_units( row, units ) == []
    odd = { **row, "response_type": "open_ended" }   # a type the baseline does not forecast is probed as yes/no
    assert aat.prompt_units( odd, units ) == []


# ---------------------------------------------------------------- the read-only tests

def test_a_write_inside_the_scripts_transaction_fails_and_the_fixture_is_unchanged( fixture_path, monkeypatch ):
    """A write made inside read_tables fails, and the fixture file is the same afterwards."""
    before = file_digest( fixture_path )
    # a connection with no mode=ro: only the script's own READ ONLY statement can stop the write
    with Session( create_engine( f"sqlite:///{fixture_path}" ) ) as session:
        def write_inside( raw ):
            session.execute( text( "INSERT INTO preference_evidence VALUES ( 'zz', 'zz', NULL )" ) )
        monkeypatch.setattr( aat, "clean_row", write_inside )
        with pytest.raises( OperationalError, match="readonly|read-only|read only" ): aat.read_tables( session )
    assert file_digest( fixture_path ) == before
    con = sqlite3.connect( fixture_path )
    assert con.execute( "SELECT count(*) FROM preference_evidence" ).fetchone()[ 0 ] == 3
    con.close()


def test_the_archive_connection_cannot_write_at_all( fixture_path ):
    """The URI itself is read-only: a write outside read_tables fails too."""
    with aat.open_archive_session( fixture_path ) as session:
        with pytest.raises( OperationalError ): session.execute( text( "INSERT INTO preference_evidence VALUES ( 'a', 'b', NULL )" ) )


def test_a_full_run_leaves_the_fixture_untouched( fixture_path, tmp_path ):
    """Reading and measuring the fixture changes no byte of it."""
    before = file_digest( fixture_path )
    records = tmp_path / "records.jsonl"
    records.write_text( "".join( json.dumps( { "id": IDS[ n ] } ) + "\n" for n in ( "p1", "p5" ) ) )
    with aat.open_archive_session( fixture_path ) as live: result = aat.run( fixture_path, str( records ), live )
    assert file_digest( fixture_path ) == before
    assert [ p[ "population" ] for p in result[ "populations" ] ] == [ "run 2 archive, the evaluation cards", "run 2 archive, every answered row",
                                                                         f"live database, asked on or after {aat.WINDOW_START}", "live database, every answered row" ]
    assert result[ "populations" ][ 0 ][ "answers" ] == { "yes_no": 1, "multiple_choice": 1 }
    assert result[ "populations" ][ 2 ][ "answers" ] == { "yes_no": 4, "multiple_choice": 2 }


def test_the_first_statement_is_the_read_only_statement_and_the_transaction_is_rolled_back( fixture_path ):
    """Record the statements and the rollback of one read_tables call."""
    seen, rolled = [], []
    engine = create_engine( f"sqlite:///file:{fixture_path}?mode=ro&uri=true" )
    from sqlalchemy import event
    event.listen( engine, "before_cursor_execute", lambda conn, cur, stmt, *a: seen.append( stmt ) )
    event.listen( engine, "rollback", lambda conn: rolled.append( 1 ) )
    with Session( engine ) as session: aat.read_tables( session )
    assert seen[ 0 ] == "PRAGMA query_only = ON"
    assert rolled


def test_postgresql_gets_set_transaction_read_only_and_an_unknown_dialect_is_refused():
    """The statement chosen per dialect, and a refusal for a dialect with none."""
    said = []
    def fake( name ):
        return types.SimpleNamespace( get_bind=lambda: types.SimpleNamespace( dialect=types.SimpleNamespace( name=name ) ), execute=lambda stmt: said.append( str( stmt ) ) )
    aat.set_read_only( fake( "postgresql" ) )
    assert said == [ "SET TRANSACTION READ ONLY" ]
    with pytest.raises( ValueError, match="mysql" ): aat.set_read_only( fake( "mysql" ) )


def test_the_transaction_is_rolled_back_when_a_read_fails():
    """An error mid-read still ends in a rollback."""
    calls = []
    class Boom:
        def get_bind( self ): return types.SimpleNamespace( dialect=types.SimpleNamespace( name="sqlite" ) )
        def execute( self, stmt ):
            calls.append( str( stmt ) )
            if len( calls ) == 2: raise RuntimeError( "read failed" )
        def rollback( self ): calls.append( "ROLLBACK" )
    with pytest.raises( RuntimeError, match="read failed" ): aat.read_tables( Boom() )
    assert calls[ -1 ] == "ROLLBACK"


# ---------------------------------------------------------------- the output

def test_the_markdown_receipt_names_run_time_sha_symbols_and_findings( fixture_path, tmp_path ):
    """The receipt opens with the run time and sha, and lists each symbol and finding."""
    with aat.open_archive_session( fixture_path ) as session: result = aat.run( None, None, session )
    assert [ p[ "population" ] for p in result[ "populations" ] ][ 0 ].startswith( "live database" )
    md = aat.render_markdown( result )
    assert md.splitlines()[ 2 ].startswith( f"**Run time:** {result[ 'run_time_utc' ]} UTC. **Code:** git sha `{result[ 'git_sha' ]}`" )
    assert all( symbol in md for symbol in aat.STEP_SYMBOLS.values() )
    assert "stance:yes: production readers 1, plain reader 2" in md
    clean = aat.render_markdown( { "run_time_utc": "t", "git_sha": "s", "populations": [] } )
    assert "- none" in clean


def test_main_writes_the_json_and_the_markdown( fixture_path, tmp_path, monkeypatch, capsys ):
    """main() with the archive only, then with --live through a patched session factory."""
    records = tmp_path / "records.jsonl"
    records.write_text( json.dumps( { "id": IDS[ "p1" ] } ) + "\n" )
    out_json, out_md = tmp_path / "r.json", tmp_path / "r.md"
    aat.main( [ "--archive", fixture_path, "--records", str( records ), "--out-json", str( out_json ), "--out-md", str( out_md ) ] )
    assert len( json.loads( out_json.read_text() )[ "populations" ] ) == 2
    assert out_md.read_text() in capsys.readouterr().out
    import cosa.rest.db.database as database
    @contextlib.contextmanager
    def fake_db():
        with aat.open_archive_session( fixture_path ) as session: yield session
    monkeypatch.setattr( database, "get_db", fake_db )
    aat.main( [ "--live", "--out-json", str( out_json ), "--out-md", str( out_md ) ] )
    assert [ p[ "population" ] for p in json.loads( out_json.read_text() )[ "populations" ] ][ 0 ].startswith( "live database" )


def test_provenance_names_the_sha_and_falls_back_when_git_cannot_say( monkeypatch ):
    """The sha comes from check_bundle_freshness.current_sha; a git failure reads unknown."""
    real = aat.provenance()
    assert real[ "git_sha" ] == aat.current_sha( Path( cu.get_project_root() ) ) != "unknown" and real[ "run_time_utc" ].endswith( "+00:00" )
    monkeypatch.setattr( aat, "current_sha", lambda root: "unknown" )
    assert aat.provenance()[ "git_sha" ] == "unknown"


# ---------------------------------------------------------------- the helpers

def clean( kind, value, options=None, rid="r1" ):
    """A clean row for a helper test."""
    return aat.clean_row( { "id": rid, "recipient_id": ME, "response_type": kind, "response_value": value, "response_options": options } )


def test_as_json_decodes_text_and_passes_other_values_through():
    """JSON text decodes, bad text is None, a decoded value passes through."""
    assert aat.as_json( '{"a": 1}' ) == { "a": 1 }
    assert aat.as_json( "not json" ) is None
    assert aat.as_json( { "a": 1 } ) == { "a": 1 }
    assert aat.as_json( b'{"a": 1}' ) == { "a": 1 } and aat.as_json( b"\xff\xfe" ) is None and aat.as_json( "  " ) is None
    assert aat.norm_id( "AB-cd" ) == "abcd"


def test_schema_of_reads_a_card_schema_and_nothing_else():
    """A schema gives labels and the multi flag; anything else gives {}."""
    schema = aat.schema_of( json.dumps( OPTIONS ) )
    assert schema[ "Tags" ] == { "labels": { "x", "y" }, "multi": True }
    assert aat.schema_of( None ) == {} and aat.schema_of( { "questions": "no" } ) == {}
    odd = aat.schema_of( { "questions": [ "text", { "header": 3 }, { "header": "H" } ] } )
    assert odd == { "H": { "labels": set(), "multi": False } }


def test_field_units_classifies_every_shape():
    """Lists, blank text, batch text, open text, listed picks and typed text."""
    labels = { "a", "b" }
    assert aat.field_units( "multiple_choice", "H", [], labels ) == [ ( "empty_selection", "H", "" ) ]
    assert aat.field_units( "multiple_choice", "H", [ "a", " z " ], labels ) == [ ( "multi_pick", "H", "a" ), ( "typed_other", "H", "z" ) ]
    assert aat.field_units( "multiple_choice", "H", "  ", labels ) == [ ( "empty_selection", "H", "" ) ]
    assert aat.field_units( "open_ended_batch", "H", "t", set() ) == [ ( "batch_field", "H", "t" ) ]
    assert aat.field_units( "multiple_choice", "H", "t", set() ) == [ ( "open_text", "H", "t" ) ]
    assert aat.field_units( "multiple_choice", "H", "a", labels ) == [ ( "single_listed_pick", "H", "a" ) ]
    assert aat.field_units( "multiple_choice", "H", "q", labels ) == [ ( "typed_other", "H", "q" ) ]


def test_answers_map_and_is_timeout_and_timeout_units():
    """Each stored shape of an answers map, and the timeout helpers."""
    assert aat.answers_map( "x" ) is None
    assert aat.answers_map( { "answers": { "a": "b" } } ) == { "a": "b" }
    assert aat.answers_map( { "value": json.dumps( { "answers": { "a": "b" } } ) } ) == { "a": "b" }
    assert aat.answers_map( { "value": { "answers": { "a": "b" } } } ) == { "a": "b" }
    assert aat.answers_map( { "value": 3 } ) is None
    assert aat.is_timeout( clean( "yes_no", { "value": "yes", "source": "timeout_default" } ) )
    assert not aat.is_timeout( clean( "yes_no", None ) )
    assert aat.timeout_units( clean( "yes_no", { "value": "yes", "source": "timeout_default" } ) ) == [ ( "timeout", aat.WHOLE, "yes" ) ]
    assert aat.timeout_units( clean( "multiple_choice", { "value": { "a": 1 }, "source": "timeout_default" } ) ) == [ ( "timeout", aat.WHOLE, '{"a": 1}' ) ]


def test_production_and_plain_readers_on_odd_stored_answers():
    """Blank open-ended text, unreadable card answers, a non-text yes/no and a non-text field."""
    assert aat.production_units( clean( "open_ended", { "value": "  " } ) ) == []
    assert aat.plain_units( clean( "open_ended", { "value": "  " } ) ) == []
    assert aat.production_units( clean( "multiple_choice", { "value": "garbage" } ) ) == []
    assert aat.plain_units( clean( "multiple_choice", { "value": "garbage" } ) ) == []
    assert aat.plain_units( clean( "yes_no", { "value": None } ) ) == [ ( "stance:none", aat.WHOLE, "" ) ]
    assert aat.plain_units( clean( "yes_no", { "value": "yes [comment: c]" } ) ) == [ ( "stance:yes", aat.WHOLE, "" ), ( "comment", aat.WHOLE, "" ) ]
    assert aat.plain_units( clean( "open_ended_batch", { "answers": { "n": 5 } } ) ) == [ ( "batch_field", "n", "5" ) ]


def test_derived_writer_and_store_units_on_edge_answers():
    """Unread, none and text answers; every writer rule; stored values that cannot be read."""
    row = clean( "multiple_choice", { "value": "garbage" } )
    assert aat.derived_units( { "kind": "unread", "text": "g" }, row ) == []
    assert aat.derived_units( { "kind": "text", "text": "  " }, row ) == []
    assert aat.derived_units( { "kind": "text", "text": None }, row ) == []
    assert aat.derived_units( { "kind": "text", "text": "t" }, row ) == [ ( "open_text", aat.WHOLE, "t" ) ]
    assert aat.derived_units( { "kind": "stance", "stance": "no", "qualifier": None }, row ) == [ ( "stance:no", aat.WHOLE, "" ) ]
    fields = { "H": { "mode": "single", "selected": [], "text": None } }
    assert aat.derived_units( { "kind": "fields", "fields": fields }, row ) == [ ( "empty_selection", "H", "" ) ]
    entries = [ { "field_key": aat.WHOLE, "text": "" }, { "field_key": "H", "text": "word" } ]
    kept = aat.writer_units( [ ( "stance:yes", aat.WHOLE, "" ), ( "comment", aat.WHOLE, "" ), ( "empty_selection", aat.WHOLE, "" ), ( "open_text", "H", "word" ),
                               ( "open_text", "H", "absent" ), ( "open_text", "gone", "x" ) ], entries )
    assert kept == [ ( "empty_selection", aat.WHOLE, "" ), ( "open_text", "H", "word" ) ]
    yes_no = clean( "yes_no", { "value": "yes" } )
    assert aat.store_units( yes_no, None ) == [] and aat.store_units( yes_no, "maybe" ) == []
    assert aat.store_units( clean( "open_ended", { "value": "t" } ), "  " ) == []
    assert aat.store_units( clean( "open_ended", { "value": "t" } ), "t" ) == [ ( "open_text", aat.WHOLE, "t" ) ]
    assert aat.store_units( clean( "multiple_choice", { "value": "t" } ), "not json" ) == []
    assert aat.neighbour_units( yes_no, None ) == [] and aat.neighbour_units( clean( "open_ended", { "value": "t" } ), "t" ) == []
    assert aat.neighbour_units( yes_no, "maybe" ) == []


def test_scoring_probes_on_every_kind_of_answer():
    """No forecast possible, open-ended, a card timeout, and a card the comparator cannot match."""
    assert aat.perfect_forecast( clean( "yes_no", { "value": "maybe" } ) ) is None
    assert aat.perfect_forecast( clean( "multiple_choice", { "value": "garbage" } ) ) is None
    assert aat.score_units( clean( "yes_no", { "value": "maybe" } ), [] ) == { "match": [], "detail": [], "typed_miss": [], "typed_left_out": [] }
    open_row = clean( "open_ended", { "value": "same words" } )
    assert aat.score_units( open_row, aat.production_units( open_row ) )[ "match" ] == [ ( "open_text", aat.WHOLE, "same words" ) ]
    mc_timeout = clean( "multiple_choice", { "value": json.dumps( { "answers": { "Pick": "Alpha" } } ), "source": "timeout_default" }, OPTIONS )
    assert aat.score_units( mc_timeout, aat.timeout_units( mc_timeout ) )[ "match" ] == aat.timeout_units( mc_timeout )
    unmatched = clean( "multiple_choice", { "value": json.dumps( { "answers": { "Pick": "Alpha" } } ) }, OPTIONS )
    from cosa.research.preference_replay import replay_loop
    saved, replay_loop._score = replay_loop._score, lambda *a: False
    try: assert aat.score_units( unmatched, aat.production_units( unmatched ) )[ "match" ] == []
    finally: replay_loop._score = saved


def test_label_equality_and_typed_denominators_classify_every_shape():
    """Each label-equality class once, and the typed denominators over two cards."""
    answers = { "Pick": "Alpha", "Tags": [ "x" ] }
    cases = [ ( "Alpha", "equals a label character for character (a click cannot be told from typing)" ), ( " Alpha ", "equals a label except surrounding spaces" ),
              ( "alpha", "equals a label except case or the (Recommended) suffix" ), ( "Alpha but more", "starts with a label then adds words" ), ( "zzz", "matches no label" ) ]
    for typed, expected in cases:
        row = clean( "multiple_choice", { "value": json.dumps( { "answers": { "Pick": typed, "Blank": " ", "Num": 3 } } ) }, OPTIONS )
        assert aat.label_equality( row ) == Counter( { expected: 1 } ), typed
    row = clean( "multiple_choice", { "answers": answers }, OPTIONS, rid="a" )
    other = clean( "multiple_choice", { "answers": { "Pick": "novel" } }, OPTIONS, rid="b" )
    units = { "a": aat.production_units( row ), "b": aat.production_units( other ) }
    assert aat.typed_denominators( [ row, other ], units ) == { "typed fields": 1, "cards holding a typed field": 1, "distinct ( card, header ) pairs": 1,
                                                                "distinct ( header, text ) pairs": 1, "typed fields on multiple_choice": 1 }


def test_measure_counts_odd_rows_and_the_three_unread_shapes():
    """A stored value that is not an object, and the three shapes of unread yes/no text."""
    rows = [ clean( "yes_no", "plain text", rid="o" ), clean( "yes_no", { "value": None }, rid="e" ), clean( "yes_no", { "value": "yes, later" }, rid="s" ),
             clean( "yes_no", { "value": "hmm" }, rid="n" ), clean( "yes_no", { "value": "yes", "source": "timeout_default" }, rid="t" ) ]
    result = aat.measure( rows, [], [], "odd" )
    assert result[ "stored_value_not_an_object" ] == { "yes_no": 1 }
    assert result[ "unread_shapes" ] == { "empty or missing text": 1, "first word is a stance, rest not read": 1, "no stance word": 1 }
    assert result[ "timeouts" ] == { "yes_no": 1 }
    assert result[ "unreadable_card_answers" ] == {}
    cards = aat.measure( [ clean( "multiple_choice", { "value": "garbage" } ), clean( "open_ended_batch", { "value": "garbage" }, rid="b" ) ], [], [], "cards" )
    assert cards[ "unreadable_card_answers" ] == { "multiple_choice": 1, "open_ended_batch": 1 } and cards[ "unread_shapes" ] == {}
