#!/usr/bin/env python3
"""
`set_overrides` — THE ONE VALIDATED DOOR, at the unit level.

Its HTTP arms live in `test_the_approval_settings_door_is_operator_only.py` and prove
the gate is REACHED. This file proves the writer itself is correct, which the HTTP arms
cannot state without driving every branch through a request.
"""
import json
import os
import sys

import pytest

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

import cosa.rest.task_approval_settings as approval


@pytest.fixture
def override( tmp_path, monkeypatch ):
    """
    The override file inside tmp_path.

    🔴 WITHOUT THIS THESE ARMS WRITE THE LIVE FLEET FILE, which holds Rick's standing
    rescission. A test that flips `manager_pull_disabled` there switches the pull gate
    back on for everybody.
    """
    target = tmp_path / "task-approval-settings.json"
    monkeypatch.setattr( approval, "override_path", lambda: str( target ) )
    monkeypatch.setattr( approval, "_cache_mtime", None )
    return target


def test_the_arms_are_writing_the_TEMP_file_and_not_the_fleet_one( override ):
    """If this fails, every other result in this file was written to the live deployment."""
    assert "projects-data" not in approval.override_path()
    assert "/var/lupin"    not in approval.override_path()


# ── real booleans only ───────────────────────────────────────────────────────

@pytest.mark.parametrize( "key", [ "enforcement_active", "default_to_holding",
                                   "manager_pull_disabled" ] )
@pytest.mark.parametrize( "bad", [ "true", "false", "1", "0", 1, 0, [ ], { }, 1.0, None ] )
def test_a_NON_BOOLEAN_is_REFUSED_not_coerced( override, key, bad ):
    """
    `bool( "false" )` is True. Coercing here would switch a gate ON for a caller who
    asked to switch it off — the defect this whole row exists to close.

    ⚠️ `None` is in this list deliberately. The HTTP layer strips None as "leave
    unchanged", so it never reaches here from a request; a DIRECT caller passing it
    explicitly means something it cannot have, and treating it as False would be a
    coercion by another name.
    """
    with pytest.raises( ValueError ) as raised:
        approval.set_overrides( **{ key: bad } )
    assert key in str( raised.value )
    assert not override.exists(), "the file was written despite the refusal"


@pytest.mark.parametrize( "key", [ "enforcement_active", "default_to_holding",
                                   "manager_pull_disabled" ] )
@pytest.mark.parametrize( "good", [ True, False ] )
def test_a_REAL_boolean_is_written_and_read_back( override, key, good ):
    """THE POSITIVE ARM — without it the refusals prove only that the door can say no."""
    live = approval.set_overrides( **{ key: good } )
    assert json.loads( override.read_text() )[ key ] is good
    assert live[ key ][ "value" ]  is good
    assert live[ key ][ "source" ] == "override"


# ── the collection-shaped keys ───────────────────────────────────────────────

@pytest.mark.parametrize( "bad", [ "rick", { "a": 1 }, [ "rick", "" ], [ "rick", None ],
                                   [ "rick", 3 ], [ "  " ] ] )
def test_a_MALFORMED_approvers_list_is_REFUSED( override, bad ):
    with pytest.raises( ValueError ) as raised:
        approval.set_overrides( approvers=bad )
    assert "approver" in str( raised.value ).lower()
    assert not override.exists()


def test_approvers_are_STRIPPED_but_NOT_canonicalized( override ):
    """
    Storing a canonicalized form would make the file disagree with what the operator
    sent, which is how an operator concludes their own edit did not take.
    `get_approvers` canonicalizes on READ, where it belongs.
    """
    approval.set_overrides( approvers=[ "  Mr. Radio  ", "rick" ] )
    assert json.loads( override.read_text() )[ "approvers" ] == [ "Mr. Radio", "rick" ]


@pytest.mark.parametrize( "bad", [ [ "a" ], "a=b", { "": "rick" }, { "a@b.com": "" },
                                   { "a@b.com": None }, { "a@b.com": 3 } ] )
def test_a_MALFORMED_approver_accounts_map_is_REFUSED( override, bad ):
    with pytest.raises( ValueError ):
        approval.set_overrides( approver_accounts=bad )
    assert not override.exists()


def test_approver_account_emails_are_LOWERCASED( override ):
    """The reader compares on a lower-cased email; storing mixed case would never match."""
    approval.set_overrides( approver_accounts={ "  Rick@Example.COM ": " rick " } )
    assert json.loads( override.read_text() )[ "approver_accounts" ] == {
        "rick@example.com": "rick"
    }


# ── the shape of the call itself ─────────────────────────────────────────────

def test_an_UNKNOWN_key_is_REPORTED_rather_than_ignored( override ):
    with pytest.raises( ValueError ) as raised:
        approval.set_overrides( enforcment_active=True )
    assert "enforcment_active" in str( raised.value )
    assert "Writable keys are" in str( raised.value ), (
        "the refusal must name the keys that ARE writable, or the caller is left "
        "guessing at a spelling."
    )
    assert not override.exists()


def test_an_EMPTY_call_is_REFUSED( override ):
    with pytest.raises( ValueError ):
        approval.set_overrides()


def test_a_BAD_key_in_a_MULTI_KEY_call_writes_NOTHING( override ):
    """
    Validation completes for EVERY key before the file is touched. A half-applied call
    leaves the gate in a state the caller never asked for and cannot see.
    """
    override.write_text( json.dumps( { "approvers": [ "rick" ] } ) )
    with pytest.raises( ValueError ):
        approval.set_overrides( enforcement_active=True, approvers=[ "" ] )
    assert json.loads( override.read_text() ) == { "approvers": [ "rick" ] }, (
        "the good key landed before the bad one was rejected — the call half-applied."
    )


def test_a_write_PRESERVES_every_other_key( override ):
    """
    Clobbering `approvers` while flipping a toggle would take the approval gate down as
    a side effect of an unrelated switch.
    """
    override.write_text( json.dumps( {
        "approvers"            : [ "rick" ],
        "manager_pull_disabled": True,
    } ) )
    approval.set_overrides( enforcement_active=True )
    on_disk = json.loads( override.read_text() )
    assert on_disk[ "approvers" ]             == [ "rick" ]
    assert on_disk[ "manager_pull_disabled" ] is True
    assert on_disk[ "enforcement_active" ]    is True


def test_a_CORRUPT_existing_file_is_REPLACED_rather_than_raising( override, capsys ):
    """
    A bad settings file must not make the settings unflippable — that leaves an operator
    unable to fix the very thing that is broken.
    """
    override.write_text( "{ this is not json" )
    approval.set_overrides( enforcement_active=True )
    assert json.loads( override.read_text() )[ "enforcement_active" ] is True
    assert "unusable" in capsys.readouterr().out


def test_a_NON_OBJECT_existing_file_is_REPLACED( override, capsys ):
    override.write_text( json.dumps( [ "a", "list" ] ) )
    approval.set_overrides( enforcement_active=True )
    assert json.loads( override.read_text() )[ "enforcement_active" ] is True
    assert "not an object" in capsys.readouterr().out


def test_a_MISSING_directory_is_CREATED( tmp_path, monkeypatch ):
    target = tmp_path / "nested" / "deeper" / "task-approval-settings.json"
    monkeypatch.setattr( approval, "override_path", lambda: str( target ) )
    monkeypatch.setattr( approval, "_cache_mtime", None )
    approval.set_overrides( enforcement_active=True )
    assert json.loads( target.read_text() )[ "enforcement_active" ] is True


def test_the_return_is_READ_BACK_not_ECHOED( override, monkeypatch ):
    """
    A caller must report what TOOK EFFECT, not what it asked for. Pinned by making the
    reader disagree with the argument: an echo would return True.
    """
    monkeypatch.setattr( approval, "get_enforcement_active", lambda: "read-back-sentinel" )
    live = approval.set_overrides( enforcement_active=True )
    assert live[ "enforcement_active" ][ "value" ] == "read-back-sentinel"


def test_the_cache_is_INVALIDATED_so_a_write_then_read_inside_one_second_is_correct( override ):
    """
    mtime has one-second granularity — the same whole-second trap that defeats .pyc
    invalidation elsewhere in this repo. Without the invalidation a write-then-read
    inside one second returns the OLD value.
    """
    approval.set_overrides( enforcement_active=True )
    assert approval.get_enforcement_active() is True
    approval.set_overrides( enforcement_active=False )      # same second, deliberately
    assert approval.get_enforcement_active() is False


def test_the_write_is_ATOMIC_leaving_no_temp_behind( override ):
    """
    temp + os.replace, so a concurrent reader sees the old file or the new one, never a
    half-written one. A leftover `.tmp` means the replace did not happen.
    """
    approval.set_overrides( enforcement_active=True )
    assert not ( override.parent / f"{override.name}.tmp" ).exists()


# ── current_settings ─────────────────────────────────────────────────────────

def test_current_settings_reports_EVERY_writable_key( override ):
    assert set( approval.current_settings() ) == set( approval.WRITABLE_KEYS )


def test_current_settings_reports_the_EFFECTIVE_value_not_the_FILE( override ):
    """
    A settings endpoint that echoes the file rather than the effective value is how an
    operator comes to believe a setting is in force while a fallback overrules it.
    """
    override.write_text( json.dumps( { "enforcement_active": "banana" } ) )
    approval._cache_mtime = None
    settings = approval.current_settings()

    # The VALUE is whatever the next layer down decides — this environment's INI, or
    # the fallback if it is unset. What is pinned is that the unparseable override did
    # NOT produce it, and that the endpoint says so.
    assert settings[ "enforcement_active" ][ "value" ] is approval.get_enforcement_active()
    assert settings[ "enforcement_active" ][ "source" ] == "config", (
        "an unparseable override was reported as the SOURCE of a value it did not "
        "produce. Presence is not provenance: a value nobody can parse is not a "
        "decision, so it is not a source either."
    )


def test_current_settings_distinguishes_OVERRIDE_from_CONFIG( override ):
    """
    The value alone cannot tell an operator whether the INI is in force or is being
    masked by a saved override — the one confusion a two-layer scheme reliably creates.
    """
    assert approval.current_settings()[ "enforcement_active" ][ "source" ] == "config"
    approval.set_overrides( enforcement_active=True )
    assert approval.current_settings()[ "enforcement_active" ][ "source" ] == "override"


def test_current_settings_reports_the_HOLDING_default_as_a_BOOLEAN( override ):
    """
    `default_mint_status` returns a STATUS STRING; the settings surface reports the
    SETTING. Echoing "not_approved" into a field called `default_to_holding` would make
    the read door disagree with the write door about what the value even is.
    """
    approval.set_overrides( default_to_holding=True )
    assert approval.current_settings()[ "default_to_holding" ][ "value" ] is True
    approval.set_overrides( default_to_holding=False )
    assert approval.current_settings()[ "default_to_holding" ][ "value" ] is False


def test_set_manager_pull_disabled_STILL_WORKS_after_delegating( override ):
    """
    THE REGRESSION CHECK FOR THE REFACTOR. Its body moved onto `_validated_bool` and
    `_patch_override_file`; its CONTRACT must not have moved with it.
    """
    assert approval.set_manager_pull_disabled( True ) is True
    assert json.loads( override.read_text() )[ "manager_pull_disabled" ] is True
    with pytest.raises( ValueError ) as raised:
        approval.set_manager_pull_disabled( "false" )
    assert "manager_pull_disabled" in str( raised.value )
