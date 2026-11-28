"""The judge's reader on replies captured from the real model, and the capture script."""

import json
import runpy
import sys

import pytest

import cosa.utils.util as cu
from cosa.agents.prediction_engine.accuracy_comparators import _ask_judge
from cosa.agents.prediction_engine.answer_judge import judge_model, make_judge
from cosa.repo.doc_lint import model_transport
from cosa.research.judge_validation import capture

KINDS = ( "before_after", "staging_production", "must_may", "negated_permission", "scope_change", "time_change", "easy", "invented_condition" )
SIDES = [ ( kind, side ) for kind in KINDS for side in ( "matching", "altered" )
          if not ( kind == "easy" and side == "altered" ) and not ( kind == "invented_condition" and side == "matching" ) ]


def _fixture( kind ):
    """Read one committed fixture."""
    with open( f"{cu.get_project_root()}{capture.FIXTURE_DIR}/{kind}.json", encoding="utf-8" ) as handle:
        return json.load( handle )


def _without_timestamp( fixture ):
    """Drop the one field that differs between two captures of the same replies."""
    return { key: value for key, value in fixture.items() if key != "captured_at" }


def _replay_every_fixture():
    """Answer from all eight fixtures, trying each until one holds the request."""
    replays = [ capture.replay_complete( _fixture( kind ) ) for kind in KINDS ]

    def complete( model, system_prompt, user_prompt, **options ):
        for replay in replays:
            try:
                return replay( model, system_prompt, user_prompt, **options )
            except KeyError:
                continue
        raise KeyError( "no fixture holds this request" )

    return complete


@pytest.mark.parametrize( "kind,side", SIDES )
def test_the_reader_reads_each_captured_reply_as_the_judge_was_expected_to( kind, side ):
    """The assembled judge asks for the recorded request and reads the recorded reply."""
    fixture = _fixture( kind )
    record  = fixture[ "sides" ][ side ]
    judge   = make_judge( fixture[ "model" ], complete=capture.replay_complete( fixture ) )

    passed, verdict = _ask_judge( judge, record[ "predicted_text" ], fixture[ "actual_text" ] )

    assert passed is record[ "expected_pass" ]
    for key in ( "keeps_every_restriction", "invents_nothing", "actual_atoms", "predicted_atoms" ):
        assert verdict[ key ] == record[ "verdict" ][ key ]
    assert verdict[ "raw_reply" ] == record[ "calls" ][ -1 ][ "raw_reply" ]


def test_each_fixture_holds_the_case_the_pairs_file_names_for_its_kind():
    cases = capture.load_cases()

    assert set( cases ) == set( KINDS )
    for kind, case in cases.items():
        fixture = _fixture( kind )
        assert ( fixture[ "case_id" ], fixture[ "actual_text" ], fixture[ "model" ] ) == ( case[ "id" ], case[ "actual_text" ], judge_model() )
        recorded = { side: record[ "predicted_text" ] for side, record in fixture[ "sides" ].items() }
        assert recorded == { side: case[ key ] for side, key, _ in capture.SIDES if key in case }


def test_the_replay_ignores_the_tag_suffix_and_nothing_else():
    fixture = _fixture( "before_after" )
    call    = fixture[ "sides" ][ "matching" ][ "calls" ][ 0 ]
    replay  = capture.replay_complete( fixture )
    renamed = capture.TAG_SUFFIX.sub( r"\1_00000000>", call[ "user_prompt" ] )

    assert renamed != call[ "user_prompt" ]
    assert replay( call[ "model" ], call[ "system_prompt" ], renamed ) == call[ "raw_reply" ]
    for changed in ( ( "other-model", call[ "system_prompt" ], renamed ),
                     ( call[ "model" ], call[ "system_prompt" ] + " ", renamed ),
                     ( call[ "model" ], call[ "system_prompt" ], renamed.replace( "multiplexer", "console" ) ) ):
        with pytest.raises( KeyError, match="capture it again" ):
            replay( *changed )


def test_capturing_from_the_recorded_replies_rebuilds_the_fixture():
    fixture = _fixture( "must_may" )
    case    = capture.load_cases()[ "must_may" ]

    rebuilt = capture.capture_case( case, fixture[ "model" ], complete=capture.replay_complete( fixture ) )

    assert rebuilt[ "captured_at" ]
    for side, record in rebuilt[ "sides" ].items():
        old = fixture[ "sides" ][ side ]
        assert [ call[ "raw_reply" ] for call in record[ "calls" ] ] == [ call[ "raw_reply" ] for call in old[ "calls" ] ]
        assert record[ "verdict" ][ "actual_atoms" ] == old[ "verdict" ][ "actual_atoms" ]
    assert _without_timestamp( rebuilt ).keys() == _without_timestamp( fixture ).keys()


def test_main_writes_one_file_per_kind_and_returns_zero_when_all_agree( tmp_path, capsys ):
    code = capture.main( [ "--out", str( tmp_path ) ], complete=_replay_every_fixture() )

    assert code == 0
    assert sorted( path.name for path in tmp_path.iterdir() ) == sorted( kind + ".json" for kind in KINDS )
    assert capsys.readouterr().out.count( "expected pass=" ) == len( SIDES )


def test_main_returns_one_when_a_side_is_judged_against_its_expectation( tmp_path, capsys, monkeypatch ):
    case  = capture.load_cases()[ "easy" ]
    wrong = dict( case, altered_text=case[ "matching_text" ] )
    del wrong[ "matching_text" ]
    monkeypatch.setattr( capture, "load_cases", lambda: { "easy": wrong } )

    code = capture.main( [ "--out", str( tmp_path ), "--kind", "easy" ], complete=_replay_every_fixture() )

    assert code == 1
    assert "easy altered: expected pass=False judged pass=True" in capsys.readouterr().out


def test_run_as_a_module_exits_with_mains_code( tmp_path, monkeypatch ):
    """The run reaches main itself, so the exit code is what main returned."""
    monkeypatch.setattr( model_transport, "complete_sync", capture.replay_complete( _fixture( "easy" ) ) )
    monkeypatch.setattr( sys, "argv", [ "capture", "--out", str( tmp_path ), "--kind", "easy" ] )
    monkeypatch.delitem( sys.modules, "cosa.research.judge_validation.capture" )

    with pytest.raises( SystemExit ) as stopped:
        runpy.run_module( "cosa.research.judge_validation.capture", run_name="__main__" )

    assert stopped.value.code == 0 and ( tmp_path / "easy.json" ).exists()
