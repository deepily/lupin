#!/usr/bin/env python3
"""
Unit tests for cosa.agents.decision_proxy.responder.

DecisionResponder extends BaseResponder with trust-aware routing of
notification events through a domain strategy, plus best-effort DB +
LanceDB persistence. Every external boundary is mocked: submit_response
(REST), the DB session/repository, the embedding provider, and the
embedding store. Async handlers are driven via asyncio.run. ZERO real I/O
or API spend.
"""

import sys
import asyncio
from types import SimpleNamespace
from unittest.mock import patch, MagicMock, AsyncMock

from cosa.agents.decision_proxy.responder import DecisionResponder


# ----------------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------------
def _responder( **kwargs ):
    # BaseResponder.__init__ only sets attributes (no network) → safe to construct.
    return DecisionResponder( **kwargs )


def _result( action="shadow", value=None, category="testing", confidence=0.8,
             trust_level=1, reason="reason" ):
    return SimpleNamespace(
        action=action, value=value, category=category,
        confidence=confidence, trust_level=trust_level, reason=reason,
    )


def _event( **fields ):
    base = { "response_requested": True, "id_hash": "nid-1", "message": "Do X?", "sender_id": "s@x" }
    base.update( fields )
    return base


def _run( coro ):
    return asyncio.run( coro )


# ============================================================================
# __init__ / set_domain_strategy
# ============================================================================
def test_init_defaults():
    r = _responder()
    assert r.trust_mode == "shadow"
    assert r.accepted_senders == []
    assert r.domain_strategy is None
    assert r.embedding_provider is None
    assert r._embedding_store is None
    # base + decision-specific stats keys
    for key in ( "events_received", "responses_sent", "skipped", "errors",
                 "decisions_classified", "decisions_shadowed", "decisions_suggested",
                 "decisions_acted", "decisions_deferred", "sender_rejected" ):
        assert r.stats[ key ] == 0


def test_init_with_accepted_senders():
    r = _responder( accepted_senders=[ "a@x", "b@x" ] )
    assert r.accepted_senders == [ "a@x", "b@x" ]


def test_set_domain_strategy():
    r = _responder()
    strat = object()
    r.set_domain_strategy( strat )
    assert r.domain_strategy is strat


# ============================================================================
# handle_event
# ============================================================================
def test_handle_event_routes_notification_queue_update():
    r = _responder()
    r._handle_decision_event = AsyncMock()
    _run( r.handle_event( "notification_queue_update", { "x": 1 } ) )
    assert r.stats[ "events_received" ] == 1
    r._handle_decision_event.assert_awaited_once_with( { "x": 1 } )


def test_handle_event_job_state_transition_verbose_prints( capsys ):
    r = _responder( verbose=True )
    _run( r.handle_event( "job_state_transition", { "job_id": "j1", "from_queue": "a", "to_queue": "b" } ) )
    assert "Job state: j1 a -> b" in capsys.readouterr().out


def test_handle_event_job_state_transition_quiet( capsys ):
    r = _responder( verbose=False )
    _run( r.handle_event( "job_state_transition", { "job_id": "j1" } ) )
    assert capsys.readouterr().out == ""


def test_handle_event_other_type_verbose_prints( capsys ):
    r = _responder( verbose=True )
    _run( r.handle_event( "some_other_event", {} ) )
    assert "Event: some_other_event" in capsys.readouterr().out


def test_handle_event_other_type_quiet( capsys ):
    r = _responder( verbose=False )
    _run( r.handle_event( "some_other_event", {} ) )
    assert capsys.readouterr().out == ""


# ============================================================================
# _handle_decision_event — gating / early returns
# ============================================================================
def test_decision_event_skips_when_no_response_requested():
    r = _responder()
    _run( r._handle_decision_event( _event( response_requested=False ) ) )
    assert r.stats[ "skipped" ] == 1


def test_decision_event_errors_when_no_notification_id( capsys ):
    r = _responder()
    _run( r._handle_decision_event( { "response_requested": True } ) )
    assert r.stats[ "errors" ] == 1
    assert "No notification_id" in capsys.readouterr().out


def test_decision_event_sender_rejected_quiet():
    r = _responder( accepted_senders=[ "allowed@x" ] )
    _run( r._handle_decision_event( _event( sender_id="other@x" ) ) )
    assert r.stats[ "sender_rejected" ] == 1


def test_decision_event_sender_rejected_debug_prints( capsys ):
    r = _responder( accepted_senders=[ "allowed@x" ], debug=True )
    _run( r._handle_decision_event( _event( sender_id="other@x" ) ) )
    assert "Sender rejected" in capsys.readouterr().out


def test_decision_event_sender_accepted_proceeds_to_shadow():
    r = _responder( accepted_senders=[ "s@x" ] )      # sender in list → `and` second operand False
    _run( r._handle_decision_event( _event( sender_id="s@x" ) ) )
    # no strategy loaded → shadow path
    assert r.stats[ "decisions_shadowed" ] == 1


def test_empty_allowlist_rejects_every_sender_fail_closed():
    # 960a4ec9 Option C: fail-closed. An empty allowlist means "trust no one", so
    # the default sender is rejected at the gate and nothing downstream runs. Goes
    # RED under the old fail-open guard (empty list => check skipped => shadowed==1).
    #
    # This is NOT a hypothetical state: __main__._load_swe_profile's `except
    # ImportError` arm leaves accepted_senders empty (and domain_strategy None), so
    # a profile-import failure lands a live Responder in exactly this shape. This
    # test is that reachable path.
    r = _responder()                                # empty allowlist (the default)
    r.submit_response = MagicMock( return_value=True )
    _run( r._handle_decision_event( _event() ) )    # sender "s@x"
    assert r.stats[ "sender_rejected" ] == 1
    assert r.stats[ "decisions_shadowed" ] == 0
    r.submit_response.assert_not_called()           # rejected at the gate → nothing acts


def test_decision_event_dry_run_yes_no_sends_no():
    r = _responder( dry_run=True, accepted_senders=[ "s@x" ] )
    r.submit_response = MagicMock( return_value=True )
    _run( r._handle_decision_event( _event( response_type="yes_no" ) ) )
    r.submit_response.assert_called_once_with( "nid-1", "no" )
    assert r.stats[ "skipped" ] == 1


def test_decision_event_dry_run_non_yes_no_sends_cancel():
    r = _responder( dry_run=True, accepted_senders=[ "s@x" ] )
    r.submit_response = MagicMock( return_value=True )
    _run( r._handle_decision_event( _event( response_type="text" ) ) )
    r.submit_response.assert_called_once_with( "nid-1", "cancel" )


def test_decision_event_no_strategy_shadows_quiet():
    r = _responder( accepted_senders=[ "s@x" ] )
    _run( r._handle_decision_event( _event() ) )
    assert r.stats[ "decisions_shadowed" ] == 1


def test_decision_event_no_strategy_shadows_debug( capsys ):
    r = _responder( debug=True, accepted_senders=[ "s@x" ] )
    _run( r._handle_decision_event( _event() ) )
    assert "No strategy loaded" in capsys.readouterr().out


# ============================================================================
# _handle_decision_event — strategy actions
# ============================================================================
def _with_strategy( result, **kwargs ):
    # Fail-closed sender gate (960a4ec9 C): a responder that should PROCEED must
    # allow the default _event() sender, or it is rejected before the strategy runs.
    kwargs.setdefault( "accepted_senders", [ "s@x" ] )
    r = _responder( **kwargs )
    ds = MagicMock()
    ds.evaluate.return_value = result
    r.domain_strategy = ds
    r._persist_decision = MagicMock()
    r.submit_response = MagicMock( return_value=True )
    return r


def test_decision_event_shadow_action():
    r = _with_strategy( _result( action="shadow" ) )
    _run( r._handle_decision_event( _event() ) )
    assert r.stats[ "decisions_classified" ] == 1
    assert r.stats[ "decisions_shadowed" ] == 1
    r._persist_decision.assert_called_once()


def test_decision_event_shadow_action_debug_prints( capsys ):
    r = _with_strategy( _result( action="shadow" ), debug=True )
    _run( r._handle_decision_event( _event() ) )
    out = capsys.readouterr().out
    assert "SHADOW" in out
    assert "Notification:" in out          # covers the debug-display block


def test_decision_event_suggest_action():
    r = _with_strategy( _result( action="suggest", value="maybe" ) )
    _run( r._handle_decision_event( _event() ) )
    assert r.stats[ "decisions_suggested" ] == 1
    _, kwargs = r._persist_decision.call_args
    assert kwargs[ "requires_ratification" ] is True


def test_decision_event_suggest_action_debug( capsys ):
    r = _with_strategy( _result( action="suggest", value="maybe" ), debug=True )
    _run( r._handle_decision_event( _event() ) )
    assert "SUGGEST" in capsys.readouterr().out


def test_decision_event_act_with_value_success():
    r = _with_strategy( _result( action="act", value="yes" ) )
    r.submit_response = MagicMock( return_value=True )
    _run( r._handle_decision_event( _event() ) )
    assert r.stats[ "decisions_acted" ] == 1
    assert r.stats[ "responses_sent" ] == 1
    r.submit_response.assert_called_once_with( "nid-1", "yes" )


def test_decision_event_act_with_value_submit_fails():
    r = _with_strategy( _result( action="act", value="yes" ) )
    r.submit_response = MagicMock( return_value=False )
    _run( r._handle_decision_event( _event() ) )
    assert r.stats[ "errors" ] == 1
    assert r.stats[ "responses_sent" ] == 0


def test_decision_event_act_with_none_value_skips_submit():
    r = _with_strategy( _result( action="act", value=None ) )
    r.submit_response = MagicMock( return_value=True )
    _run( r._handle_decision_event( _event() ) )
    assert r.stats[ "decisions_acted" ] == 1
    r.submit_response.assert_not_called()


def test_decision_event_defer_action():
    r = _with_strategy( _result( action="defer" ) )
    _run( r._handle_decision_event( _event() ) )
    assert r.stats[ "decisions_deferred" ] == 1
    r._persist_decision.assert_called_once()


def test_decision_event_defer_action_debug( capsys ):
    r = _with_strategy( _result( action="defer" ), debug=True )
    _run( r._handle_decision_event( _event() ) )
    assert "DEFER" in capsys.readouterr().out


def test_decision_event_unknown_action_falls_through():
    # action matches none of shadow/suggest/act/defer → elif chain falls through
    r = _with_strategy( _result( action="noop" ) )
    _run( r._handle_decision_event( _event() ) )
    assert r.stats[ "decisions_classified" ] == 1
    assert r.stats[ "decisions_shadowed" ] == 0
    assert r.stats[ "decisions_deferred" ] == 0
    r._persist_decision.assert_not_called()


# ----------------------------------------------------------------------------
# notification extraction variants
# ----------------------------------------------------------------------------
def test_decision_event_nested_notification_payload():
    r = _responder( accepted_senders=[ "s@x" ] )
    _run( r._handle_decision_event( { "notification": _event() } ) )
    assert r.stats[ "decisions_shadowed" ] == 1     # reached no-strategy shadow → id resolved


def test_decision_event_notification_id_falls_back_to_id_field():
    r = _responder( accepted_senders=[ "s@x" ] )
    payload = { "response_requested": True, "id": "by-id", "message": "?", "sender_id": "s@x" }
    _run( r._handle_decision_event( payload ) )
    assert r.stats[ "decisions_shadowed" ] == 1     # `id` used as notification_id


# ============================================================================
# _get_embedding_store
# ============================================================================
def test_get_embedding_store_returns_cached():
    r = _responder()
    sentinel = object()
    r._embedding_store = sentinel
    assert r._get_embedding_store() is sentinel


def test_get_embedding_store_none_without_provider():
    r = _responder()                 # embedding_provider None
    assert r._get_embedding_store() is None


def test_get_embedding_store_initializes_on_success():
    r = _responder( embedding_provider=MagicMock() )
    sentinel_store = MagicMock()
    fake_pde = MagicMock()
    fake_pde.ProxyDecisionEmbeddings.return_value = sentinel_store
    fake_cfg = MagicMock()
    cm = MagicMock()
    cm.get.return_value = "value"
    fake_cfg.ConfigurationManager.return_value = cm

    with patch.dict( sys.modules, {
            "cosa.agents.decision_proxy.proxy_decision_embeddings": fake_pde,
            "cosa.config.configuration_manager": fake_cfg } ):
        store = r._get_embedding_store()
    assert store is sentinel_store
    assert r._embedding_store is sentinel_store

    # No location is built or handed over — the store is Postgres-backed.
    kwargs = fake_pde.ProxyDecisionEmbeddings.call_args.kwargs
    assert "db_path" not in kwargs
    assert kwargs[ "table_name" ] == "value"


def test_get_embedding_store_swallows_init_failure( capsys ):
    r = _responder( embedding_provider=MagicMock(), debug=True )
    with patch.dict( sys.modules, { "cosa.agents.decision_proxy.proxy_decision_embeddings": None } ):
        store = r._get_embedding_store()
    assert store is None
    assert "Embedding store init failed" in capsys.readouterr().out


# ============================================================================
# _persist_decision
# ============================================================================
def _inject_db( get_db, repo_cls ):
    fake_db = MagicMock(); fake_db.get_db = get_db
    fake_repo = MagicMock(); fake_repo.ProxyDecisionRepository = repo_cls
    return patch.dict( sys.modules, {
        "cosa.rest.db.database": fake_db,
        "cosa.rest.db.repositories.proxy_decision_repository": fake_repo } )


def test_persist_decision_shadow_logs_shadow():
    r = _responder()
    r._persist_embedding = MagicMock()
    repo_cls = MagicMock()
    with _inject_db( MagicMock(), repo_cls ):
        r._persist_decision( "nid", _result( action="shadow" ), "question text" )
    repo_cls.return_value.log_shadow.assert_called_once()
    r._persist_embedding.assert_called_once()


def test_persist_decision_non_shadow_logs_decision_infers_ratification():
    r = _responder()
    r.domain_strategy = SimpleNamespace( name="swe" )
    r._persist_embedding = MagicMock()
    repo_cls = MagicMock()
    with _inject_db( MagicMock(), repo_cls ):
        r._persist_decision( "nid", _result( action="suggest", value="v" ), "q" )   # req=None → infer suggest→True
    _, kwargs = repo_cls.return_value.log_decision.call_args
    assert kwargs[ "requires_ratification" ] is True
    assert kwargs[ "domain" ] == "swe"


def test_persist_decision_explicit_ratification_flag():
    r = _responder()
    r._persist_embedding = MagicMock()
    repo_cls = MagicMock()
    with _inject_db( MagicMock(), repo_cls ):
        r._persist_decision( "nid", _result( action="act", value="v" ), "q", requires_ratification=False )
    _, kwargs = repo_cls.return_value.log_decision.call_args
    assert kwargs[ "requires_ratification" ] is False


def test_persist_decision_db_failure_is_swallowed( capsys ):
    r = _responder( debug=True )
    r._persist_embedding = MagicMock()
    with patch.dict( sys.modules, { "cosa.rest.db.database": None } ):
        r._persist_decision( "nid", _result( action="shadow" ), "q" )
    assert "DB persistence failed" in capsys.readouterr().out
    r._persist_embedding.assert_called_once()       # embedding step still runs


def test_persist_decision_db_failure_quiet_when_debug_off( capsys ):
    # debug=False → except arm skips the print (covers the False branch)
    r = _responder( debug=False )
    r._persist_embedding = MagicMock()
    with patch.dict( sys.modules, { "cosa.rest.db.database": None } ):
        r._persist_decision( "nid", _result( action="shadow" ), "q" )
    assert capsys.readouterr().out == ""
    r._persist_embedding.assert_called_once()


# ============================================================================
# _persist_embedding
# ============================================================================
def test_persist_embedding_returns_when_store_none():
    r = _responder( embedding_provider=MagicMock() )
    r._get_embedding_store = MagicMock( return_value=None )
    r._persist_embedding( "nid", _result(), "q", None )
    r.embedding_provider.generate_embedding.assert_not_called()


def test_persist_embedding_pending_state():
    r = _responder( embedding_provider=MagicMock() )
    store = MagicMock()
    r._get_embedding_store = MagicMock( return_value=store )
    r.embedding_provider.generate_embedding.return_value = [ 0.1, 0.2 ]
    r._persist_embedding( "nid", _result( value="yes" ), "q", True )
    _, kwargs = store.add_decision.call_args
    assert kwargs[ "ratification_state" ] == "pending"
    assert kwargs[ "decision_value" ] == "yes"


def test_persist_embedding_autonomous_state():
    r = _responder( embedding_provider=MagicMock() )
    store = MagicMock()
    r._get_embedding_store = MagicMock( return_value=store )
    r.embedding_provider.generate_embedding.return_value = [ 0.1 ]
    r._persist_embedding( "nid", _result( value="yes" ), "q", False )
    _, kwargs = store.add_decision.call_args
    assert kwargs[ "ratification_state" ] == "autonomous"


def test_persist_embedding_shadow_state_and_empty_value():
    r = _responder( embedding_provider=MagicMock() )
    store = MagicMock()
    r._get_embedding_store = MagicMock( return_value=store )
    r.embedding_provider.generate_embedding.return_value = [ 0.1 ]
    r._persist_embedding( "nid", _result( value=None ), "q", None )      # req None → shadow; value None → ""
    _, kwargs = store.add_decision.call_args
    assert kwargs[ "ratification_state" ] == "shadow"
    assert kwargs[ "decision_value" ] == ""


def test_persist_embedding_swallows_exception( capsys ):
    r = _responder( embedding_provider=MagicMock(), debug=True )
    store = MagicMock()
    r._get_embedding_store = MagicMock( return_value=store )
    r.embedding_provider.generate_embedding.side_effect = RuntimeError( "boom" )
    r._persist_embedding( "nid", _result(), "q", None )
    assert "Embedding persistence failed" in capsys.readouterr().out


def test_persist_embedding_exception_quiet_when_debug_off( capsys ):
    # debug=False → except arm skips the print (covers the False branch)
    r = _responder( embedding_provider=MagicMock(), debug=False )
    store = MagicMock()
    r._get_embedding_store = MagicMock( return_value=store )
    r.embedding_provider.generate_embedding.side_effect = RuntimeError( "boom" )
    r._persist_embedding( "nid", _result(), "q", None )
    assert capsys.readouterr().out == ""


# ============================================================================
# get_decision_diagnostics
# ============================================================================
def test_diagnostics_stats_only_when_no_strategy():
    r = _responder()
    diag = r.get_decision_diagnostics()
    assert "stats" in diag
    assert "thompson_sampling" not in diag
    assert "conformal" not in diag


def test_diagnostics_includes_thompson():
    r = _responder()
    r.domain_strategy = SimpleNamespace( get_thompson_diagnostics=lambda: { "arm": 1 } )
    diag = r.get_decision_diagnostics()
    assert diag[ "thompson_sampling" ] == { "arm": 1 }


def test_diagnostics_includes_conformal_when_wrapper_present():
    r = _responder()
    wrapper = SimpleNamespace( get_status=lambda: { "calibrated": True } )
    r.domain_strategy = SimpleNamespace( _conformal_wrapper=wrapper )
    diag = r.get_decision_diagnostics()
    assert diag[ "conformal" ] == { "calibrated": True }


def test_diagnostics_skips_conformal_when_wrapper_none():
    r = _responder()
    r.domain_strategy = SimpleNamespace( _conformal_wrapper=None )
    diag = r.get_decision_diagnostics()
    assert "conformal" not in diag


# ============================================================================
# print_stats
# ============================================================================
def test_print_stats_outputs_all_counters( capsys ):
    r = _responder()
    r.print_stats()
    out = capsys.readouterr().out
    assert "Decision Proxy Statistics" in out
    assert "Events Received" in out


# ============================================================================
# `enabled` master switch (row 960a4ec9) — a disabled proxy cannot submit
# ----------------------------------------------------------------------------
# The splainer promises "when false, the proxy will not run"; before this the
# flag was read into config and never consulted. These assert the ENFORCEMENT:
# with enabled=False the decision pipeline is a no-op and submit_response is
# never reached — on the ACT path (the real submit) and the DRY-RUN path alike.
# The contrast test proves the guard is not simply blocking everything.
# ============================================================================
def _act_responder( enabled, dry_run=False ):
    r = _responder( enabled=enabled, dry_run=dry_run, accepted_senders=[ "s@x" ] )
    r.submit_response = MagicMock( return_value=True )
    strategy = MagicMock()
    strategy.evaluate = MagicMock( return_value=_result( action="act", value="yes" ) )
    r.set_domain_strategy( strategy )
    return r


def test_disabled_proxy_cannot_submit_on_act_path():
    r = _act_responder( enabled=False )
    _run( r._handle_decision_event( _event() ) )
    r.submit_response.assert_not_called()
    assert r.stats[ "disabled_skipped" ] == 1
    assert r.stats[ "decisions_acted" ] == 0
    assert r.stats[ "responses_sent" ] == 0


def test_disabled_proxy_cannot_submit_on_dry_run_path():
    # dry-run submits a cancel BEFORE any strategy runs — the disabled guard must
    # still preempt it, or a disabled proxy would emit cancels.
    r = _responder( enabled=False, dry_run=True )
    r.submit_response = MagicMock( return_value=True )
    _run( r._handle_decision_event( _event( response_type="yes_no" ) ) )
    r.submit_response.assert_not_called()
    assert r.stats[ "disabled_skipped" ] == 1


def test_enabled_proxy_still_submits_on_act_path():
    # The load-bearing contrast: the SAME event with enabled=True DOES reach
    # submit — so the disabled assertions above mean "the flag stopped it", not
    # "this path never submits anyway".
    r = _act_responder( enabled=True )
    _run( r._handle_decision_event( _event() ) )
    r.submit_response.assert_called_once_with( "nid-1", "yes" )
    assert r.stats[ "disabled_skipped" ] == 0
    assert r.stats[ "responses_sent" ] == 1
