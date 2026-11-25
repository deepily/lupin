"""
The SWE proxy's three-way (yes, no, neither) forecast, in shadow.

Covers the switch and the pure three_way_agreement function.
Covers the shadow fields a gated confirmation writes on its decision row.
Pins that, with the switch off, the row and the live counters are exactly as before.
Nothing here reaches a database or a notification: the boundaries are patched.
"""
import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cosa.agents.decision_proxy import agreement as ag
from cosa.agents.decision_proxy import config as proxy_config
from cosa.agents.swe_team.config import SweTeamConfig
from cosa.agents.swe_team.orchestrator import SweTeamOrchestrator
from cosa.agents.utils.agent_notification_dispatcher import ConfirmationAnswer

ROOT          = os.environ[ "LUPIN_ROOT" ]
SHADOW_SWITCH = "cosa.agents.swe_team.orchestrator.neither_forecast_shadow_enabled"
NEITHER_SWITCH= "cosa.agents.swe_team.orchestrator.neither_is_no_ruling_enabled"
STAMP         = { "user_id": "u-1", "account_email": "rick@example.com", "method": "jwt" }
SHADOW_KEYS   = ( "three_way_forecast", "three_way_agreement", "full_answer_forecast", "full_answer_agreement", "live_agreement" )
FULL_READER   = "cosa.agents.decision_proxy.shadow_stances.full_answer_stance"
NO_BASELINE   = { "status": "no_baseline_row" }


# --------------------------------------------------------------------------- the pure function
@pytest.mark.parametrize( "forecast, answer, expected", [
    ( "yes", "yes", True ), ( "no", "no", True ), ( "neither", "neither", True ),
    ( "yes", "no", False ), ( "no", "neither", False ), ( "neither", "yes", False ),
    ( None, "yes", None ), ( "yes", None, None ), ( None, None, None ),
    ( "approved", "yes", None ), ( "yes", "maybe", None ),
] )
def test_three_way_agreement_scores_the_stance_and_abstains_on_anything_else( forecast, answer, expected ):
    assert ag.three_way_agreement( forecast, answer ) is expected


def test_three_way_agreement_leaves_forecast_agreement_alone():
    assert ag.forecast_agreement( "approved", None ) is None
    assert ag.forecast_agreement( "approved", True ) is True


# --------------------------------------------------------------------------- the switch
def test_the_switch_is_off_by_default_and_shipped_on_with_an_explainer():
    # The code default stays off; the INI ships it on since Mr. Radio's go on 25 Nov 2026 (shadow only).
    assert proxy_config.DEFAULT_NEITHER_FORECAST_SHADOW is False
    key  = proxy_config.NEITHER_FORECAST_SHADOW_KEY
    assert key == "decision proxy neither forecast shadow enabled"
    ini  = [ l for l in open( f"{ROOT}/src/conf/lupin-app.ini" ) if l.startswith( key ) ]
    expl = [ l for l in open( f"{ROOT}/src/conf/lupin-app-splainer.ini" ) if l.startswith( key ) ]
    assert len( ini ) == 1 and ini[ 0 ].split( "=" )[ 1 ].strip() == "true" and len( expl ) == 1


@pytest.mark.parametrize( "value", [ True, False ] )
def test_the_switch_reads_the_ini_value( value ):
    manager = MagicMock()
    manager.return_value.get.return_value = value
    with patch( "cosa.config.configuration_manager.ConfigurationManager", manager ):
        assert proxy_config.neither_forecast_shadow_enabled() is value
    assert manager.return_value.get.call_args.args[ 0 ] == proxy_config.NEITHER_FORECAST_SHADOW_KEY


def test_an_unreadable_config_reads_off_and_prints_a_line( capsys ):
    with patch( "cosa.config.configuration_manager.ConfigurationManager", side_effect=RuntimeError( "no config" ) ):
        assert proxy_config.neither_forecast_shadow_enabled() is False
    assert "neither-forecast shadow switch unreadable" in capsys.readouterr().out


# --------------------------------------------------------------------------- the shadow fields
def _orch( value="approved", action="shadow" ):
    orch  = SweTeamOrchestrator( task_description="t", config=SweTeamConfig( trust_mode="disabled" ), job_id="swe-1" )
    proxy = MagicMock()
    proxy.trust_mode  = "shadow"
    proxy.trust_tracker.trust_model = "count"
    proxy.evaluate.return_value = SimpleNamespace( action=action, value=value, category="testing", confidence=0.9, trust_level=1, reason="r" )
    orch.proxy = proxy
    orch._ask_before_act = True
    orch._persist_trust_feedback          = MagicMock()
    orch._emit_proxy_summary_notification = MagicMock()
    return orch, proxy


def _io( raw, source="human" ):
    from cosa.utils.notification_utils import extract_qualifier_comment
    stance, comment = extract_qualifier_comment( raw )
    io = MagicMock()
    io.ask_confirmation_answer = AsyncMock( return_value=ConfirmationAnswer( stance, comment, raw, source=source, answered_by=STAMP ) )
    return io


def _repo( row ):
    """Patch the database boundary so get_by_notification_id answers with row."""
    repo = MagicMock()
    repo.return_value.get_by_notification_id.return_value = row
    return patch( "cosa.rest.db.database.get_db" ), patch( "cosa.rest.db.repositories.prediction_log_repository.PredictionLogRepository", repo ), repo


def _ask( orch, io, shadow, neither=False, row=None, notification_id="n-1", full=None ):
    db, repo_patch, repo = _repo( row )
    with patch( SHADOW_SWITCH, return_value=shadow ), patch( NEITHER_SWITCH, return_value=neither ), \
         patch( "cosa.agents.swe_team.orchestrator.take_last_ask_notification_id", side_effect=[ None, notification_id ] ), \
         patch( FULL_READER, return_value=NO_BASELINE if full is None else full ), \
         patch( "cosa.agents.swe_team.orchestrator.write_proxy_decision" ) as write, db, repo_patch:
        result = asyncio.run( orch._gated_confirmation( "Proceed?", "lead", "no", 60, None, io ) )
    return result, write, repo


def _metadata( write ):
    return write.call_args.kwargs[ "extra" ][ "metadata_json" ]


STANCE_NEITHER = SimpleNamespace( three_way_shadow={ "value": "neither", "confidence": 0.5, "probabilities": { "yes": 0.3, "no": 0.2, "neither": 0.5 }, "neighbours": 4 } )
STANCE_YES     = SimpleNamespace( three_way_shadow={ "value": "yes", "confidence": 0.6, "probabilities": { "yes": 0.6, "no": 0.2, "neither": 0.2 }, "neighbours": 4 } )


def test_a_neither_answer_against_a_neither_forecast_is_a_shadow_agreement_and_moves_no_counter():
    orch, proxy = _orch()
    result, write, repo = _ask( orch, _io( "neither" ), shadow=True, neither=True, row=STANCE_NEITHER )
    meta = _metadata( write )
    assert meta[ "three_way_forecast" ][ "value" ] == "neither" and meta[ "three_way_agreement" ] is True
    assert meta[ "live_agreement" ] is None
    proxy.trust_tracker.record_decision.assert_not_called()
    repo.return_value.get_by_notification_id.assert_called_once_with( "n-1" )


def test_a_neither_answer_against_a_yes_forecast_is_a_shadow_disagreement():
    orch, proxy = _orch()
    _, write, _ = _ask( orch, _io( "neither" ), shadow=True, neither=True, row=STANCE_YES )
    assert _metadata( write )[ "three_way_agreement" ] is False
    proxy.trust_tracker.record_decision.assert_not_called()


def test_a_yes_answer_records_the_live_agreement_beside_the_shadow_one():
    orch, proxy = _orch( value="approved" )
    _, write, _ = _ask( orch, _io( "yes" ), shadow=True, row=STANCE_YES )
    meta = _metadata( write )
    assert meta[ "three_way_agreement" ] is True and meta[ "live_agreement" ] is True
    proxy.trust_tracker.record_decision.assert_called_once_with( "testing", success=True )


def test_a_yes_with_a_comment_scores_as_a_yes_in_the_shadow():
    orch, _ = _orch()
    _, write, _ = _ask( orch, _io( "yes [comment: check the tests]" ), shadow=True, neither=True, row=STANCE_YES )
    meta = _metadata( write )
    assert meta[ "three_way_agreement" ] is True and meta[ "answer_outcome" ] == "qualified_yes"


def test_a_default_answer_has_no_shadow_agreement():
    orch, proxy = _orch()
    _, write, _ = _ask( orch, _io( "no", source="default" ), shadow=True, row=STANCE_YES )
    meta = _metadata( write )
    assert meta[ "three_way_agreement" ] is None and meta[ "live_agreement" ] is None
    proxy.trust_tracker.record_decision.assert_not_called()


@pytest.mark.parametrize( "row, notification_id, status", [
    ( None, "n-1", "no_forecast_row" ),
    ( SimpleNamespace( three_way_shadow=None ), "n-1", "not_recorded" ),
    ( SimpleNamespace( three_way_shadow={ "status": "no_embedding" } ), "n-1", None ),
    ( None, None, "no_notification" ),
] )
def test_an_unavailable_forecast_is_named_and_scores_none( row, notification_id, status ):
    orch, _ = _orch()
    _, write, repo = _ask( orch, _io( "yes" ), shadow=True, row=row, notification_id=notification_id )
    meta = _metadata( write )
    assert meta[ "three_way_agreement" ] is None
    assert meta[ "three_way_forecast" ][ "status" ] == ( status or "no_embedding" )
    if notification_id is None: repo.return_value.get_by_notification_id.assert_not_called()


def test_a_failed_read_is_named_and_never_stops_the_row_or_the_counters():
    orch, proxy = _orch()
    repo = MagicMock()
    repo.return_value.get_by_notification_id.side_effect = RuntimeError( "db down" )
    with patch( SHADOW_SWITCH, return_value=True ), patch( NEITHER_SWITCH, return_value=False ), \
         patch( "cosa.agents.swe_team.orchestrator.take_last_ask_notification_id", side_effect=[ None, "n-1" ] ), \
         patch( FULL_READER, return_value=NO_BASELINE ), \
         patch( "cosa.agents.swe_team.orchestrator.write_proxy_decision" ) as write, \
         patch( "cosa.rest.db.database.get_db" ), \
         patch( "cosa.rest.db.repositories.prediction_log_repository.PredictionLogRepository", repo ):
        result = asyncio.run( orch._gated_confirmation( "Proceed?", "lead", "no", 60, None, _io( "yes" ) ) )
    meta = _metadata( write )
    assert result is True
    assert meta[ "three_way_forecast" ] == { "status": "error", "error_class": "RuntimeError" } and meta[ "three_way_agreement" ] is None
    proxy.trust_tracker.record_decision.assert_called_once_with( "testing", success=True )


# --------------------------------------------------------------------------- the switch off pins today's behaviour
@pytest.mark.parametrize( "raw, neither", [ ( "yes", False ), ( "no", False ), ( "neither", False ), ( "neither", True ), ( "yes [comment: wait]", True ) ] )
def test_with_the_switch_off_the_row_and_the_counters_are_as_before( raw, neither ):
    off_orch, off_proxy = _orch()
    on_orch,  on_proxy  = _orch()
    off_result, off_write, off_repo = _ask( off_orch, _io( raw ), shadow=False, neither=neither, row=STANCE_YES )
    on_result,  on_write,  _        = _ask( on_orch,  _io( raw ), shadow=True,  neither=neither, row=STANCE_YES )
    off_meta = dict( _metadata( off_write ) )
    on_meta  = dict( _metadata( on_write ) )
    assert not any( key in off_meta for key in SHADOW_KEYS )
    off_repo.return_value.get_by_notification_id.assert_not_called()
    assert all( key in on_meta for key in SHADOW_KEYS )
    for key in SHADOW_KEYS: on_meta.pop( key )
    assert on_meta == off_meta
    assert on_result == off_result
    assert on_proxy.trust_tracker.record_decision.call_args_list == off_proxy.trust_tracker.record_decision.call_args_list
    assert on_orch._persist_trust_feedback.call_args_list == off_orch._persist_trust_feedback.call_args_list


# --------------------------------------------------------------------------- a stored value that is not a dict never stops the row
@pytest.mark.parametrize( "stored, type_name", [ ( [ "neither" ], "list" ), ( "oops", "str" ), ( 5, "int" ) ] )
def test_a_malformed_stored_forecast_still_writes_the_row_and_moves_the_counters_as_before( stored, type_name ):
    orch, proxy = _orch()
    result, write, _ = _ask( orch, _io( "yes" ), shadow=True, row=SimpleNamespace( three_way_shadow=stored ) )
    meta = _metadata( write )
    assert result is True
    assert meta[ "three_way_forecast" ] == { "status": "malformed", "stored_type": type_name } and meta[ "three_way_agreement" ] is None
    assert meta[ "live_agreement" ] is True
    proxy.trust_tracker.record_decision.assert_called_once_with( "testing", success=True )


# --------------------------------------------------------------------------- the full-answer arm is a second source on the same row
FULL_NEITHER = { "value": "neither", "confidence": 0.6, "probabilities": { "yes": 0.2, "no": 0.2, "neither": 0.6 } }
FULL_YES     = { "value": "yes", "confidence": 0.7, "probabilities": { "yes": 0.7, "no": 0.2, "neither": 0.1 } }


def test_the_two_sources_are_scored_apart_on_one_row():
    orch, proxy = _orch()
    _, write, _ = _ask( orch, _io( "neither" ), shadow=True, neither=True, row=STANCE_YES, full=FULL_NEITHER )
    meta = _metadata( write )
    assert meta[ "three_way_forecast" ][ "value" ] == "yes" and meta[ "three_way_agreement" ] is False
    assert meta[ "full_answer_forecast" ] == FULL_NEITHER and meta[ "full_answer_agreement" ] is True
    proxy.trust_tracker.record_decision.assert_not_called()


def test_a_yes_answer_against_a_full_answer_yes_and_a_lookup_neither():
    orch, _ = _orch()
    _, write, _ = _ask( orch, _io( "yes" ), shadow=True, row=STANCE_NEITHER, full=FULL_YES )
    meta = _metadata( write )
    assert meta[ "three_way_agreement" ] is False and meta[ "full_answer_agreement" ] is True


def test_an_unavailable_full_answer_forecast_is_named_and_scores_none():
    orch, _ = _orch()
    _, write, _ = _ask( orch, _io( "yes" ), shadow=True, row=STANCE_YES, full={ "status": "unavailable", "reason": "forecast_timed_out" } )
    meta = _metadata( write )
    assert meta[ "full_answer_forecast" ][ "reason" ] == "forecast_timed_out" and meta[ "full_answer_agreement" ] is None and meta[ "three_way_agreement" ] is True


def test_a_default_answer_scores_neither_source():
    orch, _ = _orch()
    _, write, _ = _ask( orch, _io( "no", source="default" ), shadow=True, row=STANCE_YES, full=FULL_YES )
    meta = _metadata( write )
    assert meta[ "three_way_agreement" ] is None and meta[ "full_answer_agreement" ] is None


def test_a_card_with_no_notification_id_reads_neither_source():
    orch, _ = _orch()
    _, write, repo = _ask( orch, _io( "yes" ), shadow=True, row=STANCE_YES, notification_id=None, full=FULL_YES )
    meta = _metadata( write )
    assert meta[ "three_way_forecast" ] == meta[ "full_answer_forecast" ] == { "status": "no_notification" }
    repo.return_value.get_by_notification_id.assert_not_called()


def test_a_full_answer_read_that_fails_is_named_and_leaves_the_lookup_source_alone():
    orch, proxy = _orch()
    db, repo_patch, _ = _repo( STANCE_YES )
    with patch( SHADOW_SWITCH, return_value=True ), patch( NEITHER_SWITCH, return_value=False ), \
         patch( "cosa.agents.swe_team.orchestrator.take_last_ask_notification_id", side_effect=[ None, "n-1" ] ), \
         patch( "cosa.agents.swe_team.orchestrator.write_proxy_decision" ) as write, db, repo_patch:
        asyncio.run( orch._gated_confirmation( "Proceed?", "lead", "no", 60, None, _io( "yes" ) ) )
    meta = _metadata( write )
    assert meta[ "full_answer_forecast" ] == { "status": "error", "error_class": "ValueError" }, "the id n-1 is not a UUID, and the real reader says so"
    assert meta[ "three_way_agreement" ] is True
    proxy.trust_tracker.record_decision.assert_called_once_with( "testing", success=True )
