"""
The census selection helper and its runner: what is picked, and what refuses.

The helper picks whole files by name, and each test_every_* function in every other file.
The runner cases use a scratch git tree holding the real runner, resolver and helper.
"""

import io
import os
import shutil
import subprocess
import warnings

import pytest

import cosa.utils.util as cu
from tests.helpers import census_selection as cs

PROJECT_ROOT = cu.get_project_root()
VENV         = os.path.join( PROJECT_ROOT, ".venv" )
RUNNER_FILES = ( "src/tests/run-census-guards.sh", "src/scripts/lib/resolve-venv-pytest.sh", "src/tests/__init__.py", "src/tests/helpers/__init__.py", "src/tests/helpers/census_selection.py" )

SOURCE = '''
import pytest


def test_every_module_level_guard(): pass
def test_other_module_level(): pass
async def test_every_async_guard(): pass


class TestHolder:
    def test_every_method_guard( self ): pass
    def test_other_method( self ): pass

    class TestInner:
        def test_every_inner_guard( self ): pass


if True:
    def test_every_guard_under_an_if(): pass
else:
    def test_every_guard_under_an_else(): pass

try:
    pass
except ImportError:
    def test_every_guard_in_a_handler(): pass
finally:
    def test_every_guard_in_a_finally(): pass

with scratch():
    def test_every_guard_in_a_with(): pass

for _ in ():
    def test_every_guard_in_a_for(): pass

while False:
    def test_every_guard_in_a_while(): pass


def test_outer():
    def test_every_nested_in_a_function(): pass


def test_every_module_level_guard(): pass
'''


@pytest.mark.parametrize( "path, picked", [
    ( "src/tests/unit/test_every_thing.py",              True ),
    ( "src/tests/unit/test_the_census.py",               True ),
    ( "src/tests/unit/deploy/test_x_pins.py",            True ),
    ( "src/tests/unit/test_x_pinned_y.py",               True ),
    ( "src/tests/unit/test_a_pin.py",                    True ),
    ( "src/tests/unit/test_xpins.py",                    True ),      # pins without a _pin before it
    ( "src/tests/unit/test_foopinned.py",                True ),      # pinned without a _pin before it
    ( "src/tests/unit/test_ordinary.py",                 False ),
    ( "src/tests/unit/test_every.py",                    False ),     # the rule asks for test_every_, with its underscore
    ( "src/tests/unit/helper_census.py",                 False ),     # not a test_ file
    ( "src/tests/unit/attest_census.py",                 False ),     # test_ must start the file name
    ( "src/tests/unit/test_census_notes.txt",            False ) ] )
def test_a_file_is_picked_by_name_for_the_names_the_old_rule_picked( path, picked ):
    assert cs.picked_by_name( path ) is picked


def test_guard_ids_lists_each_test_every_function_through_classes_and_compound_statements_once():
    ids = cs.guard_ids( "t.py", SOURCE )
    assert ids == [ "t.py::test_every_module_level_guard", "t.py::test_every_async_guard", "t.py::TestHolder::test_every_method_guard",
                    "t.py::TestHolder::TestInner::test_every_inner_guard", "t.py::test_every_guard_under_an_if", "t.py::test_every_guard_under_an_else", "t.py::test_every_guard_in_a_handler",
                    "t.py::test_every_guard_in_a_finally", "t.py::test_every_guard_in_a_with", "t.py::test_every_guard_in_a_for", "t.py::test_every_guard_in_a_while" ]


def test_guard_ids_of_a_file_with_none_is_empty_and_a_syntax_warning_is_not_printed():
    with warnings.catch_warnings( record=True ) as seen:
        warnings.simplefilter( "always" )
        assert cs.guard_ids( "t.py", "def test_a():\n    return '\\s'\n" ) == []
    assert [ w for w in seen if issubclass( w.category, SyntaxWarning ) ] == []


def test_guard_ids_raises_for_source_that_does_not_parse():
    with pytest.raises( SyntaxError ): cs.guard_ids( "t.py", "def test_every_(:\n" )


def test_select_runs_a_name_picked_file_whole_without_reading_it_and_picks_functions_from_the_rest():
    read = []

    def fake( path ):
        read.append( path )
        return SOURCE

    chosen = cs.select( [ "src/tests/unit/test_b.py", "src/tests/unit/test_the_census.py", "src/tests/unit/notes.txt", "src/tests/unit/test_a.py" ], fake )
    assert chosen[ 0 ] == "src/tests/unit/test_a.py::test_every_module_level_guard"
    assert "src/tests/unit/test_the_census.py" in chosen and not any( c.startswith( "src/tests/unit/test_the_census.py::" ) for c in chosen )
    assert read == [ "src/tests/unit/test_a.py", "src/tests/unit/test_b.py" ] and not any( "notes.txt" in c for c in chosen )
    assert chosen.index( "src/tests/unit/test_a.py::test_every_module_level_guard" ) < chosen.index( "src/tests/unit/test_b.py::test_every_module_level_guard" )


def test_main_prints_the_selection_and_returns_zero():
    out = io.StringIO()
    assert cs.main( io.StringIO( "src/tests/unit/test_a.py\n\nsrc/tests/unit/test_x_census.py\n" ), out, io.StringIO(), read=lambda path: SOURCE ) == 0
    assert out.getvalue().splitlines()[ -1 ] == "src/tests/unit/test_x_census.py" and "src/tests/unit/test_a.py::TestHolder::test_every_method_guard" in out.getvalue()


@pytest.mark.parametrize( "failure", [ SyntaxError( "bad" ), FileNotFoundError( "gone" ), UnicodeDecodeError( "utf-8", b"\xff", 0, 1, "bad byte" ) ] )
def test_main_refuses_with_two_and_names_the_file_when_one_cannot_be_read( failure ):
    def read( path ):
        if path.endswith( "test_bad.py" ): raise failure
        return SOURCE

    out, err = io.StringIO(), io.StringIO()
    assert cs.main( io.StringIO( "src/tests/unit/test_a.py\nsrc/tests/unit/test_bad.py\n" ), out, err, read=read ) == 2
    assert out.getvalue() == "" and "src/tests/unit/test_bad.py" in err.getvalue()


def test_main_reads_the_files_from_disk_by_default( tmp_path, monkeypatch ):
    ( tmp_path / "test_here.py" ).write_text( "def test_every_here(): pass\n", encoding="utf-8" )
    monkeypatch.chdir( tmp_path )
    out = io.StringIO()
    assert cs.main( io.StringIO( "test_here.py\n" ), out, io.StringIO() ) == 0 and out.getvalue().strip() == "test_here.py::test_every_here"


# ---- the runner, in a scratch git tree ---------------------------------------------------------------------------

@pytest.fixture
def tree( tmp_path ):
    """A scratch git tree holding the real runner, resolver and helper, and this tree's venv."""
    subprocess.run( [ "git", "init", "-q" ], cwd=tmp_path, check=True, capture_output=True )
    for rel in RUNNER_FILES:
        ( tmp_path / rel ).parent.mkdir( parents=True, exist_ok=True )
        shutil.copy( os.path.join( PROJECT_ROOT, rel ), tmp_path / rel )
    if os.path.isdir( VENV ): os.symlink( VENV, tmp_path / ".venv" )
    return tmp_path


def add( tree, rel, text ):
    """Write a tracked file in the scratch tree."""
    ( tree / rel ).parent.mkdir( parents=True, exist_ok=True )
    ( tree / rel ).write_text( text, encoding="utf-8" )
    subprocess.run( [ "git", "add", rel ], cwd=tree, check=True, capture_output=True )


def runner( tree, *args ):
    """Run the runner copy; one that does not stop at --list fails in 30 seconds."""
    try:
        done = subprocess.run( [ "bash", str( tree / "src" / "tests" / "run-census-guards.sh" ), *args ], capture_output=True, text=True, timeout=30 )
    except subprocess.TimeoutExpired:
        pytest.fail( "the runner did not stop at --list" )
    return done.returncode, done.stdout, done.stderr


def test_the_runner_lists_a_named_file_whole_and_a_guard_function_in_an_ordinary_file_by_node_id( tree ):
    add( tree, "src/tests/unit/test_the_census.py", "def test_a(): pass\n" )
    add( tree, "src/tests/unit/test_ordinary.py", "def test_x(): pass\n\n\nclass TestK:\n    def test_every_kind( self ): pass\n" )
    add( tree, "src/tests/unit/test_nothing_here.py", "def test_y(): pass\n" )
    code, out, err = runner( tree, "--list" )
    assert code == 0, err
    assert out.splitlines() == [ "src/tests/unit/test_ordinary.py::TestK::test_every_kind", "src/tests/unit/test_the_census.py" ]


def test_the_runner_refuses_with_two_when_the_selection_cannot_read_a_file( tree ):
    add( tree, "src/tests/unit/test_the_census.py", "def test_a(): pass\n" )
    add( tree, "src/tests/unit/test_broken.py", "def test_every_(:\n" )
    code, out, err = runner( tree, "--list" )
    assert code == 2 and out == "" and "test_broken.py" in err and "could not read a file; refusing" in err


def test_the_runner_refuses_with_two_when_nothing_is_selected( tree ):
    add( tree, "src/tests/unit/test_nothing_here.py", "def test_y(): pass\n" )
    code, out, err = runner( tree, "--list" )
    assert code == 2 and "found nothing" in err
