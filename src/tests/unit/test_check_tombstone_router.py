"""
Unit tests for check_tombstone_router and the four retired-door smoke blocks that call it.

The helper checks one retired door's router against the table in _retired_doors. The smoke
blocks in the four routers print a failure line instead of raising, so a test reads their output.
"""
from types import SimpleNamespace

import pytest

from cosa.rest.routers import _retired_doors as rd
from cosa.rest.routers import deep_research_to_podcast, deep_research_to_presentation, podcast_generator, presentation_generator

PATH = "/api/podcast-generator/submit"


def router( prefix="/api/podcast-generator", tags=( "podcast-generator", ), paths=( PATH, ) ):
    """Ensures: returns a stand-in router with the given prefix, tags and route paths."""
    return SimpleNamespace( prefix=prefix, tags=list( tags ), routes=[ SimpleNamespace( path=p ) for p in paths ] )


def check( r ):
    """Ensures: runs the helper for the podcast-generator door against router r."""
    return rd.check_tombstone_router( r, "/api/podcast-generator", "podcast-generator", PATH, rd.V2_ASK )


def test_a_router_that_matches_the_table_returns_the_refusal_text():
    detail = check( router() )
    assert detail == rd.refusal_detail( PATH ) and rd.V2_ASK in detail and "REMOVE BY" in detail


@pytest.mark.parametrize( "bad, fragment", [
    ( dict( prefix="/api/other" ),                                  "prefix is /api/other" ),
    ( dict( tags=( "other", ) ),                                    "tag podcast-generator is not in" ),
    ( dict( paths=( "/api/podcast-generator/api/podcast-generator/submit", ) ), "mounted at" ),
    ( dict( paths=( PATH, PATH ) ),                                 "mounted at" ),
] )
def test_each_wrong_router_property_is_named_in_the_error( bad, fragment ):
    with pytest.raises( AssertionError, match=fragment ):
        check( router( **bad ) )


def test_a_target_the_table_does_not_hold_for_the_path_is_named():
    with pytest.raises( AssertionError, match="RETIRED_DOORS maps" ) as caught:
        rd.check_tombstone_router( router(), "/api/podcast-generator", "podcast-generator", PATH, rd.V2_SUBMIT )
    assert "refusal does not name" in str( caught.value )


def test_a_path_missing_from_the_table_fails_without_a_key_error():
    gone_path = "/api/not-retired/submit"
    with pytest.raises( AssertionError, match="RETIRED_DOORS maps /api/not-retired/submit to None" ) as caught:
        rd.check_tombstone_router( router( paths=( gone_path, ) ), "/api/podcast-generator", "podcast-generator", gone_path, rd.V2_ASK )
    assert "refusal does not name" in str( caught.value )


def test_every_problem_is_listed_in_one_error():
    with pytest.raises( AssertionError ) as caught:
        check( router( prefix="/x", tags=( "y", ), paths=( "/z", ) ) )
    text = str( caught.value )
    assert "prefix is /x" in text and "tag podcast-generator" in text and "mounted at" in text


@pytest.mark.parametrize( "module, banner", [
    ( deep_research_to_podcast,      "Deep Research to Podcast Router Smoke Test" ),
    ( deep_research_to_presentation, "Deep Research to Presentation Router Smoke Test" ),
    ( podcast_generator,             "Podcast Generator Router Smoke Test" ),
    ( presentation_generator,        "Presentation Generator Router Smoke Test" ),
] )
def test_each_retired_door_smoke_runs_clean_and_checks_its_route( module, banner, capsys ):
    module.quick_smoke_test()
    out = capsys.readouterr().out
    assert banner in out and "failed" not in out.lower() and "Testing the retired route..." in out


def test_a_smoke_block_reports_a_wrong_door_instead_of_passing( monkeypatch, capsys ):
    monkeypatch.setitem( rd.RETIRED_DOORS, PATH, rd.V2_SUBMIT )
    podcast_generator.quick_smoke_test()
    assert "Smoke test failed" in capsys.readouterr().out
