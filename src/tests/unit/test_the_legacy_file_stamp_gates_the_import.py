#!/usr/bin/env python3
"""
THE STAMP ON THE LEGACY `task-approval-settings.json`, NOW CHECKED AT IMPORT — item D of row `a5bf74ff`, re-aimed by row `80513825`.

🔨 RICK, 2026-09-08: "Only the server writes it." Scope A, B and C landed at `cc85a0e1`
— a validated writer and an operator-gated endpoint. They made the endpoint the
SANCTIONED path. They did not make it the ONLY one: the file is `664 rruiz:rruiz` in a
`775 rruiz:rruiz` directory and every Claude seat runs as `rruiz`, so `chmod` cannot
express "someone else may not write this" when there is no someone else.

⇒ THE STAMP IS WHAT THE FILE LAYER GETS INSTEAD. The writer signs what it writes; the
reader refuses what it cannot verify.

🔴 A POLICY CONTROL, NOT A SECURITY BOUNDARY, AND NEVER TESTED AS ONE. The scheme is in
this repo and so is the key's name; a seat that decides to forge a stamp can. It stops a
hand-edit and a mistake — which is the failure that actually happened, at ~15:50 on
2026-09-08, when the live file read `manager_pull_disabled: false`, Rick's rescission was
OFF, nobody knew, and there was no audit trail. Not one arm below claims more than that.

🔴 WHY THE REFUSAL IS PER-KEY. A blanket "ignore an unstamped file" FAILS OPEN on
`enforcement_active`, whose fallback is `False` by deliberate policy. So only
`STAMP_ENFORCED_KEYS` are refused — today just `manager_pull_disabled`, whose fallback is
`True`, i.e. pulling frozen, i.e. Rick's rescission PRESERVED rather than dropped. The
direction of each fallback is what decides whether refusing a key is safe, and that is
asserted here rather than assumed.

✅ RE-AIMED 2026-09-29 (row 80513825). The file is no longer read at runtime — the settings
live in the `approval_settings` table — so the stamp survives only as the check the ONE-TIME
IMPORT makes before copying the retired file's values in: a file whose stamp does not verify
does not get its rescission imported. Every arm below therefore writes the file and runs
`import_legacy_override_file`, then reads the value THROUGH THE TABLE. The writer arms went
with the writer: the file is not written any more.
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
    Write the LEGACY file inside tmp_path, import it into the in-memory table, return a handle.

    `override( body, stamped )` stamps (or not) and imports; `override.raw( payload )` writes a
    payload exactly as given and imports it.
    """
    monkeypatch.setenv( "LUPIN_FLOW_RATIO_DIR", str( tmp_path ) )
    target = tmp_path / approval.OVERRIDE_FILENAME

    def raw( payload ):
        target.write_text( json.dumps( payload ) )
        return approval.import_legacy_override_file()

    def write( body, stamped ):
        payload = dict( body )
        if stamped:
            stamp = approval._expected_stamp( payload )
            if stamp is not None: payload[ approval.STAMP_KEY ] = stamp
        return raw( payload )

    write.raw = raw
    return write


# ═══ THE INSTRUMENT, FIRST. A green run from a disarmed guard proves nothing. ═══

def test_the_SIGNING_KEY_IS_PRESENT_so_every_arm_below_is_actually_armed():
    """
    🔴 RUNS FIRST AND ON PURPOSE. With no `JWT_SECRET_KEY` the whole stamp stands down —
    `_expected_stamp` returns None, `_stamp_is_valid` returns None, and the reader
    honours every key. EVERY REFUSAL ARM IN THIS FILE WOULD THEN PASS FOR THE WRONG
    REASON, or worse, quietly stop testing anything.

    ⚠️ MEASURED, NOT ASSUMED: the key is absent from a bare login shell on this host and
    present inside pytest. So "it worked when I ran it" is exactly the evidence that
    cannot be trusted here, and this arm is the one that settles it.
    """
    assert approval._stamp_secret() is not None, (
        "JWT_SECRET_KEY is not set in this process, so the stamp is stood down and every "
        "refusal arm in this file is vacuous. This is not a reason to skip them — it is a "
        "reason to fix the environment, because the guard they watch is also stood down."
    )
    assert approval._expected_stamp( { "a": 1 } ) is not None


def test_a_VALIDLY_STAMPED_file_is_honoured( override ):
    """
    🔴 THE POSITIVE CONTROL, AND WITHOUT IT EVERY ARM BELOW IS SATISFIED BY A READER THAT
    IGNORES THE FILE ENTIRELY. A guard that refuses everything is not a guard.
    """
    override( { "manager_pull_disabled": False }, stamped=True )
    assert approval.get_manager_pull_disabled() is False, (
        "a file the validated writer would have produced was refused — the stamp is "
        "rejecting its own output"
    )


# ═══ THE REFUSAL, AND WHAT IT DOES AND DOES NOT REACH ═══════════════════════════

def test_an_UNSTAMPED_file_loses_the_enforced_key( override ):
    """
    The failure that actually happened: a hand-edit turning the pull toggle back on.

    ⚠️ `False` IS THE VALUE ON PURPOSE. Writing `True` would leave the reader returning
    True whether it honoured the file or refused it — an assertion satisfiable by two
    paths, and it would pass against a completely disabled stamp.
    """
    override( { "manager_pull_disabled": False }, stamped=False )
    assert approval.get_manager_pull_disabled() is True, (
        "a hand-written 'pulling is allowed' was honoured — the stamp is not being checked"
    )


def test_a_WRONG_stamp_is_refused_exactly_like_an_absent_one( override ):
    """
    Forging badly must not be better than not forging. Same expectation, different input,
    so a reader that only checked PRESENCE of the key would pass the arm above and fail here.
    """
    override.raw( {
        "manager_pull_disabled": False,
        approval.STAMP_KEY     : "0" * 64,        # right shape, wrong value
    } )
    assert approval.get_manager_pull_disabled() is True


@pytest.mark.parametrize( "junk", [ None, 7, [ ], { }, True, "" ] )
def test_a_NON_STRING_stamp_is_refused_rather_than_raising( override, junk ):
    """A settings file must never be able to take the board down, whatever is in it."""
    override.raw( { "manager_pull_disabled": False, approval.STAMP_KEY: junk } )
    assert approval.get_manager_pull_disabled() is True


def test_the_refusal_is_PER_KEY_and_leaves_the_fail_open_keys_alone( override ):
    """
    🔴 THE DESIGN DECISION, GUARDED — and it is the opposite of the obvious one.

    A blanket "ignore an unstamped file" would ALSO drop `enforcement_active`, whose
    fallback is `False`. Refusing it would therefore turn the approval gate OFF, which is
    a worse outcome than honouring an unverified value. So the refusal is restricted to
    keys whose fallback points CLOSED.

    ⚠️ This is not a compromise and must not be "tidied" into a blanket refusal later.
    """
    override( { "manager_pull_disabled": False, "enforcement_active": True }, stamped=False )

    assert approval.get_manager_pull_disabled() is True,  "the enforced key was honoured unstamped"
    assert approval.get_enforcement_active()    is True,  (
        "an unstamped `enforcement_active` was DROPPED. It falls back to False, so "
        "refusing it switches the approval gate off — the fail-open direction this "
        "design exists to avoid"
    )


def test_the_enforced_keys_all_fall_back_CLOSED_which_is_what_makes_refusing_them_safe():
    """
    🔴 THE INVARIANT UNDER THE WHOLE DESIGN, ASSERTED RATHER THAN TRUSTED.

    Refusing a key is only safe when its fallback points the safe way. Adding a key to
    `STAMP_ENFORCED_KEYS` whose fallback is False would silently make the stamp a way to
    DISABLE a gate — corrupt the file, lose the key, land on an open default.

    ⇒ So this arm enumerates the tuple rather than naming today's single member. A key
    added next month trips it; a test asserting `== ("manager_pull_disabled",)` would
    merely need updating and would teach nobody why.
    """
    fallbacks = {
        "manager_pull_disabled": approval.FALLBACK_MANAGER_PULL_DISABLED,
        "enforcement_active"   : approval.FALLBACK_ENFORCEMENT_ACTIVE,
        "default_to_holding"   : approval.FALLBACK_DEFAULT_TO_HOLDING,
    }
    assert approval.STAMP_ENFORCED_KEYS, "the tuple is empty — nothing is enforced at all"

    for key in approval.STAMP_ENFORCED_KEYS:
        assert key in fallbacks, (
            f"`{key}` is stamp-enforced but this guard does not know its fallback. Add it "
            f"here, with its direction, rather than deleting the check."
        )
        assert fallbacks[ key ] is True, (
            f"`{key}` is stamp-enforced and its fallback is {fallbacks[ key ]!r}. Refusing "
            f"it therefore lands on the OPEN side, so a corrupted stamp DISABLES this gate "
            f"instead of holding it shut."
        )










# ═══ THE THIRD STATE — "CANNOT CHECK" IS NOT "FORGED" ══════════════════════════

def test_with_NO_SECRET_the_verdict_is_None_and_every_key_is_honoured( override, monkeypatch ):
    """
    🔴 THE KEYLESS DEV BOX, AND WHY THE VERDICT HAS THREE VALUES RATHER THAN TWO.

    Collapsing "cannot check" into False would make a machine with no signing key read
    every settings file as forged — the gate would refuse content that is perfectly
    legitimate, on a box that simply has no key. Two different facts; the caller acts
    differently on each.

    ⚠️ AND IT IS NOT A HOLE. A process with no `JWT_SECRET_KEY` cannot serve: the
    `jwt_service` module raises `ValueError` at import, so a running server always has
    one. The state exists for tests and dev shells, not for production.
    """
    monkeypatch.setattr( approval, "_stamp_secret", lambda: None )

    assert approval._stamp_is_valid( { "manager_pull_disabled": False } ) is None, (
        "an unverifiable body reported as FORGED rather than UNCHECKABLE"
    )

    override( { "manager_pull_disabled": False }, stamped=False )
    assert approval.get_manager_pull_disabled() is False, (
        "a keyless process refused a file it was never able to check"
    )


def test_an_UNSERIALISABLE_body_reports_and_returns_None_rather_than_raising( capsys ):
    """A settings file must not be able to take the board down, and neither must a stamp."""
    assert approval._expected_stamp( { "bad": object() } ) is None
    assert "not serialisable" in capsys.readouterr().out


# ═══ WHAT THE DOOR WILL NOT ACCEPT ═════════════════════════════════════════════



def test_the_STAMP_KEY_is_not_writable_through_the_door():
    """
    🔴 THE STAMP MUST NOT BE SETTABLE BY A CALLER. If it were, forging would not even
    need the key — you would just PATCH the stamp you wanted alongside the value.
    """
    assert approval.STAMP_KEY not in approval.WRITABLE_KEYS, (
        "the stamp is writable through PATCH /api/tasks/approval-settings — a caller can "
        "supply their own signature"
    )
    with pytest.raises( ValueError ):
        approval.set_overrides( **{ approval.STAMP_KEY: "anything" } )


def test_the_comparison_is_CONSTANT_TIME( ):
    """
    ⚠️ A SOURCE PREDICATE, AND ITS LIMIT IS STATED: it proves the module CALLS
    `hmac.compare_digest`, not that no `==` comparison exists anywhere. A timing oracle on
    a policy control is a small thing, but `==` here would be a needless one and the fix
    is one identifier.
    """
    import inspect
    source = inspect.getsource( approval._stamp_is_valid )
    assert "compare_digest" in source, (
        "`_stamp_is_valid` no longer uses a constant-time comparison"
    )
