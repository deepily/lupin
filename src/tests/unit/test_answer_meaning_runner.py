"""
The meaning runner and the store hook (plan section 8, the fourth build step).

Rows go through the real repository into a scratch copy of the tables. The model layer is a double.
"""
import json
import sys
import types
import uuid
from datetime import datetime, timezone

import pytest

from cosa.agents.answer_meaning import on_store, rules, runner
from cosa.research.preference_replay.scratch_db import scratch_session, session_scope
from cosa.rest.db.repositories.answer_meaning_repository import ( SCHEMA_VERSION_V2, AnswerMeaningRepository, MeaningAlreadyRecorded )
from cosa.rest.postgres_models import AnswerMeaning, Notification

ANNOTATOR = "model-x:abc+answer-meaning-v2"
ANSWERED  = datetime( 2026, 11, 20, 12, 0, tzinfo=timezone.utc )
STAMP     = ( "certified_classes: [yes]   uncertified: [no, neither, support-on-no, dissent, re_frame]   "
              "basis: fewer than 20 of Rick's own labelled cards in the class, or fewer than 30 slice cards" )


def nid( n ): return uuid.UUID( f"aaaaaaaa-0000-4000-8000-{n:012x}" )


def ask( db, n, response_type="yes_no", value="yes", source="ui", options=None ):
    stored = None if value is None else { "value": value, "source": source }
    db.add( Notification( id=nid( n ), recipient_id=nid( 999 ), sender_id="claude.code@lupin#sess1234", title="t", message="m", type="task",
                          priority="low", response_requested=True, response_type=response_type, response_value=stored,
                          response_options=options, created_at=datetime( 2026, 11, 20, 0, 0, n, tzinfo=timezone.utc ), responded_at=ANSWERED ) )
    db.commit()


@pytest.fixture
def db():
    with scratch_session() as session:
        AnswerMeaning.__table__.create( session.get_bind(), checkfirst=True )
        yield session


@pytest.fixture
def scope( db ): return lambda: session_scope_of( db )


def session_scope_of( db ):
    from contextlib import contextmanager
    @contextmanager
    def _scope():
        yield db
        db.commit()
    return _scope()


class Model:
    """A model-layer double: labels every pending field support, and records the drafts it saw."""

    def __init__( self ): self.drafts = []

    def __call__( self, draft ):
        self.drafts.append( draft )
        native = {}
        for key, field in draft[ "fields" ].items():
            native[ key ] = { "kind": field[ "kind" ], "relation": field[ "relation" ] or "support" }
            if field[ "relation" ] is None and field[ "stance" ] is None:
                native[ key ].update( stance="yes", stance_source="inferred" )
        return { "native_answer": native, "acts": [], "conditions": [], "supporting_spans": None, "uncertainty": 0.2,
                 "unknowns": list( draft[ "unknowns" ] ) }


def test_meaning_of_merges_the_models_label_into_the_full_entry():
    draft = rules.draft_of( types.SimpleNamespace( response_type="yes_no", response_value={ "value": "Yeah, if", "source": "ui" },
                                                   response_options=None, response_default=None, title="t", message="m", abstract=None ) )
    entry = runner.meaning_of( draft, Model() )[ "native_answer" ][ "answer" ]
    assert entry == { "kind": "yes_no_stance", "selected_option_ids": [], "empty_selection": False, "write_in_text": None,
                      "referred_option_ids": [], "text": "Yeah, if", "relation": "support", "stance": "yes", "stance_source": "inferred" }


def test_meaning_of_keeps_a_plain_entry_and_a_field_the_model_could_not_label():
    options = { "questions": [ { "header": "A", "options": [ { "label": "x" } ] }, { "header": "B", "options": [ { "label": "y" } ] } ] }
    draft   = rules.draft_of( types.SimpleNamespace( response_type="multiple_choice", response_default=None, title="t", message="m", abstract=None,
                                                     response_options=options, response_value={ "value": json.dumps( { "answers": { "A": [], "B": "typed" } } ), "source": "ui" } ) )
    def failed( d ): return { "native_answer": { "B": { "kind": "write_in_text" } }, "acts": [], "conditions": [], "supporting_spans": None,
                              "uncertainty": None, "unknowns": [ "unreadable_payload" ] }
    meaning = runner.meaning_of( draft, failed )
    assert meaning[ "native_answer" ][ "A" ][ "empty_selection" ] is True
    assert "relation" not in meaning[ "native_answer" ][ "B" ] and meaning[ "unknowns" ] == [ "unreadable_payload" ]


def test_record_one_writes_a_v2_row_with_the_answers_time_and_session( db, scope ):
    ask( db, 1, value="no" )
    report = runner.record_one( scope, str( nid( 1 ) ), ANNOTATOR, Model() )
    row    = AnswerMeaningRepository( db ).get( nid( 1 ), SCHEMA_VERSION_V2, ANNOTATOR )
    assert report == { "status": "written", "relations": [ "no_comment" ], "unknowns": [] }
    assert ( row.source, row.session_key, row.alignment, row.uncertainty ) == ( "labeller", "sess1234", "unknown", 0.2 )
    assert row.native_answer[ "answer" ][ "relation" ] == "no_comment"
    assert row.answered_at.replace( tzinfo=timezone.utc ) == ANSWERED


def test_a_second_run_adds_no_row_and_calls_no_model( db, scope ):
    ask( db, 1, value="yes [comment: later]" )
    model = Model()
    runner.record_one( scope, str( nid( 1 ) ), ANNOTATOR, model )
    assert runner.record_one( scope, str( nid( 1 ) ), ANNOTATOR, model ) == { "status": "already" }
    assert len( model.drafts ) == 1 and db.query( AnswerMeaning ).count() == 1


def test_a_row_written_between_the_check_and_the_add_is_counted_not_raised( db, scope, monkeypatch ):
    ask( db, 1 )
    def taken( self, *args, **kwargs ): raise MeaningAlreadyRecorded( "taken" )
    monkeypatch.setattr( AnswerMeaningRepository, "add", taken )
    assert runner.record_one( scope, str( nid( 1 ) ), ANNOTATOR, Model() ) == { "status": "already" }


def test_a_missing_notification_is_an_error( db, scope ):
    with pytest.raises( LookupError, match="no notification" ): runner.record_one( scope, str( nid( 7 ) ), ANNOTATOR, Model() )


def test_stored_answer_ids_are_the_answered_cards_oldest_first( db ):
    ask( db, 3 )
    ask( db, 1, response_type="open_ended", value="words" )
    ask( db, 2, value=None )
    ask( db, 4, response_type=None, value="x" )
    assert runner.stored_answer_ids( db ) == [ str( nid( 1 ) ), str( nid( 3 ) ) ]


def test_run_labels_every_stored_answer_counts_and_stamps_and_is_idempotent( db, scope ):
    ask( db, 1, value="yes" )
    ask( db, 2, value="Hey, I just saw" )
    ask( db, 3, source="timeout_default" )
    first = runner.run( scope, ANNOTATOR, Model() )
    assert ( first[ "answers" ], first[ "written" ], first[ "already" ] ) == ( 3, 3, 0 )
    assert first[ "relations" ] == { "no_comment": 1, "support": 1 }
    assert first[ "unknowns" ] == { "cancellation": 1, "no_explicit_stance": 1 }
    assert first[ "annotator" ] == ANNOTATOR and first[ "stamp" ][ 0 ] == STAMP
    assert first[ "stamp" ][ 1: ] == [ "no certificate: multiple-choice, open-ended and batch relations", "pass line for yes: not yet run (plan step 9)" ]
    second = runner.run( scope, ANNOTATOR, Model() )
    assert ( second[ "written" ], second[ "already" ] ) == ( 0, 3 ) and db.query( AnswerMeaning ).count() == 3


def test_run_takes_named_ids_and_a_limit_and_prints_progress( db, scope, capsys ):
    for n in ( 1, 2, 3 ): ask( db, n )
    assert runner.run( scope, ANNOTATOR, Model(), ids=[ str( nid( 2 ) ) ] )[ "written" ] == 1
    assert runner.run( scope, ANNOTATOR, Model(), limit=1, every=1 )[ "answers" ] == 1
    assert "1/1" in capsys.readouterr().out


class FakeLabeller( types.ModuleType ):
    def __init__( self ):
        super().__init__( "cosa.agents.answer_meaning.labeller" )
        self.calls = []

    def model_id( self ): return "ini-model"

    def annotator_of( self, model ): return f"{model}:v+{SCHEMA_VERSION_V2}"

    def label( self, draft, model ):
        self.calls.append( model )
        return Model()( draft )


@pytest.fixture
def labeller( monkeypatch ):
    fake = FakeLabeller()
    monkeypatch.setitem( sys.modules, fake.__name__, fake )
    return fake


def test_bound_labeller_names_its_annotator_and_sends_its_model( labeller ):
    annotator, label = runner.bound_labeller()
    assert annotator == f"ini-model:v+{SCHEMA_VERSION_V2}"
    label( { "fields": {}, "unknowns": [] } )
    assert labeller.calls == [ "ini-model" ]
    assert runner.bound_labeller( "other" )[ 0 ].startswith( "other:" )


def test_main_runs_the_ids_of_a_file_and_prints_the_report( db, scope, labeller, tmp_path, capsys ):
    for n in ( 1, 2 ): ask( db, n )
    ids = tmp_path / "ids.txt"
    ids.write_text( f"{nid( 2 )}\n\n" )
    assert runner.main( [ "--ids-file", str( ids ), "--model", "m1" ], session_scope=scope ) == 0
    report = json.loads( capsys.readouterr().out )
    assert report[ "written" ] == 1 and report[ "annotator" ].startswith( "m1:" )


def test_main_defaults_to_the_server_database( db, scope, labeller, monkeypatch, capsys ):
    import cosa.rest.db.database as database
    monkeypatch.setattr( database, "get_db", scope )
    ask( db, 1 )
    assert runner.main( [] ) == 0
    assert json.loads( capsys.readouterr().out )[ "written" ] == 1


def test_the_store_hook_does_nothing_and_says_nothing_with_the_switch_off( monkeypatch, capsys ):
    monkeypatch.setattr( on_store, "is_enabled", lambda: False )
    def explode( *a, **k ): raise AssertionError( "touched" )
    assert on_store.record_after_answer( "x", explode, start=explode ) == { "queued": False, "reason": "disabled" }
    assert capsys.readouterr().out == ""


def test_the_committed_switch_is_off_and_is_the_plans_key():
    assert on_store.STORE_KEY == "prediction learner answer meaning on store enabled"
    from cosa.config.configuration_manager import ConfigurationManager
    assert ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" ).get_required( on_store.STORE_KEY, return_type="boolean" ) is False
    assert on_store.is_enabled() is False


def test_an_unreadable_switch_is_off_and_named( monkeypatch, capsys ):
    def broken( env_var_name ): raise OSError( "no ini" )
    monkeypatch.setattr( on_store, "ConfigurationManager", broken )
    assert on_store.is_enabled() is False
    assert "no ini" in capsys.readouterr().out


def test_with_the_switch_on_the_answer_is_recorded_on_a_thread( db, scope, labeller, monkeypatch, capsys ):
    ask( db, 1 )
    monkeypatch.setattr( on_store, "is_enabled", lambda: True )
    threads = []
    assert on_store.record_after_answer( str( nid( 1 ) ), scope, start=threads.append ) == { "queued": True, "reason": "queued" }
    assert db.query( AnswerMeaning ).count() == 0 and len( threads ) == 1 and threads[ 0 ].daemon
    threads[ 0 ].run()
    assert db.query( AnswerMeaning ).count() == 1 and "written" in capsys.readouterr().out


def test_without_a_start_stand_in_the_thread_really_starts( db, scope, labeller, monkeypatch ):
    ask( db, 1 )
    monkeypatch.setattr( on_store, "is_enabled", lambda: True )
    started = []
    monkeypatch.setattr( on_store.threading.Thread, "start", lambda self: started.append( self ) )
    on_store.record_after_answer( str( nid( 1 ) ), scope )
    assert len( started ) == 1


def test_a_failed_recording_is_printed_and_not_raised( db, scope, labeller, monkeypatch, capsys ):
    monkeypatch.setattr( on_store, "is_enabled", lambda: True )
    threads = []
    on_store.record_after_answer( str( nid( 5 ) ), scope, start=threads.append )
    threads[ 0 ].run()
    assert "non-fatal" in capsys.readouterr().out


def failing( draft ):
    """The model layer's shape after a failed call: no relation on any pending field."""
    native = { key: { "kind": field[ "kind" ], **( { "relation": field[ "relation" ] } if field[ "relation" ] else {} ) } for key, field in draft[ "fields" ].items() }
    return { "native_answer": native, "acts": [], "conditions": [], "supporting_spans": None, "uncertainty": None,
             "unknowns": list( draft[ "unknowns" ] ) + [ "unreadable_payload" ] }


def test_a_failed_model_call_leaves_no_row_and_the_rerun_writes_it( db, scope ):
    ask( db, 1, value="yes [comment: later]" )
    assert runner.record_one( scope, str( nid( 1 ) ), ANNOTATOR, failing ) == { "status": "failed" }
    assert db.query( AnswerMeaning ).count() == 0
    assert runner.record_one( scope, str( nid( 1 ) ), ANNOTATOR, Model() )[ "status" ] == "written"


def test_run_counts_a_failed_answer_apart( db, scope ):
    ask( db, 1, value="yes [comment: later]" )
    ask( db, 2, value="yes" )
    report = runner.run( scope, ANNOTATOR, failing )
    assert ( report[ "written" ], report[ "failed" ], report[ "already" ] ) == ( 1, 1, 0 )


def test_a_stored_payload_nobody_can_read_is_still_written_since_no_call_was_made( db, scope ):
    ask( db, 1, source="robot" )
    assert runner.record_one( scope, str( nid( 1 ) ), ANNOTATOR, failing )[ "status" ] == "written"


def test_acts_conditions_and_spans_reach_the_row( db, scope ):
    ask( db, 1, response_type="open_ended", value="not now" )
    def rich( draft ):
        return { "native_answer": { "answer": { "kind": "open_ended_text", "relation": "declines_or_defers" } },
                 "acts": [ { "act": "defer", "field_key": "answer" } ], "conditions": [ { "text": "not now", "modifies_option_id": None } ],
                 "supporting_spans": [ { "field_key": "answer", "text": "not now" } ], "uncertainty": None, "unknowns": [] }
    runner.record_one( scope, str( nid( 1 ) ), ANNOTATOR, rich )
    row = db.query( AnswerMeaning ).one()
    assert row.acts == [ { "act": "defer", "field_key": "answer" } ]
    assert row.conditions == [ { "text": "not now", "modifies_option_id": None } ]
    assert row.supporting_spans == [ { "field_key": "answer", "text": "not now" } ]


def test_stored_answer_ids_cover_all_four_card_types_in_the_order_they_were_asked( db ):
    asked = [ ( 4, "multiple_choice" ), ( 3, "open_ended_batch" ), ( 2, "open_ended" ), ( 1, "yes_no" ) ]
    for second, ( n, response_type ) in enumerate( asked ):
        ask( db, n, response_type=response_type, value="x" )
        db.get( Notification, nid( n ) ).created_at = datetime( 2026, 11, 21, 0, 0, second, tzinfo=timezone.utc )
    db.commit()
    assert runner.stored_answer_ids( db ) == [ str( nid( n ) ) for n, _ in asked ]


def test_an_empty_selection_is_written_though_it_has_no_relation( db, scope ):
    options = { "questions": [ { "header": "A", "options": [ { "label": "x" } ] } ] }
    ask( db, 1, response_type="multiple_choice", value=json.dumps( { "answers": { "A": [] } } ), options=options )
    assert runner.record_one( scope, str( nid( 1 ) ), ANNOTATOR, failing )[ "status" ] == "written"
    assert db.query( AnswerMeaning ).one().native_answer[ "A" ][ "empty_selection" ] is True


def own_labels( stance, count ):
    return [ { "item_id": f"i{n}", "notification_id": f"n{n}", "field_key": "answer", "relation": "support", "card_stance": stance,
               "source": "human", "reader": "rick", "batch_id": "b", "ts": "2026-11-27T00:00:00+00:00" } for n in range( count ) ]


def test_the_reports_stamp_lifts_a_class_that_is_triggered_and_scorable( db, scope ):
    report = runner.run( scope, ANNOTATOR, Model(), gold_labels=own_labels( "no", 20 ), slice_counts={ "no": 30 } )
    assert report[ "stamp" ][ 0 ].startswith( "certified_classes: [yes, no]   uncertified: [neither, support-on-no, dissent, re_frame]" )
    assert report[ "gold_progress" ][ "stamp_lifts_for" ] == [ "no" ] and len( report[ "stamp" ] ) == 3


def test_a_triggered_class_the_slice_cannot_score_stays_stamped_in_the_report( db, scope ):
    report = runner.run( scope, ANNOTATOR, Model(), gold_labels=own_labels( "no", 20 ), slice_counts={ "no": 29 } )
    assert report[ "stamp" ][ 0 ] == STAMP and report[ "gold_progress" ][ "reached" ] == [ "no" ]


def test_main_reads_the_gold_store_and_the_slice_counts( db, scope, labeller, tmp_path, capsys ):
    store = tmp_path / "gold.jsonl"
    store.write_text( "".join( json.dumps( line ) + "\n" for line in own_labels( "neither", 20 ) ) )
    assert runner.main( [ "--gold", str( store ), "--slice-counts", '{"neither": 31}' ], session_scope=scope ) == 0
    assert json.loads( capsys.readouterr().out )[ "stamp" ][ 0 ].startswith( "certified_classes: [yes, neither]" )


def test_main_without_a_gold_option_reads_the_default_store( db, scope, labeller, monkeypatch, tmp_path, capsys ):
    from cosa.repo.labelling import gold_store
    store = tmp_path / "default.jsonl"
    store.write_text( "".join( json.dumps( line ) + "\n" for line in own_labels( "no", 3 ) ) )
    monkeypatch.setattr( gold_store, "default_path", lambda: store )
    assert runner.main( [], session_scope=scope ) == 0
    assert json.loads( capsys.readouterr().out )[ "gold_progress" ][ "rick" ][ "no" ] == 3
