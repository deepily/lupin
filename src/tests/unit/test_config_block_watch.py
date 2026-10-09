"""
The collection guard that names a test file which changes the config block variable.

The watch is plain data, tested directly. The root conftest wires it to pytest's collection hooks,
and that wiring is tested through the loaded conftest module with a fake session.
"""

import os
import sys
from types import SimpleNamespace

import pytest

from tests.helpers.config_block_watch import ConfigBlockWatch, unit_dir_of

DEV   = "config_block_id=Lupin:+Development"
TEST  = "config_block_id=Lupin:+Testing"
UNIT  = unit_dir_of( "/repo/src/tests" )


def _conftest():
    found = [ m for m in sys.modules.values() if getattr( m, "__file__", "" ) and m.__file__.replace( "\\", "/" ).endswith( "src/tests/conftest.py" ) ]
    assert len( found ) == 1, f"expected the one root conftest, found {len( found )}"
    return found[ 0 ]


def test_unit_dir_ends_with_a_separator_so_a_sibling_folder_does_not_match():
    assert UNIT == "/repo/src/tests/unit" + os.sep
    assert not "/repo/src/tests/unit_other/test_x.py".startswith( UNIT )


def test_a_run_where_nothing_changed_the_variable_has_no_verdict():
    watch = ConfigBlockWatch( DEV )
    watch.note( "a.py", DEV )
    watch.note( "b.py", DEV )
    assert watch.offenders == [ ] and watch.verdict( [ UNIT + "a.py" ], UNIT ) is None


def test_the_first_file_that_changed_it_is_named_and_a_later_file_is_not_blamed_for_the_same_value():
    watch = ConfigBlockWatch( DEV )
    watch.note( "good.py", DEV )
    watch.note( "leaker.py", TEST )
    watch.note( "after.py", TEST )
    assert watch.offenders == [ "leaker.py" ]
    message = watch.verdict( [ UNIT + "a.py" ], UNIT )
    assert "leaker.py" in message and "after.py" not in message and DEV in message and TEST in message


def test_a_file_that_changes_it_back_and_a_second_file_that_changes_it_are_both_named():
    watch = ConfigBlockWatch( DEV )
    for name, value in ( ( "one.py", TEST ), ( "two.py", DEV ), ( "three.py", TEST ) ): watch.note( name, value )
    assert watch.offenders == [ "one.py", "two.py", "three.py" ]


def test_a_variable_that_was_unset_and_is_then_set_counts_as_a_change():
    watch = ConfigBlockWatch( None )
    watch.note( "leaker.py", TEST )
    assert watch.offenders == [ "leaker.py" ]


@pytest.mark.parametrize( "paths", [ [ ], [ UNIT + "a.py", "/repo/src/tests/integration/b.py" ], [ "/repo/src/tests/e2e_ui/c.py" ] ] )
def test_no_verdict_for_an_empty_run_or_a_run_that_reaches_outside_the_unit_folder( paths ):
    watch = ConfigBlockWatch( DEV )
    watch.note( "leaker.py", TEST )
    assert watch.verdict( paths, UNIT ) is None


def test_the_root_conftest_refuses_a_unit_run_whose_collection_changed_the_variable( monkeypatch ):
    conftest = _conftest()
    unit_dir = unit_dir_of( os.path.dirname( os.path.abspath( conftest.__file__ ) ) )
    watch    = ConfigBlockWatch( DEV )
    watch.note( "src/tests/unit/leaker.py", TEST )
    monkeypatch.setattr( conftest, "_config_block_watch", watch )
    with pytest.raises( pytest.UsageError, match="leaker.py" ):
        conftest.pytest_collection_finish( SimpleNamespace( items=[ SimpleNamespace( fspath=unit_dir + "x.py" ) ] ) )


def test_the_root_conftest_lets_a_clean_run_through( monkeypatch ):
    conftest = _conftest()
    monkeypatch.setattr( conftest, "_config_block_watch", ConfigBlockWatch( DEV ) )
    assert conftest.pytest_collection_finish( SimpleNamespace( items=[ ] ) ) is None


def test_the_hook_notes_the_current_value_after_a_collector_runs( monkeypatch ):
    conftest = _conftest()
    watch = ConfigBlockWatch( DEV )
    monkeypatch.setattr( conftest, "_config_block_watch", watch )
    monkeypatch.setenv( "LUPIN_CONFIG_MGR_CLI_ARGS", TEST )
    hook = conftest.pytest_make_collect_report( SimpleNamespace( nodeid="src/tests/unit/leaker.py" ) )
    next( hook )
    with pytest.raises( StopIteration ): next( hook )
    assert watch.offenders == [ "src/tests/unit/leaker.py" ]
