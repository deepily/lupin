#!/usr/bin/env python3
"""
Config-parse proof for the podcast-card expeditor revert flag.

The flag "podcast card uses runtime argument expeditor" (lupin-app.ini) gates
whether /api/podcast-generator/submit routes through the Runtime Argument
Expeditor (row 7c46fdde) or the legacy endpoint-owned resolver. The router
reads it with `return_type="boolean"` and branches on `if use_expeditor:`.

The router unit tests mock `config_mgr.get` to return a Python bool, so they
prove the DISPATCH given a real bool — but NOT that the value the running
server reads from the .ini is a real bool. That gap matters here because the
failure is silent: a non-"boolean" read returns the raw string, and the string
"False" is TRUTHY — `bool("False") is True`. If the flag were ever read without
the boolean cast, flipping it to False in the file would NOT restore the legacy
path, and nothing would raise. These tests close that gap against the config
the server actually loads.
"""

import os
import sys

import pytest

# ============================================================================
# Bootstrap PYTHONPATH (test entry point runs before cosa is on the path)
# ============================================================================
lupin_root = os.environ.get( "LUPIN_ROOT" )
if lupin_root is None:
    lupin_root = os.path.abspath( os.path.join( os.path.dirname( __file__ ), "..", ".." ) )
src_path = os.path.join( lupin_root, "src" )
if src_path not in sys.path:
    sys.path.insert( 0, src_path )

from cosa.config.configuration_manager import ConfigurationManager


FLAG_KEY = "podcast card uses runtime argument expeditor"


@pytest.fixture( scope="module" )
def config_mgr():
    """The real ConfigurationManager the app instantiates (reads lupin-app.ini)."""
    return ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )


def test_flag_reads_as_a_real_bool_from_the_ini( config_mgr ):
    """
    Ensures:
        - the flag the SERVER reads is a genuine bool, never the raw string.

    This is the load-bearing assertion: a string "False" is truthy, so a
    string-typed flag would silently keep the expeditor path on when the file
    says False. isinstance(bool) is what proves the revert is real.
    """
    value = config_mgr.get( FLAG_KEY, default=True, return_type="boolean" )
    assert isinstance( value, bool ), (
        f"{FLAG_KEY!r} must parse to a real bool, got {type( value ).__name__} "
        f"({value!r}); a truthy string would break the revert"
    )


def test_flag_key_is_present_not_defaulted( config_mgr ):
    """
    Ensures:
        - the flag exists in the .ini, so the value under test is the file's,
          not the caller-supplied default masking a missing key.
    """
    raw = config_mgr.get( FLAG_KEY, default="@@@_missing_@@@", return_type="string" )
    assert raw != "@@@_missing_@@@", f"{FLAG_KEY!r} is absent from lupin-app.ini"


def test_boolean_parse_maps_both_directions( config_mgr ):
    """
    Ensures:
        - the boolean cast maps "True"->True and "False"->False, so flipping the
          file string flips the branch. Decoupled from the flag's current value
          so it holds whether the demo ships it on or off.

    The `is False` assertion is deliberate: it proves the cast returns the bool
    singleton, not the truthy raw string "False" that this whole file guards.
    """
    assert config_mgr._get_typed_value( "True",  "boolean" ) is True
    assert config_mgr._get_typed_value( "False", "boolean" ) is False
