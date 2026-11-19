"""
The retune command reads the cohort, replays the grid and the sweep, and writes a report.

The database is a fake that records every statement, so the first statement is checked and nothing
real is touched. The asks are the retune tests' synthetic ones. The engine is the real one.
"""

import contextlib
import hashlib
import json
from datetime import datetime, timezone

import pytest

import cosa.research.preference_replay.retune_run as retune_run
from cosa.agents.prediction_engine.prediction_engine import PredictionEngine
from cosa.research.phi4_flash_lite_study.freeze_corpus import sha256_of_rows
from cosa.research.preference_replay.question_vectors import write_side_file
from cosa.research.preference_replay.retune_run import build_report, ControlMismatch, check_vectors_cover, restrict_to_ids, write_control_ids, main, read_cohort, run_report
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


def _side_file( tmp_path, rejects=() ):
    """A real side file, written through write_side_file, holding one vector."""
    path   = str( tmp_path / "vectors.json" )
    result = { "stamp": { "model": "m", "revision": "r1", "dtype": "float16", "dimensions": 768 }, "vectors": { "a": [ 3.0, 4.0 ] },
               "rejects": list( rejects ), "probe_seconds": 1.0, "total_seconds": 2.0, "texts": 1 }
    write_side_file( path, result, { "database": "lupin_db_dev" } )
    return path


def _fake_cohort( monkeypatch, asks_by_type ):
    """Make cohort_asks answer from a dict and record the response types asked for, in order."""
    asked = []

    def fake( session, response_type, vectors ):
        asked.append( response_type )
        return list( asks_by_type[ response_type ] )

    monkeypatch.setattr( retune_run, "cohort_asks", fake )
    return asked


def test_an_ask_with_no_vector_and_no_reject_entry_is_refused_and_a_listed_reject_is_allowed():
    asks = [ { "id": "a", "question_embedding": [ 1.0 ] }, { "id": "b", "question_embedding": None }, { "id": "c", "question_embedding": None } ]
    check_vectors_cover( asks, { "rejects": [ { "id": "b", "reason": "empty question text" }, { "id": "c", "reason": "r" } ] } )
    with pytest.raises( ValueError, match=r"1 cohort asks have no vector .*\['c'\]" ):
        check_vectors_cover( asks, { "rejects": [ { "id": "b", "reason": "r" } ] } )


def test_the_step_9_run_script_calls_read_cohort_with_one_argument_and_that_reads_the_stored_vectors( monkeypatch ):
    import ast
    from cosa.utils import util as cu
    with open( cu.get_project_root() + "/src/scripts/preference_step9_checkpoint_run.py", encoding="utf-8" ) as handle: tree = ast.parse( handle.read() )
    calls = [ node for node in ast.walk( tree ) if isinstance( node, ast.Call ) and getattr( node.func, "id", None ) == "read_cohort" ]
    assert len( calls ) == 1 and len( calls[ 0 ].args ) == 1 and calls[ 0 ].keywords == []
    seen = []
    monkeypatch.setattr( retune_run, "cohort_asks", lambda session, kind, vectors: seen.append( vectors ) or [] )
    read_cohort( FakeSession() )
    assert seen == [ None, None ]


def test_a_side_file_with_one_reject_reports_one_reject( engine, monkeypatch, tmp_path ):
    _fake_cohort( monkeypatch, { "yes_no": _asks( engine ), "multiple_choice": [] } )
    out = tmp_path / "r.json"
    main( [ "--out", str( out ), "--vectors", _side_file( tmp_path, [ { "id": "zz", "reason": "empty question text" } ] ) ], printer=lambda line: None,
          session_factory=lambda: contextlib.nullcontext( FakeSession() ), engine_factory=lambda: engine, code_sha="d" * 40 )
    assert json.loads( out.read_text( encoding="utf-8" ) )[ "provenance" ][ "vector_rejects" ] == 1


def test_giving_neither_a_side_file_nor_the_stored_switch_is_a_usage_error( tmp_path, capsys ):
    with pytest.raises( SystemExit ) as raised: main( [ "--out", str( tmp_path / "r.json" ) ] )
    assert raised.value.code == 2 and "one of the arguments --vectors --stored-vectors is required" in capsys.readouterr().err


def test_giving_both_a_side_file_and_the_stored_switch_is_a_usage_error( tmp_path ):
    with pytest.raises( SystemExit ) as raised: main( [ "--out", str( tmp_path / "r.json" ), "--vectors", "a", "--stored-vectors" ] )
    assert raised.value.code == 2


def _control_report( asks, engine, final_correct=None ):
    """A report from a real replay, and the final-window correct count at the frozen point."""
    report = run_report( asks, FACTS, engine, RUN )
    point  = next( p for p in report[ "grid_points" ] if p[ "threshold" ] == 0.5 and p[ "top_k" ] == 10 )
    return report, point[ "final_correct" ]


def test_the_control_writes_the_replayable_ids_in_cohort_order_only_when_both_figures_match( engine, tmp_path ):
    asks = _asks( engine ) + [ dict( _asks( engine )[ 0 ], id="no-vector", question_embedding=None ) ]
    report, final_correct = _control_report( asks, engine )
    path = tmp_path / "ids.txt"
    write_control_ids( report, asks, str( path ), 10, final_correct )
    assert path.read_text( encoding="utf-8" ).split() == [ ask[ "id" ] for ask in asks[ :10 ] ]
    assert [ p.name for p in tmp_path.iterdir() ] == [ "ids.txt" ]


@pytest.mark.parametrize( "replayable_delta, correct_delta, named", [ ( 1, 0, "replayable: measured 10, expected 11" ),
                                                                       ( 0, 1, "final_correct: measured" ),
                                                                       ( 1, 1, "replayable: measured 10, expected 11; final_correct" ) ] )
def test_the_control_writes_nothing_and_names_each_figure_that_differs( engine, tmp_path, replayable_delta, correct_delta, named ):
    asks = _asks( engine )
    report, final_correct = _control_report( asks, engine )
    path = tmp_path / "ids.txt"
    with pytest.raises( ControlMismatch, match="does not reproduce the baseline" ) as raised:
        write_control_ids( report, asks, str( path ), 10 + replayable_delta, final_correct + correct_delta )
    assert named in str( raised.value ) and list( tmp_path.iterdir() ) == []


def test_the_command_writes_the_control_ids_after_the_report_and_refuses_a_wrong_expectation( engine, monkeypatch, tmp_path ):
    asks = _asks( engine )
    _fake_cohort( monkeypatch, { "yes_no": asks, "multiple_choice": [] } )
    _, final_correct = _control_report( asks, engine )
    base = [ "--stored-vectors" ]
    kwargs = dict( printer=lambda line: None, session_factory=lambda: contextlib.nullcontext( FakeSession() ), engine_factory=lambda: engine, code_sha="d" * 40 )
    good = tmp_path / "ids.txt"
    assert main( [ "--out", str( tmp_path / "r1.json" ) ] + base + [ "--control-ids-out", str( good ), "--expect-replayable", "10",
                                                                    "--expect-final-correct", str( final_correct ) ], **kwargs ) == 0
    assert len( good.read_text( encoding="utf-8" ).split() ) == 10
    bad = tmp_path / "bad.txt"
    with pytest.raises( ControlMismatch ):
        main( [ "--out", str( tmp_path / "r2.json" ) ] + base + [ "--control-ids-out", str( bad ), "--expect-replayable", "11",
                                                                "--expect-final-correct", str( final_correct ) ], **kwargs )
    assert ( tmp_path / "r2.json" ).exists() and not bad.exists()


@pytest.mark.parametrize( "extra", [ [ "--expect-replayable", "1" ], [ "--expect-final-correct", "1" ], [] ] )
def test_the_control_output_without_both_expectations_is_a_usage_error( tmp_path, extra, capsys ):
    with pytest.raises( SystemExit ) as raised:
        main( [ "--out", str( tmp_path / "r.json" ), "--stored-vectors", "--control-ids-out", str( tmp_path / "i.txt" ) ] + extra )
    assert raised.value.code == 2 and "--control-ids-out needs --expect-replayable and --expect-final-correct" in capsys.readouterr().err


def _ids_file( tmp_path, ids ):
    path = tmp_path / "ids.jsonl"
    path.write_text( "".join( json.dumps( { "id": ask_id } ) + "\n" for ask_id in ids ) + "\n", encoding="utf-8" )
    return str( path )


def test_the_id_list_cuts_the_cohort_to_exactly_those_asks_in_cohort_order_and_refuses_an_absent_id( tmp_path ):
    asks = [ { "id": name } for name in ( "d", "c", "b", "a" ) ]
    kept, facts = restrict_to_ids( asks, _ids_file( tmp_path, [ "a", "d", "b" ] ) )
    assert [ ask[ "id" ] for ask in kept ] == [ "d", "b", "a" ] and facts[ "only_ids_count" ] == 3 and facts[ "only_ids_file" ].endswith( "ids.jsonl" )
    assert len( facts[ "only_ids_sha256" ] ) == 64
    with pytest.raises( ValueError, match=r"1 listed ids are not in the cohort, first: \['zz'\]" ):
        restrict_to_ids( asks, _ids_file( tmp_path, [ "a", "zz" ] ) )


def test_a_duplicate_id_in_the_list_keeps_the_ask_once_and_counts_it_once( tmp_path ):
    asks = [ { "id": name } for name in ( "a", "b", "c" ) ]
    kept, facts = restrict_to_ids( asks, _ids_file( tmp_path, [ "b", "a", "b" ] ) )
    assert [ ask[ "id" ] for ask in kept ] == [ "a", "b" ] and facts[ "only_ids_count" ] == 2


def test_the_command_replays_only_the_listed_ids_and_names_the_list( engine, monkeypatch, tmp_path ):
    asks = _asks( engine )
    _fake_cohort( monkeypatch, { "yes_no": asks, "multiple_choice": [] } )
    out = tmp_path / "r.json"
    main( [ "--out", str( out ), "--stored-vectors", "--only-ids", _ids_file( tmp_path, [ ask[ "id" ] for ask in asks[ :8 ] ] ) ], printer=lambda line: None,
          session_factory=lambda: contextlib.nullcontext( FakeSession() ), engine_factory=lambda: engine, code_sha="d" * 40 )
    provenance = json.loads( out.read_text( encoding="utf-8" ) )[ "provenance" ]
    assert provenance[ "cohort_asks" ] == 8 and provenance[ "only_ids_count" ] == 8


def test_the_stored_vector_source_reads_no_side_file_and_says_so( engine, monkeypatch, tmp_path ):
    seen = []
    monkeypatch.setattr( retune_run, "cohort_asks", lambda session, kind, vectors: seen.append( vectors ) or ( _asks( engine ) if kind == "yes_no" else [] ) )
    out = tmp_path / "r.json"
    main( [ "--out", str( out ), "--stored-vectors" ], printer=lambda line: None, session_factory=lambda: contextlib.nullcontext( FakeSession() ),
          engine_factory=lambda: engine, code_sha="d" * 40 )
    provenance = json.loads( out.read_text( encoding="utf-8" ) )[ "provenance" ]
    assert seen == [ None, None ] and provenance[ "vector_source" ] == "stored" and "vector_side_file" not in provenance


def test_the_command_refuses_a_cohort_with_an_unexplained_missing_vector( engine, monkeypatch, tmp_path ):
    _fake_cohort( monkeypatch, { "yes_no": [ dict( _asks( engine )[ 0 ], question_embedding=None ) ], "multiple_choice": [] } )
    with pytest.raises( ValueError, match="no vector in the side file" ):
        main( [ "--out", str( tmp_path / "r.json" ), "--vectors", _side_file( tmp_path ) ], printer=lambda line: None,
              session_factory=lambda: contextlib.nullcontext( FakeSession() ), engine_factory=lambda: engine, code_sha="d" * 40 )


def test_the_cohort_is_read_in_a_read_only_transaction_and_dated( monkeypatch ):
    """The read-only statement comes first, the types are read in order, and a rollback ends it."""
    asked   = _fake_cohort( monkeypatch, { "yes_no": [ { "id": "y1" } ], "multiple_choice": [ { "id": "m1" }, { "id": "m2" } ] } )
    session = FakeSession()
    asks, facts = read_cohort( session, { "y1": [ 1.0 ] } )
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
    code = main( [ "--out", str( out ), "--vectors", _side_file( tmp_path ) ], printer=printed.append, session_factory=lambda: contextlib.nullcontext( session ),
                 engine_factory=lambda: engine, code_sha="d" * 40, clock=lambda: READ_AT )
    report = json.loads( out.read_text( encoding="utf-8" ) )
    with open( retune_run.__file__, "rb" ) as handle: expected_sha = hashlib.sha256( handle.read() ).hexdigest()
    assert code == 0 and session.statements[ 0 ] == "SET TRANSACTION READ ONLY"
    assert report[ "provenance" ][ "command" ] == f"python -m cosa.research.preference_replay.retune_run --out {out} --vectors {tmp_path / 'vectors.json'}"
    assert ( report[ "provenance" ][ "code_sha" ], report[ "provenance" ][ "driver_sha256" ] ) == ( "d" * 40, expected_sha )
    assert report[ "provenance" ][ "started" ] == READ_AT.isoformat()
    provenance = report[ "provenance" ]
    assert ( provenance[ "vector_source" ], provenance[ "vector_rejects" ] ) == ( "side_file", 0 )
    assert ( provenance[ "vector_model" ], provenance[ "vector_revision" ], provenance[ "vector_side_file" ] ) == ( "m", "r1", str( tmp_path / "vectors.json" ) )
    with open( tmp_path / "vectors.json", "rb" ) as handle: assert provenance[ "vector_side_file_sha256" ] == hashlib.sha256( handle.read() ).hexdigest()
    assert json.loads( printed[ 0 ] ) == report[ "frozen_settings" ]
    assert list( report ) == sorted( report ), "keys are written sorted"


def test_without_an_injected_sha_the_command_asks_for_the_head_commit( engine, monkeypatch, tmp_path ):
    """The code sha comes from resolve_commit on the project root and the name HEAD."""
    calls = []
    monkeypatch.setattr( retune_run, "resolve_commit", lambda repo, name: calls.append( ( repo, name ) ) or "e" * 40 )
    _fake_cohort( monkeypatch, { "yes_no": _asks( engine ), "multiple_choice": [] } )
    out = tmp_path / "report.json"
    main( [ "--out", str( out ), "--vectors", _side_file( tmp_path ) ], printer=lambda line: None, session_factory=lambda: contextlib.nullcontext( FakeSession() ), engine_factory=lambda: engine )
    assert calls == [ ( retune_run.cu.get_project_root(), "HEAD" ) ]
    assert json.loads( out.read_text( encoding="utf-8" ) )[ "provenance" ][ "code_sha" ] == "e" * 40


def test_without_injected_factories_the_command_uses_get_db_and_the_live_engine_builder( engine, monkeypatch, tmp_path ):
    """With no factories given, main falls back to get_db and the live engine builder."""
    opened = []
    session = FakeSession()
    monkeypatch.setattr( retune_run, "get_db", lambda: opened.append( "get_db" ) or contextlib.nullcontext( session ) )
    monkeypatch.setattr( retune_run, "_open_engine", lambda: opened.append( "_open_engine" ) or engine )
    _fake_cohort( monkeypatch, { "yes_no": _asks( engine ), "multiple_choice": [] } )
    out = tmp_path / "report.json"
    assert main( [ "--out", str( out ), "--vectors", _side_file( tmp_path ) ], printer=lambda line: None, code_sha="f" * 40, clock=lambda: READ_AT ) == 0
    assert opened == [ "get_db", "_open_engine" ] and session.statements[ 0 ] == "SET TRANSACTION READ ONLY"
    assert out.exists()


def test_the_live_engine_is_built_with_embedding_generation_switched_off():
    """A replay on this engine cannot reach an embedding service: the call raises."""
    live = retune_run._open_engine()
    try:
        with pytest.raises( RuntimeError, match="stored vectors only" ):
            live._generate_embedding( "anything" )
    finally:
        PredictionEngine.reset()
