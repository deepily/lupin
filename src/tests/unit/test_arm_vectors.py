#!/usr/bin/env python3
"""
One arm's side file, made from a fake session and a fake embedding provider.

Nothing reaches a database or a model server. The fake provider answers from the text it is sent,
so a vector in the output shows which text went in. The frozen ids name three asks of four notifications.
"""

import hashlib
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from cosa.research.preference_replay.arm_vectors import ARM_TEXT_RULES, load_frozen_ids, main, restamp_text_rule
from cosa.research.preference_replay.context_arms import ARMS
from cosa.research.preference_replay.question_vectors import load_side_file

T0    = datetime( 2026, 11, 10, 12, 0, tzinfo=timezone.utc )
STAMP = { "model": "m", "revision": "r1", "dtype": "float16", "dimensions": 768 }


def _row( note_id, minutes, **extra ):
    """
    Build a Notification-shaped row `minutes` after the fixed ask time.

    Requires:
        - note_id is a string and minutes is a number

    Ensures:
        - returns a namespace with every column the arm builders read
    """
    row = dict( id=note_id, created_at=T0 + timedelta( minutes=minutes ), message=f" question {note_id} ", abstract=None, response_options=None,
                sender_id="claude.code@lupin.deepily.ai#ab12cd34", reply_to=None, thread_id=None, job_id=None, direction="ai_to_human",
                response_requested=True, responded_at=None, response_value=None )
    row.update( extra )
    return SimpleNamespace( **row )


class _Result:
    """Answers the one facts query."""

    def fetchall( self ):
        return [ ( "fake_db", "fake_role", "2026-11-19 12:00:00" ) ]


class _Query:
    """Hands back its rows after a filter call."""

    def __init__( self, rows ):
        self.rows = rows

    def filter( self, _condition ):
        return self

    def all( self ):
        return self.rows


class _Session:
    """A session over four rows; records the statements it ran."""

    def __init__( self, rows ):
        self.rows       = { r.id: r for r in rows }
        self.statements = []
        self.rolled     = False

    def __enter__( self ):
        return self

    def __exit__( self, *exc ):
        return False

    def execute( self, statement ):
        self.statements.append( str( statement ) )
        return _Result()

    def get( self, model, key ):
        return self.rows.get( key )

    def query( self, model ):
        return _Query( list( self.rows.values() ) )

    def rollback( self ):
        self.rolled = True


def _vector_of( text ):
    """
    Give the vector the fake provider returns for a text.

    Requires:
        - text is a string

    Ensures:
        - returns 768 floats with one 20.0 on an axis chosen by a hash of the whole text, so two texts rarely share a vector
    """
    axis = int.from_bytes( hashlib.md5( text.encode() ).digest()[ :2 ], "big" ) % 768
    return [ 20.0 if i == axis else 0.0 for i in range( 768 ) ]


class _Provider:
    """Embeds each text as a one-axis vector and records what it was sent."""

    def __init__( self ):
        self.sent  = []
        self.calls = []
        self.reads = 0

    def describe_engines( self ):
        return { "prose": dict( STAMP, loaded=True ) }

    def generate_embeddings_batch( self, texts, content_type="prose", role=None, pin_fastapi=False ):
        self.sent += texts
        self.calls.append( len( texts ) )
        return [ _vector_of( text ) for text in texts ]


def _rows():
    """
    Build a prior answered question and three asks.

    Ensures:
        - returns the four rows; asks a1, a2, a3 are the frozen ones
    """
    prior = _row( "p", -30, thread_id="t1", response_value="yes", responded_at=T0 - timedelta( minutes=20 ) )
    return [ prior, _row( "a1", 0, thread_id="t1", abstract="why" ), _row( "a2", 5, abstract="more" ), _row( "a3", 9, sender_id="plain@lupin.deepily.ai" ) ]


def _frozen( tmp_path, ids=( "a1", "a2", "a3" ) ):
    """
    Write the frozen id file.

    Requires:
        - tmp_path is a directory path

    Ensures:
        - returns its path, with one {"id": ...} line per id
    """
    path = tmp_path / "frozen.jsonl"
    path.write_text( "".join( json.dumps( { "id": i } ) + "\n" for i in ids ) )
    return str( path )


def _run( tmp_path, arm, *flags, session=None, provider=None ):
    """
    Run main against the fakes.

    Requires:
        - tmp_path is a directory path; flags are extra command-line words

    Ensures:
        - returns ( exit code, printed lines, session, provider, output path )
    """
    session  = session or _Session( _rows() )
    provider = provider or _Provider()
    out      = str( tmp_path / "side.jsonl" )
    lines    = []
    code     = main( [ "--arm", arm, "--frozen-ids", _frozen( tmp_path ), "--out", out, *flags ], printer=lines.append,
                     session_factory=lambda: session, provider_factory=lambda: provider )
    return code, lines, session, provider, out


def test_the_abstract_arm_embeds_question_plus_abstract_in_frozen_order( tmp_path ):
    code, lines, session, provider, out = _run( tmp_path, "Q+A" )
    assert code == 0
    assert provider.sent == [ "question a1\n\nAbstract: why", "question a2\n\nAbstract: more", "question a3" ]
    header, vectors = load_side_file( out )
    assert sorted( vectors ) == [ "a1", "a2", "a3" ] and header[ "count" ] == 3
    assert vectors == { "a1": _vector_of( "question a1\n\nAbstract: why" ), "a2": _vector_of( "question a2\n\nAbstract: more" ),
                        "a3": _vector_of( "question a3" ) }
    assert lines[ 0 ] == "arm Q+A: {'asks': 3, 'with_section': 2, 'no_context': 0, 'arm_input_absent': 1}"
    assert session.statements[ 0 ] == "SET TRANSACTION READ ONLY" and session.rolled


def test_the_header_names_the_arm_its_counts_its_frozen_file_and_its_own_text_rule( tmp_path ):
    _, _, _, _, out = _run( tmp_path, "Q+H" )
    header, _ = load_side_file( out )
    assert header[ "text_rule" ] == ARM_TEXT_RULES[ "Q+H" ]
    facts = header[ "facts" ]
    assert facts[ "arm" ] == "Q+H" and facts[ "frozen_ids" ] == 3 and facts[ "database" ] == "fake_db"
    assert facts[ "frozen_ids_sha256" ] == hashlib.sha256( ( tmp_path / "frozen.jsonl" ).read_bytes() ).hexdigest()
    assert facts[ "arm_counts" ] == { "asks": 3, "with_section": 2, "no_context": 1, "arm_input_absent": 0 }


def test_the_history_arm_embeds_the_thread_answer_then_the_session_answer_then_the_question_alone( tmp_path ):
    _, _, _, provider, _ = _run( tmp_path, "Q+H" )
    assert provider.sent == [ "question a1\n\nPrevious answer on this thread: question p -> yes",
                              "question a2\n\nPrevious answer in this session: question p -> yes", "question a3" ]


def test_the_q_arm_embeds_the_stripped_question_alone( tmp_path ):
    _, _, _, provider, _ = _run( tmp_path, "Q" )
    assert provider.sent == [ "question a1", "question a2", "question a3" ]


def test_probe_only_writes_nothing_and_reports_the_timing( tmp_path ):
    code, lines, _, provider, out = _run( tmp_path, "Q+P", "--probe-only" )
    assert code == 0 and len( provider.sent ) == 3
    assert lines[ 1 ].startswith( "probe: 3 texts in " ) and not ( tmp_path / "side.jsonl" ).exists()


def test_a_rejected_vector_gives_exit_one_and_the_file_is_still_written( tmp_path ):
    class _Bad( _Provider ):
        def generate_embeddings_batch( self, texts, content_type="prose", role=None, pin_fastapi=False ):
            return [ [ 1.0, 2.0 ] for _ in texts ]
    code, lines, _, _, out = _run( tmp_path, "Q", provider=_Bad() )
    header, vectors = load_side_file( out )
    assert code == 1 and vectors == {} and len( header[ "rejects" ] ) == 3
    assert lines[ -1 ].startswith( f"wrote {out}: 0 vectors, 3 rejects" )


def test_a_frozen_ask_with_no_notification_is_refused_before_anything_is_embedded( tmp_path ):
    provider = _Provider()
    with pytest.raises( LookupError, match="no notification row" ):
        main( [ "--arm", "Q", "--frozen-ids", _frozen( tmp_path, ( "a1", "ghost" ) ), "--out", str( tmp_path / "x" ) ], printer=print,
              session_factory=lambda: _Session( _rows() ), provider_factory=lambda: provider )
    assert provider.sent == []


def test_equal_length_texts_keep_their_own_vectors_so_a_swap_of_ids_would_show( tmp_path ):
    _, _, _, _, out = _run( tmp_path, "Q" )
    _, vectors = load_side_file( out )
    assert len( "question a1" ) == len( "question a2" ) and _vector_of( "question a1" ) != _vector_of( "question a2" )
    assert vectors[ "a1" ] == _vector_of( "question a1" ) and vectors[ "a2" ] == _vector_of( "question a2" ) and vectors[ "a3" ] == _vector_of( "question a3" )


def test_the_probe_line_projects_the_probe_time_over_the_whole_cohort( tmp_path ):
    ids      = [ f"b{n}" for n in range( 30 ) ]
    rows     = [ _row( ask_id, n ) for n, ask_id in enumerate( ids ) ]
    ticks    = iter( [ 0.0, 4.0, 9.0 ] )
    lines    = []
    main( [ "--arm", "Q", "--frozen-ids", _frozen( tmp_path, ids ), "--out", str( tmp_path / "x" ), "--probe-only" ], printer=lines.append,
          session_factory=lambda: _Session( rows ), provider_factory=_Provider, clock=lambda: next( ticks ) )
    assert lines[ 1 ] == "probe: 20 texts in 4.00s, projected 6.0s for 30"


def test_batch_size_sets_how_many_texts_go_in_each_call( tmp_path ):
    _, _, _, provider, out = _run( tmp_path, "Q", "--batch-size", "2" )
    assert provider.calls == [ 2, 1 ] and len( load_side_file( out )[ 1 ] ) == 3


def test_the_default_batch_holds_the_whole_small_cohort_in_one_call( tmp_path ):
    _, _, _, provider, _ = _run( tmp_path, "Q" )
    assert provider.calls == [ 3 ]


def test_every_arm_has_a_text_rule():
    assert sorted( ARM_TEXT_RULES ) == sorted( ARMS )


def test_frozen_ids_are_read_in_file_order( tmp_path ):
    assert load_frozen_ids( _frozen( tmp_path, ( "c", "a", "b" ) ) ) == [ "c", "a", "b" ]


@pytest.mark.parametrize( "ids, message", [ ( (), "holds no ids" ), ( ( "a", "a" ), "holds an id twice" ) ] )
def test_a_frozen_file_with_no_ids_or_a_repeat_is_refused( tmp_path, ids, message ):
    with pytest.raises( ValueError, match=message ):
        load_frozen_ids( _frozen( tmp_path, ids ) )


def test_restamp_changes_only_the_text_rule( tmp_path ):
    path = tmp_path / "f.jsonl"
    path.write_text( json.dumps( { "kind": "header", "text_rule": "old", "count": 1 } ) + "\n" + json.dumps( { "id": "x" } ) )
    restamp_text_rule( str( path ), "new rule" )
    lines = path.read_text().split( "\n" )
    assert json.loads( lines[ 0 ] ) == { "kind": "header", "text_rule": "new rule", "count": 1 } and json.loads( lines[ 1 ] ) == { "id": "x" }
    assert not ( tmp_path / "f.jsonl.part" ).exists()
