#!/usr/bin/env python3
"""
THE VALIDATED WRITE PATH for Rick's manager-pull toggle (row 458e9947).

Before this, `task_approval_settings` had NO WRITER AT ALL — hand-editing the override
file was the only way to flip anything in it. That is the "guard on the door nobody
could open" shape: `set_overrides` in the SISTER module validates, but no request could
reach a field that did not exist, so the only reachable door had no validation.

🔴 AND THE PATCH ROUTE WAS SHADOWED WHEN FIRST WRITTEN. Measured against the assembled
router: registered after `PATCH /tasks/{task_id}`, `PATCH /api/tasks/manager-pull`
resolved to `patch_task` and answered 422 "invalid UUID" — the identical defect
`/api/tasks/flow-ratio` shipped with. The GET was safe only because its `{task_id}` twin
happens to be registered later. `test_the_manager_pull_routes_are_not_shadowed` pins
BOTH verbs so a future move reddens by name.
"""
import json
import os
import sys

import pytest
from starlette.routing import Match

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

import cosa.rest.task_approval_settings as approval
from cosa.rest.routers import tasks


@pytest.fixture
def override( tmp_path, monkeypatch ):
    target = tmp_path / "task-approval-settings.json"
    monkeypatch.setattr( approval, "override_path", lambda: str( target ) )
    monkeypatch.setattr( approval, "_cache", { "manager_pull_disabled": None } )
    monkeypatch.setattr( approval, "_cache_mtime", None )
    return target


# ── the writer refuses what the reader tolerates ──────────────────────────────

@pytest.mark.parametrize( "bad", [ "true", "false", "1", "0", 1, 0, None, [ ], { }, 1.0 ] )
def test_a_NON_BOOLEAN_is_REFUSED_by_the_writer_not_coerced( override, bad ):
    """
    🔴 "false" is the one that matters: it is TRUTHY, so coercing would switch the
    toggle ON while the caller believed they had turned it off.
    """
    with pytest.raises( ValueError ):
        approval.set_manager_pull_disabled( bad )
    assert not override.exists(), "a refused write must not have touched the file"


@pytest.mark.parametrize( "value", [ True, False ] )
def test_a_REAL_BOOLEAN_is_written_and_read_back_BOTH_WAYS( override, value ):
    """
    The control. Without it, a writer that refused everything would satisfy the test
    above — and a guard satisfied by refusing everything is not a guard.
    """
    assert approval.set_manager_pull_disabled( value ) is value
    assert json.loads( override.read_text() )[ "manager_pull_disabled" ] is value
    assert approval.get_manager_pull_disabled() is value


def test_the_returned_value_is_READ_BACK_not_echoed( override, monkeypatch ):
    """A caller must learn what took effect, not what it asked for."""
    monkeypatch.setattr( approval, "get_manager_pull_disabled", lambda: "read-back-sentinel" )
    assert approval.set_manager_pull_disabled( True ) == "read-back-sentinel"


def test_an_UNRELATED_KEY_SURVIVES_the_flip( override ):
    """
    Clobbering `approvers` while flipping a toggle would take the approval gate down as
    a side effect of an unrelated switch. This is a PATCH of one key.
    """
    override.write_text( json.dumps( { "approvers": [ "maria" ], "enforcement_active": True } ) )
    approval._cache_mtime = None
    approval.set_manager_pull_disabled( True )

    body = json.loads( override.read_text() )
    assert body[ "approvers" ]            == [ "maria" ]
    assert body[ "enforcement_active" ]   is True
    assert body[ "manager_pull_disabled" ] is True


def test_a_CORRUPT_existing_file_does_not_make_the_toggle_unflippable( override ):
    """A bad file must not be a lock. The reader tolerates it; the writer must too."""
    override.write_text( "{ not json at all" )
    approval._cache_mtime = None
    assert approval.set_manager_pull_disabled( True ) is True
    assert json.loads( override.read_text() )[ "manager_pull_disabled" ] is True


def test_a_write_then_read_INSIDE_ONE_SECOND_sees_the_new_value( override ):
    """
    mtime has one-second granularity, so a cache keyed on it can serve the OLD value to
    a read that follows a write immediately — the same whole-second trap that defeats
    .pyc invalidation elsewhere in this repo. The writer clears the cache for this.
    """
    approval.set_manager_pull_disabled( True )
    assert approval.get_manager_pull_disabled() is True
    approval.set_manager_pull_disabled( False )
    assert approval.get_manager_pull_disabled() is False


# ── the routes reach their own handlers ───────────────────────────────────────

@pytest.mark.parametrize( "method,expected", [
    ( "GET",   "get_manager_pull" ),
    ( "PATCH", "set_manager_pull" ),
] )
def test_the_manager_pull_routes_are_not_shadowed( method, expected ):
    """
    🔴 THE REGRESSION. `PATCH` really did resolve to `patch_task` when this block sat
    below `PATCH /tasks/{task_id}`. Asks the ASSEMBLED router, not the source text.
    """
    scope = { "type": "http", "method": method, "path": "/api/tasks/manager-pull",
              "path_params": { }, "headers": [ ], "query_string": b"" }
    for route in tasks.router.routes:
        if route.matches( scope )[ 0 ] == Match.FULL:
            assert route.endpoint.__name__ == expected
            assert route.path == "/api/tasks/manager-pull"
            return
    pytest.fail( f"no route matched {method} /api/tasks/manager-pull at all" )


def test_the_wire_model_refuses_a_STRING_one_layer_above_the_writer():
    """
    Defence in depth, and not redundant: `StrictBool` stops "true"/"false" at the wire,
    the writer stops it for every other caller of the module.
    """
    from pydantic import ValidationError
    for bad in ( "true", "false", 1, 0 ):
        with pytest.raises( ValidationError ):
            tasks.ManagerPullRequest( disabled=bad )
    assert tasks.ManagerPullRequest( disabled=True ).disabled is True
    assert tasks.ManagerPullRequest( disabled=False ).disabled is False


def test_omitting_the_field_is_REFUSED_because_a_flip_must_say_which_way():
    from pydantic import ValidationError
    with pytest.raises( ValidationError ):
        tasks.ManagerPullRequest()
