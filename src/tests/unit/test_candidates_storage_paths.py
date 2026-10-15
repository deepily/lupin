"""
Unit tests for the candidate stage's storage keys and for data_dir's use of one.

Every key comes from the INI file or its override variable. A missing key is a named error.
The INI is read for real in two tests. One uses the registered command's arguments.
The other compares data_dir with the path the unchanged code returned.
"""
import pathlib
import re

import pytest

from cosa.repo.symindex import paths
from cosa.repo.symindex.candidates import storage_paths as sp
from cosa.repo.symindex.candidates.errors import CandidateError, STORAGE_KEY_MISSING, DEPENDENCY_MISSING

CONFIG_ARGS = "config_path=/src/conf/lupin-app.ini splainer_path=/src/conf/lupin-app-splainer.ini config_block_id=Lupin:+Development"


class FakeConfig:
    """A config manager that answers from a dict and returns None for an absent key."""

    def __init__( self, values ): self.values = values

    def get( self, key, default=None, silent=False, return_type="string" ):
        return self.values.get( key, default )


FULL = {
    "reuse review data subdir"             : "rr",
    "reuse candidate vectors subdir"       : "vec",
    "reuse candidate query cache subdir"   : "qc",
    "reuse candidate purpose lines subdir" : "pl",
    "reuse candidate search interpreter"   : ""
}


def test_data_subdir_reads_the_ini_value():
    assert sp.data_subdir( FakeConfig( FULL ), {} ) == "rr"


def test_data_subdir_override_variable_beats_the_ini():
    assert sp.data_subdir( FakeConfig( FULL ), { "LUPIN_REUSE_REVIEW_DATA_SUBDIR": " other " } ) == "other"


def test_blank_override_is_ignored():
    assert sp.data_subdir( FakeConfig( FULL ), { "LUPIN_REUSE_REVIEW_DATA_SUBDIR": "   " } ) == "rr"


@pytest.mark.parametrize( "name, key", [
    ( "vectors",     "reuse candidate vectors subdir" ),
    ( "query_cache", "reuse candidate query cache subdir" ),
    ( "purpose",     "reuse candidate purpose lines subdir" )
] )
def test_candidate_dir_is_relative_to_the_data_directory( name, key ):
    d = sp.candidate_dir( name, "/data/root", FakeConfig( FULL ), {} )
    assert d == pathlib.Path( "/data/root" ) / FULL[ key ]


@pytest.mark.parametrize( "name, var", [
    ( "vectors",     "LUPIN_REUSE_CANDIDATE_VECTORS_DIR" ),
    ( "query_cache", "LUPIN_REUSE_CANDIDATE_QUERY_CACHE_DIR" ),
    ( "purpose",     "LUPIN_REUSE_CANDIDATE_PURPOSE_DIR" )
] )
def test_candidate_dir_override_is_an_absolute_path_that_wins( name, var ):
    d = sp.candidate_dir( name, "/data/root", FakeConfig( FULL ), { var: "/elsewhere/x" } )
    assert d == pathlib.Path( "/elsewhere/x" )


def test_candidate_dir_refuses_a_relative_override():
    with pytest.raises( CandidateError ) as e:
        sp.candidate_dir( "vectors", "/data/root", FakeConfig( FULL ), { "LUPIN_REUSE_CANDIDATE_VECTORS_DIR": "rel/x" } )
    assert e.value.code == STORAGE_KEY_MISSING
    assert "absolute" in e.value.detail


@pytest.mark.parametrize( "missing", [ "absent", "empty" ] )
def test_missing_or_empty_key_is_storage_key_missing( missing ):
    values = dict( FULL )
    if missing == "absent": del values[ "reuse candidate vectors subdir" ]
    else: values[ "reuse candidate vectors subdir" ] = "  "
    with pytest.raises( CandidateError ) as e:
        sp.candidate_dir( "vectors", "/d", FakeConfig( values ), {} )
    assert e.value.code == STORAGE_KEY_MISSING
    assert "reuse candidate vectors subdir" in e.value.detail


def test_interpreter_with_no_value_is_dependency_missing():
    with pytest.raises( CandidateError ) as e:
        sp.search_interpreter( FakeConfig( FULL ), {} )
    assert e.value.code == DEPENDENCY_MISSING


def test_interpreter_that_is_not_a_file_is_dependency_missing( tmp_path ):
    with pytest.raises( CandidateError ) as e:
        sp.search_interpreter( FakeConfig( FULL ), { "LUPIN_REUSE_CANDIDATE_INTERPRETER": str( tmp_path / "nope" ) } )
    assert e.value.code == DEPENDENCY_MISSING
    assert "not a file" in e.value.detail


def test_interpreter_that_is_a_file_is_returned( tmp_path ):
    py = tmp_path / "python"
    py.write_text( "" )
    assert sp.search_interpreter( FakeConfig( FULL ), { "LUPIN_REUSE_CANDIDATE_INTERPRETER": str( py ) } ) == str( py )


def test_interpreter_can_come_from_the_ini( tmp_path ):
    py = tmp_path / "python"
    py.write_text( "" )
    values = { **FULL, "reuse candidate search interpreter": str( py ) }
    assert sp.search_interpreter( FakeConfig( values ), {} ) == str( py )


def test_module_default_environ_is_os_environ( monkeypatch ):
    monkeypatch.setenv( "LUPIN_REUSE_REVIEW_DATA_SUBDIR", "from-os-environ" )
    assert sp.data_subdir( FakeConfig( FULL ) ) == "from-os-environ"
    monkeypatch.setenv( "LUPIN_REUSE_CANDIDATE_VECTORS_DIR", "/abs/vec" )
    assert sp.candidate_dir( "vectors", "/d", FakeConfig( FULL ) ) == pathlib.Path( "/abs/vec" )
    monkeypatch.setenv( "LUPIN_REUSE_CANDIDATE_INTERPRETER", "/no/such/file" )
    with pytest.raises( CandidateError, match="not a file" ):
        sp.search_interpreter( FakeConfig( FULL ) )


def test_build_config_failure_is_dependency_missing( monkeypatch ):
    import cosa.config.configuration_manager as cm

    def boom( *args, **kwargs ): raise RuntimeError( "no env var" )

    monkeypatch.setattr( cm, "ConfigurationManager", boom )
    with pytest.raises( CandidateError ) as e:
        sp.build_config()
    assert e.value.code == DEPENDENCY_MISSING
    assert "no env var" in e.value.detail


def test_config_is_built_when_none_is_given( monkeypatch ):
    monkeypatch.setattr( sp, "build_config", lambda: FakeConfig( FULL ) )
    assert sp.data_subdir( environ={} ) == "rr"


# ── the real INI, through the registered command's arguments ────────────────


@pytest.fixture
def real_config( monkeypatch ):
    monkeypatch.setenv( sp.CONFIG_ENV_VAR, CONFIG_ARGS )
    from cosa.config.configuration_manager import ConfigurationManager
    return ConfigurationManager( env_var_name=sp.CONFIG_ENV_VAR, _reset_singleton=True )


def test_the_registered_command_arguments_read_all_five_keys( real_config ):
    values = { name: real_config.get( ini_key, silent=True ) for name, ( ini_key, _ ) in sp.KEYS.items() }
    assert values == { "data_subdir": "reuse-review", "vectors": "vectors", "query_cache": "query-cache",
                       "purpose": "purpose-lines", "interpreter": "" }


def test_every_key_is_in_both_ini_files():
    root = pathlib.Path( __file__ ).resolve().parents[ 2 ] / "conf"
    for fname in ( "lupin-app.ini", "lupin-app-splainer.ini" ):
        text = ( root / fname ).read_text( encoding="utf-8" )
        for ini_key, _ in sp.KEYS.values():
            assert re.search( rf"^{re.escape( ini_key )}\s*=", text, re.M ), f"{ini_key} is not in {fname}"


def test_data_dir_with_the_default_key_is_the_path_the_unchanged_code_returned( real_config, tmp_path ):
    from lupin_cli.claude_code.hooks.lib.heartbeat_hold import fleet_data_root
    expected = pathlib.Path( fleet_data_root( tmp_path ) ) / "reuse-review"
    assert paths.data_dir( tmp_path ) == expected


def test_data_dir_follows_the_override_variable( real_config, tmp_path, monkeypatch ):
    from lupin_cli.claude_code.hooks.lib.heartbeat_hold import fleet_data_root
    monkeypatch.setenv( "LUPIN_REUSE_REVIEW_DATA_SUBDIR", "elsewhere" )
    assert paths.data_dir( tmp_path ) == pathlib.Path( fleet_data_root( tmp_path ) ) / "elsewhere"


def test_no_storage_literal_in_the_candidates_package_or_paths():
    src    = pathlib.Path( __file__ ).resolve().parents[ 2 ] / "cosa" / "repo" / "symindex"
    files  = sorted( ( src / "candidates" ).glob( "*.py" ) ) + [ src / "paths.py", src / "candidate_build.py" ]
    assert len( files ) >= 8
    # the key defaults live in the INI files, so no code line names one of the hyphenated folders
    literal = re.compile( r"""["'/](?:reuse-review|query-cache|purpose-lines)\b""" )
    for f in files:
        code = [ l for l in f.read_text( encoding="utf-8" ).splitlines() if not l.lstrip().startswith( "#" ) ]
        hits = [ l for l in code if literal.search( l ) ]
        assert hits == [], f"{f.name} names a storage folder in code: {hits}"


def test_default_out_dir_of_a_lupin_tree_is_inside_the_tree( monkeypatch, tmp_path ):
    monkeypatch.setattr( paths, "is_lupin_tree", lambda root: True )
    assert paths.default_out_dir( tmp_path ) == tmp_path / "src" / "docs" / "index"


def test_default_out_dir_of_another_repo_is_under_the_data_directory( monkeypatch, tmp_path ):
    monkeypatch.setattr( paths, "is_lupin_tree", lambda root: False )
    monkeypatch.setattr( paths, "data_dir", lambda root: tmp_path / "data" )
    assert paths.default_out_dir( tmp_path / "lupin-mobile" ) == tmp_path / "data" / "index" / "lupin-mobile"
