#!/usr/bin/env python3
"""
Unit tests for the tier guard on the test-suite live pipeline smoke.

The job this smoke submits is a test-suite job, which always takes the monopolize slot.
Inside a tier that slot is held by the tier itself, so the job waits until the tier ends.
A tier exports its own id as LUPIN_TEST_MONOPOLIZE_PARENT_ID to every pytest it starts.
The smoke skips when that variable is set, and runs the full flow when it is not.
"""

import os
from unittest.mock import patch

import pytest

import tests.smoke.test_test_suite_live_pipeline as smoke

ENV = "LUPIN_TEST_MONOPOLIZE_PARENT_ID"


def _run_the_smoke():
    """Run the smoke body; a skip fails here, because these callers expect the flow to run."""
    try:
        smoke.test_test_suite_live_pipeline()
    except pytest.skip.Exception as skipped:
        pytest.fail( f"the smoke skipped outside a tier: {skipped}" )


def _env_without_the_tier_id( **extra ):
    env = { k: v for k, v in os.environ.items() if k != ENV }
    env.update( extra )
    return env


@pytest.fixture
def flow_calls( monkeypatch ):
    """Replace the live flow with a recorder that reports success."""
    calls = []
    monkeypatch.setattr( smoke, "quick_smoke_test", lambda: calls.append( "ran" ) or True )
    return calls


def test_inside_a_tier_the_smoke_skips_and_never_reaches_the_flow( flow_calls ):
    with patch.dict( os.environ, _env_without_the_tier_id( **{ ENV: "ts-abc123" } ), clear=True ):
        with pytest.raises( pytest.skip.Exception ) as skipped:
            smoke.test_test_suite_live_pipeline()
    assert flow_calls == []
    reason = str( skipped.value )
    assert "monopolize" in reason and "tier" in reason and "scheduled run" in reason, reason


@pytest.mark.parametrize( "value", [ None, "" ] )
def test_outside_a_tier_the_smoke_runs_the_flow( flow_calls, value ):
    extra = {} if value is None else { ENV: value }
    with patch.dict( os.environ, _env_without_the_tier_id( **extra ), clear=True ):
        _run_the_smoke()
    assert flow_calls == [ "ran" ]


def test_a_failing_flow_outside_a_tier_still_fails_the_test( monkeypatch ):
    monkeypatch.setattr( smoke, "quick_smoke_test", lambda: False )
    with patch.dict( os.environ, _env_without_the_tier_id(), clear=True ):
        with pytest.raises( AssertionError ):
            _run_the_smoke()
