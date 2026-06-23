#!/usr/bin/env python3
"""
Unit tests for the Heartbeat-Hook settings loader (heartbeat_settings.py).

Covers every branch of load_heartbeat_settings() + _validate_poke_cap():
file-missing, unreadable/bad-JSON, block-missing, block-not-dict, individual
field defaults, enabled coercion, poke_cap validation (pass + every fail
shape), the Thread-B count_inbound_questions_as_owed gate key (default-OFF,
present True/False, coercion), and the conservative default-OFF posture.
Hermetic — a tmp settings.json via monkeypatched expanduser; no real ~/.claude
touch.

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


# Full default dict (5 keys as of 6929f4ac verification_threshold_seconds).
# Single source for the many "returns defaults" assertions below — bump it here
# if a 6th key ever lands.
_DEFAULTS = { "enabled": False, "poke_cap": DEFAULT_POKE_CAP,
              "count_inbound_questions_as_owed": False,
              "owed_source_from_store": False,
              "verification_threshold_seconds": 600 }


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
    assert hs._defaults() == _DEFAULTS


def test_default_enabled_is_false():
    """Brand-new ACTIVE behavior must be opt-in — dormant until explicitly wired."""
    assert hs.DEFAULT_ENABLED is False


def test_default_count_inbound_as_owed_is_false():
    """Thread B (Rick 2026-06-16): owed-inbound poke signal is REMOVED by default."""
    assert hs.DEFAULT_COUNT_INBOUND_AS_OWED is False


def test_file_missing_returns_defaults( settings_file ):
    settings_file( None )                       # nothing on disk
    assert hs.load_heartbeat_settings() == _DEFAULTS


def test_unreadable_json_returns_defaults( settings_file ):
    settings_file( "{ this is not valid json " )
    assert hs.load_heartbeat_settings() == _DEFAULTS


def test_block_missing_returns_defaults( settings_file ):
    settings_file( { "idle_detection": { "enabled": True } } )   # no "heartbeat" key
    assert hs.load_heartbeat_settings() == _DEFAULTS


def test_block_not_dict_returns_defaults( settings_file ):
    settings_file( { "heartbeat": "on" } )      # not an object
    assert hs.load_heartbeat_settings() == _DEFAULTS


# ── Field reading / coercion ──────────────────────────────────────────────────

def test_enabled_true_poke_cap_read( settings_file ):
    settings_file( { "heartbeat": { "enabled": True, "poke_cap": 5 } } )
    assert hs.load_heartbeat_settings() == { **_DEFAULTS, "enabled": True, "poke_cap": 5 }


def test_enabled_coerced_to_bool( settings_file ):
    """Truthy non-bool 'enabled' is coerced via Python truthiness."""
    settings_file( { "heartbeat": { "enabled": 1 } } )
    loaded = hs.load_heartbeat_settings()
    assert loaded[ "enabled" ] is True
    assert loaded[ "poke_cap" ] == DEFAULT_POKE_CAP   # missing → default


def test_enabled_present_poke_cap_missing_uses_default( settings_file ):
    settings_file( { "heartbeat": { "enabled": True } } )
    assert hs.load_heartbeat_settings() == { **_DEFAULTS, "enabled": True }


def test_poke_cap_present_enabled_missing_defaults_off( settings_file ):
    settings_file( { "heartbeat": { "poke_cap": 7 } } )
    assert hs.load_heartbeat_settings() == { **_DEFAULTS, "poke_cap": 7 }


# ── Thread B: count_inbound_questions_as_owed gate key ────────────────────────

def test_count_inbound_missing_defaults_false( settings_file ):
    """A heartbeat block without the key → the gate stays OFF (owed-inbound removed)."""
    settings_file( { "heartbeat": { "enabled": True, "poke_cap": 3 } } )
    assert hs.load_heartbeat_settings()[ "count_inbound_questions_as_owed" ] is False


def test_count_inbound_true_opt_in( settings_file ):
    """Explicit opt-in restores the v3 worker-inbound poke signal."""
    settings_file( { "heartbeat": { "enabled": True, "poke_cap": 3,
                                    "count_inbound_questions_as_owed": True } } )
    assert hs.load_heartbeat_settings()[ "count_inbound_questions_as_owed" ] is True


def test_count_inbound_false_explicit( settings_file ):
    settings_file( { "heartbeat": { "count_inbound_questions_as_owed": False } } )
    assert hs.load_heartbeat_settings()[ "count_inbound_questions_as_owed" ] is False


def test_count_inbound_coerced_to_bool( settings_file ):
    """Truthy non-bool is coerced via Python truthiness (mirrors 'enabled')."""
    settings_file( { "heartbeat": { "count_inbound_questions_as_owed": 1 } } )
    assert hs.load_heartbeat_settings()[ "count_inbound_questions_as_owed" ] is True


def test_count_inbound_falsy_non_bool_coerced( settings_file ):
    """Falsy non-bool (0) coerces to False — the gate stays OFF."""
    settings_file( { "heartbeat": { "count_inbound_questions_as_owed": 0 } } )
    assert hs.load_heartbeat_settings()[ "count_inbound_questions_as_owed" ] is False


# ── 6929f4ac: verification_threshold_seconds (read + fail-loud validation) ────

def test_verification_threshold_default_is_600():
    assert hs.DEFAULT_VERIFICATION_THRESHOLD_SECONDS == 600


def test_verification_threshold_missing_defaults_600( settings_file ):
    settings_file( { "heartbeat": { "enabled": True, "poke_cap": 3 } } )
    assert hs.load_heartbeat_settings()[ "verification_threshold_seconds" ] == 600


def test_verification_threshold_read( settings_file ):
    settings_file( { "heartbeat": { "verification_threshold_seconds": 1200 } } )
    assert hs.load_heartbeat_settings()[ "verification_threshold_seconds" ] == 1200


@pytest.mark.parametrize( "bad", [ "ten", True, False, 600.0, 0, -1, None, [ 600 ] ] )
def test_invalid_verification_threshold_raises( settings_file, bad ):
    settings_file( { "heartbeat": { "verification_threshold_seconds": bad } } )
    with pytest.raises( ValueError ):
        hs.load_heartbeat_settings()


@pytest.mark.parametrize( "good", [ 1, 600, 3600 ] )
def test_valid_verification_threshold_passes( good ):
    hs._validate_verification_threshold( good )   # must not raise


@pytest.mark.parametrize( "bad", [ "x", True, False, 2.5, 0, -5, None, [ 3 ] ] )
def test_validate_verification_threshold_rejects( bad ):
    with pytest.raises( ValueError ):
        hs._validate_verification_threshold( bad )


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
