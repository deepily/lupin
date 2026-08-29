"""
Unit tests for cosa.config.configuration_manager.ConfigurationManager.

The class is a @singleton-decorated INI configuration manager supporting
block inheritance (intra-file and file-based), default-value layering,
immutable-key (@_) scoping, CLI overrides, typed getters, and a 'splainer'
documentation lookup.

Tests build throwaway INI files in tempdirs and ALWAYS construct with
_reset_singleton=True (the decorator's atomic reset hook) so each test gets a
fresh instance; tearDown clears the singleton to prevent cross-test pollution.
get_project_root() is patched to the tempdir for the env-var construction path
and the splainer load.

Assertions harvested and strengthened from the module's quick_smoke_test() and
the legacy core/test_config_mgr.py harness (both superseded).
"""

import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import cosa.config.configuration_manager as cm_mod
from cosa.config.configuration_manager import ConfigurationManager


def _capture( fn, *args, **kwargs ):
    """Run fn and return everything it printed to stdout."""
    buf = io.StringIO()
    with redirect_stdout( buf ):
        fn( *args, **kwargs )
    return buf.getvalue()


_MAIN_INI = """\
[default]
app debug = False
common = base_default
@_def_immutable = keep

[grandparent]
inherits = __BASE_PATH__
gp_key = gp_val

[parent]
inherits = grandparent
shared = from_parent
dupe = parentval
@_inh = inherited_immutable

[child]
inherits = parent
my_int = 42
my_float = 3.14
my_bool = True
my_str = hello
my_list = a, b, c
my_json = {"k": 1}
my_dict = {'k': 2}
dupe = childval
@_secret = remove_me
expand_me = ${HOME}/sub
blank_key =
expand_blank = ${LUPIN_TEST_BLANK_VAR}

[filechild]
inherits = __BASE_PATH__
local = localval

[leaf]
leaf_key = leaf_val

[midblock]
inherits = leaf
mid_key = mid_val
"""

_BASE_INI = """\
[base]
file_key = file_value
"""

_SPLAINER_INI = """\
[default]
my_int = An integer configuration value.

[my_int]
"""


def _write_fixtures():
    """Create a tempdir with main / base / splainer INIs; return (dir, paths)."""
    tmp = tempfile.TemporaryDirectory()
    base_path     = os.path.join( tmp.name, "base_inherit.ini" )
    config_path   = os.path.join( tmp.name, "main.ini" )
    splainer_path = os.path.join( tmp.name, "splainer.ini" )
    with open( base_path, "w" ) as f:
        f.write( _BASE_INI )
    with open( config_path, "w" ) as f:
        f.write( _MAIN_INI.replace( "__BASE_PATH__", base_path ) )
    with open( splainer_path, "w" ) as f:
        f.write( _SPLAINER_INI )
    return tmp, config_path, splainer_path, base_path


class _CfgBase( unittest.TestCase ):
    """Shared fixture setup + singleton hygiene."""

    def setUp( self ):
        self._tmp, self.config_path, self.splainer_path, self.base_path = _write_fixtures()
        self.addCleanup( self._tmp.cleanup )

    def tearDown( self ):
        ConfigurationManager.reset_for_testing()

    def _build( self, block_id="child", silent=True, **kwargs ):
        return ConfigurationManager(
            config_path=self.config_path,
            splainer_path=self.splainer_path,
            config_block_id=block_id,
            silent=silent,
            _reset_singleton=True,
            **kwargs,
        )


class TestSingletonAndConstruction( _CfgBase ):
    """Singleton decorator + __init__ validation branches."""

    def test_zero_arg_raises( self ):
        with self.assertRaises( ValueError ):
            ConfigurationManager( _reset_singleton=True )

    def test_conflicting_params_raise( self ):
        with self.assertRaises( ValueError ):
            ConfigurationManager(
                env_var_name="X", config_path="/a", splainer_path="/b",
                _reset_singleton=True,
            )

    def test_missing_env_var_raises( self ):
        with patch.dict( os.environ, {}, clear=False ):
            os.environ.pop( "NOPE_CFG_VAR", None )
            with self.assertRaises( ValueError ):
                ConfigurationManager( env_var_name="NOPE_CFG_VAR", _reset_singleton=True )

    def test_incomplete_explicit_paths_raise( self ):
        with self.assertRaises( ValueError ):
            ConfigurationManager(
                config_path=self.config_path, _reset_singleton=True
            )

    def test_singleton_returns_same_instance( self ):
        first = self._build()
        # No reset -> same instance handed back.
        second = ConfigurationManager(
            config_path=self.config_path, splainer_path=self.splainer_path,
            config_block_id="child", silent=True,
        )
        self.assertIs( first, second )

    def test_reset_for_testing_true_then_false( self ):
        self._build()
        self.assertTrue( ConfigurationManager.reset_for_testing() )   # had instance
        self.assertFalse( ConfigurationManager.reset_for_testing() )  # none now

    def test_reset_singleton_flag_when_instance_exists( self ):
        self._build()                       # first instance created
        mgr = self._build()                 # _reset_singleton=True with instance present
        self.assertEqual( mgr.get( "my_int", return_type="int" ), 42 )

    def test_init_with_no_path_args_reuses_state( self ):
        mgr = self._build( block_id="child" )
        # Re-run init() with no path/block args -> exercises the None-skip branches.
        mgr.init( silent=True )
        self.assertEqual( mgr.get( "my_int", return_type="int" ), 42 )


class TestConstructionPaths( _CfgBase ):
    """Inheritance, defaults, immutable scoping, splainer load on construction."""

    def test_intra_file_inheritance_and_immutables( self ):
        mgr = self._build( block_id="child", debug=True, verbose=True, silent=False )
        # Inherited non-immutable value flows in.
        self.assertEqual( mgr.get( "shared" ), "from_parent" )
        # @_ keys are scrubbed from the child block.
        self.assertFalse( mgr.exists( "@_secret" ) )
        # Default-block keys are layered in.
        self.assertEqual( mgr.get( "common" ), "base_default" )

    def test_file_based_inheritance( self ):
        mgr = self._build( block_id="filechild", debug=False, verbose=True, silent=False )
        self.assertEqual( mgr.get( "file_key" ), "file_value" )
        self.assertEqual( mgr.get( "local" ), "localval" )

    def test_default_block_skips_defaults_and_inheritance( self ):
        mgr = self._build( block_id="default", silent=False )
        self.assertEqual( mgr.get( "common" ), "base_default" )

    def test_inheritance_from_leaf_block( self ):
        # midblock -> leaf (a block with no further 'inherits') exercises the
        # no-inheritance-flag recursion branch with debug+verbose output.
        mgr = self._build( block_id="midblock", debug=True, verbose=True, silent=False )
        self.assertEqual( mgr.get( "leaf_key" ), "leaf_val" )
        self.assertEqual( mgr.get( "mid_key" ), "mid_val" )

    def test_env_var_construction_with_override( self ):
        with patch.object( cm_mod.du, "get_project_root", return_value=self._tmp.name ):
            env_val = "config_path=/main.ini splainer_path=/splainer.ini config_block_id=child extra_key=extra_val"
            with patch.dict( os.environ, { "TEST_CFG_ENV": env_val } ):
                mgr = ConfigurationManager( env_var_name="TEST_CFG_ENV", _reset_singleton=True )
            # The non-path cli_arg became an override on the child block.
            self.assertEqual( mgr.get( "extra_key" ), "extra_val" )
            # config block loaded from the env-resolved path.
            self.assertEqual( mgr.get( "my_int", return_type="int" ), 42 )


class TestAccessors( _CfgBase ):
    """get / exists / set_config / get_keys / in_config + typed retrieval."""

    def setUp( self ):
        super().setUp()
        self.mgr = self._build( block_id="child" )

    def test_exists_true_false_and_none( self ):
        self.assertTrue( self.mgr.exists( "my_int" ) )
        self.assertFalse( self.mgr.exists( "absent_key" ) )
        self.assertFalse( self.mgr.exists( None ) )

    def test_in_config_deprecated( self ):
        self.assertTrue( self.mgr.in_config( "my_int" ) )
        self.assertFalse( self.mgr.in_config( "absent_key" ) )

    def test_set_config_and_get( self ):
        self.mgr.set_config( "new_key", 99 )
        self.assertEqual( self.mgr.get( "new_key" ), "99" )

    def test_get_keys_returns_block_options( self ):
        keys = self.mgr.get_keys()
        self.assertIn( "my_int", keys )

    def test_get_typed_values( self ):
        self.assertEqual( self.mgr.get( "my_int", return_type="int" ), 42 )
        self.assertAlmostEqual( self.mgr.get( "my_float", return_type="float" ), 3.14 )
        self.assertTrue( self.mgr.get( "my_bool", return_type="boolean" ) )
        self.assertEqual( self.mgr.get( "my_list", return_type="list-string" ), [ "a", "b", "c" ] )
        self.assertEqual( self.mgr.get( "my_json", return_type="json" ), { "k": 1 } )
        self.assertEqual( self.mgr.get( "my_dict", return_type="dict" ), { "k": 2 } )

    def test_get_expands_env_vars( self ):
        with patch.dict( os.environ, { "HOME": "/home/test" } ):
            self.assertEqual( self.mgr.get( "expand_me" ), "/home/test/sub" )

    def test_get_missing_with_default_splains( self ):
        self.assertEqual(
            self.mgr.get( "absent_key", default="fallback" ), "fallback"
        )

    def test_get_missing_with_default_silent_skips_splain( self ):
        # silent=True takes the no-splain path to the typed default.
        self.assertEqual(
            self.mgr.get( "absent_key", default="d", silent=True ), "d"
        )

    def test_get_missing_no_default_returns_none( self ):
        self.assertIsNone( self.mgr.get( "absent_key" ) )


class TestTypedValueConversion( _CfgBase ):
    """_get_typed_value() — every return_type branch + invalid."""

    def setUp( self ):
        super().setUp()
        self.mgr = self._build( block_id="child" )

    def test_boolean_from_bool_and_string( self ):
        self.assertTrue( self.mgr._get_typed_value( True, "boolean" ) )
        self.assertTrue( self.mgr._get_typed_value( "True", "boolean" ) )
        self.assertFalse( self.mgr._get_typed_value( "false", "boolean" ) )

    def test_numeric_and_string( self ):
        self.assertEqual( self.mgr._get_typed_value( "7", "int" ), 7 )
        self.assertEqual( self.mgr._get_typed_value( "1.5", "float" ), 1.5 )
        self.assertEqual( self.mgr._get_typed_value( "raw", "string" ), "raw" )

    def test_list_json_dict( self ):
        self.assertEqual( self.mgr._get_typed_value( "x, y", "list-string" ), [ "x", "y" ] )
        self.assertEqual( self.mgr._get_typed_value( '{"a": 1}', "json" ), { "a": 1 } )
        self.assertEqual( self.mgr._get_typed_value( "{'a': 2}", "dict" ), { "a": 2 } )

    def test_invalid_return_type_raises( self ):
        with self.assertRaises( ValueError ):
            self.mgr._get_typed_value( "x", "bogus" )


class TestOverrideAndSplainAndPrint( _CfgBase ):
    """_override_configuration immutability skips, splain_me, print_* methods."""

    def setUp( self ):
        super().setUp()
        self.mgr = self._build( block_id="child" )

    def test_override_skips_immutable_keys( self ):
        # Directly exercise the config_path / config_block_id skip branches.
        self.mgr._override_configuration(
            { "config_path": "x", "config_block_id": "y", "real_key": "real_val" }
        )
        self.assertEqual( self.mgr.get( "real_key" ), "real_val" )

    def test_override_none_and_empty_are_noops( self ):
        # None leaves config untouched.
        before = self.mgr.get( "my_int" )
        self.mgr._override_configuration( None )
        self.assertEqual( self.mgr.get( "my_int" ), before )
        # Empty dict with debug on takes the "Skipping cli_args" branch and
        # likewise leaves the config untouched.
        self.mgr.debug = True
        out = _capture( self.mgr._override_configuration, {} )
        self.assertIn( "Skipping cli_args", out )
        self.assertEqual( self.mgr.get( "my_int" ), before )

    def test_splain_me_found_and_missing( self ):
        # Reassign splainer to a parser carrying the documented key.
        import configparser
        sp = configparser.ConfigParser()
        sp.read_string( _SPLAINER_INI )
        self.mgr.splainer = sp
        found = _capture( self.mgr.splain_me, "my_int" )
        self.assertIn( "'Splainer says", found )
        self.assertIn( "An integer configuration value.", found )
        missing = _capture( self.mgr.splain_me, "undocumented" )
        self.assertIn( "WUH?", missing )
        self.assertIn( "undocumented", missing )

    def test_print_sections_marks_current_block( self ):
        out = _capture( self.mgr.print_sections )
        self.assertIn( "child", out )
        self.assertIn( "* child", out )            # current block flagged with asterisk

    def test_print_configuration_shows_keys_and_values( self ):
        out = _capture(
            self.mgr.print_configuration, brackets=True, include_sections=False
        )
        self.assertIn( "my_int", out )
        self.assertIn( "[42]", out )               # value wrapped in brackets
        # Without brackets the value is bare.
        bare = _capture(
            self.mgr.print_configuration, brackets=False, include_sections=False
        )
        self.assertIn( "my_int", bare )
        self.assertNotIn( "[42]", bare )

    def test_print_configuration_with_prefix_match( self ):
        out = _capture( self.mgr.print_configuration, prefixes=[ "my_" ] )
        self.assertIn( "my_int", out )

    def test_print_configuration_with_prefix_no_match( self ):
        # No key starts with this prefix -> "No configuration keys to print" + return.
        out = _capture( self.mgr.print_configuration, prefixes=[ "zzz_no_match_" ] )
        self.assertIn( "No configuration keys to print", out )


class TestGetRequired( _CfgBase ):
    """get_required() — the loud sibling of get(), for values a caller cannot survive without.

    Row 3e4a4a4a: get() returning None into a caller that concatenates it produced
    'can only concatenate str (not NoneType) to str' with nothing naming the key.
    These tests pin the two things that fix: it RAISES, and the message says which
    key, which block, and which file.
    """

    def setUp( self ):
        super().setUp()
        self.mgr = self._build( block_id="child" )

    def test_present_key_returns_typed_value( self ):
        self.assertEqual( self.mgr.get_required( "my_str" ), "hello" )
        self.assertEqual( self.mgr.get_required( "my_int", return_type="int" ), 42 )
        self.assertTrue( self.mgr.get_required( "my_bool", return_type="boolean" ) )
        self.assertEqual( self.mgr.get_required( "my_list", return_type="list-string" ), [ "a", "b", "c" ] )

    def test_inherited_key_is_resolved_not_raised( self ):
        # Inheritance is why get() cannot simply be made to raise; get_required
        # must see through it the same way get() does.
        self.assertEqual( self.mgr.get_required( "shared" ), "from_parent" )
        self.assertEqual( self.mgr.get_required( "gp_key" ), "gp_val" )

    def test_expands_env_vars_like_get( self ):
        with patch.dict( os.environ, { "HOME": "/home/test" } ):
            self.assertEqual( self.mgr.get_required( "expand_me" ), "/home/test/sub" )

    def test_missing_key_raises_naming_key_block_and_path( self ):
        with self.assertRaises( cm_mod.MissingConfigKeyError ) as ctx:
            _capture( self.mgr.get_required, "absent_key" )
        msg = str( ctx.exception )
        self.assertIn( "absent_key", msg )
        self.assertIn( "child", msg )                    # the resolved block
        self.assertIn( self.config_path, msg )           # where to go fix it
        self.assertIn( "not found", msg )
        self.assertEqual( ctx.exception.key, "absent_key" )
        self.assertEqual( ctx.exception.block_id, "child" )
        self.assertFalse( ctx.exception.blank )

    def test_missing_key_splains_before_raising( self ):
        buf = io.StringIO()
        with redirect_stdout( buf ):
            with self.assertRaises( cm_mod.MissingConfigKeyError ):
                self.mgr.get_required( "absent_key" )
        out = buf.getvalue()
        self.assertIn( "Required key", out )
        self.assertIn( "absent_key", out )

    def test_missing_key_silent_skips_the_banner( self ):
        buf = io.StringIO()
        with redirect_stdout( buf ):
            with self.assertRaises( cm_mod.MissingConfigKeyError ):
                self.mgr.get_required( "absent_key", silent=True )
        self.assertNotIn( "Required key", buf.getvalue() )

    def test_missing_key_mute_splainer_skips_the_banner( self ):
        self.mgr.mute_splainer = True
        buf = io.StringIO()
        with redirect_stdout( buf ):
            with self.assertRaises( cm_mod.MissingConfigKeyError ):
                self.mgr.get_required( "absent_key" )
        self.assertNotIn( "Required key", buf.getvalue() )

    def test_blank_value_raises_as_blank_not_missing( self ):
        # A required key set to nothing is a configuration error. get() hands
        # back "" here, which concatenates without complaint and silently
        # produces a wrong path — the quiet cousin of the None crash.
        self.assertEqual( self.mgr.get( "blank_key" ), "" )
        with self.assertRaises( cm_mod.MissingConfigKeyError ) as ctx:
            _capture( self.mgr.get_required, "blank_key" )
        self.assertTrue( ctx.exception.blank )
        self.assertIn( "empty value", str( ctx.exception ) )

    def test_env_var_expanding_to_whitespace_counts_as_blank( self ):
        with patch.dict( os.environ, { "LUPIN_TEST_BLANK_VAR": "   " } ):
            with self.assertRaises( cm_mod.MissingConfigKeyError ) as ctx:
                _capture( self.mgr.get_required, "expand_blank" )
        self.assertTrue( ctx.exception.blank )

    def test_blank_value_silent_skips_the_banner( self ):
        buf = io.StringIO()
        with redirect_stdout( buf ):
            with self.assertRaises( cm_mod.MissingConfigKeyError ):
                self.mgr.get_required( "blank_key", silent=True )
        self.assertNotIn( "Required key", buf.getvalue() )

    def test_blank_value_mute_splainer_skips_the_banner( self ):
        self.mgr.mute_splainer = True
        buf = io.StringIO()
        with redirect_stdout( buf ):
            with self.assertRaises( cm_mod.MissingConfigKeyError ):
                self.mgr.get_required( "blank_key" )
        self.assertNotIn( "Required key", buf.getvalue() )

    def test_invalid_return_type_still_raises_value_error( self ):
        with self.assertRaises( ValueError ):
            self.mgr.get_required( "my_str", return_type="bogus" )

    def test_get_behaviour_is_unchanged_by_this_row( self ):
        # The whole point of the split: get() keeps returning None, so the call
        # sites that pass a default and the callers that tolerate absence are
        # untouched. Making get() itself raise would turn a key present in
        # Development and absent in Testing-GCS into a hard startup failure.
        self.mgr.mute_splainer = True
        self.assertIsNone( self.mgr.get( "absent_key" ) )
        self.assertEqual( self.mgr.get( "absent_key", default="fallback" ), "fallback" )


if __name__ == "__main__":
    unittest.main()
