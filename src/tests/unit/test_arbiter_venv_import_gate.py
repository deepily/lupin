#!/usr/bin/env python3
"""
Unit tests for src/scripts/check-arbiter-venv.py — the deploy-time import gate.

Venue: :7999-eligible (pure in-process; no network, no venv creation, no
persistent state).

WHY THIS SUITE EXISTS
---------------------
The checker is the control for a failure that was silent three times: the light
arbiter host venv drifting behind the arbiter's import graph. A control that
cannot itself fail is worthless, so these tests assert BOTH directions — it passes
a good venv AND it fails a venv missing the closure, naming the module.

Record: src/rnd/v0.2.0/2026.08.10-arbiter-fleet-loop-silent-death.md
"""
import importlib.util
import os

import pytest

import cosa.utils.util as cu


def _load_checker():
    """Load the script by path — it is a script, not an importable package module."""
    path = os.path.join( cu.get_project_root(), "src", "scripts", "check-arbiter-venv.py" )
    spec = importlib.util.spec_from_file_location( "check_arbiter_venv", path )
    mod  = importlib.util.module_from_spec( spec )
    spec.loader.exec_module( mod )
    return mod


CHK = _load_checker()


def test_check_modules_reports_nothing_when_every_import_succeeds():
    assert CHK.check_modules( [ "json", "os", "sys" ] ) == [ ]


def test_check_modules_names_the_missing_module():
    """POSITIVE CONTROL — the checker must actually detect a missing module."""
    failures = CHK.check_modules( [ "json", "a_module_that_does_not_exist_xyz" ] )
    assert len( failures ) == 1
    name, err = failures[ 0 ]
    assert name == "a_module_that_does_not_exist_xyz"
    assert "ModuleNotFoundError" in err


def test_check_modules_reports_a_broken_import_not_just_a_missing_one( tmp_path, monkeypatch ):
    """A module that raises ON IMPORT is a deploy blocker too, not just an absent one."""
    ( tmp_path / "boom_mod.py" ).write_text( "raise RuntimeError( 'bad module' )\n" )
    monkeypatch.syspath_prepend( str( tmp_path ) )
    failures = CHK.check_modules( [ "boom_mod" ] )
    assert len( failures ) == 1 and "RuntimeError" in failures[ 0 ][ 1 ]


def test_db_closure_is_conditional_on_the_flag():
    """
    The whole point of the 2026-08-10 gate: with the feature OFF the arbiter must not
    need sqlalchemy at all, so the checker must not demand it.
    """
    assert "sqlalchemy" in CHK.REQUIRED_WHEN_FOLLOW_THROUGH_ENABLED
    assert "sqlalchemy" not in CHK.ALWAYS_REQUIRED
    assert "pgvector"   not in CHK.ALWAYS_REQUIRED
    assert "psycopg2"   not in CHK.ALWAYS_REQUIRED


def test_yaml_stays_in_the_always_list():
    """Regression guard for instance #1 (2026-07-22, live ModuleNotFoundError('yaml'))."""
    assert "yaml" in CHK.ALWAYS_REQUIRED


def test_unreadable_config_checks_MORE_not_less( monkeypatch ):
    """
    A config that cannot be loaded must widen the required set, never shrink it —
    a gate that quietly stops checking is the failure mode this milestone is about.
    """
    import cosa.config.configuration_manager as cm
    def _boom( *a, **k ): raise RuntimeError( "no config here" )
    monkeypatch.setattr( cm, "ConfigurationManager", _boom )
    assert CHK.follow_through_enabled() is True


def test_main_returns_zero_when_all_required_modules_import( monkeypatch, capsys ):
    monkeypatch.setattr( CHK, "follow_through_enabled", lambda: False )
    monkeypatch.setattr( CHK, "ALWAYS_REQUIRED", [ "json", "os" ] )
    assert CHK.main( [ ] ) == 0
    assert "OK —" in capsys.readouterr().out


def test_main_returns_one_and_prints_the_remedy_on_failure( monkeypatch, capsys ):
    monkeypatch.setattr( CHK, "follow_through_enabled", lambda: False )
    monkeypatch.setattr( CHK, "ALWAYS_REQUIRED", [ "a_module_that_does_not_exist_xyz" ] )
    assert CHK.main( [ ] ) == 1
    out = capsys.readouterr().out
    assert "FAILED: 1" in out
    assert "requirements-arbiter.txt" in out            # the remedy names the deploy contract


def test_main_json_mode_is_machine_readable( monkeypatch, capsys ):
    import json
    monkeypatch.setattr( CHK, "follow_through_enabled", lambda: True )
    monkeypatch.setattr( CHK, "ALWAYS_REQUIRED", [ "json" ] )
    monkeypatch.setattr( CHK, "REQUIRED_WHEN_FOLLOW_THROUGH_ENABLED", [ "a_module_that_does_not_exist_xyz" ] )
    rc   = CHK.main( [ "--json" ] )
    body = json.loads( capsys.readouterr().out )
    assert rc == 1
    assert body[ "ok" ] is False
    assert body[ "follow_through_enabled" ] is True
    assert body[ "modules_checked" ] == 2
    assert body[ "failures" ][ 0 ][ "module" ] == "a_module_that_does_not_exist_xyz"


def test_enabled_flag_adds_the_db_closure_to_the_checked_set( monkeypatch, capsys ):
    """Flag ON must widen the set — this is the case that failed on the VM."""
    monkeypatch.setattr( CHK, "follow_through_enabled", lambda: True )
    monkeypatch.setattr( CHK, "ALWAYS_REQUIRED", [ "json" ] )
    monkeypatch.setattr( CHK, "REQUIRED_WHEN_FOLLOW_THROUGH_ENABLED", [ "os", "sys" ] )
    assert CHK.main( [ ] ) == 0
    assert "modules checked: 3" in capsys.readouterr().out
