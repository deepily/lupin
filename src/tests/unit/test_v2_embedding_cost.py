#!/usr/bin/env python3
"""
Unit tests for the v2 embedding-cost measurement instrument — its pure loop and
summary math (src/scripts/v2_embedding_cost.py). Hermetic: a FAKE probe stands in
for the live embedding path, so no server and no model server. :7999-eligible.

The live probe and the --live measurement block are infra-gated (:8000 scheduled)
and pragma-excluded in the script; this suite pins everything else at 100%.
"""

import os
import sys

import pytest

# The instrument lives under src/scripts/. Put that dir on sys.path so it imports
# by name (v2_embedding_cost) — which lets coverage target it as --cov=v2_embedding_cost.
_SCRIPTS_DIR = os.path.join( os.environ[ "LUPIN_ROOT" ], "src", "scripts" )
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert( 0, _SCRIPTS_DIR )

import v2_embedding_cost as ec


# ────────────────────────────────────────────────────────────── summarize

def test_summarize_basic():
    s = ec.summarize( [ 10.0, 20.0, 30.0, 40.0 ] )
    assert s[ "n" ]    == 4.0
    assert s[ "mean" ] == 25.0
    assert s[ "min" ]  == 10.0
    assert s[ "max" ]  == 40.0
    assert s[ "p50" ]  == 20.0          # nearest-rank
    assert s[ "p95" ]  == 40.0


def test_summarize_single_element():
    s = ec.summarize( [ 7.5 ] )
    assert s[ "p50" ]  == 7.5
    assert s[ "p95" ]  == 7.5
    assert s[ "mean" ] == 7.5


def test_summarize_empty_raises():
    with pytest.raises( ValueError ):
        ec.summarize( [] )


# ────────────────────────────────────────────────────────────── measure

def _fake_probe( warm_hits ):
    """A probe: cold call = generate (slow, not cached); warm = fast + cached flag."""
    def _embed_once( question, warm ):
        if warm:
            return warm_hits, 0.2      # warm timing
        return False, 40.0             # cold generate timing
    return _embed_once


def test_measure_with_cache_hits_reports_speedup():
    result = ec.measure( [ "a", "b" ], _fake_probe( warm_hits=True ) )
    assert len( result[ "rows" ] ) == 2
    assert result[ "generated" ][ "mean" ] == 40.0
    assert result[ "cached" ][ "n" ] == 2.0
    assert result[ "speedup" ] == pytest.approx( 200.0 )   # 40.0 / 0.2


def test_measure_without_cache_hits_has_no_speedup():
    result = ec.measure( [ "a" ], _fake_probe( warm_hits=False ) )
    assert result[ "cached" ] is None
    assert result[ "speedup" ] is None


def test_measure_cached_mean_zero_leaves_speedup_none():
    # warm hit reported but at 0.0 ms → no divide-by-zero, speedup stays None
    def _probe( question, warm ):
        return ( True, 0.0 ) if warm else ( False, 5.0 )
    result = ec.measure( [ "a" ], _probe )
    assert result[ "cached" ][ "mean" ] == 0.0
    assert result[ "speedup" ] is None


# ────────────────────────────────────────────────────────────── format

def test_format_report_with_cached():
    result = ec.measure( [ "a", "b" ], _fake_probe( warm_hits=True ) )
    text = ec.format_report( result )
    assert "| question |" in text
    assert "generate:" in text
    assert "cached:" in text
    assert "speedup:" in text
    assert "✓" in text


def test_format_report_without_cached():
    result = ec.measure( [ "a" ], _fake_probe( warm_hits=False ) )
    text = ec.format_report( result )
    assert "generate:" in text
    assert "cached:" not in text
    assert "speedup:" not in text
    assert "—" in text                 # warm-not-cached marker


# ────────────────────────────────────────────────────────────── main (non-live)

def test_main_without_live_prints_instrument_notice( monkeypatch, capsys ):
    monkeypatch.setattr( sys, "argv", [ "v2_embedding_cost.py", "-q", "extra question" ] )
    ec.main()
    out = capsys.readouterr().out
    assert "INSTRUMENT" in out
