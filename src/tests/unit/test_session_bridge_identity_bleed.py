#!/usr/bin/env python3
"""
A PROCESS WITH NO BRIDGE OF ITS OWN ADOPTS ANOTHER SEAT'S — SILENTLY, AND AS THAT SEAT.

MEASURED BY POCHOLO, 2026-09-03: a detached process (`setsid`, `CLAUDE_SESSION_ID`
unset) resolved as session `1c8db7e3` — his, not its own. It did not fail, warn, or
degrade. It succeeded, wearing somebody else's identity.

THE SELECTION RULE, READ OUT OF `_find_session_file` RATHER THAN GUESSED. Four tiers,
tried in order:

    1. `CLAUDE_SESSION_ID` env var                     (in `wait_for_session_id`)
    2. `cc-{os.getppid()}.json`                        -> source "ppid",        CACHED
    3. `cc-{grandparent pid}.json`                     -> source "grandparent", CACHED
    4. every `cc-*.json`, sorted by mtime DESCENDING, skipping dead pids, returning the
       FIRST whose recorded `cwd` equals `os.getcwd()`  -> source "cwd_fallback", NOT cached

⚠️ "IT PICKS THE NEWEST BRIDGE" IS CLOSE AND NOT THE RULE. Newest is only the ORDER.
The rule is: the most recently modified LIVE bridge whose recorded cwd equals the
caller's. Two filters and one sort, and the distinction matters because the fix depends
on which part is load-bearing.

🔴 AND THE CWD FILTER IS NOT A PER-SEAT DISCRIMINATOR — THAT IS THE WHOLE DEFECT. It
reads like a scope, and it is one: a PROJECT scope. Every seat in this fleet works out of
the same checkout, so every seat's bridge matches on cwd and the filter excludes none of
them. Tier 4 is therefore "whichever colleague most recently touched their bridge".

⚠️ THE CODE KNOWS IT IS GUESSING AND THE CALLER CANNOT FIND OUT. `_find_session_file`
returns `( path, source )` and deliberately refuses to cache a `cwd_fallback`, with a
comment saying why. Then `get_claude_session_id` and `wait_for_session_id` return a bare
`str`. The distinction between a definitive match and a best-guess is computed, acted on
internally, and then thrown away at the boundary — so a certainty and a guess reach the
caller in the same shape. That is this repo's "a clean exit is not evidence" one level
down: the failure and the success return the same type.

WHY NOTHING CAUGHT IT. `test_session_bridge_resolution_tiers.py` covers the cwd fallback
well — that a cwd match is returned, that it is never cached, and a control proving the
two routes disagree about caching. Every one of those tests PATCHES `_find_session_file`
and hands back a hardcoded `( path, source )` tuple. **The selection itself — the glob,
the sort, the liveness filter, the cwd comparison — is never executed.** The incident
enters at the directory scan; every existing test enters above it.

This file drives the real scan against a real directory.

🔨 RULED 2026-09-03, AND IT CHANGED WHAT THESE ARMS SHOULD ASSERT. María's ruling:
MAKE THE GUESS VISIBLE, DO NOT DELETE TIER 4. Removing the fallback outright trades a
silent wrong-seat resolution for a hard failure to resolve at all, and a bad alarm costs
more than it saves. So tier 4 still adopts the live stranger BY DESIGN — what changed is
that the adoption must be LABELLED, and that identity-bearing writes must refuse it.

⇒ THE LAST TWO ARMS WERE RE-POINTED, NOT RELAXED. As first written they asserted the
VALUE ("do not return the stranger's id"), which is now the ruled-CORRECT behaviour — a
guard asserting it would fail forever while reporting a DECISION as a DEFECT. They now
assert the property the ruling actually creates: the adoption is VISIBLE, and the caller
can TELL. Pocholo owns the fix (`get_claude_session_id_with_source` /
`wait_for_session_id_with_source`, plus nine identity-bearing verbs that refuse a
`cwd_fallback` identity); these arms are the spec it is built against.

⚠️ AND NOT xfail — his call, and he is right. `xfail(strict=True)` says "expected to
fail, will be fixed"; it would never flip here, because nothing is going to change the
VALUE tier 4 returns. A strict xfail on a ruling mislabels a decision as a defect,
permanently. Verified by reading his diff rather than running a tier in his live
worktree: `get_claude_session_id()` now returns `get_claude_session_id_with_source()[0]`
— the same bare id — and `_find_session_file` is untouched. So the original arms would
indeed have stayed red at his sha, for the right reason.

🔬 THE ARMS DISCRIMINATE — MEASURED, NOT ASSERTED. A skip that never self-removes is the
same defect with better manners, and a pair of arms that pass against any door would be
worse than no arms. Both were checked by swapping ONLY the door:

    door absent (today)                            3 passed, 2 SKIPPED
    HONEST door — reports the real source          5 passed      <- the skip self-removes
    LIAR door — calls every resolution "ppid"      2 FAILED      <- both arms catch it
    PARANOID door — calls everything cwd_fallback  1 FAILED      <- the paired leg catches it

⚠️ THE PARANOID ROW IS WHY ARM 2 IS A PAIR. A door that labelled every resolution a guess
would refuse every write on the fleet, and it satisfies a single-leg assertion perfectly.
Only the definitive leg — a real PPID match must still report `ppid` — can tell a door
that is honest from one that is merely alarmed.

VENUE: :7999-eligible — a tmp_path directory and one short-lived child process. No
server, no network, no shared state.
"""
import json
import os
import subprocess
import time

import pytest

from lupin_cli.claude_code.hooks.lib import session_bridge as sb


FOREIGN_ID = "1c8db7e3"          # Pocholo's, the id the detached process actually wore
OWN_ID     = "d1cbb9ef"


@pytest.fixture
def live_stranger():
    """A real, live PID that is NOT this process's parent or grandparent.

    A literal like 1 would do for liveness, but `_is_pid_alive` may answer differently
    for a process this user cannot signal — so the arm would be measuring permissions
    rather than the resolver. A child we start is unambiguous.
    """
    proc = subprocess.Popen( [ "sleep", "30" ] )
    yield proc.pid
    proc.kill()
    proc.wait()


@pytest.fixture
def bridge_dir( tmp_path, monkeypatch ):
    """An empty SESSION_DIR, so tiers 2 and 3 cannot match and tier 4 is reached."""
    monkeypatch.setattr( sb, "SESSION_DIR", tmp_path )
    monkeypatch.delenv( "CLAUDE_SESSION_ID", raising=False )
    sb.clear_cached_session_id()
    yield tmp_path
    sb.clear_cached_session_id()


def _write_bridge( directory, pid, session_id, cwd, mtime=None ):
    path = directory / f"cc-{pid}.json"
    path.write_text( json.dumps( {
        "session_id"        : session_id,
        "stable_session_id" : session_id,
        "cwd"               : cwd,
    } ) )
    if mtime is not None:
        os.utime( path, ( mtime, mtime ) )
    return path


def test_POSITIVE_CONTROL_the_resolver_still_finds_a_bridge_that_IS_ours( bridge_dir ):
    """
    Without this, every assertion below is satisfied by a resolver that finds nothing at
    all — which would look like the bleed being fixed and would in fact be the scan being
    broken, or my SESSION_DIR patch not having taken.
    """
    _write_bridge( bridge_dir, os.getppid(), OWN_ID, os.getcwd() )

    result = sb._find_session_file()
    assert result is not None, "the resolver found no bridge even for our own PPID"
    path, source = result
    assert source == sb.SOURCE_PPID
    assert sb._read_session_file( path ) == OWN_ID


def test_the_CWD_FILTER_is_real_a_bridge_from_another_directory_is_not_adopted( bridge_dir, live_stranger ):
    """
    The one filter that does exclude anything. It is worth pinning because it is the only
    thing standing between seats today — and it stops working the moment two seats share
    a checkout, which is the normal case here.
    """
    _write_bridge( bridge_dir, live_stranger, FOREIGN_ID, "/somewhere/else/entirely" )

    assert sb._find_session_file() is None, (
        "a bridge recorded against a DIFFERENT cwd was adopted — the project scope is "
        "gone and any seat on this box can be inherited by any other"
    )


def test_a_DEAD_strangers_bridge_is_not_adopted( bridge_dir ):
    """The liveness filter, pinned. An exited seat must not keep handing out its name."""
    dead = subprocess.Popen( [ "sleep", "0" ] )
    dead.wait()
    time.sleep( 0.05 )
    _write_bridge( bridge_dir, dead.pid, FOREIGN_ID, os.getcwd() )

    assert sb._find_session_file() is None, (
        f"the bridge of exited pid {dead.pid} was adopted — a dead seat's identity "
        f"outlives it"
    )


SOURCE_DOOR = getattr( sb, "get_claude_session_id_with_source", None )

_needs_door = pytest.mark.skipif(
    SOURCE_DOOR is None,
    reason=(
        "the source-carrying door is not on this branch yet — "
        "session_bridge.get_claude_session_id_with_source is absent. It is being built in "
        "lupin-wt-pocholo-idbleed, with its own guards at "
        "test_borrowed_identity_is_visible_and_refused.py and "
        "test_the_refusal_is_wired_into_every_identity_bearing_verb.py. "
        "THIS SKIP IS SELF-REMOVING: the moment that symbol lands these two arms run for "
        "real and fail if the labelling is wrong. It is not a permanent exemption and must "
        "not be turned into one."
    ),
)


@_needs_door
def test_the_adoption_of_a_LIVE_STRANGERS_bridge_is_LABELLED_as_a_guess( bridge_dir, live_stranger ):
    """
    🔴 THE LOAD-BEARING ARM. Pocholo's detached process, modelled at the level that
    decides the outcome: no `CLAUDE_SESSION_ID`, and no bridge for our PPID or
    grandparent — which is what `setsid` produces, since reparenting to init leaves no
    `cc-{ppid}.json` to find. The only bridge present belongs to a live stranger in the
    same working directory, which on this fleet describes every colleague.

    ⚠️ IT DOES NOT ASSERT THAT THE ID IS REFUSED. Under the ruling the adoption is
    ALLOWED — deleting tier 4 would trade a silent wrong seat for a hard failure to
    resolve. What must never happen is that it arrives UNLABELLED. So the assertion is:
    if a stranger's id comes back, the source must say `cwd_fallback`, out loud, in the
    same return value.
    """
    _write_bridge( bridge_dir, live_stranger, FOREIGN_ID, os.getcwd() )

    session_id, source = SOURCE_DOOR()

    if session_id != FOREIGN_ID:
        return                                     # no identity was borrowed at all

    assert source == sb.SOURCE_CWD_FALLBACK, (
        f"this process adopted session '{session_id}' from pid {live_stranger}, a live "
        f"stranger that merely shares our working directory — and reported the "
        f"resolution source as '{source}'. A borrowed identity that does not announce "
        f"itself is the whole defect: every downstream refusal keys on this label, so a "
        f"mislabelled guess is filed as a certainty and the write lands under the wrong "
        f"seat exactly as before."
    )


@_needs_door
def test_the_caller_CAN_TELL_a_guess_from_a_definitive_match( bridge_dir, live_stranger ):
    """
    🔴 THE ROOT, AND IT SURVIVES ANY DECISION ABOUT TIER 4 — which is why it is a
    separate arm rather than a clause of the one above.

    `_find_session_file` has always computed a `source` and treated `cwd_fallback` as
    untrustworthy enough to refuse the cache. The old `get_claude_session_id` then
    returned a bare `str`, so the distinction was computed, acted on internally, and
    discarded at the boundary: a borrowed identity and an owned one were the same type,
    the same shape, and equally confident. Nothing downstream could refuse what it could
    not see.

    ⚠️ THE PAIR IS THE TEST, NOT EITHER HALF. Asserting only that a borrowed identity
    reports `cwd_fallback` would pass against a door that labelled EVERYTHING that way —
    which would refuse every write on the fleet. The definitive leg is what makes the
    first one mean something.
    """
    # LEG 1 — borrowed: no bridge of our own, one live stranger sharing our cwd.
    _write_bridge( bridge_dir, live_stranger, FOREIGN_ID, os.getcwd() )
    borrowed_id, borrowed_source = SOURCE_DOOR()

    # LEG 2 — definitive: a bridge that is genuinely ours, resolved by PPID.
    sb.clear_cached_session_id()
    _write_bridge( bridge_dir, os.getppid(), OWN_ID, os.getcwd() )
    own_id, own_source = SOURCE_DOOR()

    assert own_id == OWN_ID and own_source == sb.SOURCE_PPID, (
        f"the definitive route no longer reports itself as definitive "
        f"(id={own_id!r}, source={own_source!r}) — without this leg the assertion below "
        f"is satisfied by a door that calls every resolution a guess"
    )
    assert borrowed_source != own_source, (
        f"a borrowed identity and an owned one report the SAME source "
        f"({borrowed_source!r}). The caller still cannot tell them apart, so every "
        f"identity-bearing verb downstream is deciding on a label that carries no "
        f"information — which is the shape that let the bleed be silent."
    )
