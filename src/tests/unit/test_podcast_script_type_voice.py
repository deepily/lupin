#!/usr/bin/env python3
"""
Unit tests for the voice door of the podcast script types.

A spoken status report podcast must reach script_type on both podcast commands.
The training corpus teaches the router to emit it. The expeditor contract maps it
and never asks for it. The factory builds a job that carries it.
"""

import json
import os

import pytest

import cosa.utils.util as cu
from cosa.agents.notification_proxy.config import TEST_PROFILES
from cosa.agents.runtime_argument_expeditor.agent_registry import JOB_ARG_CONTRACTS
from cosa.agents.runtime_argument_expeditor.expeditor import ArgSpec, RuntimeArgumentExpeditor
from cosa.rest.agentic_job_factory import create_agentic_job

PG = "agent router go to podcast generator"
RP = "agent router go to research to podcast"

TRAINING_JSON = os.path.join( cu.get_project_root(), "src", "conf", "training", "agent-router-agentic-commands.json" )


def _spec( command ):
    return ArgSpec.from_entry( JOB_ARG_CONTRACTS[ command ] )


@pytest.mark.parametrize( "command", [ PG, RP ] )
def test_the_contract_maps_script_type_and_defaults_it_so_the_expeditor_never_asks( command ):
    spec = _spec( command )
    assert spec.arg_mapping[ "script_type" ] == "script_type"
    assert spec.fallback_defaults[ "script_type" ] == "research_critical"
    assert "script_type" not in spec.fallback_questions and "script_type" not in spec.required_user_args


@pytest.mark.parametrize( "command", [ PG, RP ] )
def test_every_code_fallback_for_languages_is_english_only( command ):
    assert _spec( command ).fallback_defaults[ "languages" ] == "en"


def test_the_test_auto_answer_profiles_are_english_unless_they_are_the_spanish_one():
    assert TEST_PROFILES[ "research_to_podcast" ][ "languages" ] == "en"
    assert TEST_PROFILES[ "podcast" ][ "languages" ] == "en"
    assert TEST_PROFILES[ "research_to_podcast_spanish" ][ "languages" ] == "en,es-MX"
    assert [ name for name, profile in TEST_PROFILES.items() if "es-MX" in profile.get( "languages", "" ) ] == [ "research_to_podcast_spanish" ]


@pytest.mark.parametrize( "command", [ PG, RP ] )
def test_the_training_json_teaches_status_report_to_emit_script_type( command ):
    with open( TRAINING_JSON, encoding="utf-8" ) as f:
        entry = json.load( f )[ command ]
    rule = entry[ "conditional_args" ][ "script_type" ]
    assert rule[ "value" ] == "status_report" and "status report" in rule[ "triggers" ]
    with open( cu.get_project_root() + entry[ "template_file" ], encoding="utf-8" ) as f:
        lines = [ line.strip() for line in f if line.strip() and not line.startswith( "#" ) ]
    status_lines = [ line for line in lines if "status report" in line.lower() or "status-report" in line.lower() ]
    assert len( status_lines ) >= 4
    assert all( any( trigger in line.lower() for trigger in rule[ "triggers" ] ) for line in status_lines )


def test_a_routers_status_report_answer_reaches_script_type_on_the_job():
    router_answer = 'topic="climate change" script_type="status_report"'
    lora          = RuntimeArgumentExpeditor.__new__( RuntimeArgumentExpeditor )._parse_lora_args( router_answer )
    assert lora == { "topic": "climate change", "script_type": "status_report" }
    for command, key in ( ( PG, "research" ), ( RP, "query" ) ):
        spec   = _spec( command )
        mapped = { spec.arg_mapping.get( name, name ): value for name, value in lora.items() }
        assert mapped[ "script_type" ] == "status_report"
        args = { key: "io/r.md" if command == PG else "climate change", "script_type": mapped[ "script_type" ] }
        job  = create_agentic_job( command, args, "u", "u@t.com", "s" )
        assert job.script_type == "status_report" and job.target_languages == [ "en" ]


def test_a_routers_list_literal_language_answer_becomes_a_language_list():
    from cosa.rest.agentic_job_factory import _podcast_languages
    assert _podcast_languages( { "target_languages": "['es-MX']" } ) == [ "es-MX" ]
    assert _podcast_languages( { "target_languages": "['en', 'es-MX']" } ) == [ "en", "es-MX" ]
