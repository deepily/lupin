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


def test_THE_BLEED_a_process_with_no_bridge_of_its_own_adopts_a_LIVE_STRANGERS( bridge_dir, live_stranger ):
    """
    🔴 THE LOAD-BEARING ARM, AND IT IS RED AGAINST TODAY'S RESOLVER.

    This is Pocholo's detached process, modelled at the level that decides the outcome:
    no `CLAUDE_SESSION_ID`, and no bridge for our PPID or grandparent — which is exactly
    what `setsid` produces, since reparenting to init leaves no `cc-{ppid}.json` to find.
    The only bridge present belongs to a live stranger in the same working directory,
    which on this fleet describes every colleague.

    The assertion is not "return nothing". It is that the resolver must not hand back
    ANOTHER SEAT'S IDENTITY AS THOUGH IT WERE OURS. Returning None, raising, or returning
    something the caller can recognise as a guess would all satisfy it — the fix is not
    prejudged here, only the property.
    """
    _write_bridge( bridge_dir, live_stranger, FOREIGN_ID, os.getcwd() )

    result = sb._find_session_file()
    if result is None:
        return                                     # no identity was borrowed

    path, source = result
    adopted = sb._read_session_file( path )
    assert adopted != FOREIGN_ID, (
        f"this process adopted session '{adopted}' from pid {live_stranger}, a live "
        f"stranger that merely shares our working directory (resolution source: "
        f"'{source}'). Nothing failed and nothing warned — the caller receives a plain "
        f"string and cannot tell this from a definitive PPID match. Every notification, "
        f"task-store write and heartbeat made through it is filed under the wrong seat."
    )


def test_the_caller_cannot_TELL_a_guess_from_a_definitive_match( bridge_dir, live_stranger ):
    """
    🔴 THE SHAPE THAT LETS THE BLEED BE SILENT, asserted separately because it survives
    any fix to the selection rule and would otherwise go unnamed.

    `_find_session_file` computes a `source` and treats `cwd_fallback` as untrustworthy
    enough to refuse the cache. `get_claude_session_id` then returns a bare `str`. A
    borrowed identity and an owned one are the same type, the same shape, and equally
    confident.
    """
    _write_bridge( bridge_dir, live_stranger, FOREIGN_ID, os.getcwd() )

    borrowed = sb.get_claude_session_id()
    assert borrowed != FOREIGN_ID, (
        f"get_claude_session_id() returned '{borrowed}' — a live stranger's id — as an "
        f"ordinary string. The refusal to cache it proves the code knows it is a guess; "
        f"the return type gives the caller no way to find that out."
    )
