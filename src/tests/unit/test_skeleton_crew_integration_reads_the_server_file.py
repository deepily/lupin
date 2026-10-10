"""
The skeleton crew switch integration test names the file the server reads.

The suite's autouse isolation fixture points LUPIN_SKELETON_CREW_INI at an off file for every test.
Reading the variable inside a test therefore returned that file, and all six tests errored at setup.

These tests pin the fix: the path is taken when the module is imported, before any fixture runs.

Venue: :7999 (unit, no server).
"""

import importlib.util
import os

import cosa.utils.util as cu

ENV  = "LUPIN_SKELETON_CREW_INI"
PATH = os.path.join( "src", "tests", "integration", "test_skeleton_crew_switch_integration.py" )


def _load_module( monkeypatch, launched ):
    monkeypatch.setenv( ENV, launched )
    spec   = importlib.util.spec_from_file_location( "skeleton_crew_switch_integration_under_test",
                                                     os.path.join( cu.get_project_root(), PATH ) )
    module = importlib.util.module_from_spec( spec )
    spec.loader.exec_module( module )
    return module


def test_the_path_is_the_one_in_the_environment_at_import_not_at_call( monkeypatch, tmp_path ):
    launched = str( tmp_path / "skeleton-crew.test.ini" )
    module   = _load_module( monkeypatch, launched )
    open( launched, "w" ).close()

    monkeypatch.setenv( ENV, str( tmp_path / "isolation-fixture-off-file.ini" ) )

    assert module._test_ini() == launched


def test_it_still_refuses_when_nothing_was_set_at_import( monkeypatch ):
    import pytest
    monkeypatch.delenv( ENV, raising=False )
    spec   = importlib.util.spec_from_file_location( "skeleton_crew_switch_integration_unset",
                                                     os.path.join( cu.get_project_root(), PATH ) )
    module = importlib.util.module_from_spec( spec )
    spec.loader.exec_module( module )
    monkeypatch.setenv( ENV, "/tmp/some-file.ini" )

    with pytest.raises( pytest.fail.Exception ) as refused:
        module._test_ini()
    assert "is not set" in str( refused.value )


def test_it_still_refuses_the_real_configuration_file( monkeypatch ):
    import pytest
    module = _load_module( monkeypatch, os.path.join( cu.get_project_root(), "src", "conf", "lupin-app.ini" ) )

    with pytest.raises( pytest.fail.Exception ) as refused:
        module._test_ini()
    assert "real configuration file" in str( refused.value )
