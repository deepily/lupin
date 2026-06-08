"""
Unit tests for the LUPIN_ROOT validity assertion (Phase-1 Fix 1).

Proves the boot-time canary check fails loud on the /app-vs-/var/lupin path
drift and passes when LUPIN_ROOT points at a populated tree. Pure-Python,
non-mutating, sub-second — :7999-eligible / AI-discretionary.

Covers both branches of assert_lupin_root_valid (raise + pass-through) for the
100% line+branch coverage gate.
"""
import os

import pytest

from lupin_app.bootstrap_helpers import assert_lupin_root_valid


def test_valid_root_passes( tmp_path ):
    """A root containing src/conf/lupin-app.ini returns without raising."""
    conf_dir = tmp_path / "src" / "conf"
    conf_dir.mkdir( parents=True )
    ( conf_dir / "lupin-app.ini" ).write_text( "[Lupin: Baseline]\n" )

    # Pass branch — must not raise.
    assert assert_lupin_root_valid( str( tmp_path ) ) is None


def test_invalid_root_raises( tmp_path ):
    """An empty root (the /app drift) raises RuntimeError naming the problem."""
    with pytest.raises( RuntimeError, match="invalid" ):
        assert_lupin_root_valid( str( tmp_path ) )


def test_raised_message_is_actionable( tmp_path ):
    """The raised message names both the bad root and the expected canary path."""
    bad_root = str( tmp_path )
    expected_canary = os.path.join( bad_root, "src", "conf", "lupin-app.ini" )

    with pytest.raises( RuntimeError ) as exc_info:
        assert_lupin_root_valid( bad_root )

    message = str( exc_info.value )
    assert bad_root in message
    assert expected_canary in message
    assert "/var/lupin" in message  # points the operator at the Dockerfile bake path
