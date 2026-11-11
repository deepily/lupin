"""Unit tests for the code-health settings reader, through the real ConfigurationManager."""
import pytest

import cosa.utils.util as cu
from cosa.rest.job_registry import load_registry
from cosa.config.configuration_manager import ConfigurationManager
from cosa.repo import code_health_settings as chs

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


def test_repo_key_follows_the_external_repo_pattern():
    assert chs.repo_key( "lupin", chs.CEILING_KIND ) == "external repo lupin duplicate check ceiling"


def test_the_real_ini_yields_lupins_values( config ):
    """Field by field against the table's defaults."""
    assert chs.repo_settings( config, "lupin" ) == { "index_languages": [], "index_source_dirs": [], "index_test_dirs": [], "index_exclude": [],
                                                      "wiki_dir": None, "filed_title_prefix": "[LUPIN]" }
    assert chs.duplicate_check_ceiling( config, "lupin" ) == 800
    assert chs.jev_token_limit( config, "lupin" ) == 1428571428
    assert chs.data_subdir( config ) == "code-health"


def test_a_repo_with_no_keys_gets_defaults_and_detection( config ):
    """Missing keys give the default or the blank detection answer."""
    assert chs.repo_settings( config, "none-such" ) == { "index_languages": [], "index_source_dirs": [], "index_test_dirs": [], "index_exclude": [],
                                                          "wiki_dir": None, "filed_title_prefix": "[NONE-SUCH]" }


def test_the_data_subdir_defaults_when_the_key_is_gone( config ):
    config.set_config( chs.DATA_SUBDIR_KEY, "" )
    assert chs.data_subdir( config ) == "code-health"
    config.set_config( chs.DATA_SUBDIR_KEY, "elsewhere" )
    assert chs.data_subdir( config ) == "elsewhere"


def test_values_are_read_stripped_and_split( config ):
    put( config, chs.LANGUAGES_KIND, " py, ts ,dart " )
    put( config, chs.SOURCE_DIRS_KIND, "src/a, lib" )
    put( config, chs.TEST_DIRS_KIND, "tests" )
    put( config, chs.EXCLUDE_KIND, "vendor, build" )
    put( config, chs.WIKI_DIR_KIND, "docs/wiki" )
    put( config, chs.TITLE_KIND, "[T]" )
    assert chs.repo_settings( config, "t" ) == { "index_languages": [ "py", "ts", "dart" ], "index_source_dirs": [ "src/a", "lib" ], "index_test_dirs": [ "tests" ],
                                                  "index_exclude": [ "vendor", "build" ], "wiki_dir": "docs/wiki", "filed_title_prefix": "[T]" }


@pytest.mark.parametrize( "func", [ chs.duplicate_check_ceiling, chs.jev_token_limit ] )
def test_a_numeric_key_with_no_value_is_refused_naming_the_key( config, func ):
    """No code default for the ceiling or the Jev limit."""
    with pytest.raises( chs.CodeHealthSettingError, match="external repo none-such" ):
        func( config, "none-such" )


@pytest.mark.parametrize( "kind,func", [ ( chs.CEILING_KIND, chs.duplicate_check_ceiling ), ( chs.JEV_LIMIT_KIND, chs.jev_token_limit ) ] )
@pytest.mark.parametrize( "bad", [ "0", "-5", "12.5", "abc", "" ] )
def test_a_bad_number_fails_loud_and_names_the_key( config, kind, func, bad ):
    """Zero, negative, not a whole number, blank."""
    put( config, kind, bad )
    with pytest.raises( chs.CodeHealthSettingError, match=chs.repo_key( "t", kind ) ):
        func( config, "t" )


def test_a_good_number_is_returned_as_an_int( config ):
    put( config, chs.CEILING_KIND, "7" )
    assert chs.duplicate_check_ceiling( config, "t" ) == 7


def test_a_language_outside_the_three_is_refused( config ):
    put( config, chs.LANGUAGES_KIND, "py, rust" )
    with pytest.raises( chs.CodeHealthSettingError, match="index languages" ):
        chs.index_languages( config, "t" )


@pytest.mark.parametrize( "kind", [ chs.SOURCE_DIRS_KIND, chs.TEST_DIRS_KIND ] )
@pytest.mark.parametrize( "bad", [ "/abs/path", "src/../x" ] )
def test_an_absolute_or_climbing_dir_is_refused( config, kind, bad ):
    """Refusal test."""
    put( config, kind, f"ok, {bad}" )
    with pytest.raises( chs.CodeHealthSettingError, match=chs.repo_key( "t", kind ) ):
        chs.relative_paths( config, "t", kind )


@pytest.mark.parametrize( "bad", [ "/abs/wiki", "../wiki" ] )
def test_an_absolute_or_climbing_wiki_dir_is_refused( config, bad ):
    """Refusal test."""
    put( config, chs.WIKI_DIR_KIND, bad )
    with pytest.raises( chs.CodeHealthSettingError, match="wiki dir" ):
        chs.wiki_dir( config, "t" )


@pytest.mark.parametrize( "bad", [ "a/b", "a\\b" ] )
def test_a_path_in_the_exclude_list_is_refused( config, bad ):
    """Refusal test."""
    put( config, chs.EXCLUDE_KIND, f"ok, {bad}" )
    with pytest.raises( chs.CodeHealthSettingError, match="index exclude" ):
        chs.index_exclude( config, "t" )


@pytest.mark.parametrize( "bad", [ "a/b", "a\\b", ".", ".." ] )
def test_a_data_subdir_that_is_a_path_is_refused( config, bad ):
    config.set_config( chs.DATA_SUBDIR_KEY, bad )
    with pytest.raises( chs.CodeHealthSettingError, match="code health data subdir" ):
        chs.data_subdir( config )


def test_the_registry_has_lupin_and_a_job_with_a_repo_key_counts():
    assert chs.registry_repo_names( load_registry( cu.get_project_root() ) ) == [ "lupin" ]
    assert chs.registry_repo_names( { "jobs": [ { "id": 1 }, { "repo": "other" } ] } ) == [ "lupin", "other" ]


def test_name_matches_the_checkout_directory_for_lupin_and_a_mismatch_is_caught():
    """The real name matches; a name that differs from its directory is reported."""
    assert chs.name_mismatches( { "lupin": cu.get_project_root() } ) == []
    assert chs.name_mismatches( { "par-pacific": "/nowhere/par-pacific-financials-er-442109" } ) == [ "par-pacific" ]
