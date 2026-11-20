"""
The per-arm summary on a synthetic cohort of six cards and three arms.

The cohort sits in real prediction_log and prediction_arm_forecast tables on SQLite. Each expected figure is
written here as a literal. The database counts are also read back with plain SQL over the same rows.
So the summary is held to two independent counts and not to its own code.

Times are seconds after 12:00:00 on 19 Nov 2026. Cards n1 to n5 are answered at second 10; n6 is not answered.
"""
import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from cosa.agents.prediction_engine.prediction_engine import PredictionEngine
from cosa.research.preference_replay.arm_summary import SUMMARY_KEYS, per_arm_summary, render_summary, summarize_arm
from cosa.research.preference_replay import scratch_db  # noqa: F401  registers the one shared SQLite hooks for JSONB and Vector
from cosa.rest.routers.notifications import _stored_response_dict
from cosa.rest.postgres_models import PredictionArmForecast, PredictionLog

T0 = datetime( 2026, 11, 19, 12, 0, 0, tzinfo=timezone.utc )


def _nid( n ):
    return f"a000000{n}-0000-0000-0000-000000000000"


def _at( seconds ):
    return None if seconds is None else T0 + timedelta( seconds=seconds )


# The final answers are what the real door stores for a human answer: the value, its source and who answered.
ANSWERED_BY = { "user_id": "u1", "account_email": "someone@example.com", "method": "ui" }
YES         = _stored_response_dict( "yes", ANSWERED_BY )
NO          = _stored_response_dict( "no", ANSWERED_BY )
DRAFT_YES   = { "value": "yes" }
DRAFT_NO    = { "value": "no" }

# card number: ( responded_at, fold_opened_at, draft at the reveal, final answer ); card 4 has no draft on record
CARDS = {
    1: ( 10,   None, None, YES ),
    2: ( 10,   5,    DRAFT_YES,  YES ),
    3: ( 10,   5,    DRAFT_YES,  NO  ),
    4: ( 10,   5,    None, YES ),
    5: ( 10,   12,   DRAFT_NO,   YES ),
    6: ( None, None, None, None ),
}
# arm: { card number: forecast_ready_at second }
ARMS = {
    "A1": { 1: 2, 2: 10, 3: 11, 4: None, 5: 3, 6: 4 },
    "B1": { 1: 20, 2: 20, 3: 20, 4: 9, 5: 9 },
    "C0": { 1: 1, 2: 1 },
    "D0": { 1: None, 2: 1 },
}
# the forecast rows the concurrency cap turned away: ( arm, card number )
CAPPED = { ( "D0", 1 ) }


@pytest.fixture
def session():
    engine = sa.create_engine( "sqlite://", poolclass=StaticPool )
    PredictionLog.__table__.create( engine )
    PredictionArmForecast.__table__.create( engine )
    with Session( engine ) as sess:
        for n, ( responded, opened, draft, final ) in CARDS.items():
            # A JSON column given Python None stores the JSON value null, not SQL NULL, so an absent value is left out.
            json_columns = { name: value for name, value in ( ( "draft_at_reveal", draft ), ( "actual_value", final ) ) if value is not None }
            sess.add( PredictionLog( notification_id=uuid.UUID( _nid( n ) ), response_type="yes_no", category="c", predicted_at=T0,
                                     prediction_confidence=0.5, prediction_strategy="s", similar_case_count=0,
                                     responded_at=_at( responded ), fold_opened_at=_at( opened ), **json_columns ) )
        for arm, ready_by_card in ARMS.items():
            for n, ready in ready_by_card.items():
                sess.add( PredictionArmForecast( notification_id=uuid.UUID( _nid( n ) ), arm=arm, forecast_ready_at=_at( ready ), displayed=( arm == "A1" ),
                                                 abstention_reason="capacity" if ( arm, n ) in CAPPED else None ) )
        sess.commit()
        yield sess


def _by_arm( summaries ):
    return { s[ "arm" ]: s for s in summaries }


def test_each_arm_counts_equal_the_literal_counts( session ):
    got = _by_arm( per_arm_summary( session ) )
    assert list( got ) == [ "A1", "B1", "C0", "D0" ]
    assert all( tuple( s ) == SUMMARY_KEYS for s in got.values() )
    assert got[ "A1" ] == { "arm": "A1", "forecasts": 6, "orphaned": 0, "no_row": 0, "answered": 5, "timely": 3, "late": 1, "not_ready": 1, "capped": 0, "timeliness": 0.6,
                            "revealed": 3, "unaided": 3, "switched": 1, "exposed": 1, "no_final": 0, "switch_rate": 0.5 }
    assert got[ "B1" ] == { "arm": "B1", "forecasts": 5, "orphaned": 0, "no_row": 0, "answered": 5, "timely": 2, "late": 3, "not_ready": 0, "capped": 0, "timeliness": 0.4,
                            "revealed": 3, "unaided": 3, "switched": 1, "exposed": 1, "no_final": 0, "switch_rate": 0.5 }
    assert got[ "C0" ] == { "arm": "C0", "forecasts": 2, "orphaned": 0, "no_row": 3, "answered": 2, "timely": 2, "late": 0, "not_ready": 0, "capped": 0, "timeliness": 1.0,
                            "revealed": 1, "unaided": 2, "switched": 0, "exposed": 0, "no_final": 0, "switch_rate": 0.0 }
    assert got[ "D0" ] == { "arm": "D0", "forecasts": 2, "orphaned": 0, "no_row": 3, "answered": 2, "timely": 1, "late": 0, "not_ready": 0, "capped": 1, "timeliness": 0.5,
                            "revealed": 1, "unaided": 2, "switched": 0, "exposed": 0, "no_final": 0, "switch_rate": 0.0 }


def test_the_database_counts_equal_a_direct_sql_count_over_the_same_rows( session ):
    got = _by_arm( per_arm_summary( session ) )
    answered = "l.responded_at IS NOT NULL"
    not_capped = "( a.abstention_reason IS NULL OR a.abstention_reason <> 'capacity' )"
    rows = session.execute( sa.text(
        "SELECT a.arm, COUNT(*), "
        f"SUM( CASE WHEN {answered} THEN 1 ELSE 0 END ), "
        f"SUM( CASE WHEN {answered} AND {not_capped} AND a.forecast_ready_at IS NOT NULL AND a.forecast_ready_at <= l.responded_at THEN 1 ELSE 0 END ), "
        f"SUM( CASE WHEN {answered} AND {not_capped} AND a.forecast_ready_at > l.responded_at THEN 1 ELSE 0 END ), "
        f"SUM( CASE WHEN {answered} AND {not_capped} AND a.forecast_ready_at IS NULL THEN 1 ELSE 0 END ), "
        f"SUM( CASE WHEN {answered} AND a.abstention_reason = 'capacity' THEN 1 ELSE 0 END ), "
        f"SUM( CASE WHEN {answered} AND l.fold_opened_at IS NOT NULL AND l.fold_opened_at < l.responded_at THEN 1 ELSE 0 END ), "
        f"SUM( CASE WHEN {answered} AND l.fold_opened_at < l.responded_at AND l.draft_at_reveal IS NOT NULL "
        "AND json_extract( l.draft_at_reveal, '$.value' ) <> json_extract( l.actual_value, '$.value' ) THEN 1 ELSE 0 END ), "
        f"SUM( CASE WHEN {answered} AND l.fold_opened_at < l.responded_at AND l.draft_at_reveal IS NULL THEN 1 ELSE 0 END ) "
        "FROM prediction_arm_forecast a JOIN prediction_log l ON l.notification_id = a.notification_id GROUP BY a.arm ORDER BY a.arm" ) ).all()
    assert [ r[ 0 ] for r in rows ] == [ "A1", "B1", "C0", "D0" ]
    for arm, forecasts, answered_n, timely, late, not_ready, capped, revealed, switched, unknown in rows:
        s = got[ arm ]
        assert ( s[ "forecasts" ], s[ "answered" ], s[ "timely" ], s[ "late" ], s[ "not_ready" ], s[ "capped" ], s[ "revealed" ], s[ "switched" ], s[ "exposed" ] ) == \
               ( forecasts, answered_n, timely, late, not_ready, capped, revealed, switched, unknown ), arm
    assert [ tuple( r[ 1: ] ) for r in rows ] == [ ( 6, 5, 3, 1, 1, 0, 3, 1, 1 ), ( 5, 5, 2, 3, 0, 0, 3, 1, 1 ),
                                                  ( 2, 2, 2, 0, 0, 0, 1, 0, 0 ), ( 2, 2, 1, 0, 0, 1, 1, 0, 0 ) ]
    no_row = dict( session.execute( sa.text(
        "SELECT arms.arm, COUNT( l.notification_id ) FROM ( SELECT DISTINCT arm FROM prediction_arm_forecast ) arms "
        "JOIN prediction_log l ON l.responded_at IS NOT NULL AND NOT EXISTS ( SELECT 1 FROM prediction_arm_forecast f "
        "WHERE f.notification_id = l.notification_id AND f.arm = arms.arm ) GROUP BY arms.arm" ) ).all() )
    assert no_row == { "C0": 3, "D0": 3 }, "A1 and B1 hold a row for every answered card"
    assert { arm: s[ "no_row" ] for arm, s in got.items() } == { "A1": 0, "B1": 0, "C0": 3, "D0": 3 }


def test_since_keeps_only_cards_predicted_at_or_after_it( session ):
    assert per_arm_summary( session, since=T0 ) == per_arm_summary( session )
    later = per_arm_summary( session, since=T0 + timedelta( seconds=1 ) )
    assert [ ( s[ "arm" ], s[ "forecasts" ], s[ "answered" ], s[ "no_row" ] ) for s in later ] == [ ( "A1", 0, 0, 0 ), ( "B1", 0, 0, 0 ), ( "C0", 0, 0, 0 ), ( "D0", 0, 0, 0 ) ]
    naive_since = ( T0 + timedelta( seconds=1 ) ).replace( tzinfo=None )
    assert per_arm_summary( session, since=naive_since ) == later


def test_with_no_drafts_on_record_a_revealed_card_is_unknown_and_the_switch_rate_is_not_measurable( session ):
    session.execute( sa.text( "UPDATE prediction_log SET draft_at_reveal = NULL" ) )
    a1 = _by_arm( per_arm_summary( session ) )[ "A1" ]
    assert ( a1[ "revealed" ], a1[ "exposed" ], a1[ "switched" ], a1[ "unaided" ], a1[ "switch_rate" ] ) == ( 3, 3, 0, 2, None )


def test_the_partition_holds_in_every_arm( session ):
    for s in per_arm_summary( session ):
        assert s[ "timely" ] + s[ "late" ] + s[ "not_ready" ] + s[ "capped" ] == s[ "answered" ]
        assert s[ "unaided" ] + s[ "switched" ] + s[ "exposed" ] + s[ "no_final" ] == s[ "answered" ]


def test_a_forecast_whose_card_has_no_log_row_is_counted_as_orphaned_and_nothing_else( session ):
    session.add( PredictionArmForecast( notification_id=uuid.UUID( _nid( 9 ) ), arm="Z9", forecast_ready_at=_at( 1 ) ) )
    session.add( PredictionArmForecast( notification_id=uuid.UUID( _nid( 8 ) ), arm="B1", forecast_ready_at=_at( 1 ) ) )
    session.commit()
    got = _by_arm( per_arm_summary( session ) )
    assert list( got ) == [ "A1", "B1", "C0", "D0", "Z9" ]
    assert ( got[ "Z9" ][ "forecasts" ], got[ "Z9" ][ "orphaned" ], got[ "Z9" ][ "answered" ] ) == ( 0, 1, 0 )
    assert ( got[ "B1" ][ "forecasts" ], got[ "B1" ][ "orphaned" ] ) == ( 5, 1 )
    assert got[ "A1" ][ "orphaned" ] == 0


def test_an_empty_database_gives_no_summaries( session ):
    session.execute( sa.text( "DELETE FROM prediction_arm_forecast" ) )
    assert per_arm_summary( session ) == []


def test_an_arm_with_nothing_answered_has_no_timeliness_and_no_switch_rate():
    row = { "forecast_ready_at": _at( 1 ), "abstention_reason": None, "responded_at": None, "fold_opened_at": None, "draft": None, "final": None, "response_type": "yes_no" }
    s = summarize_arm( "X", [ row ] )
    assert ( s[ "forecasts" ], s[ "answered" ], s[ "timeliness" ], s[ "switch_rate" ] ) == ( 1, 0, None, None )


def _row( opened, draft, final, response_type="yes_no", ready=1, responded=10 ):
    return { "forecast_ready_at": _at( ready ), "abstention_reason": None, "responded_at": _at( responded ), "fold_opened_at": _at( opened ),
             "draft": draft, "final": final, "response_type": response_type }


# A multiple-choice card: the door stores the picks as JSON text; record_outcome decodes it into answers.
MC_TEXT   = json.dumps( { "answers": { "Review": [ "a", "b" ], "Mode": "fast" } } )
MC_FINAL  = PredictionEngine._parse_mc_decision_value( _stored_response_dict( MC_TEXT, ANSWERED_BY )[ "value" ] )


def test_a_decoded_multiple_choice_answer_is_compared_pick_for_pick_and_not_as_raw_json():
    same_other_order = json.dumps( { "answers": { "Mode": "fast", "Review": [ "b", "a" ] } } )
    changed          = json.dumps( { "answers": { "Review": [ "a" ], "Mode": "fast" } } )
    got = summarize_arm( "X", [ _row( 5, { "value": MC_TEXT }, MC_FINAL, "multiple_choice" ),
                                _row( 5, { "value": same_other_order }, MC_FINAL, "multiple_choice" ),
                                _row( 5, { "value": changed }, MC_FINAL, "multiple_choice" ) ] )
    assert MC_FINAL == { "answers": { "Review": [ "a", "b" ], "Mode": "fast" } }, "the real decoder drops the source and the author"
    assert ( got[ "unaided" ], got[ "switched" ], got[ "exposed" ], got[ "switch_rate" ] ) == ( 2, 1, 0, 0.3333 )


def test_a_real_stored_yes_no_answer_with_a_source_and_an_author_equals_a_plain_draft():
    assert set( YES ) == { "value", "source", "answered_by" }
    got = summarize_arm( "X", [ _row( 5, DRAFT_YES, YES ), _row( 5, DRAFT_NO, YES ) ] )
    assert ( got[ "unaided" ], got[ "switched" ], got[ "switch_rate" ] ) == ( 1, 1, 0.5 )


def test_a_multiple_choice_draft_that_cannot_be_read_is_exposed_and_stays_out_of_the_rate():
    got = summarize_arm( "X", [ _row( 5, { "value": "not json" }, MC_FINAL, "multiple_choice" ), _row( 5, { "value": MC_TEXT }, MC_FINAL, "multiple_choice" ),
                                _row( 5, { "value": json.dumps( { "answers": { "Review": [ "a" ], "Mode": "fast" } } ) }, MC_FINAL, "multiple_choice" ) ] )
    assert ( got[ "exposed" ], got[ "unaided" ], got[ "switched" ], got[ "switch_rate" ] ) == ( 1, 1, 1, 0.5 )


def test_naive_and_aware_times_in_one_row_are_compared_as_utc():
    row = _row( 5, DRAFT_YES, YES )
    row[ "forecast_ready_at" ] = row[ "forecast_ready_at" ].replace( tzinfo=None )      # naive, as SQLite returns it
    got = summarize_arm( "X", [ row ] )                                                 # aware responded_at and fold time
    assert ( got[ "timely" ], got[ "revealed" ] ) == ( 1, 1 )


def test_the_table_has_one_line_per_arm_and_reads_na_for_a_missing_rate( session ):
    session.execute( sa.text( "UPDATE prediction_log SET draft_at_reveal = NULL" ) )
    text = render_summary( per_arm_summary( session ) )
    lines = text.splitlines()
    assert len( lines ) == 2 + 4 and lines[ 0 ].startswith( "| arm | forecasts | orphaned | no_row" )
    assert lines[ 2 ] == "| A1 | 6 | 0 | 0 | 5 | 3 | 1 | 1 | 0 | 0.600 | 3 | 2 | 0 | 3 | 0 | n/a |"


def test_the_table_shows_a_measured_switch_rate_to_three_places( session ):
    lines = render_summary( per_arm_summary( session ) ).splitlines()
    assert lines[ 2 ] == "| A1 | 6 | 0 | 0 | 5 | 3 | 1 | 1 | 0 | 0.600 | 3 | 3 | 1 | 1 | 0 | 0.500 |"
    assert lines[ 4 ] == "| C0 | 2 | 0 | 3 | 2 | 2 | 0 | 0 | 0 | 1.000 | 1 | 2 | 0 | 0 | 0 | 0.000 |"


def test_a_row_with_an_answer_time_and_no_final_answer_is_counted_as_no_final_and_does_not_crash():
    got = summarize_arm( "X", [ _row( 5, DRAFT_YES, None ), _row( 5, DRAFT_YES, YES ) ] )
    assert ( got[ "answered" ], got[ "no_final" ], got[ "unaided" ], got[ "revealed" ], got[ "switch_rate" ] ) == ( 2, 1, 1, 2, 0.0 )


def test_a_capped_row_is_capped_whether_or_not_it_has_a_ready_time_and_a_reason_other_than_the_cap_is_not():
    capped_with_time = dict( _row( 5, DRAFT_YES, YES ), abstention_reason="capacity" )
    other_reason     = dict( _row( 5, DRAFT_YES, YES ), abstention_reason="switch off", forecast_ready_at=None )
    got = summarize_arm( "X", [ capped_with_time, other_reason ] )
    assert ( got[ "capped" ], got[ "not_ready" ], got[ "timely" ], got[ "timeliness" ] ) == ( 1, 1, 0, 0.0 )


def test_the_capped_reason_is_defined_once_in_the_repository_and_is_the_word_the_writers_store():
    from cosa.rest.db.repositories import arm_forecast_repository as repo
    from cosa.research.preference_replay import arm_summary
    assert repo.CAPPED_ARM_REASON == "capacity"
    assert arm_summary.CAPPED_ARM_REASON is repo.CAPPED_ARM_REASON
