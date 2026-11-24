"""
Tests that each reader of extractor rows asks for the version the job writes under.

The review-card sweep and the principle retrieval read rows by version string. If one reads the untagged
string while a switch tags the job's rows, it sees no rows. The expected strings here are literals.
"""

import asyncio
import json

import pytest

import cosa.agents.principle_learner.extractor_prompt as prompt_module
import cosa.agents.principle_learner.review_card_sweep as sweep_module
from cosa.agents.principle_learner import principles_call
from cosa.agents.principle_learner.extractor_job import MODEL_KEY
from cosa.agents.principle_learner.extractor_prompt import PROMPT_VERSION
from cosa.config.configuration_manager import ConfigurationManager
from tests.unit.test_review_card_sweep import Dispatcher, _contested, _job, db  # noqa: F401  (db is a fixture)


@pytest.fixture( autouse=True )
def _fresh_sent_ledger( monkeypatch ):
    """
    Give each test an empty record of the cards the sweep already sent.

    Ensures:
        - the sweep's module-level sent record starts empty, so one test's send never hides a principle from the next
    """
    monkeypatch.setattr( sweep_module, "_SENT", {} )


def _model():
    """
    Read the extractor model the INI file names.

    Ensures:
        - returns the configured model id
    """
    return ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" ).get_required( MODEL_KEY )


def _stage_on( monkeypatch ):
    """
    Turn the stage switch on and every other registered switch off.

    Ensures:
        - switch_on answers True for the stage key only
    """
    monkeypatch.setattr( prompt_module, "switch_on", lambda key: key == prompt_module.DECISION_STAGE_KEY )


def test_the_sweep_finds_a_contested_principle_stored_under_the_stage_tagged_version( db, monkeypatch ):
    _stage_on( monkeypatch )
    _contested( db, 1, version=f"{_model()}:{PROMPT_VERSION}+stage" )
    report = json.loads( asyncio.run( _job( db, Dispatcher() )._execute() ) )
    assert report[ "contested" ] == 1


def test_the_sweep_with_the_stage_switch_on_does_not_see_a_principle_stored_under_the_untagged_version( db, monkeypatch ):
    _stage_on( monkeypatch )
    _contested( db, 1, version=f"{_model()}:{PROMPT_VERSION}" )
    report = json.loads( asyncio.run( _job( db, Dispatcher() )._execute() ) )
    assert report[ "contested" ] == 0


def test_the_sweep_with_every_switch_off_reads_the_untagged_version( db ):
    _contested( db, 1, version=f"{_model()}:{PROMPT_VERSION}" )
    report = json.loads( asyncio.run( _job( db, Dispatcher() )._execute() ) )
    assert report[ "contested" ] == 1


def test_retrieval_asks_for_the_stage_tagged_version_with_the_switch_on_and_the_untagged_one_off( monkeypatch ):
    assert principles_call.retrieval_versions()[ 1 ] == f"{_model()}:{PROMPT_VERSION}"
    _stage_on( monkeypatch )
    assert principles_call.retrieval_versions()[ 1 ] == f"{_model()}:{PROMPT_VERSION}+stage"
