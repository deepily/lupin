"""
Unit tests for duplicate_check.frozen: decided values, live config, freeze, file.
"""
import json
import pathlib

import pytest

from cosa.repo.doc_lint import model_transport
from cosa.repo.duplicate_check import blind
from cosa.repo.duplicate_check import config as cf
from cosa.repo.duplicate_check import errors as err
from cosa.repo.duplicate_check import frozen as fz
from cosa.repo.duplicate_check import judge

# Captured 2026-10-25 from the prompt Rick approved as written; a literal, so editing the prompt reddens this test.
APPROVED_PROMPT_VERSION = "semdup-f620c8a20a"


def test_the_approved_prompt_text_has_the_version_that_was_approved():
    assert model_transport.prompt_version( "semdup", *judge.prompt_parts() ) == APPROVED_PROMPT_VERSION
    assert fz.live_config()[ "prompt_version" ] == APPROVED_PROMPT_VERSION


def test_the_decided_values_are_the_rulings_of_2026_10_25():
    cfg = fz.live_config()
    assert ( cfg[ "backend" ], cfg[ "temperature" ], cfg[ "unscorable_policy" ] ) == ( "max-plan", "unsettable:bounded-cc", "worst-rank" )
    assert cfg[ "model_id" ] == "claude-opus-5-5" and cfg[ "body_chars" ] == 10000
    assert cfg[ "jscpd" ] == { "version": "5.3.3", "min_tokens": 50, "min_lines": 5, "max_size": "5mb", "chosen_in": "label-prep-max-size" }
    assert cfg[ "backend" ] == judge.MaxPlanBackend().name and cfg[ "temperature" ] == judge.MaxPlanBackend().temperature_record


def test_the_scrub_list_holds_the_tool_tokens_and_two_distinct_arm_labels_neither_an_ordinary_word():
    assert len( fz.ARM_LABELS ) == 2 and len( set( fz.ARM_LABELS ) ) == 2
    assert not any( a in b for a in fz.ARM_LABELS for b in fz.ARM_LABELS if a != b )
    assert all( "-" in label and any( c.isdigit() for c in label ) for label in fz.ARM_LABELS )
    assert fz.live_config()[ "scrub_sha" ] == cf._sha( json.dumps( sorted( blind.scrub_tokens( fz.ARM_LABELS ) ) ) )
    assert fz.live_config()[ "scrub_sha" ] != cf._sha( json.dumps( sorted( blind.scrub_tokens( () ) ) ) )


def test_live_configuration_is_the_same_on_every_call():
    assert fz.live_config() == fz.live_config()


def test_main_freezes_to_the_given_path_prints_the_sha_and_refuses_a_second_freeze(tmp_path, capsys):
    path = tmp_path / "conf" / "frozen.json"
    assert fz.main( [ "--path", str( path ) ] ) == 0
    out = capsys.readouterr().out
    assert f"frozen {path} config_sha={fz.live_config()[ 'config_sha' ]}" in out
    assert cf.verify_frozen( str( path ), fz.live_config() ) == fz.live_config()
    with pytest.raises( err.DuplicateCheckError ) as caught: fz.main( [ "--path", str( path ) ] )
    assert caught.value.code == err.CONFIG_ALREADY_FROZEN


def test_main_without_a_path_is_refused_by_the_parser():
    with pytest.raises( SystemExit ): fz.main( [] )


def test_the_committed_frozen_file_is_the_live_configuration():
    """Pin the committed file; a changed prompt, parser, scrub list or decided value reddens it."""
    assert cf.verify_frozen( fz.frozen_path(), fz.live_config() ) == fz.live_config()


def select( monkeypatch, model ):
    # the INI key `duplicate check judge model` reads as model, whatever lupin-app.ini holds
    monkeypatch.setattr( fz.chs, "model_id", lambda key, config=None: model if key == fz.chs.JUDGE_MODEL_KEY else None )


def test_the_selected_model_is_read_from_the_ini_key_each_time_it_is_asked( monkeypatch ):
    assert fz.selected_model() == "claude-opus-5-5", "lupin-app.ini names the Opus model since the switch of 13 Nov"
    select( monkeypatch, "claude-fable-5-1" )
    assert fz.selected_model() == "claude-fable-5-1"


def test_frozen_path_finds_the_one_file_whose_model_id_is_the_selected_model( monkeypatch ):
    assert fz.frozen_path().endswith( "/src/conf/semdup-frozen-3-opus.json" )
    select( monkeypatch, "claude-fable-5-1" )
    assert fz.frozen_path().endswith( "/src/conf/semdup-frozen-2.json" )


def conf_with( tmp_path, monkeypatch, models ):
    # a project root whose src/conf holds one semdup-frozen-N.json for each model id given, plus a file that does not match the glob
    folder = tmp_path / "src" / "conf"
    folder.mkdir( parents=True )
    for n, model in enumerate( models ): ( folder / f"semdup-frozen-{n}.json" ).write_text( json.dumps( { "model_id": model } ) )
    ( folder / "other.json" ).write_text( json.dumps( { "model_id": "claude-opus-5-5" } ) )
    monkeypatch.setenv( "LUPIN_ROOT", str( tmp_path ) )


def test_a_model_with_no_frozen_file_gets_a_path_that_names_it_and_verify_frozen_cannot_open_and_two_files_are_drift( tmp_path, monkeypatch ):
    conf_with( tmp_path, monkeypatch, [ "claude-fable-5-1" ] )
    select( monkeypatch, "claude-opus-5-5" )
    path = fz.frozen_path()
    assert path == f"{tmp_path}/src/conf/semdup-frozen-claude-opus-5-5.json" and not pathlib.Path( path ).exists()
    with pytest.raises( FileNotFoundError ): cf.verify_frozen( path, fz.live_config() )
    other = tmp_path / "second"
    other.mkdir()
    conf_with( other, monkeypatch, [ "claude-opus-5-5", "claude-opus-5-5" ] )
    with pytest.raises( err.DuplicateCheckError ) as twice: fz.frozen_path()
    assert twice.value.code == err.CONFIG_DRIFT and "semdup-frozen-0.json" in twice.value.detail and "semdup-frozen-1.json" in twice.value.detail


def test_live_config_carries_the_selected_model_and_its_own_sha( monkeypatch ):
    opus = fz.live_config()
    select( monkeypatch, "claude-fable-5-1" )
    live = fz.live_config()
    assert live[ "model_id" ] == "claude-fable-5-1" and live[ "config_sha" ] == cf.config_sha( live ) != opus[ "config_sha" ]


def test_the_committed_opus_file_is_the_live_configuration_under_opus_and_differs_from_the_fable_file_in_model_and_sha_only( monkeypatch ):
    opus  = cf.verify_frozen( fz.frozen_path(), fz.live_config() )
    select( monkeypatch, "claude-fable-5-1" )
    fable = cf.verify_frozen( fz.frozen_path(), fz.live_config() )
    assert opus[ "model_id" ] == "claude-opus-5-5"
    assert sorted( k for k in fable if fable[ k ] != opus[ k ] ) == [ "config_sha", "model_id" ]


def test_the_opus_file_refuses_a_fable_run_as_drift( monkeypatch ):
    path = fz.frozen_path()
    select( monkeypatch, "claude-fable-5-1" )
    with pytest.raises( err.DuplicateCheckError ) as caught: cf.verify_frozen( path, fz.live_config() )
    assert caught.value.code == err.CONFIG_DRIFT and "model_id" in caught.value.detail
