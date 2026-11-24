"""
The Haiku baseline, tested through a stand-in for the SDK.

The model is always a stand-in for the SDK (complete's query_fn), so no test calls one. The job tests run over
in-memory SQLite with the real episode_view and the real run_arm.

Each test names what it would catch:
  - a default or a timeout read as an answer                          -> test_the_default_and_time_*
  - a later answer or history leaking into the prompt                -> test_the_prompt_holds_only_*
  - a reply the card never offered stored as a forecast               -> test_parse_*
  - a repeat prompt paying for a second call                          -> test_a_repeat_*
  - a timeout, crash or refusal storing no row or two                -> test_the_job_*
"""

import asyncio
import json
import stat
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import cosa.agents.prediction_engine.context_baseline as cb
import cosa.agents.prediction_engine.episode_view as ev
from cosa.agents.prediction_engine.principles_forecast import CapGate
from cosa.repo.doc_lint import model_transport as mt
from cosa.research.preference_replay import scratch_db  # noqa: F401  registers the one shared SQLite hooks for JSONB and Vector
from cosa.rest.db.repositories.arm_forecast_repository import CAPPED_ARM_REASON
from cosa.rest.postgres_models import Notification, PredictionArmForecast, PredictionLog
import cosa.agents.prediction_engine.full_answer as fa


@pytest.fixture( autouse=True )
def full_answer_off( monkeypatch ):
    """
    Turn the full-answer reply off for every test in this file.

    These tests pin the old reply path. The INI ships the switch on since 24 Nov 2026.
    The on path is tested in test_full_answer.py.
    """
    monkeypatch.setattr( fa, "full_answer_enabled", lambda: False )


T0        = datetime( 2026, 11, 10, 12, 0, tzinfo=timezone.utc )
RECIPIENT = uuid.UUID( "00000000-0000-4000-8000-0000000000bb" )
SENDER    = "claude.code@lupin.deepily.ai#ab12cd34"
CHOICES   = { "questions": [
    { "header": "Plan", "question": "Which plan?", "options": [ { "label": "Plan A", "description": "the safe one" }, { "label": "Plan B (Recommended)" } ] },
    { "header": "Extras", "question": "Which extras?", "multi_select": True, "options": [ { "label": "Docs" }, { "label": "Tests" } ] },
    { "header": "Note", "question": "Anything else?", "input_type": "text" },
] }


@pytest.fixture
def factory( monkeypatch ):
    """Give a session factory over empty copies of the three tables the job reads or writes."""
    engine = create_engine( "sqlite://", connect_args={ "check_same_thread": False }, poolclass=StaticPool )
    for model in ( Notification, PredictionLog, PredictionArmForecast ): model.__table__.create( engine )
    monkeypatch.setattr( ev, "pool_limit", lambda: 50 )
    yield lambda: Session( engine )
    engine.dispose()


def ask( factory, **extra ):
    """Insert one ask to the test recipient and return its id as text."""
    row = dict( id=uuid.uuid4(), sender_id=SENDER, recipient_id=RECIPIENT, title="Ship it?", message="Should the worker ship?", abstract="Plan in [the task](/app/tasks/approve?row=abc)",
                type="task", priority="medium", created_at=T0, response_requested=True, response_type="yes_no", response_default="no", timeout_seconds=120 )
    row.update( extra )
    with factory() as db:
        db.add( Notification( **row ) )
        db.commit()
    return str( row[ "id" ] )


def episode( factory, **extra ):
    """Return episode_view's result for a new ask."""
    with factory() as db: return ev.episode_view( db, ask( factory, **extra ), limit=50 )


def replying( *texts, calls=None ):
    """Build an SDK stand-in that answers each call with the next text, repeating the last."""
    queue = list( texts )

    async def query( prompt, options ):
        if calls is not None: calls.append( ( options.system_prompt, prompt ) )
        yield AssistantMessage( content=[ TextBlock( queue.pop( 0 ) if len( queue ) > 1 else queue[ 0 ] ) ], model=options.model )
    return query


def baseline( tmp_path, query_fn, timeout=5, layers=cb.ALL_LAYERS ):
    """Build a baseline over a ledger in tmp_path."""
    return cb.ContextBaseline( "haiku-x", timeout, layers, cb.open_ledger( str( tmp_path / "ledger.jsonl" ) ), query_fn=query_fn )


def arm_rows( factory ):
    """All sibling rows."""
    with factory() as db: return db.query( PredictionArmForecast ).all()


def test_the_prompt_holds_the_card_and_the_reply_format_for_its_type( factory ):
    ep = episode( factory )
    text = cb.build_user_prompt( ep )
    assert text.startswith( "Question: Should the worker ship?" ) and text.endswith( cb.YES_NO_FORMAT )
    assert "Title: Ship it?" in text and "approval link to /app/tasks/approve?row=abc" in text
    choice = cb.build_user_prompt( episode( factory, response_type="multiple_choice", response_options=CHOICES ) )
    assert choice.endswith( cb.CHOICE_FORMAT )


def test_the_prompt_holds_only_the_layers_asked_for( factory ):
    ep = episode( factory, response_type="multiple_choice", response_options=CHOICES )
    only = cb.build_user_prompt( ep, ( "prompt", ) )
    assert "Which plan?" in only and "Plan A" not in only and "Title:" not in only and "If nobody answers" not in only
    options = cb.build_user_prompt( ep, ( "prompt", "options" ) )
    assert '"Plan A" - the safe one' in options and "(recommended by the asker)" in options and "several may be chosen" in options and "(free text)" in options
    assert "Title:" not in options
    assert "Links in the abstract: none" in cb.build_user_prompt( episode( factory, abstract="no links here" ), ( "title_abstract", ) )


def test_the_prompt_leaves_out_an_empty_title_and_abstract_and_a_field_with_no_key( factory ):
    ep   = episode( factory, title="", abstract=None, response_type="multiple_choice", response_options={ "questions": [ { "question": "Pick", "options": [ { "label": "x" } ] } ] } )
    text = cb.build_user_prompt( ep )
    assert "Title:" not in text and "Abstract:" not in text and "- field: Pick" in text and "Links in the abstract: none" in text


def test_the_default_and_time_are_inputs_worded_as_a_fallback_never_an_answer( factory ):
    text = cb.build_user_prompt( episode( factory ), ( "default_time", ) )
    assert 'If nobody answers within 120 seconds, the card falls back to "no". That fallback is not their answer.' in text
    bare = cb.build_user_prompt( episode( factory, response_default=None, timeout_seconds=None ), ( "default_time", ) )
    assert "If nobody answers, the card has no fallback. That fallback is not their answer." in bare
    assert "Ship it?" not in cb.build_user_prompt( episode( factory ), ( "default_time", ) ), "no layer leaks into another"


def test_the_prompt_holds_only_ask_time_fields_never_history_or_a_later_answer( factory ):
    ep = episode( factory )
    ep[ "history" ] = [ { "status": "answered", "answer": { "value": "LATE-ANSWER" } } ]
    ep[ "exposure" ] = { "revealed_at": "REVEALED", "draft_at_reveal": None }
    assert "LATE-ANSWER" not in cb.build_user_prompt( ep ) and "REVEALED" not in cb.build_user_prompt( ep )


def test_an_unsupported_card_type_is_refused_by_the_prompt_and_the_parser( factory ):
    ep = episode( factory, response_type="open_ended" )
    with pytest.raises( cb.UnsupportedAsk ): cb.build_user_prompt( ep )
    with pytest.raises( cb.UnsupportedAsk ): cb.parse_reply( "{}", ep )


@pytest.mark.parametrize( "reply,expected", [
    ( '{"answer": "yes", "confidence": 0.8}',                        { "value": "yes", "confidence": 0.8 } ),
    ( 'Here:\n```json\n{"answer": "no", "confidence": 1}\n```',      { "value": "no", "confidence": 1.0 } ),
] )
def test_parse_reads_a_yes_no_reply_even_inside_a_code_fence( factory, reply, expected ):
    assert cb.parse_reply( reply, episode( factory ) ) == expected


@pytest.mark.parametrize( "reply,why", [
    ( "no braces at all",                                  "no JSON object" ),
    ( '{"answer": "yes", "confidence": }',                 "no JSON object" ),
    ( '{"answer": "maybe", "confidence": 0.5}',            "answer must be one of" ),
    ( '{"answer": "yes"}',                                 "confidence must be" ),
    ( '{"answer": "yes", "confidence": true}',             "confidence must be" ),
    ( '{"answer": "yes", "confidence": 1.5}',              "confidence must be" ),
    ( '{"answer": "yes", "confidence": "high"}',           "confidence must be" ),
] )
def test_parse_refuses_an_unreadable_yes_no_reply( factory, reply, why ):
    with pytest.raises( ValueError, match=why ): cb.parse_reply( reply, episode( factory ) )


@pytest.mark.parametrize( "reply", [ "[1]", "7", '"yes"' ] )
def test_parse_refuses_a_reply_whose_json_is_not_an_object( factory, reply ):
    with pytest.raises( ValueError, match="holds no JSON object" ): cb.parse_reply( reply, episode( factory ) )


def test_parse_reads_a_multiple_choice_reply_field_by_field_and_skips_free_text( factory ):
    ep    = episode( factory, response_type="multiple_choice", response_options=CHOICES )
    reply = json.dumps( { "answers": { "Plan": "Plan A", "Extras": [ "Docs", "Tests" ] }, "confidence": 0.6 } )
    assert cb.parse_reply( reply, ep ) == { "answers": { "Plan": "Plan A", "Extras": [ "Docs", "Tests" ] }, "confidence": 0.6 }


@pytest.mark.parametrize( "answers,why", [
    ( "not a dict",                                            "answers must be an object" ),
    ( { "Plan": "Plan A" },                                    "leaves out field 'Extras'" ),
    ( { "Plan": "Plan Z", "Extras": [ "Docs" ] },              "not among" ),
    ( { "Plan": [ "Plan A", "Plan B (Recommended)" ], "Extras": [ "Docs" ] }, "takes one option" ),
    ( { "Plan": "Plan A", "Extras": [] },                      "not among" ),
] )
def test_parse_refuses_a_choice_the_card_did_not_offer( factory, answers, why ):
    ep = episode( factory, response_type="multiple_choice", response_options=CHOICES )
    with pytest.raises( ValueError, match=why ): cb.parse_reply( json.dumps( { "answers": answers, "confidence": 0.5 } ), ep )


def test_parse_refuses_a_multiple_choice_card_with_no_option_field( factory ):
    ep = episode( factory, response_type="multiple_choice", response_options={ "questions": [ { "header": "Note", "question": "Why?", "input_type": "text" } ] } )
    with pytest.raises( ValueError, match="no option field" ): cb.parse_reply( '{"answers": {}, "confidence": 0.5}', ep )


def test_the_version_changes_with_the_layers_and_is_stable_otherwise():
    assert cb.predictor_version() == cb.predictor_version( cb.ALL_LAYERS ) != cb.predictor_version( ( "prompt", ) )
    assert cb.predictor_version().startswith( "context-baseline-" )


class Settings:
    """A stand-in for ConfigurationManager that answers get_required from a dict."""
    values = {}

    def __init__( self, env_var_name ): pass

    def get_required( self, key, silent=False, return_type="string" ):
        value = self.values[ key ]
        return float( value ) if return_type == "float" else int( value ) if return_type == "int" else value


@pytest.fixture
def settings( monkeypatch ):
    """Point the module's settings reader at a dict the test fills."""
    Settings.values = { cb.MODEL_KEY: "haiku-x", cb.TIMEOUT_KEY: "30", cb.LAYERS_KEY: "default_time, prompt", cb.CAP_KEY: "2", cb.LEDGER_KEY: "/io/x/ledger.jsonl" }
    monkeypatch.setattr( cb, "ConfigurationManager", Settings )
    monkeypatch.setattr( "cosa.agents.prediction_engine.principles_forecast.ConfigurationManager", Settings )
    return Settings.values


def test_the_settings_are_read_from_the_ini_and_checked( settings ):
    assert cb.context_model() == "haiku-x" and cb.context_timeout() == 30.0
    assert cb.context_layers() == ( "prompt", "default_time" ), "in card order, whatever order the INI lists them"
    assert cb.context_gate().limit == 2
    settings[ cb.TIMEOUT_KEY ] = "0"
    with pytest.raises( ValueError, match="above zero" ): cb.context_timeout()
    settings[ cb.LAYERS_KEY ] = "prompt,mystery"
    with pytest.raises( ValueError, match="must name layers" ): cb.context_layers()
    settings[ cb.LAYERS_KEY ] = " , "
    with pytest.raises( ValueError, match="must name layers" ): cb.context_layers()


def test_the_two_switches_read_the_ini_and_read_off_when_it_is_unreadable( monkeypatch ):
    seen = []
    monkeypatch.setattr( cb, "switch_enabled", lambda key: seen.append( key ) or key == cb.SWITCH_KEY )
    assert cb.context_forecast_enabled() is True and cb.context_display_enabled() is False and seen == [ cb.SWITCH_KEY, cb.DISPLAY_KEY ]


def test_the_ledger_file_name_carries_the_binary_version_and_the_directory_is_made( tmp_path ):
    script = tmp_path / "fake-claude"
    script.write_text( "#!/bin/sh\necho '2.1.7 (Claude Code)'\n" )
    script.chmod( script.stat().st_mode | stat.S_IEXEC )
    ledger = cb.open_ledger( str( tmp_path / "deep" / "ledger.jsonl" ), cli_path=str( script ) )
    assert ( tmp_path / "deep" / "ledger-2.1.7-Claude-Code.jsonl" ).exists()
    ledger.put( "k", "v" )
    assert ledger.get( "k" ) == "v" and ledger.get( "other" ) is None
    bundled = cb.open_ledger( str( tmp_path / "ledger.jsonl" ) )
    assert ( tmp_path / "ledger-bundled.jsonl" ).exists() and bundled.get( "k" ) is None


def test_the_ledger_path_defaults_to_the_ini_key_under_the_project_root( settings, monkeypatch, tmp_path ):
    monkeypatch.setattr( cb.cu, "get_project_root", lambda: str( tmp_path ) )
    cb.open_ledger()
    assert ( tmp_path / "io" / "x" / "ledger-bundled.jsonl" ).exists()


def test_the_baseline_holds_the_contract_principles_forecast_checks( tmp_path ):
    from cosa.agents.prediction_engine.principles_forecast import check_baseline
    c0 = baseline( tmp_path, replying( "x" ) )
    assert check_baseline( c0 ) is None
    assert mt.ModelCallError in c0.errors and mt.CallBudgetExceeded in c0.errors and c0.predictor_version.startswith( "context-baseline-" )


def test_a_repeat_of_the_same_prompts_is_a_ledger_read_and_makes_no_call( tmp_path ):
    calls = []
    c0    = baseline( tmp_path, replying( "first", "second", calls=calls ) )
    assert asyncio.run( c0.complete( "haiku-x", "SYS", "USER" ) ) == "first"
    assert asyncio.run( c0.complete( "haiku-x", "SYS", "USER" ) ) == "first" and len( calls ) == 1
    assert asyncio.run( c0.complete( "haiku-x", "SYS2", "USER" ) ) == "second", "a changed system prompt can never return a stale reply"
    assert asyncio.run( c0.complete( "haiku-x", "SYS", "USER2" ) ) == "second" and len( calls ) == 3


def test_the_model_is_part_of_the_ledger_key_so_an_opus_twin_never_reads_haikus_reply( tmp_path ):
    calls = []
    c0    = baseline( tmp_path, replying( "haiku reply", "opus reply", calls=calls ) )
    assert asyncio.run( c0.complete( "haiku-x", "SYS", "USER" ) ) == "haiku reply"
    assert asyncio.run( c0.complete( "opus-x", "SYS", "USER" ) ) == "opus reply" and len( calls ) == 2, "same prompts, another model: a second call"
    assert asyncio.run( c0.complete( "haiku-x", "SYS", "USER" ) ) == "haiku reply" and len( calls ) == 2, "each model still reads its own"


def test_a_ledger_that_outlives_the_process_answers_a_fresh_baseline_without_a_call( tmp_path ):
    calls = []
    asyncio.run( baseline( tmp_path, replying( "kept", calls=calls ) ).complete( "haiku-x", "S", "U" ) )
    assert asyncio.run( baseline( tmp_path, replying( "other", calls=calls ) ).complete( "haiku-x", "S", "U" ) ) == "kept" and len( calls ) == 1


def test_an_explicit_timeout_overrides_the_baselines_own( tmp_path ):
    async def hanging( prompt, options ):
        await asyncio.sleep( 30 )
        yield None
    with pytest.raises( mt.ModelCallTimeout, match="after 0.2s" ):
        asyncio.run( baseline( tmp_path, hanging, timeout=60 ).complete( "haiku-x", "S", "U", timeout_seconds=0.2 ) )


YES = '{"answer": "yes", "confidence": 0.9}'


def run_job( factory, nid, c0, gate=None, enabled=True ):
    """Run the baseline job for one card."""
    return asyncio.run( cb.run_context_forecast( nid, session_factory=factory, c0=c0, gate=gate or CapGate( 2 ), enabled=enabled ) )


def test_the_job_ready_path_stores_one_c0_row_with_the_typed_forecast( factory, tmp_path ):
    nid    = ask( factory )
    result = run_job( factory, nid, baseline( tmp_path, replying( YES ) ) )
    row    = arm_rows( factory )[ 0 ]
    assert result == { "status": "ran", "reason": None } and len( arm_rows( factory ) ) == 1
    assert ( row.arm, row.displayed, row.forecast, row.abstention_reason ) == ( "C0", False, { "value": "yes", "confidence": 0.9 }, None )
    assert row.forecast_ready_at is not None and row.predictor_version.startswith( "context-baseline-" ) and str( row.notification_id ) == nid


def test_the_job_sends_the_cards_prompt_to_the_configured_model_with_the_timeout( factory, tmp_path ):
    calls, models, limits = [], [], []

    async def query( prompt, options ):
        models.append( options.model )
        calls.append( ( options.system_prompt, prompt ) )
        yield AssistantMessage( content=[ TextBlock( YES ) ], model=options.model )
    run_job( factory, ask( factory ), baseline( tmp_path, query ) )
    assert models == [ "haiku-x" ] and calls[ 0 ][ 0 ] == cb.SYSTEM_PROMPT and "Should the worker ship?" in calls[ 0 ][ 1 ]


def test_the_job_timeout_stores_one_row_with_the_timeout_reason_and_kills_the_child( factory, tmp_path ):
    import os, subprocess, sys
    children = []

    async def hanging( prompt, options ):
        children.append( subprocess.Popen( [ sys.executable, "-c", "import time; time.sleep( 300 )" ], env=dict( os.environ, **options.env ) ) )
        await asyncio.sleep( 60 )
        yield None
    result = run_job( factory, ask( factory ), baseline( tmp_path, hanging, timeout=0.3 ) )
    row    = arm_rows( factory )[ 0 ]
    assert result[ "status" ] == "failed" and row.abstention_reason == "model_error: ModelCallTimeout" and row.forecast is None and row.forecast_ready_at is None
    assert children[ 0 ].wait( timeout=5 ) == -9 and len( arm_rows( factory ) ) == 1


def test_the_job_crash_and_the_model_refusal_each_store_one_row_with_their_reason( factory, tmp_path ):
    async def crashing( prompt, options ):
        raise RuntimeError( "the stream broke" )
        yield None
    run_job( factory, ask( factory ), baseline( tmp_path, crashing ) )

    async def refusing( prompt, options ):
        yield ResultMessage( subtype="error_during_execution", duration_ms=1, duration_api_ms=1, is_error=True, num_turns=1, session_id="s", result="AUTH api error" )
    run_job( factory, ask( factory ), baseline( tmp_path, refusing ) )
    run_job( factory, ask( factory ), baseline( tmp_path, replying( "I would rather not say" ) ) )
    reasons = sorted( row.abstention_reason for row in arm_rows( factory ) )
    assert reasons == [ "model_error: ModelCallError", "model_error: ModelCallError", "unreadable_forecast" ] and all( row.forecast is None for row in arm_rows( factory ) )


def test_the_job_budget_refusal_stores_a_not_ready_row_and_contacts_no_model( factory, tmp_path, monkeypatch ):
    def refuse( model ): raise mt.CallBudgetExceeded( "capped" )
    monkeypatch.setattr( mt, "CHARGE_HOOK", refuse )
    calls = []
    run_job( factory, ask( factory ), baseline( tmp_path, replying( YES, calls=calls ) ) )
    assert arm_rows( factory )[ 0 ].abstention_reason == "model_error: CallBudgetExceeded" and calls == []


def test_a_card_beyond_the_cap_gets_a_capacity_row_at_once_and_no_call( factory, tmp_path ):
    gate = CapGate( 1 )
    assert gate.try_enter()
    calls = []
    result = run_job( factory, ask( factory ), baseline( tmp_path, replying( YES, calls=calls ) ), gate=gate )
    assert result[ "status" ] == "capacity" and arm_rows( factory )[ 0 ].abstention_reason == CAPPED_ARM_REASON and calls == [] and gate.inflight == 1


def test_no_card_gets_two_forecasts( factory, tmp_path ):
    nid, calls = ask( factory ), []
    c0 = baseline( tmp_path, replying( YES, calls=calls ) )
    run_job( factory, nid, c0 )
    again = run_job( factory, nid, c0 )
    assert again == { "status": "not_run", "reason": "already stored" } and len( arm_rows( factory ) ) == 1 and len( calls ) == 1


def test_an_unsupported_card_stores_one_input_error_row_and_calls_no_model( factory, tmp_path ):
    calls = []
    result = run_job( factory, ask( factory, response_type="open_ended" ), baseline( tmp_path, replying( YES, calls=calls ) ) )
    assert result[ "status" ] == "failed" and arm_rows( factory )[ 0 ].abstention_reason == "input_error: UnsupportedAsk" and calls == []


def test_with_the_switch_off_nothing_is_built_read_or_written( factory ):
    nid = ask( factory )
    assert asyncio.run( cb.run_context_forecast( nid, session_factory=factory, enabled=False ) ) == { "status": "not_run", "reason": "switch off" }
    assert arm_rows( factory ) == [] and cb._BASELINE is None


def test_the_switch_is_read_from_the_ini_when_not_given( factory, monkeypatch ):
    monkeypatch.setattr( cb, "switch_enabled", lambda key: False )
    assert asyncio.run( cb.run_context_forecast( ask( factory ), session_factory=factory ) )[ "reason" ] == "switch off"


def test_the_process_baseline_is_built_once_from_the_settings_and_used_by_the_job( factory, settings, monkeypatch, tmp_path ):
    monkeypatch.setattr( cb.cu, "get_project_root", lambda: str( tmp_path ) )
    monkeypatch.setattr( mt, "complete", None, raising=True )
    cb.reset_baseline()
    first, gate = cb.get_baseline()
    assert cb.get_baseline() == ( first, gate ) and first.model == "haiku-x" and first.layers == ( "prompt", "default_time" ) and gate.limit == 2
    seen = []

    async def fake_complete( model, system, user, **options ):
        seen.append( model )
        return YES
    monkeypatch.setattr( mt, "complete", fake_complete )
    result = asyncio.run( cb.run_context_forecast( ask( factory ), session_factory=factory, enabled=True ) )
    assert result[ "status" ] == "ran" and seen == [ "haiku-x" ]
    cb.reset_baseline()
    assert cb._BASELINE is None and cb._GATE is None


def test_the_job_uses_the_apps_database_sessions_when_none_are_given( factory, monkeypatch, tmp_path ):
    import cosa.rest.db.database as database
    monkeypatch.setattr( database, "get_db", factory )
    nid = ask( factory )
    assert asyncio.run( cb.run_context_forecast( nid, c0=baseline( tmp_path, replying( YES ) ), gate=CapGate( 1 ), enabled=True ) )[ "status" ] == "ran"
    assert len( arm_rows( factory ) ) == 1


def test_the_episode_carries_the_cards_message_type_default_and_timeout( factory ):
    ep = episode( factory )
    assert ( ep[ "message" ], ep[ "response_type" ], ep[ "default" ], ep[ "timeout_seconds" ] ) == ( "Should the worker ship?", "yes_no", "no", 120 )


# Rick ruled on 21 Nov 2026 at about 12:35 EST: the forecast runs on live asks for measurement, and is not displayed
@pytest.mark.parametrize( "key, shipped", [ ( cb.SWITCH_KEY, "true" ), ( cb.DISPLAY_KEY, "false" ) ] )
def test_each_switch_ships_as_ruled_in_the_ini_and_has_an_explainer( key, shipped ):
    import os
    root = os.environ[ "LUPIN_ROOT" ]
    line = [ l for l in open( f"{root}/src/conf/lupin-app.ini", encoding="utf-8" ).read().splitlines() if l.startswith( key + " " ) ]
    assert len( line ) == 1 and line[ 0 ].split( "=", 1 )[ 1 ].strip() == shipped
    assert sum( 1 for l in open( f"{root}/src/conf/lupin-app-splainer.ini", encoding="utf-8" ) if l.startswith( key + " " ) ) == 1
