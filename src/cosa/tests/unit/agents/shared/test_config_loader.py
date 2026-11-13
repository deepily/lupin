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


class _SilentMgr:
    """A manager whose get accepts silent and records the keywords it was given."""

    def __init__( self ):
        self.extra = []

    def get( self, key, default=None, return_type=None, **extra ):
        self.extra.append( extra )
        return default


def test_silent_left_false_leaves_the_argument_out_of_every_get():
    mgr = _SilentMgr()
    load_kwargs_from_ini( _Cfg, mgr, KEY_MAP )
    assert mgr.extra == [ {}, {}, {}, {} ]


def test_silent_true_is_passed_to_every_get():
    mgr = _SilentMgr()
    load_kwargs_from_ini( _Cfg, mgr, KEY_MAP, silent=True )
    assert mgr.extra == [ { "silent": True } ] * 4


def test_load_dataclass_passes_silent_through():
    mgr = _SilentMgr()
    load_dataclass_from_ini( _Cfg, mgr, KEY_MAP, silent=True )
    assert mgr.extra == [ { "silent": True } ] * 4


def test_load_dataclass_passes_debug_and_label_through( capsys ):
    load_dataclass_from_ini( _Cfg, _Mgr( {} ), KEY_MAP, debug=True, label="Lbl" )
    lines = [ l for l in capsys.readouterr().out.splitlines() if l.startswith( "  [Lbl] " ) ]
    assert len( lines ) == 4
    load_dataclass_from_ini( _Cfg, _Mgr( {} ), KEY_MAP )
    assert capsys.readouterr().out == ""


# ----------------------------------------------------------------------------
# model ids: read from the INI, no default in code
# ----------------------------------------------------------------------------
from dataclasses import MISSING, field, fields

from cosa.agents.shared.config_loader import model_field, required_model_id


class _RequiredMgr:
    """get_required answers from a dict, as the real manager does, and records each call."""

    def __init__( self, values ):
        self.values = values
        self.calls  = []

    def get_required( self, key, silent=False, return_type="string" ):
        self.calls.append( ( key, silent, return_type ) )
        return self.values[ key ]


@dataclass
class _WithModel:
    lead  : str = model_field( "x lead model" )
    count : int = 3


def test_required_model_id_reads_the_key_through_get_required_silently():
    mgr = _RequiredMgr( { "x lead model": "m-1" } )
    assert required_model_id( "x lead model", mgr ) == "m-1"
    assert mgr.calls == [ ( "x lead model", True, "string" ) ]


def test_required_model_id_builds_the_process_manager_and_keeps_its_banner_off_stdout( capsys ):
    built = []
    class _Builds( _RequiredMgr ):
        def __init__( self, env_var_name=None ):
            super().__init__( { "x lead model": "from-process" } )
            built.append( env_var_name )
            print( "BANNER" )
    from unittest.mock import patch
    with patch( "cosa.config.configuration_manager.ConfigurationManager", _Builds ):
        assert required_model_id( "x lead model" ) == "from-process"
    captured = capsys.readouterr()
    assert built == [ "LUPIN_CONFIG_MGR_CLI_ARGS" ]
    assert ( captured.out, captured.err ) == ( "", "BANNER\n" )


def test_required_model_id_refuses_a_key_the_real_ini_lacks():
    # Imported here, not at module top: a peer test swaps the manager module in sys.modules, and
    # required_model_id imports it at call time, so only a call-time import names the class it raises.
    from cosa.config.configuration_manager import MissingConfigKeyError
    with pytest.raises( MissingConfigKeyError, match="no such model key for the test" ):
        required_model_id( "no such model key for the test" )


def test_required_model_id_reads_a_key_the_real_ini_holds():
    assert required_model_id( "deep research lead model" ).startswith( "claude-" )


def test_a_model_field_has_no_default_in_code_and_reads_the_ini_when_omitted():
    lead = [ f for f in fields( _WithModel ) if f.name == "lead" ][ 0 ]
    assert ( lead.default, lead.default_factory is MISSING ) == ( MISSING, False )
    from unittest.mock import patch
    with patch( "cosa.agents.shared.config_loader.required_model_id", return_value="never-called" ):
        assert _WithModel( lead="passed" ).lead == "passed"         # a passed value is used as given


def test_a_model_field_left_out_of_the_constructor_refuses_a_missing_key():
    from cosa.config.configuration_manager import MissingConfigKeyError     # call-time import, as above
    with pytest.raises( MissingConfigKeyError, match="x lead model" ):
        _WithModel()


def test_the_loader_reads_a_model_field_with_get_required_and_the_rest_with_get():
    mgr = _RequiredMgr( { "x lead model": "m-2" } )
    mgr.get = lambda key, default=None, return_type=None, silent=False: default
    kwargs = load_kwargs_from_ini( _WithModel, mgr, { "lead": "x lead model", "count": "x count" }, silent=True )
    assert kwargs == { "lead": "m-2", "count": 3 }
    assert mgr.calls == [ ( "x lead model", True, "string" ) ]


def test_the_loader_refuses_a_model_field_whose_key_is_missing():
    mgr = _RequiredMgr( {} )
    with pytest.raises( KeyError, match="x lead model" ):
        load_kwargs_from_ini( _WithModel, mgr, { "lead": "x lead model" } )


def test_a_field_with_another_default_factory_is_read_with_get():
    @dataclass
    class _Listy:
        items : list = field( default_factory=list )
    mgr = _Mgr( { "x items": [ 1 ] } )
    assert load_kwargs_from_ini( _Listy, mgr, { "items": "x items" } ) == { "items": [ 1 ] }
