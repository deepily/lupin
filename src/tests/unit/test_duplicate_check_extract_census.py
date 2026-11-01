"""Census guard: every script file of the web client extracts whole, with its account closed."""
import pathlib
import subprocess

import pytest

import cosa.utils.util as cu
from cosa.repo.semdup import errors as err
from cosa.repo.semdup import extract as ex

CLIENT_DIR = "src/lupin_app/static/js"
EXCLUDED   = ( ".d.ts", ".min.js" )


def client_files():
    """List the tracked script files of the web client, as git names them."""
    root = cu.get_project_root()
    out  = subprocess.run( [ "git", "ls-files", "--", CLIENT_DIR ], cwd=root, capture_output=True, text=True, check=True ).stdout.split()
    return [ pathlib.Path( root ) / f for f in out if f.endswith( ex.SCRIPT_SUFFIXES ) and not f.endswith( EXCLUDED ) ]


def test_the_census_population_is_the_clients_script_files_and_it_is_not_small():
    files = client_files()
    assert len( files ) > 150 and any( f.name == "notifications.js" for f in files )


def test_every_client_script_file_parses_and_its_account_closes():
    files  = client_files()
    report = ex.extract_tree( cu.get_project_root(), files, "server" )
    assert report[ "skipped_script" ] == []
    assert len( report[ "script_accounts" ] ) == len( files )                         # the compiler read every file git lists
    assert sum( a[ "reported" ] for a in report[ "script_accounts" ] ) == len( report[ "definitions" ] ) + len( report[ "repeated_ids" ] )
    assert len( report[ "definitions" ] ) > 1000
    ex.completeness( report )


def test_the_census_goes_red_when_one_file_does_not_parse(tmp_path):
    root = tmp_path / "tree"
    root.mkdir()
    ( root / "ok.ts" ).write_text( "export function ok() { return 1; }\n", encoding="utf-8" )
    ( root / "broken.ts" ).write_text( "export function ( {{{\n", encoding="utf-8" )
    report = ex.extract_tree( root, [ root / "ok.ts", root / "broken.ts" ], "server" )
    assert report[ "skipped_script" ] == [ "broken.ts" ]
    with pytest.raises( err.SemdupError ) as caught:
        ex.completeness( report )
    assert caught.value.code == err.EXTRACT_INCOMPLETE
