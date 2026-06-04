#!/usr/bin/env python3
"""
Unit tests for the prediction-hint thumbs vote CAPTURE path (Stage 2 backend).

Covers (all mocked — no DB, no server → :7999-eligible):
  - PredictionEngine.record_hint_vote()      : up→approved insert, down→rejected insert,
                                               re-vote updates in place, bad vote / no store
  - PredictionEngine._decision_value_from_predicted() : serialization shapes
  - POST /api/notify/prediction-vote/{id} endpoint : success / engine-ValueError 422 / 500
"""

import json
import types
import asyncio
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from cosa.agents.prediction_engine.prediction_engine import PredictionEngine
from cosa.rest.routers import notifications as nmod
import cosa.agents.prediction_engine as pe_pkg


@pytest.fixture( autouse=True )
def _reset_engine_singleton():
    """PredictionEngine is a singleton — these tests mutate instance state/methods
    (e.g. overriding _get_embedding_store). Reset before AND after each test so the
    singleton never leaks a mock into a later test/file (FM-21 config/registry bleed)."""
    PredictionEngine.reset()
    yield
    PredictionEngine.reset()


def _engine():
    eng = PredictionEngine( debug=True )
    eng._embedding_store    = MagicMock()
    eng._embedding_provider = MagicMock()
    return eng


# ── record_hint_vote ──────────────────────────────────────────────────────────
class TestRecordHintVote:
    def test_up_new_inserts_approved_organic_case( self ):
        eng = _engine()
        eng._embedding_store.exists.return_value = False
        out = eng.record_hint_vote( "n1", "Ship it?", "yes", "deploy", "yes_no", "up" )
        assert out[ "ratification_state" ] == "approved" and out[ "updated" ] is False
        kwargs = eng._embedding_store.add_decision.call_args.kwargs
        assert kwargs[ "id" ] == "hintvote-n1"
        assert kwargs[ "ratification_state" ] == "approved"
        assert kwargs[ "data_origin" ] == "organic"
        eng._embedding_store.update_ratification_state.assert_not_called()

    def test_down_new_inserts_rejected_case( self ):
        eng = _engine()
        eng._embedding_store.exists.return_value = False
        out = eng.record_hint_vote( "n2", "Ship it?", "no", "deploy", "yes_no", "down" )
        assert out[ "ratification_state" ] == "rejected"
        assert eng._embedding_store.add_decision.call_args.kwargs[ "ratification_state" ] == "rejected"

    def test_revote_flips_state_in_place_no_duplicate( self ):
        eng = _engine()
        eng._embedding_store.exists.return_value = True
        out = eng.record_hint_vote( "n3", "Ship it?", "yes", "deploy", "yes_no", "down" )
        assert out[ "updated" ] is True and out[ "ratification_state" ] == "rejected"
        eng._embedding_store.update_ratification_state.assert_called_once_with( "hintvote-n3", "rejected" )
        eng._embedding_store.add_decision.assert_not_called()

    def test_bad_vote_raises_value_error( self ):
        eng = _engine()
        with pytest.raises( ValueError ):
            eng.record_hint_vote( "n4", "q", "yes", "c", "yes_no", "sideways" )

    def test_no_store_raises_runtime_error( self ):
        eng = PredictionEngine( debug=True )
        eng._get_embedding_store    = MagicMock( return_value=None )
        eng._get_embedding_provider = MagicMock( return_value=None )
        with pytest.raises( RuntimeError ):
            eng.record_hint_vote( "n5", "q", "yes", "c", "yes_no", "up" )


# ── _decision_value_from_predicted ────────────────────────────────────────────
class TestDecisionValueFromPredicted:
    def test_mc_dict_with_answers_serializes_json( self ):
        out = PredictionEngine._decision_value_from_predicted( { "answers": { "DB": "PostgreSQL" } } )
        assert json.loads( out ) == { "answers": { "DB": "PostgreSQL" } }

    def test_yes_no_scalar_string_passthrough( self ):
        assert PredictionEngine._decision_value_from_predicted( "yes" ) == "yes"

    def test_value_envelope_extracts_value( self ):
        assert PredictionEngine._decision_value_from_predicted( { "value": "maybe" } ) == "maybe"

    def test_bare_dict_falls_back_to_json( self ):
        out = PredictionEngine._decision_value_from_predicted( { "x": 1 } )
        assert json.loads( out ) == { "x": 1 }


# ── endpoint ──────────────────────────────────────────────────────────────────
class TestVoteEndpoint:
    def _patch_engine( self, monkeypatch, record_fn ):
        fake = types.SimpleNamespace( record_hint_vote=record_fn )
        monkeypatch.setattr( pe_pkg, "get_prediction_engine", lambda *a, **k: fake )
        monkeypatch.setattr( nmod, "get_local_timestamp", lambda: "2026-06-03T00:00:00" )

    def test_success_returns_state( self, monkeypatch ):
        self._patch_engine( monkeypatch,
                            lambda **kw: { "case_id": "hintvote-n1", "ratification_state": "approved", "updated": False } )
        body = nmod.PredictionVoteRequest( vote="up", question="Ship it?", predicted_value="yes" )
        out  = asyncio.run( nmod.vote_on_prediction_hint( notification_id="n1", body=body, authenticated_user_id="u1" ) )
        assert out[ "status" ] == "success"
        assert out[ "vote" ] == "up" and out[ "ratification_state" ] == "approved" and out[ "updated" ] is False

    def test_engine_value_error_raises_422( self, monkeypatch ):
        def boom( **kw ): raise ValueError( "bad vote" )
        self._patch_engine( monkeypatch, boom )
        body = nmod.PredictionVoteRequest( vote="up", question="q", predicted_value="yes" )
        with pytest.raises( HTTPException ) as exc:
            asyncio.run( nmod.vote_on_prediction_hint( notification_id="n1", body=body, authenticated_user_id="u1" ) )
        assert exc.value.status_code == 422

    def test_engine_failure_raises_500( self, monkeypatch ):
        def boom( **kw ): raise RuntimeError( "store down" )
        self._patch_engine( monkeypatch, boom )
        body = nmod.PredictionVoteRequest( vote="down", question="q", predicted_value="no" )
        with pytest.raises( HTTPException ) as exc:
            asyncio.run( nmod.vote_on_prediction_hint( notification_id="n1", body=body, authenticated_user_id="u1" ) )
        assert exc.value.status_code == 500

    # — authoritative resolution of question/response_type from the persisted notification —
    def _patch_db( self, monkeypatch, notif ):
        import contextlib
        @contextlib.contextmanager
        def fake_get_db():
            yield "SESSION"
        monkeypatch.setattr( nmod, "get_db", fake_get_db )
        monkeypatch.setattr( nmod, "NotificationRepository",
                            lambda session: types.SimpleNamespace( get_by_id=lambda _id: notif ) )

    def test_resolves_question_and_type_from_db_when_client_omits( self, monkeypatch ):
        captured = {}
        def _record( **kw ):
            captured.update( kw )
            return { "ratification_state": "approved", "updated": False }
        self._patch_engine( monkeypatch, _record )
        self._patch_db( monkeypatch, types.SimpleNamespace( message="Ship the release?", response_type="yes_no" ) )
        VALID = "12345678-1234-1234-1234-123456789abc"
        body  = nmod.PredictionVoteRequest( vote="up", predicted_value="yes" )   # no question / response_type
        out   = asyncio.run( nmod.vote_on_prediction_hint( notification_id=VALID, body=body, authenticated_user_id="u1" ) )
        assert out[ "status" ] == "success"
        assert captured[ "question" ] == "Ship the release?"      # pulled from the notification
        assert captured[ "response_type" ] == "yes_no"

    def test_unresolvable_question_raises_422( self, monkeypatch ):
        self._patch_engine( monkeypatch, lambda **kw: { "ratification_state": "approved", "updated": False } )
        self._patch_db( monkeypatch, None )                       # notification not found
        VALID = "12345678-1234-1234-1234-123456789abc"
        body  = nmod.PredictionVoteRequest( vote="up", predicted_value="yes" )   # no question, none in DB
        with pytest.raises( HTTPException ) as exc:
            asyncio.run( nmod.vote_on_prediction_hint( notification_id=VALID, body=body, authenticated_user_id="u1" ) )
        assert exc.value.status_code == 422

    def test_missing_predicted_value_raises_422( self, monkeypatch ):
        self._patch_engine( monkeypatch, lambda **kw: { "ratification_state": "approved", "updated": False } )
        body = nmod.PredictionVoteRequest( vote="up", question="q?" )            # predicted_value omitted → None
        with pytest.raises( HTTPException ) as exc:
            asyncio.run( nmod.vote_on_prediction_hint( notification_id="n1", body=body, authenticated_user_id="u1" ) )
        assert exc.value.status_code == 422
