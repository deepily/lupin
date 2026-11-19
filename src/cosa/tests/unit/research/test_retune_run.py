"""
The retune command reads the cohort, replays the grid and the sweep, and writes a report.

The database is a fake that records every statement, so the first statement is checked and nothing
real is touched. The asks are the retune tests' synthetic ones. The engine is the real one.
"""

import contextlib
import hashlib
import json
from datetime import datetime, timezone

import cosa.research.preference_replay.retune_run as retune_run
from cosa.research.phi4_flash_lite_study.freeze_corpus import sha256_of_rows
from cosa.research.preference_replay.retune_run import build_report, main, read_cohort, run_report
from cosa.tests.unit.research.test_retune import SHA, _asks, engine  # noqa: F401 - engine is a fixture

READ_AT = datetime( 2026, 11, 19, 0, 36, 39, tzinfo=timezone.utc )
FACTS   = { "database": "lupin_db_dev", "db_role": "lupin_host", "read_at": str( READ_AT ), "prediction_decisions_rows": 1544, "answer_source_null_rows": 0 }
RUN     = { "command": "python -m cosa.research.preference_replay.retune_run --out x.json", "code_sha": "a" * 40, "driver_sha256": "b" * 64, "started": "2026-11-19T00:36:39+00:00" }


class FakeResult:
    """What a SQL statement returns: only fetchall is read."""

    def __init__( self, rows ): self.rows = rows

    def fetchall( self ): return self.rows


class FakeSession:
    """A session that records each statement and answers the facts query with one row."""

    def __init__( self ):
        self.statements = []
        self.rolled_back = False

    def execute( self, statement ):
        self.statements.append( str( statement ) )
        return FakeResult( [ ( "lupin_db_dev", "lupin_host", READ_AT, 1544, 0 ) ] )

    def rollback( self ): self.rolled_back = True


def _fake_cohort( monkeypatch, asks_by_type ):
    """Make cohort_asks answer from a dict and record the response types asked for, in order."""
    asked = []

    def fake( session, response_type ):
        asked.append( response_type )
        return list( asks_by_type[ response_type ] )

    monkeypatch.setattr( retune_run, "cohort_asks", fake )
    return asked


def test_the_cohort_is_read_in_a_read_only_transaction_and_dated( monkeypatch ):
    """The read-only statement comes first, the types are read in order, and a rollback ends it."""
    asked   = _fake_cohort( monkeypatch, { "yes_no": [ { "id": "y1" } ], "multiple_choice": [ { "id": "m1" }, { "id": "m2" } ] } )
    session = FakeSession()
    asks, facts = read_cohort( session )
    assert session.statements[ 0 ] == "SET TRANSACTION READ ONLY"
    assert len( session.statements ) == 2 and session.statements[ 1 ].startswith( "select current_database()" )
    assert asked == [ "yes_no", "multiple_choice" ] and [ ask[ "id" ] for ask in asks ] == [ "y1", "m1", "m2" ]
    assert facts == FACTS and session.rolled_back is True


def test_the_report_keeps_the_sweep_apart_from_the_frozen_settings( engine ):
    """The frozen settings come from the grid result; the sweep sits in its own key."""
    from cosa.research.preference_replay.retune import report_only_sweep, retune
    asks   = _asks( engine )
    result = retune( asks, engine, SHA )
    sweep  = report_only_sweep( asks, engine, SHA )
    report = build_report( result, sweep, dict( FACTS, cohort_sha256_all_ids="c" * 64, command="x" ) )
    assert report[ "frozen_settings" ] == { "prediction engine cbr similarity threshold": 0.6, "prediction engine cbr top k": 3, "prediction engine retrieval metric": "cosine" }
    assert report[ "cohort_sha256_all_ids" ] == "c" * 64 and "cohort_sha256_all_ids" not in report[ "provenance" ]
    assert report[ "provenance" ][ "command" ] == "x" and report[ "provenance" ][ "database" ] == "lupin_db_dev"
    assert len( report[ "grid_points" ] ) == 36 and len( report[ "report_only_sweep_points" ] ) == 16
    assert all( point[ "threshold" ] < 0.5 for point in report[ "report_only_sweep_points" ] )
    assert report[ "best_point" ] == result[ "best" ] and report[ "version" ] == 1 and len( report[ "notes" ] ) == 3


def test_the_run_counts_the_asks_it_could_not_replay_and_names_the_run( engine ):
    """Eleven asks, one with no vector: ten replayable, one counted out, snapshot of all eleven."""
    asks = _asks( engine ) + [ dict( _asks( engine )[ 0 ], id="no-vector", question_embedding=None ) ]
    report = run_report( asks, FACTS, engine, RUN )
    provenance = report[ "provenance" ]
    assert ( provenance[ "cohort_asks" ], provenance[ "not_replayable" ] ) == ( 11, 1 )
    assert provenance[ "cohort_asks_by_type" ] == { "yes_no": 11 } and provenance[ "replayable_by_type" ] == { "yes_no": 10 }
    assert report[ "cohort_sha256_all_ids" ] == sha256_of_rows( [ { "id": ask[ "id" ] } for ask in asks ] )
    assert all( provenance[ key ] == RUN[ key ] for key in RUN ) and provenance[ "response_types" ] == [ "yes_no", "multiple_choice" ]
    assert report[ "frozen_settings" ][ "prediction engine cbr top k" ] == 3 and report[ "eligible" ] == 10


def test_the_command_writes_the_report_and_names_its_own_command_and_code( engine, monkeypatch, tmp_path, capsys ):
    """The report on disk names the command line, the code sha and the driver file checksum."""
    _fake_cohort( monkeypatch, { "yes_no": _asks( engine ), "multiple_choice": [] } )
    out      = tmp_path / "report.json"
    session  = FakeSession()
    printed  = []
    code = main( [ "--out", str( out ) ], printer=printed.append, session_factory=lambda: contextlib.nullcontext( session ),
                 engine_factory=lambda: engine, code_sha="d" * 40, clock=lambda: READ_AT )
    report = json.loads( out.read_text( encoding="utf-8" ) )
    with open( retune_run.__file__, "rb" ) as handle: expected_sha = hashlib.sha256( handle.read() ).hexdigest()
    assert code == 0 and session.statements[ 0 ] == "SET TRANSACTION READ ONLY"
    assert report[ "provenance" ][ "command" ] == f"python -m cosa.research.preference_replay.retune_run --out {out}"
    assert ( report[ "provenance" ][ "code_sha" ], report[ "provenance" ][ "driver_sha256" ] ) == ( "d" * 40, expected_sha )
    assert report[ "provenance" ][ "started" ] == READ_AT.isoformat()
    assert json.loads( printed[ 0 ] ) == report[ "frozen_settings" ]
    assert list( report ) == sorted( report ), "keys are written sorted"
