"""
GET /api/epic-stories — unit tests for the epic story-text surface.

Plan: src/rnd/v0.2.0/2026.08.24-epic-accordion-mini-plan.md §5 (Rick's ruling
2026-08-24: the hand-maintained epic-story file MOVES into this repo and is
served from the router that already serves the rows).

The behavior worth pinning is the DEGRADE contract, not the happy path: a
MISSING file must return 200 with an empty map so the board renders de-slugged
epic names, while an UNPARSEABLE file must be loud. A missing story is a nudge;
it must never be an outage.
"""

import json
import os

import pytest
from fastapi import HTTPException

from cosa.rest.routers import tasks as tasks_router


AUTHED = "test-user"


@pytest.fixture
def epic_stories_path( tmp_path, monkeypatch ):
    """
    Point the endpoint's project root at a temp tree and yield the path the
    endpoint will read, WITHOUT creating the file.

    Ensures:
        - cu.get_project_root() resolves under tmp_path for the test's duration
        - the src/conf directory exists; epic-stories.json does NOT
        - returns the absolute path the endpoint will open
    """
    root = tmp_path / "root"
    ( root / "src" / "conf" ).mkdir( parents=True )
    monkeypatch.setattr( tasks_router.cu, "get_project_root", lambda: str( root ) )
    return str( root ) + tasks_router.EPIC_STORIES_REL_PATH


def test_happy_path_returns_the_file_verbatim( epic_stories_path ):
    payload = {
        "_README" : "Hand-maintained.",
        "epic:board-visibility" : { "title": "Rick can see his own board", "story": "…" },
        "epic:seal-the-test-tier" : { "title": "Seal the test tier", "story": "…" },
    }
    with open( epic_stories_path, "w", encoding="utf-8" ) as handle:
        json.dump( payload, handle )

    result = tasks_router.get_epic_stories( AUTHED )

    assert result[ "stories" ] == payload, "the file is returned AS-IS, not reshaped"


def test_count_excludes_the_underscore_readme_key( epic_stories_path ):
    payload = {
        "_README" : "Hand-maintained.",
        "epic:a"  : { "title": "A", "story": "a" },
        "epic:b"  : { "title": "B", "story": "b" },
    }
    with open( epic_stories_path, "w", encoding="utf-8" ) as handle:
        json.dump( payload, handle )

    result = tasks_router.get_epic_stories( AUTHED )

    assert result[ "count" ] == 2, "the _README key is documentation, not an epic"


def test_missing_file_returns_200_and_an_empty_map_not_a_5xx( epic_stories_path ):
    # The whole point: an absent story file must degrade the board to de-slugged
    # names. If this ever raises, a panel goes dark over a file nobody wrote yet.
    assert not os.path.exists( epic_stories_path )

    result = tasks_router.get_epic_stories( AUTHED )

    assert result == { "stories": {}, "count": 0 }


def test_unparseable_file_raises_500_rather_than_returning_empty( epic_stories_path ):
    # A human edited a comma out. That is a real defect and must be loud —
    # silently serving {} would look identical to "no epics have stories yet".
    with open( epic_stories_path, "w", encoding="utf-8" ) as handle:
        handle.write( '{ "epic:a": { "title": "A" },, }' )

    with pytest.raises( HTTPException ) as excinfo:
        tasks_router.get_epic_stories( AUTHED )

    assert excinfo.value.status_code == 500
    assert "not valid JSON" in excinfo.value.detail


def test_non_object_root_raises_500( epic_stories_path ):
    with open( epic_stories_path, "w", encoding="utf-8" ) as handle:
        json.dump( [ "epic:a", "epic:b" ], handle )

    with pytest.raises( HTTPException ) as excinfo:
        tasks_router.get_epic_stories( AUTHED )

    assert excinfo.value.status_code == 500
    assert "JSON object" in excinfo.value.detail


def test_empty_object_is_valid_and_not_an_error( epic_stories_path ):
    with open( epic_stories_path, "w", encoding="utf-8" ) as handle:
        json.dump( {}, handle )

    result = tasks_router.get_epic_stories( AUTHED )

    assert result == { "stories": {}, "count": 0 }


def test_route_is_registered_under_the_same_auth_guard_as_api_tasks():
    """
    The endpoint must sit on the SAME router as /api/tasks, which is what makes
    "behind the same auth guard" true by construction rather than by promise.
    """
    routes = { r.path: r for r in tasks_router.router.routes }

    assert "/api/epic-stories" in routes
    epic_deps  = routes[ "/api/epic-stories" ].dependant.dependencies
    tasks_deps = routes[ "/api/tasks" ].dependant.dependencies
    epic_guards  = { d.call for d in epic_deps }
    tasks_guards = { d.call for d in tasks_deps }

    assert tasks_router.require_api_key_or_jwt in epic_guards
    assert epic_guards == tasks_guards, "same guard set as /api/tasks — no weaker door"


def test_the_shipped_conf_file_parses_and_carries_epics():
    """
    The file this milestone MOVED into src/conf/ must actually be readable —
    a move that lands a broken file is the failure this catches.
    """
    import cosa.utils.util as cu

    path = cu.get_project_root() + tasks_router.EPIC_STORIES_REL_PATH
    assert os.path.exists( path ), f"the moved file must exist at {path}"

    with open( path, "r", encoding="utf-8" ) as handle:
        stories = json.load( handle )

    epics = [ key for key in stories if key.startswith( "epic:" ) ]
    assert len( epics ) > 0
    for key in epics:
        assert isinstance( stories[ key ], dict ), f"{key} must map to an object"
        assert stories[ key ].get( "title" ), f"{key} must carry a title"
