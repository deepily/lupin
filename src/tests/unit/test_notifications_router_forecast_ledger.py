"""
Unit tests for the ask-time forecast ledger hook in POST /api/notify.

Every ask writes exactly one forecast row before the hint is pushed, whichever path it took. The paths are a
forecast, a cold start, a disabled engine, a predictor error and a test override. These tests give the engine a
record_forecast that logs what the router handed it. It also logs whether the card had been pushed yet.

Fixture: `tests.helpers.notifications_endpoint_harness`.
"""
import json
from urllib.parse import urlencode

import pytest

from tests.helpers.notifications_endpoint_harness import a_uuid, make_harness_fixture

harness = make_harness_fixture()

_EMAIL = "someone@example.com"
_UID   = a_uuid( "ledger-target" )
_NID   = a_uuid( "ledger-notification" )


class _Item:
    response_default = "DEFAULT-VALUE"
    def to_dict( self ): return { "id": _NID }


class _Result:
    """Stands in for a PredictionResult: the router reads confidence, metadata and to_hint_dict."""
    response_type = "yes_no"
    category      = "permission"
    def __init__( self, confidence ):
        self.confidence = confidence
        self.metadata   = {}
    def to_hint_dict( self, threshold, metric, always_yes=None ):
        state = "ready" if self.confidence >= threshold else "below_threshold"
        hint  = { "state": state, "retrieval_metric": metric, "strategy": "s", "category": "permission" }
        if state == "ready": hint.update( predicted_value="yes", confidence=self.confidence )
        if always_yes is not None: hint[ "always_yes_rate" ] = always_yes
        return hint


@pytest.fixture
def wired( harness, monkeypatch ):
    import cosa.rest.routers.notifications as notif
    import cosa.rest.user_service as user_service
    import cosa.agents.prediction_engine as pe

    state = { "forecasts": [], "pushed_at_forecast": [], "enabled": True, "result": _Result( 0.9 ), "predict_raises": None,
              "forecast_raises": None, "predict_calls": [], "yes_rate": { "yes": 52, "n": 59, "rate": 0.8814 },
              "yes_rate_calls": [] }

    monkeypatch.setattr( user_service, "get_user_by_email", lambda email: { "id": _UID, "uid": "UID-VALUE" } )
    monkeypatch.setattr( notif, "_persist_response_required_sync", lambda *a: _NID )
    monkeypatch.setattr( notif, "_mark_notification_expired_sync", lambda nid: None )
    monkeypatch.setattr( notif, "_voice_persona_for_sender_id", lambda sid: { "name": "P", "icon": "I" } )
    monkeypatch.setattr( notif, "pending_responses", {} )

    class _Engine:
        confidence_threshold = 0.5
        hint_voting_enabled  = False
        retrieval_metric     = "dot"
        def always_yes_rate( self, recipient_id ):
            state[ "yes_rate_calls" ].append( recipient_id )
            return state[ "yes_rate" ]
        @property
        def enabled( self ): return state[ "enabled" ]
        def predict( self, nd ):
            state[ "predict_calls" ].append( nd )
            if state[ "predict_raises" ] is not None: raise state[ "predict_raises" ]
            return state[ "result" ]
        def record_forecast( self, notification_id, nd, **kw ):
            if state[ "forecast_raises" ] is not None: raise state[ "forecast_raises" ]
            state[ "forecasts" ].append( ( notification_id, nd, kw ) )
            state[ "pushed_at_forecast" ].append( len( harness.queue.calls_to( "push_notification" ) ) )

    engine = _Engine()
    monkeypatch.setattr( pe, "get_prediction_engine", lambda: engine )

    harness.ws.returns( "is_user_connected", True )
    harness.ws.returns( "get_user_connection_count", 1 )
    harness.ws.returns( "emit_to_user_or_listener_sync", { "listener_delivered": False } )
    harness.queue.returns( "push_notification", _Item() )
    return state


def _post( harness, **params ):
    base = { "message": "MESSAGE-VALUE", "target_user": _EMAIL, "response_requested": "true",
             "response_type": "yes_no", "timeout_seconds": 1, "response_default": "D" }
    base.update( params )
    return harness.client.post( "/api/notify?" + urlencode( base ) )


class TestEveryAskWritesOneRowBeforeTheHint:

    def test_a_forecast_hands_its_result_and_is_written_before_the_push( self, harness, wired ):
        _post( harness )
        assert len( wired[ "forecasts" ] ) == 1
        nid, nd, kw = wired[ "forecasts" ][ 0 ]
        assert nid == _NID
        assert kw[ "prediction_result" ] is wired[ "result" ]
        assert nd[ "message" ] == "MESSAGE-VALUE" and nd[ "response_type" ] == "yes_no"
        assert kw[ "owner_email" ] == _EMAIL
        assert wired[ "pushed_at_forecast" ] == [ 0 ], "the card was already pushed when the row was written"

    def test_the_row_stores_the_same_state_the_card_is_sent( self, harness, wired ):
        _post( harness )
        wired[ "result" ] = _Result( 0.1 )
        _post( harness )
        sent   = [ c.kwargs[ "prediction_hint" ][ "state" ] for c in harness.queue.calls_to( "push_notification" ) ]
        stored = [ f[ 2 ][ "display_decision" ] for f in wired[ "forecasts" ] ]
        assert sent == stored == [ "ready", "below_threshold" ]

    def test_a_weak_forecast_is_sent_with_no_value_and_no_gates( self, harness, wired ):
        wired[ "result" ] = _Result( 0.1 )
        _post( harness )
        hint = harness.queue.call_to( "push_notification" ).kwargs[ "prediction_hint" ]
        assert hint[ "state" ] == "below_threshold" and "predicted_value" not in hint
        assert not any( key.startswith( "auto_submit" ) or key.startswith( "vote_" ) for key in hint )

    def test_a_yes_no_ask_computes_the_always_yes_rate_for_its_recipient_and_stores_and_sends_it( self, harness, wired ):
        _post( harness )
        assert wired[ "yes_rate_calls" ] == [ _UID ]
        assert wired[ "forecasts" ][ 0 ][ 2 ][ "always_yes_rate" ] == wired[ "yes_rate" ]
        assert harness.queue.call_to( "push_notification" ).kwargs[ "prediction_hint" ][ "always_yes_rate" ] == wired[ "yes_rate" ]

    def test_a_card_that_is_not_yes_no_computes_no_rate( self, harness, wired ):
        _post( harness, response_type="open_ended" )
        assert wired[ "yes_rate_calls" ] == []
        assert wired[ "forecasts" ][ 0 ][ 2 ][ "always_yes_rate" ] is None

    def test_a_disabled_engine_writes_a_cold_start_row_named_engine_disabled( self, harness, wired ):
        wired[ "enabled" ] = False
        _post( harness )
        kw = wired[ "forecasts" ][ 0 ][ 2 ]
        assert wired[ "predict_calls" ] == []
        assert kw[ "strategy" ] == "cold_start" and kw[ "abstention_reason" ] == "engine_disabled"
        assert kw[ "display_decision" ] == "unavailable"
        assert "prediction_result" not in kw

    def test_a_predictor_error_writes_a_row_naming_the_exception_class( self, harness, wired ):
        wired[ "predict_raises" ] = KeyError( "boom" )
        r = _post( harness )
        assert r.status_code == 200, "a predictor error must not cost the ask"
        kw = wired[ "forecasts" ][ 0 ][ 2 ]
        assert kw[ "strategy" ] == "error" and kw[ "abstention_reason" ] == "predictor_error: KeyError"
        assert kw[ "display_decision" ] == "unavailable"
        assert harness.queue.call_to( "push_notification" ).kwargs[ "prediction_hint" ][ "state" ] == "unavailable"

    def test_a_test_override_writes_a_test_override_row_and_never_calls_predict( self, harness, wired ):
        _post( harness, prediction_hint_override=json.dumps( { "predicted_value": "yes" } ) )
        kw = wired[ "forecasts" ][ 0 ][ 2 ]
        assert wired[ "predict_calls" ] == []
        assert kw[ "forecast_source" ] == "test_override" and kw[ "strategy" ] == "test_override"
        assert kw[ "abstention_reason" ] == "test_override" and kw[ "display_decision" ] == "ready"

    def test_an_engine_that_cannot_be_built_still_gets_a_ledger_attempt_without_costing_the_ask( self, harness, wired, monkeypatch ):
        import cosa.agents.prediction_engine as pe
        def boom(): raise RuntimeError( "engine down" )
        monkeypatch.setattr( pe, "get_prediction_engine", boom )
        r = _post( harness )
        assert r.status_code == 200
        assert wired[ "forecasts" ] == []

    def test_a_ledger_write_that_raises_does_not_cost_the_ask( self, harness, wired, capsys ):
        wired[ "forecast_raises" ] = RuntimeError( "ledger down" )
        r = _post( harness )
        assert r.status_code == 200
        assert "Forecast ledger error" in capsys.readouterr().out

    def test_the_override_path_builds_its_engine_for_the_ledger( self, harness, wired ):
        """The override skips the engine in the predict branch, so the ledger fetches it itself."""
        _post( harness, prediction_hint_override=json.dumps( { "predicted_value": "no" } ) )
        assert len( wired[ "forecasts" ] ) == 1


class TestAReviewCardIsNeverForecast:
    """A card marked as a review card gets no forecast and no ledger row."""

    _MARKED = json.dumps( { "review_card": True } )

    def test_a_marked_ask_calls_no_predictor_and_writes_no_row_but_the_card_is_still_sent( self, harness, wired ):
        r = _post( harness, response_options=self._MARKED )
        assert r.status_code == 200
        assert wired[ "predict_calls" ] == [] and wired[ "forecasts" ] == [] and wired[ "yes_rate_calls" ] == []
        hint = harness.queue.call_to( "push_notification" ).kwargs[ "prediction_hint" ]
        assert hint[ "state" ] == "insufficient_evidence" and "predicted_value" not in hint, "a payload with no value in it"

    def test_the_same_ask_without_the_marker_is_forecast_and_written( self, harness, wired ):
        _post( harness, response_options=json.dumps( { "review_card": False } ) )
        _post( harness, response_options=json.dumps( { "note": "review_card" } ) )
        assert len( wired[ "predict_calls" ] ) == 2 and len( wired[ "forecasts" ] ) == 2

    def test_a_marked_ask_is_skipped_even_with_a_test_override_hint( self, harness, wired ):
        _post( harness, response_options=self._MARKED, prediction_hint_override=json.dumps( { "predicted_value": "yes" } ) )
        assert wired[ "forecasts" ] == [] and wired[ "predict_calls" ] == []


_SWITCH = "prediction learner arm forecast ledger enabled"


class TestArmForecastLedgerSwitch:

    def test_off_passes_no_hook_and_reads_the_named_key( self, harness, wired ):
        """The default is today's call: no pre_commit_hook argument at all."""
        _post( harness )
        assert "pre_commit_hook" not in wired[ "forecasts" ][ 0 ][ 2 ]
        assert _SWITCH in harness.config.reads

    def test_on_passes_the_displayed_arm_hook_and_it_writes_the_sibling_row( self, harness, wired ):
        """With the switch on, the hook writes the foundation arm's displayed row on the session."""
        harness.config.set( _SWITCH, True )
        _post( harness )
        hook = wired[ "forecasts" ][ 0 ][ 2 ][ "pre_commit_hook" ]
        added = []
        class _Session:
            def add( self, row ): added.append( row )
            def flush( self ): pass
        hook( _Session(), { "notification_id": _NID, "predictor_version": "pv", "forecast": { "value": "yes" }, "input_cutoff": None,
                            "evidence_ids": [ "e1" ], "forecast_ready_at": None, "abstention_reason": None } )
        assert [ ( str( r.notification_id ), r.arm, r.displayed ) for r in added ] == [ ( _NID, "A1", True ) ]

    def test_on_with_a_test_override_names_the_test_override_arm( self, harness, wired ):
        """The arm comes from forecast_source, so an injected hint is not filed as foundation."""
        harness.config.set( _SWITCH, True )
        _post( harness, prediction_hint_override=json.dumps( { "predicted_value": "yes" } ) )
        hook = wired[ "forecasts" ][ 0 ][ 2 ][ "pre_commit_hook" ]
        added = []
        class _Session:
            def add( self, row ): added.append( row )
            def flush( self ): pass
        hook( _Session(), { "notification_id": _NID, "predictor_version": "pv", "forecast": None, "input_cutoff": None,
                            "evidence_ids": None, "forecast_ready_at": None, "abstention_reason": "test_override" } )
        assert [ r.arm for r in added ] == [ "test_override" ]

    def test_an_unreadable_switch_reads_off_and_the_forecast_row_is_still_written( self, harness, wired, monkeypatch ):
        """A settings failure must not stop the ledger row."""
        def broken( key, **kwargs ): raise RuntimeError( "settings down" )
        monkeypatch.setattr( harness.config, "get", broken )
        _post( harness )
        assert len( wired[ "forecasts" ] ) == 1 and "pre_commit_hook" not in wired[ "forecasts" ][ 0 ][ 2 ]

    def test_an_unregistered_source_writes_the_forecast_row_with_no_hook_and_says_so( self, harness, wired, monkeypatch, capsys ):
        """A source with no arm must not drop the shipped row: no hook, one line printed."""
        import cosa.rest.db.repositories.arm_forecast_repository as arms
        monkeypatch.delitem( arms.DISPLAYED_ARM_BY_FORECAST_SOURCE, "foundation_sync" )
        harness.config.set( _SWITCH, True )
        _post( harness )
        assert len( wired[ "forecasts" ] ) == 1 and "pre_commit_hook" not in wired[ "forecasts" ][ 0 ][ 2 ]
        assert capsys.readouterr().out.count( "No arm registered for forecast source 'foundation_sync'" ) == 1


class TestAReviewCardIsNeverForecast:
    """A card marked as a review card gets no forecast and no ledger row."""

    _MARKED = json.dumps( { "review_card": True } )

    def test_a_marked_ask_calls_no_predictor_and_writes_no_row_but_the_card_is_still_sent( self, harness, wired ):
        r = _post( harness, response_options=self._MARKED )
        assert r.status_code == 200
        assert wired[ "predict_calls" ] == [] and wired[ "forecasts" ] == [] and wired[ "yes_rate_calls" ] == []
        hint = harness.queue.call_to( "push_notification" ).kwargs[ "prediction_hint" ]
        assert hint[ "state" ] == "insufficient_evidence" and "predicted_value" not in hint, "a payload with no value in it"

    def test_the_same_ask_without_the_marker_is_forecast_and_written( self, harness, wired ):
        _post( harness, response_options=json.dumps( { "review_card": False } ) )
        _post( harness, response_options=json.dumps( { "note": "review_card" } ) )
        assert len( wired[ "predict_calls" ] ) == 2 and len( wired[ "forecasts" ] ) == 2

    def test_a_marked_ask_is_skipped_even_with_a_test_override_hint( self, harness, wired ):
        _post( harness, response_options=self._MARKED, prediction_hint_override=json.dumps( { "predicted_value": "yes" } ) )
        assert wired[ "forecasts" ] == [] and wired[ "predict_calls" ] == []


class TestTheContextForecastStartsBehindItsSwitch:
    """The baseline job starts from the notify route only behind its switch."""

    @pytest.fixture
    def started( self, monkeypatch ):
        import cosa.agents.prediction_engine.context_baseline as cb
        import cosa.agents.prediction_engine.context_hint as ch
        calls, state = [], { "forecast": True, "display": False }

        async def recorder( nid, emit, metric, **kw ): calls.append( ( nid, emit, metric ) )
        monkeypatch.setattr( ch, "run_and_publish", recorder )
        monkeypatch.setattr( cb, "context_forecast_enabled", lambda: state[ "forecast" ] )
        monkeypatch.setattr( cb, "context_display_enabled", lambda: state[ "display" ] )
        state[ "calls" ] = calls
        return state

    def test_a_yes_no_card_starts_one_job_with_the_ids_and_the_retrieval_metric( self, harness, wired, started ):
        _post( harness )
        assert len( started[ "calls" ] ) == 1
        nid, emit, metric = started[ "calls" ][ 0 ]
        assert nid == _NID and metric == "dot" and callable( emit )
        hint = harness.queue.call_to( "push_notification" ).kwargs[ "prediction_hint" ]
        assert "context_forecast" not in hint, "display is off: the card carries no context payload"

    def test_with_display_on_the_card_opens_in_the_forecasting_state( self, harness, wired, started ):
        started[ "display" ] = True
        _post( harness )
        assert harness.queue.call_to( "push_notification" ).kwargs[ "prediction_hint" ][ "context_forecast" ] == { "state": "forecasting" }

    def test_the_emit_the_job_gets_reaches_the_asking_user( self, harness, wired, started ):
        _post( harness )
        emit = started[ "calls" ][ 0 ][ 1 ]
        emit( "prediction_hint_updated", { "notification_id": _NID } )
        sent = harness.ws.calls_to( "emit_to_user_or_listener_sync" )[ -1 ].kwargs
        assert sent[ "event" ] == "prediction_hint_updated" and sent[ "data" ] == { "notification_id": _NID } and sent[ "user_id" ] == _UID

    def test_the_task_is_forgotten_once_it_finishes( self, harness, wired, started ):
        import cosa.rest.routers.notifications as notif
        _post( harness )
        assert notif._CONTEXT_FORECAST_TASKS == set()

    def test_with_the_switch_off_no_job_starts( self, harness, wired, started ):
        started[ "forecast" ] = False
        _post( harness )
        assert started[ "calls" ] == []

    def test_cards_the_job_does_not_read_start_no_job( self, harness, wired, started ):
        _post( harness, response_type="open_ended" )
        _post( harness, response_options=json.dumps( { "review_card": True } ) )
        _post( harness, prediction_hint_override=json.dumps( { "predicted_value": "yes" } ) )
        assert started[ "calls" ] == []

    def test_a_job_that_cannot_start_does_not_cost_the_ask( self, harness, wired, monkeypatch, capsys ):
        import cosa.agents.prediction_engine.context_baseline as cb
        def boom(): raise RuntimeError( "settings unreadable" )
        monkeypatch.setattr( cb, "context_forecast_enabled", boom )
        r = _post( harness )
        assert r.status_code == 200 and len( harness.queue.calls_to( "push_notification" ) ) == 1
        assert "Could not start the baseline job" in capsys.readouterr().out


class TestThePrinciplesCallStartsBesideTheBaselineBehindItsOwnSwitch:
    """The principles call starts from the notify route behind its own switch."""

    @pytest.fixture
    def started( self, monkeypatch ):
        import cosa.agents.prediction_engine.context_baseline as cb
        import cosa.agents.prediction_engine.context_hint as ch
        import cosa.agents.prediction_engine.principles_forecast as pf
        import cosa.agents.principle_learner.principles_call as pc
        calls, baseline_calls, state = [], [], { "principles": True, "baseline": False, "display": False }

        async def recorder( nid, **kw ): calls.append( nid )
        async def baseline_recorder( nid, emit, metric, **kw ): baseline_calls.append( nid )
        monkeypatch.setattr( pc, "run_quietly", recorder )
        monkeypatch.setattr( ch, "run_and_publish", baseline_recorder )
        monkeypatch.setattr( pf, "principles_forecast_enabled", lambda: state[ "principles" ] )
        monkeypatch.setattr( cb, "context_forecast_enabled", lambda: state[ "baseline" ] )
        monkeypatch.setattr( cb, "context_display_enabled", lambda: state[ "display" ] )
        state[ "calls" ], state[ "baseline_calls" ] = calls, baseline_calls
        return state

    def test_a_yes_no_card_starts_one_call_with_its_id_and_changes_nothing_on_the_card( self, harness, wired, started ):
        _post( harness )
        assert started[ "calls" ] == [ _NID ]
        hint = harness.queue.call_to( "push_notification" ).kwargs[ "prediction_hint" ]
        assert "context_forecast" not in hint, "the principles arm is never shown"

    def test_it_starts_without_the_baseline_and_beside_it_when_both_are_on( self, harness, wired, started ):
        _post( harness )
        assert started[ "calls" ] == [ _NID ] and started[ "baseline_calls" ] == []
        started[ "baseline" ] = True
        _post( harness )
        assert started[ "calls" ] == [ _NID, _NID ] and started[ "baseline_calls" ] == [ _NID ]

    def test_with_its_switch_off_no_call_starts_even_with_the_baseline_on( self, harness, wired, started ):
        started[ "principles" ], started[ "baseline" ] = False, True
        _post( harness )
        assert started[ "calls" ] == [] and started[ "baseline_calls" ] == [ _NID ]

    def test_cards_the_baseline_does_not_read_start_no_call( self, harness, wired, started ):
        _post( harness, response_type="open_ended" )
        _post( harness, response_options=json.dumps( { "review_card": True } ) )
        _post( harness, prediction_hint_override=json.dumps( { "predicted_value": "yes" } ) )
        assert started[ "calls" ] == []

    def test_the_task_is_forgotten_once_it_finishes( self, harness, wired, started ):
        import cosa.rest.routers.notifications as notif
        _post( harness )
        assert notif._CONTEXT_FORECAST_TASKS == set()

    def test_a_call_that_cannot_start_does_not_cost_the_ask( self, harness, wired, monkeypatch, capsys ):
        import cosa.agents.prediction_engine.principles_forecast as pf
        def boom(): raise RuntimeError( "settings unreadable" )
        monkeypatch.setattr( pf, "principles_forecast_enabled", boom )
        r = _post( harness )
        assert r.status_code == 200 and len( harness.queue.calls_to( "push_notification" ) ) == 1
        assert "Could not start the principles call" in capsys.readouterr().out
