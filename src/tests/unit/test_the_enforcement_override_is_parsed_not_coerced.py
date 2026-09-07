#!/usr/bin/env python3
"""
`get_enforcement_active` COERCED its override instead of parsing it, so a falsy STRING
turned the approval gate ON.

THE DEFECT, and it is the disarming kind rather than the loud kind: the line was
`return bool( raw )`. `bool( "false" )` is True. So an operator writing
`"enforcement_active": "false"` into the override file switched enforcement ON — and
`current_settings()` then reported `enforcement_active: True, enforcement_source:
override`, i.e. it confirmed the override had been honoured while doing the opposite of
what the file said.

⚠️ WHY NO VALIDATION CAUGHT IT. `set_overrides` DOES type-check with
`isinstance( ..., bool )` — but `FlowRatioSettingsRequest` carries no
`enforcement_active` field, so no request can reach that path. Hand-editing the file is
the only door in, and it had none. THE GUARD WAS ON THE DOOR NOBODY COULD OPEN, which is
why "there is validation" was true and useless at the same time.

Rachel 🕊️'s lead, Tiffany 💍's measurement and fix, 2026-09-06.
"""
import pytest

import cosa.rest.task_approval_settings as approval


@pytest.mark.parametrize( "raw", [ "false", "False", "FALSE", " false ", "no", "0", "off" ] )
def test_a_FALSY_STRING_override_leaves_enforcement_OFF( monkeypatch, raw ):
    """THE REGRESSION. Every one of these returned True before the fix."""
    monkeypatch.setattr( approval, "_read_overrides", lambda: { "enforcement_active": raw } )
    assert approval.get_enforcement_active() is False


@pytest.mark.parametrize( "raw", [ "true", "True", " TRUE ", "yes", "1", "on" ] )
def test_a_TRUTHY_STRING_override_turns_enforcement_ON( monkeypatch, raw ):
    """
    The control. Without it, a fix that simply returned False for every string would
    satisfy the test above — and a guard satisfied by refusing everything is not a guard.
    """
    monkeypatch.setattr( approval, "_read_overrides", lambda: { "enforcement_active": raw } )
    assert approval.get_enforcement_active() is True


@pytest.mark.parametrize( "raw,expected", [ ( True, True ), ( False, False ) ] )
def test_a_REAL_BOOLEAN_override_is_still_honoured_both_ways( monkeypatch, raw, expected ):
    """The path that always worked. It must keep working — this fix is a widening."""
    monkeypatch.setattr( approval, "_read_overrides", lambda: { "enforcement_active": raw } )
    assert approval.get_enforcement_active() is expected


def test_an_ABSENT_override_still_falls_through_to_the_INI( monkeypatch ):
    monkeypatch.setattr( approval, "_read_overrides", lambda: { "enforcement_active": None } )
    monkeypatch.setattr( approval, "_ini_value", lambda *a, **k: "true" )
    assert approval.get_enforcement_active() is True


def test_an_ABSENT_override_AND_absent_INI_fails_OPEN( monkeypatch ):
    """An unreadable config must not start refusing promotions."""
    monkeypatch.setattr( approval, "_read_overrides", lambda: { "enforcement_active": None } )
    monkeypatch.setattr( approval, "_ini_value", lambda *a, **k: None )
    assert approval.get_enforcement_active() is False
    assert approval.FALLBACK_ENFORCEMENT_ACTIVE is False
