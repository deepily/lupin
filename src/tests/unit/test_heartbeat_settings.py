#!/usr/bin/env python3
"""
Unit tests for the Heartbeat-Hook settings loader (heartbeat_settings.py).

Covers every branch of load_heartbeat_settings() + _validate_poke_cap():
file-missing, unreadable/bad-JSON, block-missing, block-not-dict, individual
field defaults, enabled coercion, poke_cap validation (pass + every fail
shape), and the conservative default-OFF posture. Hermetic — a tmp
settings.json via monkeypatched expanduser; no real ~/.claude touch.

Venue: :7999-eligible / local — pure module, tmp-dir only, sub-second.
"""
import json
import os
import sys

import pytest

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from lupin_cli.claude_code.hooks.lib import heartbeat_settings as hs
from lupin_cli.claude_code.hooks.lib.heartbeat_poke_cap import DEFAULT_POKE_CAP


# ── Fixture: point the loader's expanduser at a tmp settings.json ─────────────

@pytest.fixture
def settings_file( tmp_path, monkeypatch ):
    """
    Return a writer( obj | str | None ) that materializes ~/.claude/settings.json
    in a tmp dir and redirects the loader's os.path.expanduser to it.

    - writer( None )  → no file on disk (file-missing path)
    - writer( str )   → raw text written verbatim (malformed-JSON path)
    - writer( obj )   → json.dump( obj )
    """
    path = tmp_path / "settings.json"
    monkeypatch.setattr( hs.os.path, "expanduser", lambda _p: str( path ) )

    def _write( content ):
        if content is None:
            return path
        if isinstance( content, str ):
            path.write_text( content )
        else:
            path.write_text( json.dumps( content ) )
        return path

    return _write


# ── Defaults / conservative posture ───────────────────────────────────────────

def test_defaults_shape():
    d = hs._defaults()
    assert d == { "enabled": False, "poke_cap": DEFAULT_POKE_CAP }


def test_default_enabled_is_false():
    """Brand-new ACTIVE behavior must be opt-in — dormant until explicitly wired."""
    assert hs.DEFAULT_ENABLED is False


def test_file_missing_returns_defaults( settings_file ):
    settings_file( None )                       # nothing on disk
    assert hs.load_heartbeat_settings() == { "enabled": False, "poke_cap": DEFAULT_POKE_CAP }


def test_unreadable_json_returns_defaults( settings_file ):
    settings_file( "{ this is not valid json " )
    assert hs.load_heartbeat_settings() == { "enabled": False, "poke_cap": DEFAULT_POKE_CAP }


def test_block_missing_returns_defaults( settings_file ):
    settings_file( { "idle_detection": { "enabled": True } } )   # no "heartbeat" key
    assert hs.load_heartbeat_settings() == { "enabled": False, "poke_cap": DEFAULT_POKE_CAP }


def test_block_not_dict_returns_defaults( settings_file ):
    settings_file( { "heartbeat": "on" } )      # not an object
    assert hs.load_heartbeat_settings() == { "enabled": False, "poke_cap": DEFAULT_POKE_CAP }


# ── Field reading / coercion ──────────────────────────────────────────────────

def test_enabled_true_poke_cap_read( settings_file ):
    settings_file( { "heartbeat": { "enabled": True, "poke_cap": 5 } } )
    assert hs.load_heartbeat_settings() == { "enabled": True, "poke_cap": 5 }


def test_enabled_coerced_to_bool( settings_file ):
    """Truthy non-bool 'enabled' is coerced via Python truthiness."""
    settings_file( { "heartbeat": { "enabled": 1 } } )
    loaded = hs.load_heartbeat_settings()
    assert loaded[ "enabled" ] is True
    assert loaded[ "poke_cap" ] == DEFAULT_POKE_CAP   # missing → default


def test_enabled_present_poke_cap_missing_uses_default( settings_file ):
    settings_file( { "heartbeat": { "enabled": True } } )
    assert hs.load_heartbeat_settings() == { "enabled": True, "poke_cap": DEFAULT_POKE_CAP }


def test_poke_cap_present_enabled_missing_defaults_off( settings_file ):
    settings_file( { "heartbeat": { "poke_cap": 7 } } )
    assert hs.load_heartbeat_settings() == { "enabled": False, "poke_cap": 7 }


# ── poke_cap validation (fail-loud) ───────────────────────────────────────────

@pytest.mark.parametrize( "bad", [ "three", True, False, 3.0, 0, -1, None ] )
def test_invalid_poke_cap_raises( settings_file, bad ):
    settings_file( { "heartbeat": { "enabled": True, "poke_cap": bad } } )
    with pytest.raises( ValueError ):
        hs.load_heartbeat_settings()


@pytest.mark.parametrize( "good", [ 1, 3, 99 ] )
def test_valid_poke_cap_passes( good ):
    hs._validate_poke_cap( good )   # must not raise


@pytest.mark.parametrize( "bad", [ "x", True, False, 2.5, 0, -5, None, [ 3 ] ] )
def test_validate_poke_cap_rejects( bad ):
    with pytest.raises( ValueError ):
        hs._validate_poke_cap( bad )


# ── Smoke entrypoint ──────────────────────────────────────────────────────────

def test_quick_smoke_test_passes():
    assert hs.quick_smoke_test() is True
