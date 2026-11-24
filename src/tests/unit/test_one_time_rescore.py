"""
Tests for the one-time re-score of the context arms' stored forecasts.

The planted asks, forecasts and answers below are written out, and every expected figure is a literal worked by hand.
"""

import json
import os

import pytest

import cosa.research.preference_replay.one_time_rescore as ots

OPTIONS = { "questions": [ { "header": "H", "options": [ { "label": "A" }, { "label": "B" } ] } ] }

# a1 plain yes; a2 yes with a free-text condition; a3 no; a4 a multiple-choice card answered A
ANSWERS = {
    "a1": { "actual_value": { "value": "yes" },                        "response_options": None,    "response_type": "yes_no" },
    "a2": { "actual_value": { "value": "yes [comment: only if green]" }, "response_options": None,    "response_type": "yes_no" },
    "a3": { "actual_value": { "value": "no" },                         "response_options": None,    "response_type": "yes_no" },
    "a4": { "actual_value": { "answers": { "H": "A" } },              "response_options": OPTIONS, "response_type": "multiple_choice" },
}


def _rec( ask_id, kind, forecast, correct, always_yes=False ):
    return { "id": ask_id, "response_type": kind, "forecast": forecast, "correct": correct, "always_yes_correct": always_yes, "confidence": 0.5 }


Q_RECORDS = [
    _rec( "a1", "yes_no", { "value": "yes" }, True, True ),
    _rec( "a2", "yes_no", { "value": "yes" }, True, True ),
    _rec( "a3", "yes_no", { "value": "yes" }, False, False ),
    _rec( "a4", "multiple_choice", { "answers": { "H": "A" } }, True ),
]
# X's stored flags disagree with the new measure on a1 and a4: the old column says wrong, the new one says right
X_RECORDS = [
    _rec( "a1", "yes_no", { "value": "yes" }, False, True ),
    _rec( "a2", "yes_no", { "value": "no" }, False, True ),
    _rec( "a3", "yes_no", { "value": "no" }, True, False ),
    _rec( "a4", "multiple_choice", { "answers": { "H": "A" } }, False ),
]


def test_score_ask_gives_each_planted_forecast_its_literal_old_and_new():
    got = ots.score_arm( Q_RECORDS, ANSWERS )
    assert { i: ( s[ "old" ], s[ "new" ], s[ "decided" ] ) for i, s in got.items() } == {
        "a1": ( True, True, True ), "a2": ( True, None, False ), "a3": ( False, False, True ), "a4": ( True, True, True ) }


def test_a_condition_that_needs_the_judge_is_counted_undecided_not_guessed():
    cell = ots.tally( ots.score_arm( Q_RECORDS, ANSWERS ) )
    assert cell == { "asks": 4, "old_correct": 3, "new_passed": 2, "decided": 3, "undecided": 1, "coverage": 0.75 }
    only_yes = ots.tally( ots.score_arm( Q_RECORDS, ANSWERS ), "yes_no" )
    assert ( only_yes[ "asks" ], only_yes[ "undecided" ] ) == ( 3, 1 )


def test_an_abstained_forecast_is_a_decided_miss():
    got = ots.score_ask( _rec( "a1", "yes_no", None, False ), ANSWERS[ "a1" ] )
    assert got == { "old": False, "new": False, "decided": True }


def test_a_missing_answer_names_the_ask():
    with pytest.raises( KeyError, match = "a9" ): ots.score_arm( [ _rec( "a9", "yes_no", None, False ) ], ANSWERS )


def test_paired_old_counts_every_ask_and_new_counts_only_asks_decided_in_both():
    q, x = ots.score_arm( Q_RECORDS, ANSWERS ), ots.score_arm( X_RECORDS, ANSWERS )
    old, new = ots.paired( x, q, "old" ), ots.paired( x, q, "new" )
    assert ( old[ "n" ], old[ "arm_only" ], old[ "base_only" ], old[ "difference" ], old[ "sign" ] ) == ( 4, 1, 3, -2, -1 )
    assert ( new[ "n" ], new[ "arm_only" ], new[ "base_only" ], new[ "difference" ], new[ "sign" ] ) == ( 3, 1, 0, 1, 1 )
    assert new[ "p_value" ] == 1.0


def test_rescore_flags_a_sign_reversal_and_leaves_q_unpaired_with_itself():
    result = ots.rescore( { "Q": Q_RECORDS, "X": X_RECORDS }, ANSWERS )
    assert "vs_q" not in result[ "arms" ][ "Q" ]
    assert result[ "arms" ][ "X" ][ "vs_q" ][ "sign_reversed" ] is True
    assert result[ "arms" ][ "Q" ][ "vs_always_yes" ][ "sign_reversed" ] is False
    assert result[ "always_yes" ] == { "asks": 3, "old_correct": 2, "new_passed": 1, "decided": 2, "undecided": 1, "coverage": 2 / 3 }
    assert result[ "arms" ][ "X" ][ "all" ][ "new_passed" ] == 3 and result[ "arms" ][ "X" ][ "all" ][ "old_correct" ] == 1


def test_a_constant_in_place_of_the_scorer_would_fail_these_literals( monkeypatch ):
    monkeypatch.setattr( ots, "score_ask", lambda record, answer: { "old": True, "new": True, "decided": True } )
    constant = ots.tally( ots.score_arm( Q_RECORDS, ANSWERS ) )
    assert constant[ "new_passed" ] != 2 and constant[ "undecided" ] != 1


def _write_arm_files( directory, drop_last_of=None ):
    for arm, stem in ots.ARM_FILE_STEMS.items():
        rows = ( X_RECORDS if arm == "Q+A" else Q_RECORDS )
        rows = rows[ :-1 ] if arm == drop_last_of else rows
        doc  = { "code_sha": "c" * 40, "ids": { "only_ids_sha256": "s" * 64, "only_ids_count": 3608 }, "run": { "asks": rows } }
        with open( f"{directory}/prediction-context-arm-{stem}-per-ask.json", "w", encoding = "utf-8" ) as handle: json.dump( doc, handle )


def test_load_per_ask_reads_five_files_and_refuses_a_different_ask_list( tmp_path ):
    _write_arm_files( tmp_path )
    got = ots.load_per_ask( str( tmp_path ) )
    assert list( got[ "records" ] ) == [ "Q", "Q+A", "Q+O", "Q+P", "Q+H" ] and got[ "files" ][ "Q" ][ "ids_count" ] == 3608
    assert got[ "files" ][ "Q" ][ "code_sha" ] == "c" * 40 and len( got[ "files" ][ "Q" ][ "sha256" ] ) == 64
    _write_arm_files( tmp_path, drop_last_of = "Q+H" )
    with pytest.raises( ValueError, match = r"Q\+H" ): ots.load_per_ask( str( tmp_path ) )


def test_read_switches_reads_values_and_skips_commented_lines( tmp_path ):
    ini = tmp_path / "x.ini"
    ini.write_text( "prediction engine enabled = true\n# prediction engine old enabled = true\nother enabled = true\nprediction hint voting enabled   = false\n" )
    assert ots.read_switches( str( ini ) ) == { "prediction engine enabled": "true", "prediction hint voting enabled": "false" }


class _Session:
    """A session that records every statement and refuses any write once read-only was set."""
    def __init__( self ):
        self.statements, self.rolled_back, self.read_only = [], False, False
    def execute( self, statement ):
        text = str( statement )
        if text.startswith( ( "INSERT", "UPDATE", "DELETE" ) ) and self.read_only: raise RuntimeError( "cannot execute in a read-only transaction" )
        self.statements.append( text )
        self.read_only = self.read_only or "READ ONLY" in text
        class _Rows:
            def fetchall( self_inner ): return [ ( "db", "role", "now", 1, 0 ) ]
        return _Rows()
    def rollback( self ): self.rolled_back = True
    def __enter__( self ): return self
    def __exit__( self, *args ): return False


def _asks_from( answers ):
    return [ { "id": i, **a } for i, a in answers.items() ]


def test_the_database_read_is_read_only_leaves_the_fixture_unchanged_and_writes_nothing( monkeypatch ):
    import cosa.research.preference_replay.retune_run as rr
    fixture = json.dumps( _asks_from( ANSWERS ), sort_keys = True )
    monkeypatch.setattr( rr, "cohort_asks", lambda session, kind, vectors=None: [ a for a in _asks_from( ANSWERS ) if a[ "response_type" ] == kind ] )
    session = _Session()
    got = ots.read_answers( session )
    assert session.statements[ 0 ].startswith( "SET TRANSACTION READ ONLY" ) and session.rolled_back
    assert set( got ) == set( ANSWERS ) and got[ "a2" ][ "actual_value" ] == ANSWERS[ "a2" ][ "actual_value" ]
    assert not any( s.startswith( ( "INSERT", "UPDATE", "DELETE" ) ) for s in session.statements )
    with pytest.raises( RuntimeError, match = "read-only" ): session.execute( "INSERT INTO notifications VALUES (1)" )
    assert json.dumps( _asks_from( ANSWERS ), sort_keys = True ) == fixture


def _main_args( tmp_path ):
    src = tmp_path / "src"
    src.mkdir()
    out = tmp_path / "out"
    out.mkdir()
    _write_arm_files( src )
    return [ "--per-ask-dir", str( src ), "--out-dir", str( out ) ], out


def test_main_writes_only_its_two_report_files_with_the_figures_and_the_unscored_phases( tmp_path, monkeypatch ):
    argv, out = _main_args( tmp_path )
    monkeypatch.setattr( ots, "read_answers", lambda session: ANSWERS )
    printed = []
    class _Clock:
        def isoformat( self ): return "2026-11-23T00:00:00+00:00"
    assert ots.main( argv, printer = printed.append, session_factory = _Session, code_sha = "abc123", clock = lambda: _Clock() ) == 0
    assert sorted( os.listdir( out ) ) == [ "2026.11.23-one-time-rescore.json", "2026.11.23-one-time-rescore.md" ]
    doc  = json.load( open( out / "2026.11.23-one-time-rescore.json" ) )
    text = ( out / "2026.11.23-one-time-rescore.md" ).read_text()
    assert doc[ "run" ][ "code_sha" ] == "abc123" and doc[ "model_calls" ] == 0 and "phase 8" in doc[ "phases_without_stored_forecasts" ]
    assert "- scored sha: abc123" in text and "| Q+A | vs_q |" in text and "no stored per-ask forecasts" in text and "Sign reversals" in text
    assert doc[ "reversals" ] and "- none" not in text
    assert printed and "wrote" in printed[ 0 ]


def test_render_says_none_when_no_sign_reverses( tmp_path, monkeypatch ):
    per_ask = { "records": { "Q": Q_RECORDS }, "files": { "Q": { "ids_count": 1, "ids_sha256": "s", "code_sha": "c" * 40, "sha256": "f" } } }
    report  = ots.build_report( per_ask, ANSWERS, { "code_sha": "x", "started": "t", "command": "c" }, {} )
    assert report[ "reversals" ] == [] and "- none" in ots.render_markdown( report )


def test_main_refuses_an_output_folder_under_src_rnd( tmp_path ):
    with pytest.raises( ValueError, match = "src/rnd" ): ots.main( [ "--per-ask-dir", str( tmp_path ), "--out-dir", "/x/src/rnd/y" ] )


def test_main_defaults_resolve_the_sha_and_clock_when_none_are_injected( tmp_path, monkeypatch ):
    argv, out = _main_args( tmp_path )
    monkeypatch.setattr( ots, "read_answers", lambda session: ANSWERS )
    monkeypatch.setattr( ots, "resolve_commit", lambda root, ref: "feedface" )
    assert ots.main( argv, printer = lambda m: None, session_factory = _Session ) == 0
    assert json.load( open( out / "2026.11.23-one-time-rescore.json" ) )[ "run" ][ "code_sha" ] == "feedface"
