"""
The decision proxy's neither fix: a neither answer is no ruling.

Covers the switch, the pure agreement and re-frame functions, and the gated confirmation with the switch on and off.
It also covers the stored events and the replay of the 43 organic rows of 5 Nov 2026.
Nothing here reaches a database or a notification: the boundaries are patched.
"""
import asyncio
import importlib.util
import json
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cosa.agents.decision_proxy import agreement as ag
from cosa.agents.decision_proxy import config as proxy_config
from cosa.agents.swe_team.config import SweTeamConfig
from cosa.agents.swe_team.orchestrator import SweTeamOrchestrator
from cosa.agents.utils.agent_notification_dispatcher import ConfirmationAnswer

ROOT    = os.environ[ "LUPIN_ROOT" ]
FIXTURE = f"{ROOT}/src/tests/unit/fixtures/proxy_decisions_2026_11_05_organic.json"
SWITCH  = "cosa.agents.swe_team.orchestrator.neither_is_no_ruling_enabled"


# --------------------------------------------------------------------------- the pure functions
def test_forecast_agreement_of_no_ruling_is_none_whatever_the_forecast():
    assert [ ag.forecast_agreement( v, None ) for v in ( "approved", "requires_review", None, "rejected" ) ] == [ None ] * 4


@pytest.mark.parametrize( "forecast, answer, expected", [
    ( "approved", True, True ), ( "approved", False, False ), ( "rejected", False, True ),
    ( "rejected", True, False ), ( None, False, True ), ( None, True, False ),
    ( "requires_review", True, True ), ( "requires_review", False, True ),
] )
def test_forecast_agreement_for_a_plain_answer_is_unchanged( forecast, answer, expected ):
    assert ag.forecast_agreement( forecast, answer ) is expected


def test_the_re_frame_bar_blocks_one_ask_above_and_not_one_below():
    below = [ "neither" ] * 2 + [ "yes" ] * 18         # 2 of 20: exactly the 1-in-10 bar
    above = [ "neither" ] * 3 + [ "yes" ] * 17         # 3 of 20: one ask above
    assert ag.reframe_rate( below ) == 0.1 and ag.reframe_blocks_promotion( below ) is False
    assert ag.reframe_rate( above ) == 0.15 and ag.reframe_blocks_promotion( above ) is True
    one_under = [ "neither" ] + [ "yes" ] * 19         # 1 of 20: one ask below
    assert ag.reframe_blocks_promotion( one_under ) is False


def test_the_re_frame_rate_counts_only_the_last_twenty_asks_and_an_empty_list_is_zero():
    assert ag.reframe_rate( [ "neither" ] * 5 + [ "yes" ] * 20 ) == 0.0
    assert ag.reframe_rate( [] ) == 0.0


# --------------------------------------------------------------------------- the switch
def test_the_switch_is_off_by_default_and_shipped_off_with_an_explainer():
    assert proxy_config.DEFAULT_NEITHER_IS_NO_RULING is False
    key  = proxy_config.NEITHER_IS_NO_RULING_KEY
    assert key == "decision proxy neither is no ruling enabled"
    ini  = [ l for l in open( f"{ROOT}/src/conf/lupin-app.ini" ) if l.startswith( key ) ]
    expl = [ l for l in open( f"{ROOT}/src/conf/lupin-app-splainer.ini" ) if l.startswith( key ) ]
    assert len( ini ) == 1 and ini[ 0 ].split( "=" )[ 1 ].strip() == "false" and len( expl ) == 1


@pytest.mark.parametrize( "value", [ True, False ] )
def test_the_switch_reads_the_ini_value( value ):
    manager = MagicMock()
    manager.return_value.get.return_value = value
    with patch( "cosa.config.configuration_manager.ConfigurationManager", manager ):
        assert proxy_config.neither_is_no_ruling_enabled() is value
    assert manager.return_value.get.call_args.args[ 0 ] == proxy_config.NEITHER_IS_NO_RULING_KEY


def test_an_unreadable_config_reads_off_and_prints_a_line( capsys ):
    with patch( "cosa.config.configuration_manager.ConfigurationManager", side_effect=RuntimeError( "no config" ) ):
        assert proxy_config.neither_is_no_ruling_enabled() is False
    assert "neither-is-no-ruling switch unreadable" in capsys.readouterr().out


# --------------------------------------------------------------------------- the gated confirmation
def _orch( action="shadow", value="approved", category="testing" ):
    orch  = SweTeamOrchestrator( task_description="t", config=SweTeamConfig( trust_mode="disabled" ), job_id="swe-1" )
    proxy = MagicMock()
    proxy.trust_mode  = "shadow"
    proxy.trust_tracker.trust_model = "count"
    proxy.evaluate.return_value = SimpleNamespace( action=action, value=value, category=category, confidence=0.9, trust_level=1, reason="r" )
    orch.proxy = proxy
    orch._ask_before_act = True
    orch._persist_trust_feedback    = MagicMock()
    orch._emit_proxy_summary_notification = MagicMock()
    return orch, proxy


STAMP = { "user_id": "u-1", "account_email": "rick@example.com", "method": "jwt" }


def _io( raw ):
    from cosa.utils.notification_utils import extract_qualifier_comment
    stance, comment = extract_qualifier_comment( raw )
    io = MagicMock()
    io.ask_confirmation_answer = AsyncMock( return_value=ConfirmationAnswer( stance, comment, raw, source="human", answered_by=STAMP ) )
    io.ask_confirmation        = AsyncMock( return_value=raw.lower().strip().startswith( "yes" ) )
    return io


def _ask( orch, io, switch ):
    with patch( SWITCH, return_value=switch ), patch( "cosa.agents.swe_team.orchestrator.write_proxy_decision" ) as write:
        result = asyncio.run( orch._gated_confirmation( "Proceed?", "lead", "no", 60, None, io ) )
    return result, write


@pytest.mark.parametrize( "raw, expected_answer, expected_success", [
    ( "yes", True, True ), ( "no", False, False ), ( "yes [comment: leave config alone]", True, True ),
] )
def test_a_plain_or_qualified_answer_is_scored_as_before_with_the_switch_on( raw, expected_answer, expected_success ):
    orch, proxy = _orch( value="approved" )
    result, write = _ask( orch, _io( raw ), True )
    assert result is expected_answer
    proxy.trust_tracker.record_decision.assert_called_once_with( "testing", success=expected_success )
    orch._persist_trust_feedback.assert_called_once_with( "testing", expected_success )
    assert write.call_args.kwargs[ "extra" ][ "metadata_json" ][ "user_answer" ] is expected_answer


def test_a_qualified_yes_is_logged_with_its_comment( caplog ):
    orch, _ = _orch()
    with caplog.at_level( "INFO" ):
        _ask( orch, _io( "yes [comment: leave config alone]" ), True )
    assert "[PROXY-QUALIFIED-YES]" in caplog.text and "leave config alone" in caplog.text
    meta = _ask( _orch()[ 0 ], _io( "yes [comment: leave config alone]" ), True )[ 1 ].call_args.kwargs[ "extra" ][ "metadata_json" ]
    assert meta[ "answer_stance" ] == "yes" and meta[ "answer_comment" ] == "leave config alone"


def test_a_neither_is_no_ruling_leaves_the_counters_alone_and_logs_a_re_frame_request( caplog ):
    orch, proxy = _orch( category="deployment" )
    proxy.reframe_blocked.return_value = False
    with caplog.at_level( "INFO" ):
        result, write = _ask( orch, _io( "neither [comment: ask it another way]" ), True )
    assert result is False
    proxy.trust_tracker.record_decision.assert_not_called()
    proxy.trust_tracker.record_decision_with_features.assert_not_called()
    orch._persist_trust_feedback.assert_not_called()
    assert "[PROXY-REFRAME]" in caplog.text and "ask it another way" in caplog.text and "deployment" in caplog.text
    meta = write.call_args.kwargs[ "extra" ][ "metadata_json" ]
    assert meta == { "job_id": "swe-1", "user_answer": None, "answer_stance": "neither", "answer_comment": "ask it another way", "answer_raw": "neither [comment: ask it another way]", "answer_source": "human", "answered_by_user_id": "u-1", "answered_by_method": "jwt" }
    assert write.call_args.kwargs[ "extra" ][ "rule_agreement" ] is None


def test_a_blr_trust_model_also_records_nothing_for_a_neither():
    orch, proxy = _orch()
    proxy.trust_tracker.trust_model = "blr"
    _ask( orch, _io( "neither" ), True )
    proxy.trust_tracker.record_decision_with_features.assert_not_called()


def test_a_plain_answer_under_the_blr_model_still_records_with_features():
    orch, proxy = _orch()
    proxy.trust_tracker.trust_model = "blr"
    _ask( orch, _io( "yes" ), True )
    proxy.trust_tracker.record_decision_with_features.assert_called_once_with( "testing", True, "Proceed?" )


def test_the_model_deferred_to_rick_and_rick_deferred_the_decision_are_stored_as_different_events():
    model_deferred = _ask( _orch( action="defer" )[ 0 ], _io( "yes" ), True )[ 1 ].call_args.kwargs
    rick_deferred  = _ask( _orch( action="suggest" )[ 0 ], _io( "neither" ), True )[ 1 ].call_args.kwargs
    assert model_deferred[ "result" ].action == "defer"
    assert model_deferred[ "extra" ][ "metadata_json" ][ "answer_stance" ] == "yes"
    assert rick_deferred[ "result" ].action == "suggest"
    assert rick_deferred[ "extra" ][ "metadata_json" ][ "answer_stance" ] == "neither"
    both = _ask( _orch( action="defer" )[ 0 ], _io( "neither" ), True )[ 1 ].call_args.kwargs
    assert ( both[ "result" ].action, both[ "extra" ][ "metadata_json" ][ "answer_stance" ] ) == ( "defer", "neither" )


@pytest.mark.parametrize( "raw", [ "yes", "no", "neither", "yes [comment: x]", "neither [comment: y]", "Maybe later" ] )
def test_with_the_switch_off_every_shape_is_scored_exactly_as_today( raw ):
    orch, proxy = _orch( value="approved" )
    io          = _io( raw )
    answer      = raw.lower().strip().startswith( "yes" )
    result, write = _ask( orch, io, False )
    assert result is answer
    io.ask_confirmation_answer.assert_awaited_once()
    io.ask_confirmation.assert_not_called()
    proxy.trust_tracker.record_decision.assert_called_once_with( "testing", success=answer )
    orch._persist_trust_feedback.assert_called_once_with( "testing", answer )
    proxy.note_stance.assert_not_called()
    proxy.reframe_blocked.assert_not_called()
    assert write.call_args.kwargs[ "extra" ][ "metadata_json" ][ "user_answer" ] is answer


@pytest.mark.parametrize( "switch", [ False, True ] )
@pytest.mark.parametrize( "raw, stance, comment", [
    ( "yes", "yes", None ), ( "no", "no", None ), ( "neither", "neither", None ),
    ( "yes [comment: leave config alone]", "yes", "leave config alone" ),
    ( "neither [comment: ask it another way]", "neither", "ask it another way" ),
] )
def test_the_row_carries_the_stance_the_comment_and_the_raw_text_whatever_the_switch_says( raw, stance, comment, switch ):
    _, write = _ask( _orch()[ 0 ], _io( raw ), switch )
    meta = write.call_args.kwargs[ "extra" ][ "metadata_json" ]
    assert ( meta[ "answer_stance" ], meta[ "answer_comment" ], meta[ "answer_raw" ], meta[ "answer_source" ] ) == ( stance, comment, raw, "human" )


def test_a_neither_with_the_switch_off_is_still_scored_a_no_while_its_stance_is_stored():
    orch, proxy = _orch( value="approved" )
    result, write = _ask( orch, _io( "neither" ), False )
    meta = write.call_args.kwargs[ "extra" ][ "metadata_json" ]
    assert ( result, meta[ "user_answer" ], meta[ "answer_stance" ] ) == ( False, False, "neither" )
    proxy.trust_tracker.record_decision.assert_called_once_with( "testing", success=False )


def test_the_row_carries_the_id_of_the_card_that_asked_when_there_is_one():
    orch, _ = _orch()
    with patch( "cosa.agents.swe_team.orchestrator.take_last_ask_notification_id", side_effect=[ None, "card-123" ] ):
        _, write = _ask( orch, _io( "neither" ), False )
    assert write.call_args.kwargs[ "notification_id" ] == "card-123"


def _real_strategy( category="general" ):
    """Build a real strategy over a real tracker: level 2 after 4 successes, level 3 after 7."""
    from cosa.agents.decision_proxy.trust_tracker import TrustTracker
    from cosa.agents.swe_team.proxy.engineering_strategy import EngineeringStrategy
    tracker = TrustTracker( l2_threshold=3, l3_threshold=6, l4_threshold=9, l5_threshold=12 )
    return EngineeringStrategy( trust_tracker=tracker, trust_mode="active", cap_levels={ category: 5 } )


def _succeed( strategy, times, category="general" ):
    for _ in range( times ): strategy.trust_tracker.record_decision( category, success=True )


def _rise_while_asking( neithers ):
    """Reach level 2, record 20 asks with some neithers, then earn level 3."""
    strategy = _real_strategy()
    _succeed( strategy, 4 )
    assert strategy.get_trust_level( "general" ) == 2
    for stance in [ "neither" ] * neithers + [ "yes" ] * ( 20 - neithers ): strategy.note_stance( "general", stance )
    _succeed( strategy, 3 )
    return strategy


def test_promotion_is_blocked_one_ask_above_the_bar_and_allowed_at_it():
    above = _rise_while_asking( 3 )          # 3 of 20 asks: over 1 in 10
    at    = _rise_while_asking( 2 )          # 2 of 20 asks: exactly 1 in 10
    assert above.trust_tracker.get_level( "general" ) == 3 and above.get_trust_level( "general" ) == 2 and above.reframe_blocked( "general" ) is True
    assert at.trust_tracker.get_level( "general" ) == 3 and at.get_trust_level( "general" ) == 3 and at.reframe_blocked( "general" ) is False


def test_the_block_reaches_the_gate_through_evaluate():
    blocked = _rise_while_asking( 3 )
    free    = _rise_while_asking( 2 )
    assert blocked.evaluate( "Proceed?" ).trust_level == 2
    assert free.evaluate( "Proceed?" ).trust_level == 3


def test_the_block_lifts_once_the_rate_falls_to_the_bar_and_never_touches_the_counters():
    strategy = _rise_while_asking( 3 )
    before   = strategy.trust_tracker.get_stats()
    assert strategy.reframe_blocked( "general" ) is True
    strategy.note_stance( "general", "yes" )         # the oldest neither leaves the window: 2 of 20
    assert strategy.reframe_blocked( "general" ) is False and strategy.get_trust_level( "general" ) == 3
    assert strategy.trust_tracker.get_stats() == before


def test_a_blocked_category_can_still_be_demoted_and_other_categories_are_free():
    strategy = _rise_while_asking( 3 )
    assert strategy.get_trust_level( "testing" ) == strategy.trust_tracker.get_level( "testing" )
    assert strategy.trust_tracker.get_level( "general" ) == 3
    strategy.trust_tracker.demote_category( "general", levels=1 )
    after = strategy.trust_tracker.get_level( "general" )
    assert after < 3 and strategy.get_trust_level( "general" ) == after


def test_a_category_with_no_stance_gets_exactly_the_trackers_level():
    strategy = _real_strategy()
    _succeed( strategy, 7 )
    assert strategy.get_trust_level( "general" ) == strategy.trust_tracker.get_level( "general" ) == 3


def test_the_stance_history_keeps_only_the_last_twenty():
    strategy = _real_strategy()
    for i in range( 25 ): strategy.note_stance( "general", "yes" if i < 24 else "neither" )
    assert strategy._stance_history[ "general" ] == [ "yes" ] * 19 + [ "neither" ]


def test_a_run_of_neithers_through_the_orchestrator_logs_the_block_once_the_rate_passes_the_bar( caplog ):
    orch, _ = _orch( category="general" )
    real    = _real_strategy()
    real.evaluate         = MagicMock( return_value=orch.proxy.evaluate.return_value )
    orch.proxy            = real
    with caplog.at_level( "INFO" ):
        for raw in [ "yes" ] * 18 + [ "neither" ] * 2:
            _ask( orch, _io( raw ), True )
        assert "promotion blocked" not in caplog.text
        _ask( orch, _io( "neither" ), True )
    assert "promotion blocked" in caplog.text and real.reframe_blocked( "general" ) is True


# --------------------------------------------------------------------------- the replay
def _replay():
    """
    Replay the 43 organic rows.

    The stored rows keep only a bool, so a stored False is either a no or a neither.
    The replay reports the lower bound (none is a neither) and the upper bound (all are).
    """
    rows   = json.load( open( FIXTURE ) )
    asked  = [ r for r in rows if r[ "user_answer" ] is not None ]
    report = {}
    for category in sorted( { r[ "category" ] for r in asked } ):
        mine    = [ r for r in asked if r[ "category" ] == category ]
        stances = [ "yes" if r[ "user_answer" ] else "neither" for r in mine ]
        changed = sum( 1 for r in mine if not r[ "user_answer" ] and ag.forecast_agreement( r[ "decision_value" ], False ) is not None )
        report[ category ] = {
            "asks"               : len( mine ),
            "neither_recorded"   : 0,
            "neither_upper"      : stances.count( "neither" ),
            "changed_upper"      : changed,
            "reframe_rate_upper" : ag.reframe_rate( stances ),
        }
    return rows, report


def test_the_replay_fixture_is_the_43_organic_rows_of_5_nov():
    rows, _ = _replay()
    assert len( rows ) == 43
    assert { r[ "created_at" ][ :10 ] for r in rows } == { "2026-11-05" }
    assert sum( 1 for r in rows if r[ "user_answer" ] is None ) == 1      # the one auto-approved act row


def test_the_replay_reports_the_three_figures_per_category_and_pins_the_changed_agreements():
    _, report = _replay()
    # Measured 23 Nov 2026. neither_recorded is 0 because the stored rows keep only a bool; the upper bound treats every stored False as a neither.
    assert report == {
        "general" : { "asks": 40, "neither_recorded": 0, "neither_upper": 8, "changed_upper": 8, "reframe_rate_upper": 0.1 },
        "testing" : { "asks": 2,  "neither_recorded": 0, "neither_upper": 1, "changed_upper": 1, "reframe_rate_upper": 0.5 },
    }
    assert sum( c[ "changed_upper" ] for c in report.values() ) == 9


# --------------------------------------------------------------------------- the capture script
def _script():
    spec   = importlib.util.spec_from_file_location( "capture_proxy_decisions_fixture", f"{ROOT}/src/scripts/capture_proxy_decisions_fixture.py" )
    module = importlib.util.module_from_spec( spec )
    spec.loader.exec_module( module )
    return module


def test_the_capture_script_reads_read_only_and_maps_a_row():
    from datetime import datetime, timezone
    row     = SimpleNamespace( category="general", action="shadow", decision_value=None, rule_agreement=None,
                               metadata_json={ "user_answer": False }, question="q?", created_at=datetime( 2026, 11, 5, tzinfo=timezone.utc ) )
    session = MagicMock()
    session.execute.return_value.fetchall.return_value = [ row ]
    with patch( "cosa.rest.db.database.get_db" ) as get_db:
        get_db.return_value.__enter__.return_value = session
        rows = _script().capture( "2026-11-05" )
    assert str( session.execute.call_args_list[ 0 ].args[ 0 ] ) == "SET TRANSACTION READ ONLY"
    assert rows == [ { "category": "general", "action": "shadow", "decision_value": None, "rule_agreement": None,
                       "user_answer": False, "question": "q?", "created_at": "2026-11-05T00:00:00+00:00" } ]


def test_the_capture_script_reads_a_row_with_no_metadata_as_unanswered():
    from datetime import datetime, timezone
    row     = SimpleNamespace( category="c", action="act", decision_value="approved", rule_agreement=None,
                               metadata_json=None, question="q", created_at=datetime( 2026, 11, 5, tzinfo=timezone.utc ) )
    session = MagicMock()
    session.execute.return_value.fetchall.return_value = [ row ]
    with patch( "cosa.rest.db.database.get_db" ) as get_db:
        get_db.return_value.__enter__.return_value = session
        assert _script().capture( "2026-11-05" )[ 0 ][ "user_answer" ] is None


def test_the_capture_script_main_prints_the_rows_as_json( capsys ):
    script = _script()
    with patch.object( script, "capture", return_value=[ { "a": 1 } ] ):
        assert script.main( [ "--day", "2026-11-05" ] ) == 0
    assert json.loads( capsys.readouterr().out ) == [ { "a": 1 } ]


def _io_from( source, raw="neither", stamp=None ):
    io = MagicMock()
    io.ask_confirmation_answer = AsyncMock( return_value=ConfirmationAnswer( "neither" if raw == "neither" else raw, None, raw, source=source, answered_by=stamp ) )
    return io


@pytest.mark.parametrize( "source", [ "default", "unattributed", "not_operator" ] )
@pytest.mark.parametrize( "switch", [ False, True ] )
def test_an_answer_nobody_gave_is_never_stored_as_a_stance_and_never_counts_as_a_neither( source, switch ):
    orch, proxy = _orch()
    result, write = _ask( orch, _io_from( source ), switch )
    meta = write.call_args.kwargs[ "extra" ][ "metadata_json" ]
    assert meta[ "answer_source" ] == source and meta[ "answer_unowned_raw" ] == "neither"
    for key in ( "answer_stance", "answer_comment", "answer_raw", "answered_by_user_id", "answered_by_method" ): assert key not in meta
    assert meta[ "user_answer" ] is False and result is False      # scored as a no, as before
    proxy.trust_tracker.record_decision.assert_called_once_with( "testing", success=False )
    proxy.note_stance.assert_not_called()


def test_a_human_stamp_without_a_user_id_stores_none_for_it():
    _, write = _ask( _orch()[ 0 ], _io_from( "human", raw="yes", stamp={ "method": "api_key" } ), True )
    meta = write.call_args.kwargs[ "extra" ][ "metadata_json" ]
    assert ( meta[ "answered_by_user_id" ], meta[ "answered_by_method" ] ) == ( None, "api_key" )


def test_an_auto_approval_row_says_the_proxy_answered():
    orch, proxy = _orch( action="act", value="approved" )
    proxy.trust_mode     = "active"
    orch._ask_before_act = False
    orch._notify = AsyncMock()
    io = _io( "yes" )
    result, write = _ask( orch, io, False )
    meta = write.call_args.kwargs[ "extra" ][ "metadata_json" ]
    assert meta == { "job_id": "swe-1", "user_answer": None, "answer_source": "proxy" }
    io.ask_confirmation_answer.assert_not_called()
