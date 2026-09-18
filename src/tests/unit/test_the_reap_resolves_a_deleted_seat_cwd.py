"""
A reap must still find a seat's memento after the seat's own teardown DELETED its tree.

THE INCIDENT (María 🌸, 2026-09-18). `dismiss_sessions` reported Rachel's seat
(cc-reviewer-maria-1, session 50a277fa) as having no memento while
`io/mementos/rachel-50a277fa.md` sat in the MAIN checkout. The seat's session-end
teardown had already run `git worktree remove` on its cwd, so `seat_repo_root` asked git
about a directory that no longer existed, got nothing, and fell back to the cwd verbatim —
checking `<deleted worktree>/io/mementos/`.

THE CURE UNDER TEST: a missing absolute cwd resolves from its nearest EXISTING ancestor. A
seat tree lives under `<repo>/.claude/worktrees/`, which is inside the main checkout, so the
walk lands on the repo the memento writer used.

⚠️ THE SECOND ARM IS WHAT KEEPS ROW 80b930e6 CLOSED. A walk that landed on LUPIN_ROOT, or on
any repo but the seat's own, would pass arm 1 for a lupin seat and silently send every
non-lupin seat to lupin's slot. Arm 2 deletes a worktree of a DIFFERENT repo and requires
that repo back.

⚠️ REAL GIT, REAL WORKTREES, REALLY REMOVED — for the reason the sibling file gives: the
defect lives in what git answers from a missing directory, so a canned `run_fn` would agree
with whatever the implementation asked it.
"""

import datetime
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from lupin_mcp.reap_memento import ( DEFAULT_MIN_BYTES, seat_memento_slot, seat_repo_root,
                                     verify_seat_memento_at_any_readable_slot )


pytestmark = pytest.mark.skipif( shutil.which( "git" ) is None,
                                 reason="this case drives the real git binary" )

PERSONA = "Rachel"
SID8    = "50a277fa"


def _git( *argv, cwd ):
    subprocess.run( [ "git", *argv ], cwd=str( cwd ), check=True,
                    capture_output=True, text=True )


def _repo( root ):
    root.mkdir( parents=True )
    _git( "init", "-q", ".", cwd=root )
    _git( "config", "user.email", "t@t", cwd=root )
    _git( "config", "user.name",  "t",   cwd=root )
    ( root / "README.md" ).write_text( "seed\n", encoding="utf-8" )
    _git( "add", "-A", cwd=root )
    _git( "commit", "-qm", "seed", cwd=root )
    return root


def _removed_seat_tree( repo, name ):
    """A seat worktree in the real layout, then removed the way the teardown removes it."""
    tree = repo / ".claude" / "worktrees" / name
    _git( "worktree", "add", "-q", str( tree ), "-b", f"{name}-branch", cwd=repo )
    assert tree.is_dir(), "fixture check: the worktree was never created"
    _git( "worktree", "remove", str( tree ), cwd=repo )
    assert not tree.exists(), "fixture check: the worktree was not removed"
    return tree


def _write_memento( repo_root, now ):
    slot = Path( seat_memento_slot( str( repo_root ), PERSONA ) )
    slot.parent.mkdir( parents=True, exist_ok=True )
    header = ( f"<!-- memento-record: persona={PERSONA.lower()} session_id={SID8} "
               f"written_at={now.isoformat()} slot=io -->\n" )
    body   = "board state: the reap must find this after the seat's tree is gone.\n" * 30
    slot.write_text( header + body, encoding="utf-8" )
    assert len( slot.read_bytes() ) > DEFAULT_MIN_BYTES, "fixture is under the completeness floor"
    return slot


def _read_text_fn( path ):
    p = Path( path )
    return p.read_text( encoding="utf-8" ) if p.is_file() else None


def _verify_from( repo_root, now ):
    return verify_seat_memento_at_any_readable_slot(
        str( repo_root ), PERSONA, SID8, now,
        read_text_fn=_read_text_fn, merge_claim_fn=lambda text, root: None )


# ---------------------------------------------------------------------------
# ARM 1 — THE INCIDENT: a removed lupin-layout seat tree resolves to its main checkout
# ---------------------------------------------------------------------------
def test_a_deleted_worktree_cwd_resolves_to_its_main_checkout_and_finds_the_memento( tmp_path ):
    main = _repo( tmp_path / "main" )
    gone = _removed_seat_tree( main, "seat-cc-reviewer-maria-1" )
    now  = datetime.datetime.now().astimezone()
    slot = _write_memento( main, now )

    said     = []
    resolved = seat_repo_root( { "cwd": str( gone ) }, warn_fn=said.append )

    assert Path( resolved ) == main, f"a deleted seat cwd did not resolve to its repo: {resolved!r}"
    usable, reason, answered = _verify_from( resolved, now )
    assert usable is True, reason
    assert Path( answered ) == slot
    assert len( said ) == 1 and str( gone ) in said[ 0 ], \
        f"resolving from an ancestor must say so, naming the gone cwd: {said}"


# ---------------------------------------------------------------------------
# ARM 2 — ROW 80b930e6: a deleted cwd in a DIFFERENT repo resolves to THAT repo
# ---------------------------------------------------------------------------
def test_a_deleted_cwd_in_a_different_repo_resolves_to_that_repo_never_lupin_root( tmp_path, monkeypatch ):
    lupin = _repo( tmp_path / "lupin" )
    other = _repo( tmp_path / "lupin-mobile" )
    monkeypatch.setenv( "LUPIN_ROOT", str( lupin ) )
    gone  = _removed_seat_tree( other, "seat-cc-author-x-1" )
    now   = datetime.datetime.now().astimezone()
    slot  = _write_memento( other, now )

    resolved = seat_repo_root( { "cwd": str( gone ) }, warn_fn=lambda message: None )

    assert Path( resolved ) == other
    assert Path( resolved ) != lupin, "a non-lupin seat was resolved to LUPIN_ROOT"
    usable, reason, answered = _verify_from( resolved, now )
    assert usable is True, reason
    assert Path( answered ) == slot


# ---------------------------------------------------------------------------
# ARM 3 — the fallbacks that must not change
# ---------------------------------------------------------------------------
def test_a_deleted_cwd_with_no_repo_above_it_still_returns_the_cwd_verbatim( tmp_path ):
    gone = tmp_path / "no-repo-here" / "gone" / "deeper"          # never created
    said = []

    got = seat_repo_root( { "cwd": str( gone ) }, warn_fn=said.append )

    assert got == str( gone )
    assert any( str( tmp_path ) in message for message in said ), \
        f"the walk must name the ancestor it tried: {said}"


def test_a_relative_missing_cwd_is_never_walked_to_the_process_cwd( tmp_path, monkeypatch ):
    """Its ancestors are the process cwd — here a real repo, which the walk must NOT land on."""
    monkeypatch.chdir( _repo( tmp_path / "ambient" ) )
    asked = []

    got = seat_repo_root( { "cwd": "gone/seat" },
                          repo_root_fn=lambda start: asked.append( start ) or None,
                          warn_fn=lambda message: None )

    assert got == "gone/seat"
    assert asked == [ "gone/seat" ], f"a relative cwd was resolved from somewhere else: {asked}"


def test_a_missing_cwd_with_no_existing_ancestor_resolves_the_cwd_itself():
    """Only reachable through the seam — `/` always exists on a real filesystem."""
    asked = []
    said  = []

    got = seat_repo_root( { "cwd": "/gone/seat" },
                          repo_root_fn=lambda start: asked.append( start ) or None,
                          warn_fn=said.append,
                          exists_fn=lambda path: False )

    assert got   == "/gone/seat"
    assert asked == [ "/gone/seat" ]
    assert said  == [], f"no ancestor was used, so there is nothing to announce: {said}"


def test_an_existing_cwd_is_resolved_directly_and_silently( tmp_path ):
    main = _repo( tmp_path / "main" )
    said = []

    assert Path( seat_repo_root( { "cwd": str( main ) }, warn_fn=said.append ) ) == main
    assert said == []
