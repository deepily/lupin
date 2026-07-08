#!/usr/bin/env python3
"""
Unit tests for the SWE-team integration test's shared-pool wait-budget helper
(bug 67473d91): ``swe_wait_budget_s`` / ``_agentic_pool_workers`` in
``tests/integration/test_swe_team_pipeline.py``.

Pure-logic coverage — no live server. Validates:
  - the pool-aware formula (budget scales with the live pool width),
  - the ``LUPIN_TEST_SWE_BUDGET_S`` escape hatch (short-circuits the query),
  - the FAIL-LOUD pool-status contract (Mr. Radio rider — scream, do not guess).
"""
import math

import pytest

from tests.integration import test_swe_team_pipeline as swe


class _FakeResp:
    def __init__( self, status_code, payload=None ):
        self.status_code = status_code
        self._payload    = payload if payload is not None else {}

    def json( self ):
        return self._payload


def _fake_get( status_code, payload=None ):
    def _get( url, headers=None, timeout=None ):
        return _FakeResp( status_code, payload )
    return _get


def test_env_override_short_circuits( monkeypatch ):
    """LUPIN_TEST_SWE_BUDGET_S bypasses the pool-status query entirely."""
    monkeypatch.setenv( "LUPIN_TEST_SWE_BUDGET_S", "137" )
    # If the query were consulted, this would blow up — proves the short-circuit.
    monkeypatch.setattr( swe, "_agentic_pool_workers",
                         lambda *_a, **_k: pytest.fail( "pool queried despite env override" ) )
    assert swe.swe_wait_budget_s( {} ) == 137


@pytest.mark.parametrize( "workers, expected_waves", [ ( 1, 7 ), ( 2, 4 ), ( 3, 3 ), ( 7, 1 ), ( 10, 1 ) ] )
def test_formula_scales_with_pool_width( monkeypatch, workers, expected_waves ):
    """budget = COLD_START + ceil( N / workers ) * PER_JOB — survives a worker-count change."""
    monkeypatch.delenv( "LUPIN_TEST_SWE_BUDGET_S", raising=False )
    monkeypatch.setattr( swe, "_agentic_pool_workers", lambda *_a, **_k: workers )
    expected = swe._COLD_START_MARGIN_S + expected_waves * swe._PER_JOB_BUDGET_S
    assert swe.swe_wait_budget_s( {} ) == expected
    assert math.ceil( swe._SWE_HEAVY_JOB_COUNT / workers ) == expected_waves


def test_pool_status_unreachable_fails_loud( monkeypatch ):
    """Non-200 pool-status → AssertionError (scream, not silently guess)."""
    monkeypatch.delenv( "LUPIN_TEST_SWE_BUDGET_S", raising=False )
    monkeypatch.setattr( swe.requests, "get", _fake_get( 503 ) )
    with pytest.raises( AssertionError, match="pool-status unreachable" ):
        swe.swe_wait_budget_s( {} )


@pytest.mark.parametrize( "payload", [ {}, { "max_agentic_workers": 0 }, { "max_agentic_workers": "3" }, { "max_agentic_workers": None } ] )
def test_pool_status_malformed_fails_loud( monkeypatch, payload ):
    """200 with missing / non-positive / non-int max_agentic_workers → AssertionError."""
    monkeypatch.delenv( "LUPIN_TEST_SWE_BUDGET_S", raising=False )
    monkeypatch.setattr( swe.requests, "get", _fake_get( 200, payload ) )
    with pytest.raises( AssertionError, match="invalid max_agentic_workers" ):
        swe.swe_wait_budget_s( {} )


def test_agentic_pool_workers_happy_path( monkeypatch ):
    """_agentic_pool_workers returns the positive int from pool-status."""
    monkeypatch.setattr( swe.requests, "get", _fake_get( 200, { "max_agentic_workers": 3 } ) )
    assert swe._agentic_pool_workers( {} ) == 3
