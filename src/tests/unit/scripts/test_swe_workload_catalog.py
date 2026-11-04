"""Unit tests for the SWE workload catalog readers.

The counts are literals taken from the module docstring: 18 tasks, 3 in each of 6 categories.
A task added or dropped without updating that docstring fails here.
"""

import importlib.util
import runpy
import sys
from pathlib import Path

import pytest

import cosa.utils.util as cu

CATALOG_PATH = Path( cu.get_project_root() ) / "src" / "scripts" / "swe_workload_catalog.py"


@pytest.fixture
def cat():
    """The catalog module loaded from this tree's path."""
    spec = importlib.util.spec_from_file_location( "swe_workload_catalog_under_test", CATALOG_PATH )
    mod  = importlib.util.module_from_spec( spec )
    spec.loader.exec_module( mod )
    return mod


CATEGORIES = [ "architecture", "deployment", "deps", "destructive", "general", "testing" ]


def test_get_categories_is_the_sorted_unique_set_of_six( cat ):
    assert cat.get_categories() == CATEGORIES


def test_no_category_returns_the_whole_catalog_as_a_copy( cat ):
    everything = cat.get_tasks_by_category( None )
    assert len( everything ) == 18
    everything.pop()
    assert len( cat.WORKLOAD_CATALOG ) == 18, "the caller got the live list, not a copy"


@pytest.mark.parametrize( "category", CATEGORIES )
def test_each_category_has_exactly_three_tasks_and_only_its_own( cat, category ):
    tasks = cat.get_tasks_by_category( category )
    assert len( tasks ) == 3
    assert { t[ "category" ] for t in tasks } == { category }


def test_an_unknown_category_returns_nothing_rather_than_everything( cat ):
    assert cat.get_tasks_by_category( "no-such-category" ) == []


def test_summary_prints_every_task_id_and_the_per_category_counts( cat, capsys ):
    cat.print_catalog_summary()
    out = capsys.readouterr().out
    assert "SWE Workload Catalog: 18 tasks" in out
    for task in cat.WORKLOAD_CATALOG:
        assert task[ "id" ] in out
    for category in CATEGORIES:
        assert f"  {category:<15}: 3 tasks" in out


def test_summary_truncates_a_task_over_sixty_chars_and_leaves_a_short_one_whole( cat, capsys, monkeypatch ):
    long_task  = "L" * 61
    short_task = "short task"
    base = { "category": "general", "risk_level": "low" }
    monkeypatch.setattr( cat, "WORKLOAD_CATALOG", [ { **base, "id": "wl-long", "task": long_task },
                                                    { **base, "id": "wl-short", "task": short_task } ] )
    cat.print_catalog_summary()
    out = capsys.readouterr().out
    assert ( "L" * 58 + ".." ) in out and long_task not in out
    assert short_task in out


def test_running_the_file_as_main_prints_the_summary( capsys ):
    runpy.run_path( str( CATALOG_PATH ), run_name="__main__" )
    assert "SWE Workload Catalog: 18 tasks" in capsys.readouterr().out
