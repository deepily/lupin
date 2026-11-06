"""
The one-off rescore of old multiple-choice rows left unscored as empty_answers.

The comparator is the real one; only the database session is a stand-in. The batch rows are
never selected, and responded_at is never touched.
"""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path( __file__ ).resolve().parents[ 2 ] / "scripts" / "rescore_empty_answers_mc.py"
spec   = importlib.util.spec_from_file_location( "rescore_empty_answers_mc", SCRIPT )
rm     = importlib.util.module_from_spec( spec )
spec.loader.exec_module( rm )

PRED_COMMIT = { "answers": { "Commit": "Commit and push" } }


def stored( answers ): return { "value": json.dumps( { "answers": answers } ) }


def row( actual, predicted, n=0 ):
    return SimpleNamespace( id=f"row-{n}", notification_id=f"note-{n}", actual_value=actual, predicted_value=predicted, accuracy_match=None,
                            accuracy_detail={ "reason": "empty_answers" }, responded_at="2026-11-01" )


class FakeQuery:
    def __init__( self, rows ): self.rows, self.filters = rows, None
    def filter( self, *conditions ): self.filters = conditions; return self
    def all( self ): return self.rows


class FakeSession:
    def __init__( self, rows ): self.rows, self.query_obj, self.commits = rows, None, 0
    def query( self, model ): self.query_obj = FakeQuery( self.rows ); return self.query_obj
    def commit( self ): self.commits += 1
    def __enter__( self ): return self
    def __exit__( self, *exc ): return False


def test_a_decoded_matching_answer_scores_true():
    outcome, decoded, match, detail = rm.classify( stored( { "Commit": "Commit and push" } ), PRED_COMMIT )
    assert ( outcome, match, detail[ "matches" ] ) == ( "would_score", True, 1 ) and decoded == { "answers": { "Commit": "Commit and push" } }


def test_a_decoded_different_answer_scores_false_and_names_the_mismatch():
    outcome, _, match, detail = rm.classify( stored( { "Commit": "Commit only" } ), PRED_COMMIT )
    assert ( outcome, match ) == ( "would_score", False ) and detail[ "mismatches" ][ 0 ][ "actual" ] == "Commit only"


@pytest.mark.parametrize( "actual", [ { "value": "Approve" }, { "value": "" }, { "value": 5 }, { "no_value": 1 }, None, "Approve" ] )
def test_a_bare_label_or_malformed_stored_value_is_skipped_as_not_json_answers( actual ):
    assert rm.classify( actual, PRED_COMMIT ) == ( "skipped", "not_json_answers", None, None )


@pytest.mark.parametrize( "predicted", [ None, {}, "yes", [ 1 ] ] )
def test_an_empty_prediction_is_skipped_as_no_prediction( predicted ):
    assert rm.classify( stored( { "Commit": "x" } ), predicted ) == ( "skipped", "no_prediction", None, None )


def test_a_cancelled_answer_stays_unscored_because_the_comparator_still_says_empty():
    cancelled = { "value": json.dumps( { "cancelled": True, "answers": {} } ) }
    assert rm.classify( cancelled, PRED_COMMIT ) == ( "skipped", "comparator_unscored", None, None )


def test_an_answers_mapping_the_comparator_cannot_score_is_comparator_unscored():
    assert rm.classify( { "value": json.dumps( { "answers": { "A": "x" } } ) }, { "answers": {} } )[ :2 ] == ( "skipped", "comparator_unscored" )


def test_a_report_run_counts_every_outcome_and_writes_nothing():
    rows    = [ row( stored( { "Commit": "Commit and push" } ), PRED_COMMIT ), row( stored( { "Commit": "Commit only" } ), PRED_COMMIT ),
                row( { "value": "Approve" }, PRED_COMMIT ), row( stored( { "Commit": "x" } ), None ) ]
    before  = [ ( r.actual_value, r.accuracy_match, r.accuracy_detail ) for r in rows ]
    session = FakeSession( rows )
    counts  = rm.rescore( session )
    assert dict( counts ) == { "selected": 4, "would_score": 2, "match": 1, "miss": 1, "skipped:not_json_answers": 1, "skipped:no_prediction": 1 }
    assert [ ( r.actual_value, r.accuracy_match, r.accuracy_detail ) for r in rows ] == before and session.commits == 0


def test_a_write_run_stores_the_score_keeps_responded_at_and_skips_the_rest( tmp_path ):
    scored, bare = row( stored( { "Commit": "Commit and push" } ), PRED_COMMIT ), row( { "value": "Approve" }, PRED_COMMIT )
    session = FakeSession( [ scored, bare ] )
    rm.rescore( session, write=True, dump_path=str( tmp_path / "d.jsonl" ) )
    assert scored.actual_value == { "answers": { "Commit": "Commit and push" } } and scored.accuracy_match is True
    assert scored.accuracy_detail[ "matches" ] == 1 and scored.responded_at == "2026-11-01"
    assert bare.accuracy_match is None and bare.accuracy_detail == { "reason": "empty_answers" } and session.commits == 1


def test_a_write_run_commits_in_chunks( monkeypatch, tmp_path ):
    monkeypatch.setattr( rm, "COMMIT_EVERY", 2 )
    session = FakeSession( [ row( stored( { "Commit": "x" } ), PRED_COMMIT ) for _ in range( 5 ) ] )
    rm.rescore( session, write=True, dump_path=str( tmp_path / "d.jsonl" ) )
    assert session.commits == 3                                    # at rows 2 and 4, then the final commit


def test_select_rows_asks_for_multiple_choice_only():
    session = FakeSession( [] )
    assert rm.select_rows( session ) == [] and len( session.query_obj.filters ) == 2
    assert "multiple_choice" in [ c.right.value for c in session.query_obj.filters if hasattr( c.right, "value" ) ]


def test_main_prints_report_only_counts_and_returns_zero(capsys):
    session = FakeSession( [ row( stored( { "Commit": "Commit and push" } ), PRED_COMMIT ) ] )
    assert rm.main( [], session_factory=lambda: session ) == 0
    out = capsys.readouterr().out
    assert "mode: report only" in out and "match" in out and session.commits == 0


def test_main_write_flag_writes( capsys, tmp_path ):
    session = FakeSession( [ row( stored( { "Commit": "Commit and push" } ), PRED_COMMIT ) ] )
    dump = tmp_path / "out" / "dump.jsonl"
    assert rm.main( [ "--write", "--dump-path", str( dump ) ], session_factory=lambda: session ) == 0
    out = capsys.readouterr().out
    assert "mode: WRITE" in out and f"dump file: {dump}" in out and session.commits == 1 and session.rows[ 0 ].accuracy_match is True
    assert dump.exists()


def test_main_opens_the_real_session_factory_when_none_is_given(monkeypatch, capsys):
    session = FakeSession( [] )
    import cosa.rest.db.database as database
    monkeypatch.setattr( database, "get_db", lambda: session )
    assert rm.main( [] ) == 0
    assert "selected" in capsys.readouterr().out


def test_a_failed_import_exits_3_with_a_fatal_line(monkeypatch, capsys):
    import sys
    monkeypatch.setitem( sys.modules, "cosa.agents.prediction_engine.accuracy_comparators", None )      # None in sys.modules makes the import raise
    again = importlib.util.module_from_spec( spec )
    with pytest.raises( SystemExit ) as exit_info: spec.loader.exec_module( again )
    assert exit_info.value.code == 3 and "FATAL: import failed" in capsys.readouterr().err


def test_a_write_run_dumps_the_old_values_before_any_row_changes( tmp_path ):
    old_actual = stored( { "Commit": "Commit only" } )
    changed, bare = row( old_actual, PRED_COMMIT, 1 ), row( { "value": "Approve" }, PRED_COMMIT, 2 )
    dump = tmp_path / "dump.jsonl"

    class WatchedRow( SimpleNamespace ):
        def __setattr__( self, name, value ):
            if name == "actual_value" and "actual_value" in self.__dict__: assert dump.exists(), "a row changed before the dump file existed"
            super().__setattr__( name, value )

    changed = WatchedRow( **vars( changed ) )

    class WatchedSession( FakeSession ):
        def commit( self ):
            assert dump.exists(), "a commit ran before the dump file existed"
            super().commit()

    counts = rm.rescore( WatchedSession( [ changed, bare ] ), write=True, dump_path=str( dump ) )
    lines  = [ json.loads( line ) for line in dump.read_text().splitlines() ]
    assert counts[ "dumped" ] == 1 and len( lines ) == 1
    assert lines[ 0 ] == { "id": "row-1", "notification_id": "note-1", "actual_value": old_actual, "accuracy_match": None, "accuracy_detail": { "reason": "empty_answers" } }
    assert changed.actual_value == { "answers": { "Commit": "Commit only" } }


def test_a_failed_dump_leaves_every_row_untouched_and_commits_nothing( tmp_path ):
    target  = row( stored( { "Commit": "Commit only" } ), PRED_COMMIT )
    session = FakeSession( [ target ] )
    blocker = tmp_path / "a-file"
    blocker.write_text( "x" )
    with pytest.raises( OSError ): rm.rescore( session, write=True, dump_path=str( blocker / "dump.jsonl" ) )      # a file where the directory should be
    assert target.accuracy_match is None and target.actual_value == stored( { "Commit": "Commit only" } ) and session.commits == 0


def test_a_report_run_writes_no_dump( tmp_path ):
    dump = tmp_path / "dump.jsonl"
    rm.rescore( FakeSession( [ row( stored( { "Commit": "x" } ), PRED_COMMIT ) ] ), dump_path=str( dump ) )
    assert not dump.exists()


def test_the_default_dump_path_is_a_stamped_file_under_the_project_io_directory( monkeypatch ):
    monkeypatch.setattr( rm.cu, "get_project_root", lambda: "/proj" )
    path = rm.default_dump_path()
    assert path.startswith( "/proj/io/rescore-empty-answers-mc-" ) and path.endswith( "Z.jsonl" )


def test_a_write_run_without_a_dump_path_uses_the_default( monkeypatch, tmp_path ):
    monkeypatch.setattr( rm, "default_dump_path", lambda: str( tmp_path / "default.jsonl" ) )
    rm.rescore( FakeSession( [ row( stored( { "Commit": "x" } ), PRED_COMMIT ) ] ), write=True )
    assert ( tmp_path / "default.jsonl" ).exists()
