"""
Unit tests for semdup.frozen: decided values, live config, freeze command, committed file.
"""
import json

import pytest

from cosa.repo.doc_lint import model_transport
from cosa.repo.semdup import blind
from cosa.repo.semdup import config as cf
from cosa.repo.semdup import errors as err
from cosa.repo.semdup import frozen as fz
from cosa.repo.semdup import judge

# Captured 2026-10-25 from the prompt Rick approved as written; a literal, so editing the prompt reddens this test.
APPROVED_PROMPT_VERSION = "semdup-f620c8a20a"


def test_the_approved_prompt_text_has_the_version_that_was_approved():
    assert model_transport.prompt_version( "semdup", *judge.prompt_parts() ) == APPROVED_PROMPT_VERSION
    assert fz.live_config()[ "prompt_version" ] == APPROVED_PROMPT_VERSION


def test_the_decided_values_are_the_rulings_of_2026_10_25():
    cfg = fz.live_config()
    assert ( cfg[ "backend" ], cfg[ "temperature" ], cfg[ "unscorable_policy" ] ) == ( "max-plan", "unsettable:bounded-cc", "worst-rank" )
    assert cfg[ "model_id" ] == "claude-fable-5-1" and cfg[ "body_chars" ] == 10000
    assert cfg[ "jscpd" ] == { "version": "5.3.3", "min_tokens": 50, "min_lines": 5, "chosen_in": "initial-defaults" }
    assert cfg[ "backend" ] == judge.MaxPlanBackend().name and cfg[ "temperature" ] == judge.MaxPlanBackend().temperature_record


def test_the_scrub_list_holds_the_tool_tokens_and_two_distinct_arm_labels_neither_an_ordinary_word():
    assert len( fz.ARM_LABELS ) == 2 and len( set( fz.ARM_LABELS ) ) == 2
    assert not any( a in b for a in fz.ARM_LABELS for b in fz.ARM_LABELS if a != b )
    assert all( "-" in label and any( c.isdigit() for c in label ) for label in fz.ARM_LABELS )
    assert fz.live_config()[ "scrub_sha" ] == cf._sha( json.dumps( sorted( blind.scrub_tokens( fz.ARM_LABELS ) ) ) )
    assert fz.live_config()[ "scrub_sha" ] != cf._sha( json.dumps( sorted( blind.scrub_tokens( () ) ) ) )


def test_live_configuration_is_the_same_on_every_call():
    assert fz.live_config() == fz.live_config()


def test_frozen_path_is_under_the_project_root_conf_folder(monkeypatch, tmp_path):
    monkeypatch.setenv( "LUPIN_ROOT", str( tmp_path ) )
    assert fz.frozen_path() == f"{tmp_path}/src/conf/semdup-frozen-1.json"


def test_main_freezes_to_the_given_path_prints_the_sha_and_refuses_a_second_freeze(tmp_path, capsys):
    path = tmp_path / "conf" / "frozen.json"
    assert fz.main( [ "--path", str( path ) ] ) == 0
    out = capsys.readouterr().out
    assert f"frozen {path} config_sha={fz.live_config()[ 'config_sha' ]}" in out
    assert cf.verify_frozen( str( path ), fz.live_config() ) == fz.live_config()
    with pytest.raises( err.SemdupError ) as caught: fz.main( [ "--path", str( path ) ] )
    assert caught.value.code == err.CONFIG_ALREADY_FROZEN


def test_main_without_a_path_writes_to_the_frozen_path(monkeypatch, tmp_path):
    monkeypatch.setenv( "LUPIN_ROOT", str( tmp_path ) )
    assert fz.main( [] ) == 0
    assert ( tmp_path / "src" / "conf" / "semdup-frozen-1.json" ).is_file()


def test_the_committed_frozen_file_is_the_live_configuration():
    """Pin the committed file; a changed prompt, parser, scrub list or decided value reddens it."""
    assert cf.verify_frozen( fz.frozen_path(), fz.live_config() ) == fz.live_config()
