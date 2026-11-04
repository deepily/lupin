#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pins `run_cli`, the one refusal wrapper behind the five reuse runner command lines.

A refusal is one stderr line and exit code 2; any other error propagates; a working
call returns its own code. The five `cli` functions are checked to hand it their own refusals.
"""

import os
import sys

lupin_root = os.environ.get( "LUPIN_ROOT" )
if lupin_root is None:
    raise RuntimeError( "LUPIN_ROOT not set — export LUPIN_ROOT=/path/to/project" )
src_path = os.path.join( lupin_root, "src" )
if src_path not in sys.path: sys.path.insert( 0, src_path )

import pytest

from lupin_mcp import reuse_e2e as e2e
from lupin_mcp import reuse_e2e_run as e2r
from lupin_mcp import reuse_flip_run as frun
from lupin_mcp import reuse_phase5_run as p5
from lupin_mcp import reuse_stage1 as s1
from lupin_mcp import reuse_stage1_run as rr
from lupin_mcp import reuse_stage2_run as s2r


class Boom( Exception ):
    """A refusal stand-in."""


def test_run_cli_returns_the_calls_own_code( capsys ):
    assert rr.run_cli( lambda: 7, ( Boom, ) ) == 7
    assert capsys.readouterr().err == ""


def test_run_cli_turns_a_listed_refusal_into_one_line_and_exit_2( capsys ):
    def refuse():
        raise Boom( "no key" )
    assert rr.run_cli( refuse, ( Boom, ) ) == 2
    assert capsys.readouterr().err == "refused (Boom): no key\n"


def test_run_cli_lets_an_unlisted_error_propagate():
    def crash():
        raise KeyError( "x" )
    with pytest.raises( KeyError ):
        rr.run_cli( crash, ( Boom, ) )


def _refusal_of( module, refusal ):
    """Make module.main raise refusal, call module.cli, return ( code, stderr line )."""
    original = module.main
    def raising( *a, **k ):
        raise refusal
    module.main = raising
    try:
        return module.cli()
    finally:
        module.main = original


@pytest.mark.parametrize( "module,refusal", [
    ( rr,   rr.RunnerRefused( "r" ) ),
    ( rr,   s1.CanaryTripped( "c" ) ),
    ( e2r,  rr.RunnerRefused( "r" ) ),
    ( e2r,  e2e.FrozenInputRefused( "f" ) ),
    ( frun, rr.RunnerRefused( "r" ) ),
    ( frun, e2e.FrozenInputRefused( "f" ) ),
    ( p5,   s1.KeyMissing( "k" ) ),
    ( p5,   e2e.FrozenInputRefused( "f" ) ),
    ( s2r,  rr.RunnerRefused( "r" ) ),
    ( s2r,  e2e.FrozenInputRefused( "f" ) ),
] )
def test_each_cli_turns_its_own_refusals_into_exit_2( module, refusal, capsys ):
    assert _refusal_of( module, refusal ) == 2
    assert capsys.readouterr().err == f"refused ({type( refusal ).__name__}): {refusal}\n"


@pytest.mark.parametrize( "module,not_a_refusal", [
    ( p5,   rr.RunnerRefused( "r" ) ),
    ( p5,   s1.CanaryTripped( "c" ) ),
    ( rr,   e2e.FrozenInputRefused( "f" ) ),
] )
def test_a_refusal_a_cli_does_not_list_still_propagates( module, not_a_refusal ):
    with pytest.raises( type( not_a_refusal ) ):
        _refusal_of( module, not_a_refusal )
