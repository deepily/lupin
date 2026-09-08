#!/usr/bin/env python3
"""
THE STAMP ON `task-approval-settings.json` — item D of row `a5bf74ff`.

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

    🔴 WITHOUT THIS THESE ARMS WRITE THE LIVE FLEET FILE. `override_path()` resolves
    through `fleet_data_root()`, which is OUTSIDE every worktree — so a non-isolating
    test in any checkout writes the one file the whole fleet reads. That is not
    hypothetical; it is the standing structural hazard this module carries.
    """
    target = tmp_path / "task-approval-settings.json"
    monkeypatch.setattr( approval, "override_path", lambda: str( target ) )
    monkeypatch.setattr( approval, "_cache_mtime", None )
    monkeypatch.setattr( approval, "_cache", {
        "approvers": None, "enforcement_active": None, "default_to_holding": None,
        "approver_accounts": None, "manager_pull_disabled": None } )

    def write( body, stamped ):
        payload = dict( body )
        if stamped:
            stamp = approval._expected_stamp( payload )
            if stamp is not None: payload[ approval.STAMP_KEY ] = stamp
        target.write_text( json.dumps( payload ) )
        approval._cache_mtime = None            # mtime is whole-second; force a re-read
        return target

    write.path = target
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
    override.path.write_text( json.dumps( {
        "manager_pull_disabled": False,
        approval.STAMP_KEY     : "0" * 64,        # right shape, wrong value
    } ) )
    approval._cache_mtime = None
    assert approval.get_manager_pull_disabled() is True


@pytest.mark.parametrize( "junk", [ None, 7, [ ], { }, True, "" ] )
def test_a_NON_STRING_stamp_is_refused_rather_than_raising( override, junk ):
    """A settings file must never be able to take the board down, whatever is in it."""
    override.path.write_text( json.dumps( {
        "manager_pull_disabled": False, approval.STAMP_KEY: junk } ) )
    approval._cache_mtime = None
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


# ═══ THE WRITER ════════════════════════════════════════════════════════════════

def test_the_VALIDATED_WRITER_stamps_what_it_writes( override ):
    """
    The round trip, and the only arm that proves the two halves agree. A writer that
    stamped with a different scheme than the reader verifies would pass every arm above.
    """
    approval.set_overrides( manager_pull_disabled=False )

    on_disk = json.loads( override.path.read_text() )
    assert approval.STAMP_KEY in on_disk, "the writer left its output unstamped"
    assert approval.get_manager_pull_disabled() is False, (
        "the writer's own output did not verify — writer and reader disagree on the scheme"
    )


def test_the_stamp_does_not_cover_ITSELF_so_rewriting_is_idempotent( override ):
    """
    ⚠️ THE BUG THIS FORECLOSES: stamping over a body that still holds the OLD stamp makes
    each write depend on the last, so an unchanged file re-serialised twice gets two
    different stamps and the second read refuses a file nobody edited.
    """
    approval.set_overrides( manager_pull_disabled=True )
    first = json.loads( override.path.read_text() )[ approval.STAMP_KEY ]

    approval._cache_mtime = None
    approval.set_overrides( manager_pull_disabled=True )
    second = json.loads( override.path.read_text() )[ approval.STAMP_KEY ]

    assert first == second, "re-writing an unchanged body changed its stamp"


def test_a_KEYLESS_write_STRIPS_a_stamp_it_could_not_recompute( override, monkeypatch ):
    """
    🔴 THIS ARM EXISTS BECAUSE A MUTANT SURVIVED, AND THE SURVIVOR WAS NOT A WEAK TEST.

    Mutation arm M5 deleted `body.pop( STAMP_KEY, None )` from `_patch_override_file` and
    all 395 tests stayed GREEN. The diagnosis is TWO SUFFICIENT CAUSES: `_expected_stamp`
    ALSO excludes the stamp key, so idempotence holds whichever one you delete, and no
    assertion about idempotence can implicate either. Arm M7 confirmed it from the other
    side — breaking the exclusion in `_expected_stamp` reddens 31 tests, while
    `test_the_stamp_does_not_cover_ITSELF` is not among them.

    ⇒ So rather than reach for sharper words, here is the ONE case where the two
    mechanisms genuinely differ: a process with NO SECRET writing over a file that was
    already stamped. `_expected_stamp` returns None, so nothing is written back — and
    only the `pop` decides whether the OLD signature survives.

    IT MUST NOT. A stamp is a claim that the validated writer produced this exact body.
    Leaving a previous one attached to CHANGED content is that claim outliving its
    subject — the file would carry a signature nobody made for it.

    ⚠️ THE OUTCOME FOR A READER IS THE SAME EITHER WAY (both verdicts are False, both
    fall back closed), so this is about what the file ASSERTS, not about what the gate
    does. Said plainly so nobody upgrades it into a security claim.
    """
    override( { "manager_pull_disabled": True }, stamped=True )
    assert approval.STAMP_KEY in json.loads( override.path.read_text() ), "fixture did not stamp"

    monkeypatch.setattr( approval, "_stamp_secret", lambda: None )
    approval.set_overrides( manager_pull_disabled=False )

    on_disk = json.loads( override.path.read_text() )
    assert on_disk[ "manager_pull_disabled" ] is False, "the write did not land at all"
    assert approval.STAMP_KEY not in on_disk, (
        "a keyless writer changed the body and left the PREVIOUS stamp attached to it — "
        "the file now carries a signature that was never made for its contents"
    )


def test_a_write_PRESERVES_a_sibling_key_and_still_verifies( override ):
    """
    The patch semantics and the stamp have to hold together: a stamp computed over the
    merged body, never over the update alone. Otherwise flipping one key invalidates the
    file for every other.
    """
    override( { "approvers": [ "rick" ], "manager_pull_disabled": True }, stamped=True )
    approval.set_overrides( enforcement_active=True )

    on_disk = json.loads( override.path.read_text() )
    assert on_disk[ "approvers" ] == [ "rick" ]
    assert approval.get_manager_pull_disabled() is True, (
        "flipping an unrelated key invalidated the stamp over the keys it did not touch"
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


# ═══ WHAT THE REFUSAL SAYS, AND WHAT THE DOOR WILL NOT ACCEPT ══════════════════

def test_the_refusal_NAMES_THE_DOOR_rather_than_leaving_a_dead_end( override, capsys ):
    """
    A refusal that does not say how to proceed sends the reader straight back to the text
    editor — which is the behaviour this whole row exists to stop. The same care three
    other refusals in this module already take.
    """
    override( { "manager_pull_disabled": False }, stamped=False )
    approval.get_manager_pull_disabled()

    out = capsys.readouterr().out
    assert "/api/tasks/approval-settings" in out, "the refusal does not name the sanctioned door"
    assert approval.STAMP_ENFORCED_KEYS[ 0 ] in out, "it does not say WHICH keys it ignored"


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
