#!/usr/bin/env python3
"""
RICK'S ORDER, 2026-09-07 ~21:25 EDT (broadcast c43a29c5, row 1ec67228):

    "I want to rescind the feature that allows you to pull from the holding area into
     the queue and it must default to NO. That way you can never do it without my
     approval."

🔴 STATE IS NOT DEFAULT, AND THAT IS THE ENTIRE REASON THIS FILE EXISTS.

The live override was flipped True on his keypress the same evening, so at the moment
these tests were written the running system ALREADY refused a manager pull. A test that
asked the running system would therefore have passed whether or not a single default had
been changed -- it would have been measuring somebody's keypress and reporting it as a
property of the code.

⇒ SO EVERY TEST BELOW BUILDS ITS OWN WORLD: the override file is redirected into
`tmp_path`, the module cache is cleared, and the INI reader is pinned. Nothing here
reads :7999, and nothing reads the real override file. That is the same positive-control
discipline as `test_the_isolation_actually_isolates` in `test_task_approval_gate.py`, and
the first test in this file is that guard.

WHAT A "FRESH" SYSTEM MEANS HERE, STATED PRECISELY because the spec asked for a database
default too: there ISN'T one. Measured 2026-09-07 with a positive control -- the key
`manager_pull_disabled` appears in exactly three non-test files (task_approval_settings.py,
routers/tasks.py, notifications.html) and ZERO times in `postgres_models.py`, while the
same search shape does find `class TaskItem` there. The toggle is config-plus-file only,
so "fresh database" has no subject and no test here pretends otherwise.
"""
import json
import os
import sys

import pytest

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.rest import task_approval_settings as approval

import cosa.utils.util as cu

INI_PATH  = os.path.join( cu.get_project_root(), "src", "conf", "lupin-app.ini" )
PAGE_PATH = os.path.join( cu.get_project_root(), "src", "lupin_app", "static", "html",
                          "notifications.html" )


@pytest.fixture
def fresh( tmp_path, monkeypatch ):
    """
    A world with NO override file and NO INI key -- a fresh install, a reset, a wiped
    override. The only thing left standing is the in-code default, which is the thing
    Rick's word "default" actually names.

    Ensures:
        - `override_path()` points inside tmp_path and the file does NOT exist
        - `_ini_value` returns None for the pull key, so the reader falls all the way
          through
        - the module's mtime cache is cleared, so a previous test cannot leak a value
    """
    target = tmp_path / "task-approval-settings.json"
    monkeypatch.setattr( approval, "override_path", lambda: str( target ) )
    monkeypatch.setattr( approval, "_cache", { "approvers": None, "enforcement_active": None } )
    monkeypatch.setattr( approval, "_cache_mtime", None )

    real_ini = approval._ini_value

    def pinned( key, return_type, fallback ):
        if key == approval.INI_KEY_MANAGER_PULL_DISABLED: return None
        return real_ini( key, return_type, fallback )

    monkeypatch.setattr( approval, "_ini_value", pinned )
    return target


def test_the_isolation_actually_isolates( fresh ):
    """
    THE GUARD ON EVERY TEST BELOW IT, so it runs first.

    Without this, a green file is equally consistent with the module having read the
    REAL override — the one Rick's keypress set to True tonight — in which case every
    assertion below would pass while proving nothing about the default.
    """
    assert str( fresh ) == approval.override_path()
    assert not os.path.exists( approval.override_path() ), (
        "the fresh-world fixture starts with an override file already present"
    )
    assert "projects-data" not in approval.override_path()
    assert approval._ini_value( approval.INI_KEY_MANAGER_PULL_DISABLED, "string", None ) is None


def test_a_fresh_system_refuses_the_pull( fresh ):
    """
    THE ONE THIS FILE EXISTS FOR. No override, no INI key: the answer must be True.

    Before row 1ec67228 this returned False -- `FALLBACK_MANAGER_PULL_DISABLED` failed
    OPEN, so a fresh install, a reset config or a wiped override silently restored the
    capability the operator believed he had rescinded, and nothing would have told him.
    """
    assert approval.get_manager_pull_disabled() is True, (
        "a fresh system ALLOWS manager pull — Rick's 'it must default to NO' is not in "
        "force on any install that has not been hand-flipped"
    )


def test_the_constant_itself_is_the_closed_direction():
    """
    Asserted directly, and NOT redundant with the test above.

    That one drives the reader, which could conceivably return True for some other
    reason and mask a fallback that had been flipped back. This pins the constant a
    reader would edit.
    """
    assert approval.FALLBACK_MANAGER_PULL_DISABLED is True


def test_the_fresh_world_can_still_see_a_False( fresh ):
    """
    🔴 THE POSITIVE CONTROL, AND WITHOUT IT THIS FILE IS WORTHLESS.

    Every other assertion here expects True. A reader stuck at True — a broken fixture,
    a short-circuit, a constant nothing consults — would satisfy all of them perfectly.
    This proves the same fresh world still reports False when something says False, so
    the Trues above are readings rather than an artifact.
    """
    fresh.write_text( json.dumps( { "manager_pull_disabled": False } ) )
    approval._cache_mtime = None
    assert approval.get_manager_pull_disabled() is False

    fresh.write_text( json.dumps( { "manager_pull_disabled": True } ) )
    approval._cache_mtime = None
    assert approval.get_manager_pull_disabled() is True


def test_the_override_file_still_outranks_the_default( fresh ):
    """
    The rescission must not cost Rick his no-deploy switch.

    An operator flip lands in the override file, and it has to keep winning over the
    shipped default in BOTH directions — otherwise "default to NO" would have quietly
    become "NO, permanently", which is a different order than the one he gave.
    """
    fresh.write_text( json.dumps( { "manager_pull_disabled": False } ) )
    approval._cache_mtime = None
    assert approval.get_manager_pull_disabled() is False, (
        "the shipped default is overriding the operator's own runtime flip"
    )


def test_the_shipped_config_states_the_rule_rather_than_leaving_it_implicit():
    """
    The CONFIG layer, read off the shipped file rather than the code.

    ⚠️ THIS KEY DID NOT EXIST BEFORE ROW 1ec67228, AND ITS ABSENCE WAS THE DEFECT. The
    reader fell through to a Python constant, so the config an operator actually opens
    said nothing about a capability he believed he controlled. A default that is only
    discoverable by reading source is not a default anyone can audit.
    """
    ini = open( INI_PATH, encoding="utf-8" ).read()
    assert "task approval manager pull disabled = True" in ini, (
        f"{approval.INI_KEY_MANAGER_PULL_DISABLED!r} is absent from the shipped config, "
        "or no longer states the closed direction"
    )


def test_the_ui_ships_the_switch_already_frozen():
    """
    The UI layer -- the one that governs the moment before the server answers.

    `_hydrate` sets `.checked` from the server in both directions, so this attribute
    cannot pin the switch on. What it governs is the early-return path: when the
    hydrating GET fails or has not landed, the DOM keeps whatever the markup shipped.
    That used to be UNCHECKED, so the operator was shown "pull is allowed" at exactly
    the moment the server could not be reached to say otherwise.
    """
    page = open( PAGE_PATH, encoding="utf-8" ).read()
    assert 'data-testid="manager-pull-toggle" checked' in page, (
        "the manager-pull checkbox no longer ships checked — a failed or slow hydrate "
        "now shows the operator an unfrozen switch"
    )
