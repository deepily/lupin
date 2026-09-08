#!/usr/bin/env python3
"""
`bool( "false" )` IS TRUE, AND THIS MODULE HAS SHIPPED THAT DEFECT TWICE.

THE DEFECT. An operator hand-writes `"default_to_holding": "false"` into the override
file. The reader coerces with `bool( raw )`. `bool( "false" )` is True, so the setting
turns ON — the switch doing the exact opposite of what its own file says, while every
report of it says the override was honoured.

WHERE IT ACTUALLY LIVED, WHICH IS NOT WHERE THE NOTES SAID. Two live surfaces existed
on 2026-09-08 and the file's own prose named only the one that had already been fixed:

    get_enforcement_active   FIXED at e98659d2 — the string case handled since
                             REMAINING: an unparseable value ("banana") fell through
                             its membership test and came out False, silently, which is
                             indistinguishable from a deliberate "off" and points
                             toward enforcement OFF
    default_mint_status      🔴 FULLY LIVE — `on = bool( raw )`, unmentioned anywhere,
                             140 lines from the paragraph that said the defect was
                             "live TODAY in get_enforcement_active directly above"

⇒ Both now delegate to `_as_bool_or_none`, and a PREDICATE guards that rather than a
sentence — see `test_one_boolean_parser_for_every_surface.py`. This file pins the
BEHAVIOUR; that one pins the SHAPE. A behaviour test cannot see a third reader written
next month, and a shape test cannot see a wrong answer.

⚠️ THESE ASSERT THE PARSED VALUE, NOT AN HTTP STATUS. The defect is a wrong ANSWER from
a call that succeeds; a status code cannot see it.
"""
import json
import os
import sys

import pytest

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

import cosa.rest.task_approval_settings as approval

FALSY_STRINGS = [ "false", "False", "FALSE", " false ", "no", "off", "0" ]
TRUTHY_STRINGS = [ "true", "True", " TRUE ", "yes", "on", "1" ]


@pytest.fixture
def override( tmp_path, monkeypatch ):
    """
    The override file inside tmp_path.

    🔴 WITHOUT THIS THESE ARMS WRITE THE LIVE FLEET FILE, which holds Rick's standing
    rescission. A test that flips `manager_pull_disabled` there would switch the pull
    gate back on for the whole fleet.
    """
    target = tmp_path / "task-approval-settings.json"
    monkeypatch.setattr( approval, "override_path", lambda: str( target ) )
    monkeypatch.setattr( approval, "_cache_mtime", None )

    def write( key, value ):
        target.write_text( json.dumps( { key: value } ) )
        approval._cache_mtime = None            # mtime is whole-second; force a re-read
        return target

    return write


# ---------------------------------------------------------------------------
# The positive control FIRST. A row of identical answers is what a fixture that
# never took effect looks like, and that is exactly how the first measurement of
# this defect went wrong: injecting into `_cache` with a fabricated mtime, while
# the live file existed, so the reader re-read from disk and discarded it every
# time. Every value returned the same answer, which reads as "the defect is
# everywhere" and actually meant nothing had been measured at all.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize( "key, reader, on_value, off_value", [
    ( "default_to_holding",    lambda: approval.default_mint_status(),      "not_approved", "queued" ),
    ( "enforcement_active",    lambda: approval.get_enforcement_active(),   True,           False    ),
    ( "manager_pull_disabled", lambda: approval.get_manager_pull_disabled(), True,          False    ),
] )
def test_the_injection_MOVES_the_answer_at_all( override, key, reader, on_value, off_value ):
    """
    A real bool in each direction. If both rows agree, the fixture is inert and every
    other assertion in this file is vacuous.
    """
    override( key, True )
    assert reader() == on_value
    override( key, False )
    assert reader() == off_value


# ── the defect itself ────────────────────────────────────────────────────────

@pytest.mark.parametrize( "falsy", FALSY_STRINGS )
def test_a_falsy_STRING_leaves_the_holding_default_OFF( override, falsy ):
    """
    🔴 THE LIVE INSTANCE. Before 2026-09-08 every one of these returned "not_approved"
    — the holding-area default turning ON because the operator wrote it off.
    """
    override( "default_to_holding", falsy )
    assert approval.default_mint_status() == "queued", (
        f'"{falsy}" in the override file turned the holding-area default ON. '
        f'bool( "{falsy}" ) is True — parse the string, never coerce it.'
    )


@pytest.mark.parametrize( "falsy", FALSY_STRINGS )
def test_a_falsy_STRING_leaves_enforcement_OFF( override, falsy ):
    override( "enforcement_active", falsy )
    assert approval.get_enforcement_active() is False


@pytest.mark.parametrize( "falsy", FALSY_STRINGS )
def test_a_falsy_STRING_leaves_the_pull_toggle_OFF( override, falsy ):
    override( "manager_pull_disabled", falsy )
    assert approval.get_manager_pull_disabled() is False


@pytest.mark.parametrize( "truthy", TRUTHY_STRINGS )
def test_a_truthy_STRING_still_turns_the_setting_ON( override, truthy ):
    """
    THE OTHER DIRECTION, and it is not redundant: a reader that returned False for
    EVERYTHING would pass every arm above while being just as broken.
    """
    override( "default_to_holding", truthy )
    assert approval.default_mint_status() == "not_approved"


# ── the junk case: not a decision, so it must not make one ───────────────────

@pytest.mark.parametrize( "junk", [ "banana", "", "maybe", 0, 1, [ ], { }, 1.0 ] )
def test_an_UNPARSEABLE_value_falls_through_rather_than_deciding( override, junk, capsys ):
    """
    THE SECOND HALF OF THE SAME DEFECT, and the half `e98659d2` left behind.

    An unrecognised word fell through the `in ( "true", ... )` membership test and came
    out False — indistinguishable from a deliberate "off". `_as_bool_or_none` returns
    None instead, handing the question to the caller's own fallback, and REPORTS it: a
    setting ignored in silence is how an operator concludes the switch itself is broken.
    """
    override( "manager_pull_disabled", junk )
    assert approval.get_manager_pull_disabled() is approval.FALLBACK_MANAGER_PULL_DISABLED
    assert "not a boolean" in capsys.readouterr().out, (
        "an unparseable setting was ignored in SILENCE — the operator has no way to "
        "learn their edit did nothing."
    )


def test_the_three_fallbacks_do_NOT_point_the_same_way( override ):
    """
    🔴 A GUARD AGAINST A REASSURANCE THIS FILE USED TO CARRY. `_as_bool_or_none`'s note
    said falling through "ends at FALLBACK_MANAGER_PULL_DISABLED, which is closed" —
    written when it served ONE key. It now serves three, and they point OPPOSITE ways:

        FALLBACK_MANAGER_PULL_DISABLED   True    fails CLOSED
        FALLBACK_ENFORCEMENT_ACTIVE      False   fails OPEN
        FALLBACK_DEFAULT_TO_HOLDING      False   fails OPEN

    So "falling through is the safe direction" is true of the pull key and is NOT a
    property of the parser. This pins the asymmetry so nobody carries the pull key's
    reassurance across to the other two — and so that a future change to any fallback
    is a deliberate edit here rather than a silent policy shift.
    """
    assert approval.FALLBACK_MANAGER_PULL_DISABLED is True
    assert approval.FALLBACK_ENFORCEMENT_ACTIVE    is False
    assert approval.FALLBACK_DEFAULT_TO_HOLDING    is False
