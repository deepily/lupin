"""
Unit tests for cosa.agents.shared.config_loader.

The config_mgr fake answers from a dict and records each call, so the tests see
the key, default and return type the loader asked for.
"""

from dataclasses import dataclass

import pytest

from cosa.agents.shared.config_loader import load_dataclass_from_ini, load_kwargs_from_ini


@dataclass
class _Cfg:
    name    : str   = "n0"
    count   : int   = 3
    ratio   : float = 0.5
    enabled : bool  = False
    other   : list  = None


@dataclass
class _StringAnnotated:
    flag  : "bool" = False
    count : "int"  = 1
    ratio : "float" = 1.5
    text  : "str"  = "t"


KEY_MAP = { "name": "x name", "count": "x count", "ratio": "x ratio", "enabled": "x enabled" }


class _Mgr:
    def __init__( self, values ):
        self.values = values
        self.calls  = []

    def get( self, key, default=None, return_type=None ):
        self.calls.append( ( key, default, return_type ) )
        return self.values.get( key, default )


def test_asks_for_each_key_with_the_field_default_and_the_type_coerced_return_type():
    mgr = _Mgr( {} )
    load_kwargs_from_ini( _Cfg, mgr, KEY_MAP )
    assert mgr.calls == [
        ( "x name",    "n0", "string"  ),
        ( "x count",   3,    "int"     ),
        ( "x ratio",   0.5,  "float"   ),
        ( "x enabled", False, "boolean" ),
    ]


def test_string_annotations_are_coerced_like_real_types():
    mgr = _Mgr( {} )
    load_kwargs_from_ini( _StringAnnotated, mgr, { "flag": "k1", "count": "k2", "ratio": "k3", "text": "k4" } )
    assert [ c[ 2 ] for c in mgr.calls ] == [ "boolean", "int", "float", "string" ]


def test_unlisted_types_read_as_string():
    mgr = _Mgr( {} )
    load_kwargs_from_ini( _Cfg, mgr, { "other": "x other" } )
    assert mgr.calls == [ ( "x other", None, "string" ) ]


def test_kwargs_hold_ini_values_and_fall_back_to_defaults():
    mgr = _Mgr( { "x count": 9, "x enabled": True } )
    assert load_kwargs_from_ini( _Cfg, mgr, KEY_MAP ) == { "name": "n0", "count": 9, "ratio": 0.5, "enabled": True }


def test_load_dataclass_builds_the_instance_from_those_kwargs():
    mgr = _Mgr( { "x name": "from-ini" } )
    cfg = load_dataclass_from_ini( _Cfg, mgr, KEY_MAP )
    assert cfg == _Cfg( name="from-ini", count=3, ratio=0.5, enabled=False )


def test_an_unknown_field_name_raises_keyerror():
    with pytest.raises( KeyError ):
        load_kwargs_from_ini( _Cfg, _Mgr( {} ), { "nope": "x nope" } )


def test_debug_prints_one_line_per_field_with_the_class_name_or_the_label( capsys ):
    load_kwargs_from_ini( _Cfg, _Mgr( { "x count": 9 } ), { "count": "x count" }, debug=True )
    load_kwargs_from_ini( _Cfg, _Mgr( {} ), { "count": "x count" }, debug=True, label="Custom" )
    load_kwargs_from_ini( _Cfg, _Mgr( {} ), { "count": "x count" } )
    out = capsys.readouterr().out.splitlines()
    assert out == [ "  [_Cfg] count = 9 (from INI: x count)", "  [Custom] count = 3 (from INI: x count)" ]
