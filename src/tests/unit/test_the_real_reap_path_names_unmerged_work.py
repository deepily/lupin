#!/usr/bin/env python3
"""
The seam, driven through the REAL `dismiss_sessions` — not the probe in isolation.

WHY THIS FILE EXISTS SEPARATELY FROM `test_the_reap_names_the_branch_it_leaves_behind.py`.
That file proves the probe is correct. **It passes whether or not `dismiss_sessions` ever
calls it** — which is CLAUDE.md § IMPLEMENTED BUT NOT INSTALLED exactly: a module at 100%
that the caller never reaches. Unwire the call site and every test in that file stays
green. So this file enters at the layer the defect enters at: the reap itself.

🔴 AND IT PINS THE ASYMMETRY, WHICH IS THE PART A READER IS MOST LIKELY TO "FIX".
The memento gate WITHHOLDS a kill it cannot prove. This seam must NOT, and the design
argues why (§3.2): a memento is data only that seat can produce, while a branch is
already durable in git and the janitor provably keeps it — measured 2026-09-06, dir
removed, branch kept, WIP committed. Withholding over a branch manufactures an immortal
seat for a condition that loses nothing.

A test that only asserted "the alarm appears" would pass on an implementation that
withholds. So the decisive case drives an unmerged branch and asserts the seat is
**killed anyway**, and a second case runs the branch probe and the memento withhold
TOGETHER to prove the two seams are discriminated rather than merely coexisting.
"""
import json
import os
import sys
import tempfile
from pathlib import Path
from types   import SimpleNamespace

_src = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src not in sys.path:
    sys.path.insert( 0, _src )

import lupin_mcp.session_spawner as ss


_OK_RUNNER = lambda argv, env=None: SimpleNamespace( returncode=0 )
_NOOP      = { "emit_reap_fn": lambda i, reason="": None, "emit_reaped_fn": lambda i: None }


def _setup( tmp, tmux="cc-author-x-1", cwd="/tmp" ):
    sd  = Path( tmp )
    mgr = "mgr-abc12345"
    ss._write_manifest( ss._manifest_path( mgr, sd ),
                        [ { "session_name": tmux, "session_id": "sid-1" } ] )
    ( sd / "cc-99999.json" ).write_text( json.dumps( {
        "tmux_session"      : tmux,
        "stable_session_id" : "abcd1234-aaaa-bbbb",
        "cwd"               : cwd,
        "voice_persona"     : { "name": "Maya", "icon": "🌻" },
    } ) )
    return sd, mgr


def test_the_real_reap_surfaces_a_branch_alarm_at_the_TOP_of_its_result():
    """The wiring itself. Unwire the call site and this reddens."""
    with tempfile.TemporaryDirectory() as tmp:
        sd, mgr = _setup( tmp )
        res = ss.dismiss_sessions(
            mgr, session_names=[ "cc-author-x-1" ], runner=_OK_RUNNER, session_dir=sd,
            branch_probe_fn=lambda ids: {
                n: { "status": "unmerged", "persona": "Maya",
                     "commits": 23, "branch": "wt-cheech-authority-column" }
                for n in ids },
            **_NOOP )
        assert res[ "branch_alarm" ] is not None
        assert "23" in res[ "branch_alarm" ]
        assert "wt-cheech-authority-column" in res[ "branch_alarm" ]
        assert res[ "branch_outcomes" ][ "cc-author-x-1" ][ "status" ] == "unmerged"


def test_the_probe_RECEIVES_the_seats_own_cwd_not_the_managers():
    """
    The branch lives in the SEAT's worktree. Probing the manager's tree would answer
    confidently about the wrong repo — the wrong-tree family this repo keeps re-deriving.
    """
    with tempfile.TemporaryDirectory() as tmp:
        sd, mgr = _setup( tmp, cwd="/seats/own/worktree" )
        seen = {}
        ss.dismiss_sessions(
            mgr, session_names=[ "cc-author-x-1" ], runner=_OK_RUNNER, session_dir=sd,
            branch_probe_fn=lambda ids: seen.update( ids ) or {}, **_NOOP )
        assert seen[ "cc-author-x-1" ][ "cwd" ] == "/seats/own/worktree"


def test_an_unmerged_branch_DOES_NOT_withhold_the_kill():
    """
    🔴 THE DECISIVE CASE. Nothing is lost at the reap — the commits are in git. Withholding
    here would manufacture an immortal seat for a condition that loses nothing.
    """
    with tempfile.TemporaryDirectory() as tmp:
        sd, mgr = _setup( tmp )
        killed = []
        res = ss.dismiss_sessions(
            mgr, session_names=[ "cc-author-x-1" ], session_dir=sd,
            runner=lambda argv, env=None: ( killed.append( argv ),
                                            SimpleNamespace( returncode=0 ) )[ 1 ],
            branch_probe_fn=lambda ids: {
                n: { "status": "unmerged", "persona": "Maya", "commits": 9, "branch": "b" }
                for n in ids },
            **_NOOP )
        assert any( "kill-session" in a for a in killed[ 0 ] )      # it really died
        assert res[ "dismissed" ][ 0 ][ "status" ] == "killed"
        assert "withheld" not in res[ "dismissed" ][ 0 ][ "status" ]
        assert res[ "branch_alarm" ] is not None                    # …and was still named


def test_the_branch_seam_and_the_memento_withhold_are_discriminated():
    """
    Both seams on one reap. The memento gate withholds; the branch probe speaks and does
    not. Collapse the two and this reddens while every single-seam test stays green.
    """
    with tempfile.TemporaryDirectory() as tmp:
        sd, mgr = _setup( tmp )
        res = ss.dismiss_sessions(
            mgr, session_names=[ "cc-author-x-1" ], runner=_OK_RUNNER, session_dir=sd,
            memento_coord_fn=lambda ids: {
                n: { "status": "timeout_no_memento", "persona": "Maya" } for n in ids },
            branch_probe_fn=lambda ids: {
                n: { "status": "unmerged", "persona": "Maya", "commits": 4, "branch": "b" }
                for n in ids },
            **_NOOP )
        # the MEMENTO verdict is what stops the kill …
        assert res[ "dismissed" ][ 0 ][ "status" ] == "withheld_no_memento"
        # … and the BRANCH verdict is reported all the same, never swallowed by it
        assert res[ "branch_alarm" ] is not None and "4 commit(s)" in res[ "branch_alarm" ]


def test_a_raising_probe_NEVER_breaks_the_reap():
    """Fail-safe, like every other seam here. A git hiccup must not strand a seat."""
    with tempfile.TemporaryDirectory() as tmp:
        sd, mgr = _setup( tmp )
        def _boom( ids ): raise RuntimeError( "git exploded" )
        res = ss.dismiss_sessions(
            mgr, session_names=[ "cc-author-x-1" ], runner=_OK_RUNNER, session_dir=sd,
            branch_probe_fn=_boom, **_NOOP )
        assert res[ "dismissed" ][ 0 ][ "status" ] == "killed"       # the reap still happened
        assert "git exploded" in res[ "branch_outcomes" ][ "_error" ]  # and said so
        assert res[ "branch_alarm" ] is None                          # _error is not a seat


def test_no_probe_wired_stays_hermetic_and_silent():
    """
    The NEGATIVE CONTROL. Without it, an implementation that alarmed unconditionally
    would pass every test above — and a line that always appears carries no information.
    """
    with tempfile.TemporaryDirectory() as tmp:
        sd, mgr = _setup( tmp )
        res = ss.dismiss_sessions( mgr, session_names=[ "cc-author-x-1" ],
                                   runner=_OK_RUNNER, session_dir=sd, **_NOOP )
        assert res[ "branch_alarm" ]    is None
        assert res[ "branch_outcomes" ] == {}


def test_a_fully_merged_fleet_produces_no_alarm():
    """The quiet case stays quiet, so the line means something when it appears."""
    with tempfile.TemporaryDirectory() as tmp:
        sd, mgr = _setup( tmp )
        res = ss.dismiss_sessions(
            mgr, session_names=[ "cc-author-x-1" ], runner=_OK_RUNNER, session_dir=sd,
            branch_probe_fn=lambda ids: {
                n: { "status": "merged", "persona": "Maya", "commits": 0, "branch": "b" }
                for n in ids },
            **_NOOP )
        assert res[ "branch_alarm" ] is None
        assert res[ "branch_outcomes" ][ "cc-author-x-1" ][ "status" ] == "merged"
