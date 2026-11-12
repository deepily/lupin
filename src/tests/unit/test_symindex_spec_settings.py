"""Unit tests for the INI override of IndexSpec in spec_for and tests_spec."""
import pytest

from cosa.config.configuration_manager import ConfigurationManager
from cosa.repo import code_health_settings as chs
from cosa.repo.symindex import spec as sp
from tests.unit.symindex_helpers import make_lupin_repo, make_repo

ARGS = ( "config_path=/src/conf/lupin-app.ini splainer_path=/src/conf/lupin-app-splainer.ini "
         "config_block_id=Lupin:+Development" )


@pytest.fixture
def config( monkeypatch ):
    """The real manager over the real INI; a fresh singleton before and after."""
    monkeypatch.setenv( "LUPIN_CONFIG_MGR_CLI_ARGS", ARGS )
    mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS", _reset_singleton=True )
    yield mgr
    ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS", _reset_singleton=True )


def put( config, kind, value, name="t" ):
    config.set_config( chs.repo_key( name, kind ), value )


def rels( root, paths ):
    return [ p.relative_to( root.resolve() ).as_posix() for p in paths ]


def same_fields( a, b ):
    return ( a.root, a.name, a.py_roots, a.js_roots, a.dart_roots, a.module_base, a.skip_parts, a.scopes ) == \
           ( b.root, b.name, b.py_roots, b.js_roots, b.dart_roots, b.module_base, b.skip_parts, b.scopes )


def test_no_config_and_blank_keys_both_keep_detection( tmp_path, config ):
    """Override absent: the spec is the detected one, with or without a config."""
    root = make_repo( tmp_path )
    assert same_fields( sp.spec_for( root ), sp.detected_spec( root ) )
    assert same_fields( sp.spec_for( root, config, "t" ), sp.detected_spec( root ) )
    assert same_fields( sp.tests_spec( root, config, "t" ), sp.tests_spec( root ) )


def test_the_lupin_ini_values_reproduce_lupins_detection( tmp_path, config ):
    root = make_lupin_repo( tmp_path )
    assert same_fields( sp.spec_for( root, config, "lupin" ), sp.detected_spec( root ) )


def test_the_name_defaults_to_the_directory_name( tmp_path, config ):
    root = make_repo( tmp_path )
    put( config, chs.EXCLUDE_KIND, "vendor", name=root.name )
    assert sp.spec_for( root, config ).skip_parts == frozenset( { "vendor" } )
    ( root / "tests" ).mkdir()
    assert sp.tests_spec( root, config ).skip_parts == frozenset( { "vendor" } )


def test_a_language_list_drops_the_languages_it_leaves_out( tmp_path, config ):
    root = make_repo( tmp_path )
    put( config, chs.LANGUAGES_KIND, "py" )
    spec = sp.spec_for( root, config, "t" )
    assert rels( root, spec.py_roots ) == [ "." ] and spec.js_roots == () and spec.dart_roots == ()
    put( config, chs.LANGUAGES_KIND, "ts" )
    spec = sp.spec_for( root, config, "t" )
    assert spec.py_roots == () and rels( root, spec.js_roots ) == [ "." ]


def test_an_unknown_language_is_refused_naming_the_key_and_the_entry( tmp_path, config ):
    root = make_repo( tmp_path )
    put( config, chs.LANGUAGES_KIND, "py, cobol" )
    with pytest.raises( chs.CodeHealthSettingError, match="external repo t index languages.*cobol" ):
        sp.spec_for( root, config, "t" )


def test_source_dirs_land_only_in_the_roots_of_the_listed_languages( tmp_path, config ):
    root = make_repo( tmp_path )
    ( root / "lib" ).mkdir()
    put( config, chs.SOURCE_DIRS_KIND, "lib" )
    put( config, chs.LANGUAGES_KIND, "py" )
    spec = sp.spec_for( root, config, "t" )
    assert rels( root, spec.py_roots ) == [ "lib" ] and spec.js_roots == () and spec.dart_roots == ()
    put( config, chs.LANGUAGES_KIND, "ts" )
    spec = sp.spec_for( root, config, "t" )
    assert spec.py_roots == () and rels( root, spec.js_roots ) == [ "lib" ] and spec.dart_roots == ()
    put( config, chs.LANGUAGES_KIND, "dart" )
    spec = sp.spec_for( root, config, "t" )
    assert spec.py_roots == () and spec.js_roots == () and rels( root, spec.dart_roots ) == [ "lib" ]


def test_source_dirs_with_blank_languages_use_the_detected_languages( tmp_path, config ):
    root = make_repo( tmp_path )
    ( root / "lib" ).mkdir()
    put( config, chs.SOURCE_DIRS_KIND, "lib" )
    spec = sp.spec_for( root, config, "t" )
    assert rels( root, spec.py_roots ) == [ "lib" ] and rels( root, spec.js_roots ) == [ "lib" ] and spec.dart_roots == ()


def test_source_dirs_on_a_flutter_tree_go_to_dart_when_languages_are_blank( tmp_path, config ):
    root = tmp_path / "app"
    ( root / "lib" ).mkdir( parents=True )
    ( root / "pubspec.yaml" ).write_text( "name: app\n", encoding="utf-8" )
    ( root / "extra" ).mkdir()
    put( config, chs.SOURCE_DIRS_KIND, "extra" )
    spec = sp.spec_for( root, config, "t" )
    assert spec.py_roots == () and spec.js_roots == () and rels( root, spec.dart_roots ) == [ "extra" ]


def test_a_source_dir_that_does_not_exist_is_refused_naming_the_key( tmp_path, config ):
    root = make_repo( tmp_path )
    put( config, chs.SOURCE_DIRS_KIND, "nowhere" )
    with pytest.raises( chs.CodeHealthSettingError, match="external repo t index source dirs.*nowhere" ):
        sp.spec_for( root, config, "t" )


def test_an_absolute_source_dir_is_refused_by_the_reader( tmp_path, config ):
    put( config, chs.SOURCE_DIRS_KIND, "/etc" )
    with pytest.raises( chs.CodeHealthSettingError, match="external repo t index source dirs" ):
        sp.spec_for( make_repo( tmp_path ), config, "t" )


def test_exclude_names_replace_the_skip_set_and_a_blank_key_keeps_it( tmp_path, config ):
    root = make_repo( tmp_path )
    assert sp.spec_for( root, config, "t" ).skip_parts == sp.SKIP_PARTS
    put( config, chs.EXCLUDE_KIND, "rnd, generated" )
    assert sp.spec_for( root, config, "t" ).skip_parts == frozenset( { "rnd", "generated" } )


def test_an_exclude_path_is_refused_and_a_bare_name_is_accepted( tmp_path, config ):
    root = make_repo( tmp_path )
    put( config, chs.EXCLUDE_KIND, "src/rnd" )
    with pytest.raises( chs.CodeHealthSettingError, match="external repo t index exclude.*src/rnd" ):
        sp.spec_for( root, config, "t" )
    with pytest.raises( chs.CodeHealthSettingError, match="external repo t index exclude" ):
        sp.tests_spec( root, config, "t" )
    put( config, chs.EXCLUDE_KIND, "rnd" )
    assert sp.spec_for( root, config, "t" ).skip_parts == frozenset( { "rnd" } )


def test_test_dirs_replace_the_detected_test_roots( tmp_path, config ):
    root = make_repo( tmp_path )
    ( root / "tests" ).mkdir()
    ( root / "checks" ).mkdir()
    assert rels( root, sp.tests_spec( root, config, "t" ).py_roots ) == [ "tests" ]
    put( config, chs.TEST_DIRS_KIND, "checks" )
    spec = sp.tests_spec( root, config, "t" )
    assert rels( root, spec.py_roots ) == [ "checks" ] and spec.js_roots == spec.py_roots and spec.scopes == ( "test", )


def test_exclude_never_hides_the_tests_directory_from_the_tests_spec( tmp_path, config ):
    root = make_repo( tmp_path )
    put( config, chs.EXCLUDE_KIND, "tests, vendor" )
    assert sp.tests_spec( root, config, "t" ).skip_parts == frozenset( { "vendor" } )
    assert sp.spec_for( root, config, "t" ).skip_parts == frozenset( { "tests", "vendor" } )


def test_a_test_dir_that_does_not_exist_is_refused_naming_the_key( tmp_path, config ):
    root = make_repo( tmp_path )
    put( config, chs.TEST_DIRS_KIND, "nowhere" )
    with pytest.raises( chs.CodeHealthSettingError, match="external repo t index test dirs.*nowhere" ):
        sp.tests_spec( root, config, "t" )
