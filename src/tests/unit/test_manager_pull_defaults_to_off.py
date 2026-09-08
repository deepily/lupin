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
# 🔨 Every override body this file writes is STAMPED. Since the stamp landed, an
# unstamped file has `manager_pull_disabled` IGNORED — which is the guard working, and
# it reddened 8 arms here whose subject is the boolean parse, not the stamp. See the
# helper's own header for why it is shared rather than inlined: the population was
# under-reported as one file and is actually three.
from tests.helpers.approval_settings_fixtures import stamped_json

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
    fresh.write_text( stamped_json( { "manager_pull_disabled": False } ) )
    approval._cache_mtime = None
    assert approval.get_manager_pull_disabled() is False

    fresh.write_text( stamped_json( { "manager_pull_disabled": True } ) )
    approval._cache_mtime = None
    assert approval.get_manager_pull_disabled() is True


def test_the_override_file_still_outranks_the_default( fresh ):
    """
    The rescission must not cost Rick his no-deploy switch.

    An operator flip lands in the override file, and it has to keep winning over the
    shipped default in BOTH directions — otherwise "default to NO" would have quietly
    become "NO, permanently", which is a different order than the one he gave.
    """
    fresh.write_text( stamped_json( { "manager_pull_disabled": False } ) )
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


# ============================================================================
# 🔴 BREAKING THE CONFIG, NOT MERELY OMITTING IT — María 🌸, 2026-09-07
#
# Everything above proves the default from a FRESH construction: no override file, no
# INI key, nothing to read. Her objection is that "nothing to read" is the KINDEST way
# a config can be wrong, and it is the only way the tests above ever exercised. A
# deployed system does not usually lose its settings file; it acquires a bad one.
#
# ⇒ SO THESE ARMS HAND THE READER A FILE THAT IS PRESENT AND WRONG, one wrongness per
# arm, and require the same answer: REFUSE.
#
# 🔴 AND THE FIRST ONE FOUND A LIVE HOLE. Measured 2026-09-07 against the reader as
# shipped in `da6ae6f2`: `"banana"`, `""`, `0`, `[]` and `{}` in the override file were
# EVERY ONE of them read as False — pulling ALLOWED. The old tail was
#
#     if isinstance( raw, str ): return raw.strip().lower() in ( "true", "1", ... )
#     return bool( raw )
#
# so an unrecognized word fell out of the membership test as False, indistinguishable
# from a deliberate "off", and an empty container fell out of `bool()` the same way.
# A typo in the VALUE silently restored the capability Rick rescinded. The missing INI
# key of `da6ae6f2` was this same defect one layer out: a config that says nothing about
# a capability the operator believes he controls.
#
# ⚠️ NOTE WHICH WRONGNESS WAS ALREADY SAFE, because the difference is the finding: a
# file that will not PARSE AT ALL was already caught by `_read_overrides` and already
# failed closed. Only a well-formed file with a junk VALUE got through. Wholesale
# corruption is loud; a plausible-looking typo is not.
# ============================================================================

GARBAGE_VALUES = [
    ( "banana",   "an unrecognized word — the one that fell out of the membership test" ),
    ( "",         "an empty string, which a half-finished hand-edit leaves behind" ),
    ( "   ",      "whitespace, which strips to empty" ),
    ( 0,          "a bare JSON number an operator might write meaning false" ),
    ( 1,          "a bare JSON number an operator might write meaning true" ),
    ( [],         "an empty list — falsey under bool()" ),
    ( {},         "an empty object — falsey under bool()" ),
    ( "disabled", "a word that reads like the ANSWER rather than a boolean" ),
]


@pytest.mark.parametrize( "value,why", GARBAGE_VALUES,
                          ids=[ repr( v ) for v, _ in GARBAGE_VALUES ] )
def test_a_junk_VALUE_in_the_override_file_still_refuses( fresh, value, why ):
    """
    The arm that found the hole. Present, parseable, and wrong — and it must not open.

    Every one of these returned False (pull ALLOWED) before `_as_bool_or_none` existed.
    """
    fresh.write_text( stamped_json( { "manager_pull_disabled": value } ) )
    approval._cache_mtime = None
    assert approval.get_manager_pull_disabled() is True, (
        f"a junk override value ({why}) opens the pull gate"
    )


def test_a_junk_value_is_REPORTED_rather_than_swallowed( fresh, capsys ):
    """
    A setting that is ignored in SILENCE is how an operator concludes the switch is
    broken. The corrupt-file path already prints; the junk-value path must too.
    """
    fresh.write_text( stamped_json( { "manager_pull_disabled": "banana" } ) )
    approval._cache_mtime = None
    approval.get_manager_pull_disabled()
    out = capsys.readouterr().out
    assert "banana" in out and "not a boolean" in out, (
        f"the junk value was ignored without telling anyone; stdout was {out!r}"
    )


@pytest.mark.parametrize( "word", list( approval.FALSE_WORDS ) )
def test_the_operator_can_still_say_no_in_words( fresh, word ):
    """
    🔴 THE POSITIVE CONTROL FOR THE ARMS ABOVE, and without it they are worthless.

    Strictness that refused EVERYTHING would satisfy every junk arm perfectly while
    having broken the hand-edit door the refusal message tells operators to use. Each
    recognized false word must still turn the toggle off.
    """
    fresh.write_text( stamped_json( { "manager_pull_disabled": word } ) )
    approval._cache_mtime = None
    assert approval.get_manager_pull_disabled() is False, (
        f"the recognized false word {word!r} no longer turns the toggle off"
    )


@pytest.mark.parametrize( "word", list( approval.TRUE_WORDS ) )
def test_the_recognized_true_words_are_read_as_true( fresh, word ):
    """The other half of the parse, so a stuck-at-True reader cannot pass the pair."""
    fresh.write_text( stamped_json( { "manager_pull_disabled": word } ) )
    approval._cache_mtime = None
    assert approval.get_manager_pull_disabled() is True


def test_case_and_whitespace_do_not_decide_the_switch( fresh ):
    """`"  FALSE  "` is a hand-edit, not a different setting."""
    fresh.write_text( stamped_json( { "manager_pull_disabled": "  FaLsE  " } ) )
    approval._cache_mtime = None
    assert approval.get_manager_pull_disabled() is False


def test_an_override_file_that_will_not_PARSE_still_refuses( fresh, capsys ):
    """
    Wholesale corruption — already safe before this row, pinned so it stays that way.

    Named separately from the junk-value arms because they are different failures:
    this one never reaches the parse at all, and it is the LOUD one.
    """
    fresh.write_text( "{ not json at all" )
    approval._cache_mtime = None
    assert approval.get_manager_pull_disabled() is True
    assert "unusable" in capsys.readouterr().out


def test_an_override_file_that_is_not_an_OBJECT_still_refuses( fresh ):
    """A JSON array where a dict belongs — the shape is wrong, not the value."""
    fresh.write_text( stamped_json( [ { "manager_pull_disabled": False } ] ) )
    approval._cache_mtime = None
    assert approval.get_manager_pull_disabled() is True


def test_an_override_file_that_cannot_be_OPENED_still_refuses( fresh ):
    """
    The path EXISTS — so the missing-file branch is not what answers — and opening it
    raises. A directory is the cheapest way to build that without touching permissions.

    ⚠️ AND PERMISSIONS WOULD BE THE WRONG INSTRUMENT HERE ANYWAY: every process on this
    deployment runs as one UID, so a mode change cannot express "someone else may not
    read this". See the single-UID finding on this row.
    """
    fresh.mkdir()
    approval._cache_mtime = None
    assert approval.get_manager_pull_disabled() is True


def test_a_junk_value_in_the_INI_still_refuses( fresh, monkeypatch ):
    """
    The CONFIG layer, broken rather than absent.

    `_ini_value` returns strings, so a typo there lands in the same parser — and before
    `_as_bool_or_none` it came out False and opened the gate exactly as the file did.
    """
    monkeypatch.setattr(
        approval, "_ini_value",
        lambda key, return_type, fallback: (
            "Trrue" if key == approval.INI_KEY_MANAGER_PULL_DISABLED else fallback
        ),
    )
    assert approval.get_manager_pull_disabled() is True


def test_a_config_manager_that_THROWS_still_refuses( tmp_path, monkeypatch, capsys ):
    """
    The whole config subsystem broken — an unreadable or malformed INI file.

    Deliberately does NOT pin `_ini_value`: this arm drives the real one, whose only
    job is to survive a ConfigurationManager that raises. With the manager throwing,
    the reader must reach the in-code constant and refuse.
    """
    target = tmp_path / "task-approval-settings.json"
    monkeypatch.setattr( approval, "override_path", lambda: str( target ) )
    monkeypatch.setattr( approval, "_cache_mtime", None )

    def explode( *args, **kwargs ):
        raise RuntimeError( "config file is unreadable" )

    monkeypatch.setattr( approval, "ConfigurationManager", explode )

    assert approval._ini_value( approval.INI_KEY_MANAGER_PULL_DISABLED, "string", None ) is None, (
        "the broken-config fixture is not actually breaking the config"
    )
    assert approval.get_manager_pull_disabled() is True


def test_the_broken_world_answers_from_the_CONSTANT_and_not_from_something_stuck( fresh, monkeypatch ):
    """
    🔴 THE DISCRIMINATING CONTROL FOR EVERY BROKEN-CONFIG ARM ABOVE.

    All of them expect True, and a reader hard-wired to True — or one short-circuiting
    before it reads anything — would satisfy the lot. This flips the fallback CONSTANT
    to False in the same broken world and requires the answer to follow it, which is
    only possible if the constant is genuinely what is answering.
    """
    fresh.write_text( stamped_json( { "manager_pull_disabled": "banana" } ) )
    approval._cache_mtime = None
    assert approval.get_manager_pull_disabled() is True

    monkeypatch.setattr( approval, "FALLBACK_MANAGER_PULL_DISABLED", False )
    approval._cache_mtime = None
    assert approval.get_manager_pull_disabled() is False, (
        "the broken-config answer does not track the fallback constant — something "
        "else is returning True and every arm above is measuring it"
    )


def test_a_broken_config_REFUSES_A_REAL_PULL_and_not_merely_a_flag_read( fresh ):
    """
    The flag is not the gate. This drives `refusal_for_pull`, which is what the router
    calls, so the broken-config arms speak about the decision rather than about a
    getter.

    ⚠️ Entered at the layer that decides, per the repo rule that a test entering below
    the layer an incident enters at cannot speak to the incident.
    """
    fresh.write_text( stamped_json( { "manager_pull_disabled": "banana" } ) )
    approval._cache_mtime = None
    detail = approval.refusal_for_pull( "queued", "in_progress", "sam b29ad216" )
    assert detail is not None, "a junk override value lets a real pull through"
    assert "in_progress" in detail
