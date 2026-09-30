"""
A reap must not silently delete gitignored files that are somebody's data.

MEASURED 2026-09-14 (row 033538f6): a worktree holding ONLY a gitignored
`.claude-memento.md` showed `git status --porcelain` = 0 lines, and a plain
`git worktree remove` (no --force) exited 0 and DELETED it. `drain_then_remove` stages
with `git add -A`, which respects .gitignore, so its WIP commit never saw the file either.
Every reap — TFE, BFE and the janitor — was losing ignored files without a word.

The rule (Mr. Radio's review, adopted): REFUSE, don't dump into a salvage folder, since a
salvage folder is the same pile moved to where nobody reads it. Build artifacts and
symlinks never block. A root-slot memento RECORD never blocks when its mirror is
byte-identical, because memento_io writes the root slot into the seat's OWN tree by design
and the mirror is the durable copy. Its POINTER never blocks when the record it NAMES
cleared.

⚠️ THE MEMENTO FIXTURE IS A REAL `memento_io.py write` FROM INSIDE A REAL WORKTREE, not a
hand-planted file. Mr. Radio named the trap: the mirror is keyed on the repo basename
memento_io resolves, and a reaper that guesses a different basename reads "no mirror",
which fails closed but refuses EVERY reap. A hand-planted mirror would agree with whatever
the reaper guessed and prove nothing.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from cosa.agents.shared import worktree_reaper as wr


PIP_ROOT      = os.environ.get( "PLANNING_IS_PROMPTING_ROOT", "" )
MEMENTO_IO    = Path( PIP_ROOT ) / "workflow" / "scripts" / "memento_io.py"
IGNORES       = "\n".join( [ ".claude/worktrees/", "io/", "tmp/", "node_modules/", ".claude-session.md", ".claude-memento.md",
                             ".claude-memento-*.md", "" ] )


def _git( *args, cwd ):
    return subprocess.run( [ "git", *args ], cwd=cwd, capture_output=True, text=True )


@pytest.fixture
def repo_and_tree( tmp_path, monkeypatch ):
    """A real main checkout named `lupin`, and a real linked worktree in the seat lane."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv( "HOME", str( home ) )
    monkeypatch.setenv( "LUPIN_MEMENTO_MIRROR_HOME", str( home / ".claude" / "mementos" ) )

    main = tmp_path / "projects" / "lupin"
    main.mkdir( parents=True )
    ( main / ".gitignore" ).write_text( IGNORES )
    ( main / "README.md" ).write_text( "seed\n" )
    _git( "init", "-q", "-b", "main", cwd=main )
    _git( "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A", cwd=main )
    _git( "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "seed", cwd=main )

    tree = main / ".claude" / "worktrees" / "seat-cc-author-maria-1"
    tree.parent.mkdir( parents=True )
    added = _git( "worktree", "add", "-q", "--detach", str( tree ), "HEAD", cwd=main )
    assert added.returncode == 0, added.stderr
    return main, tree, home


def _memento_write( tree, home, persona="maria", sid="ee680ab6" ):
    """Run the REAL memento_io CLI from inside the worktree, exactly as a seat does."""
    return subprocess.run(
        [ sys.executable, str( MEMENTO_IO ), "write", "--slot", "root", "--persona", persona,
          "--session-id", sid, "--allow-foreign-session-id" ],
        input="# Memento\n\nbody text\n", cwd=tree, capture_output=True, text=True,
        env=dict( os.environ, HOME=str( home ) ) )


def _reap( main, tree ):
    return wr.drain_then_remove( str( tree ), project_root=str( main ) )


needs_memento_io = pytest.mark.skipif(
    not MEMENTO_IO.is_file(),
    reason="PLANNING_IS_PROMPTING_ROOT is unset or has no workflow/scripts/memento_io.py — the memento "
           "arms need the REAL writer, and a hand-planted mirror would prove nothing" )


# ---------------------------------------------------------------------------
# THE DEFECT
# ---------------------------------------------------------------------------
def test_an_ignored_data_file_refuses_the_removal_and_leaves_the_tree_untouched( repo_and_tree ):
    main, tree, _ = repo_and_tree
    ( tree / "io" ).mkdir()
    ( tree / "io" / "results.json" ).write_text( "{}\n" )
    assert _git( "status", "--porcelain", cwd=tree ).stdout == "", \
        "premise: git status must be blind to the file, or this is not the measured defect"

    result = _reap( main, tree )

    assert result[ "removed" ] is False
    assert result[ "skipped_reason" ] == "ignored_files_present"
    assert result[ "ignored_blockers" ] == [ "io/results.json" ]
    assert ( tree / "io" / "results.json" ).read_text() == "{}\n"
    assert result[ "rescue_branch" ] is None, "a refused tree must be left exactly as found"
    assert "rescue" not in _git( "branch", "--list", cwd=main ).stdout


def test_a_refused_tree_gets_no_wip_commit_even_with_tracked_edits( repo_and_tree ):
    """Mr. Radio's arm: the ignored check runs BEFORE the WIP commit. Move it after, and a
    refused tree would carry a rescue branch and a WIP commit it never asked for."""
    main, tree, _ = repo_and_tree
    head_before = _git( "rev-parse", "HEAD", cwd=tree ).stdout
    ( tree / "README.md" ).write_text( "edited\n" )
    ( tree / "io" ).mkdir()
    ( tree / "io" / "results.json" ).write_text( "{}\n" )

    result = _reap( main, tree )

    assert result[ "skipped_reason" ] == "ignored_files_present"
    assert result[ "wip_committed" ] is False and result[ "rescue_branch" ] is None
    assert _git( "rev-parse", "HEAD", cwd=tree ).stdout == head_before
    assert ( tree / "README.md" ).read_text() == "edited\n"


def test_a_trees_own_run_output_does_not_block( repo_and_tree ):
    """Ruled with Mr. Radio on the 233-tree census: io/test-suite, io/swe-team,
    io/claude_code_hooks, tmp/ and a root .claude-session.md are the tree's own run output."""
    main, tree, _ = repo_and_tree
    for rel in ( "io/test-suite/run-1/results.json", "io/swe-team/reports/r.md",
                 "io/claude_code_hooks/logs/h.jsonl", "tmp/scratch.txt" ):
        ( tree / rel ).parent.mkdir( parents=True, exist_ok=True )
        ( tree / rel ).write_text( "x\n" )
    ( tree / ".claude-session.md" ).write_text( "# manifest\n" )
    with open( tree / ".git" ) as fh: pass                     # premise: a linked worktree
    ignores = ( main / ".gitignore" ).read_text()
    assert "io/" in ignores

    result = _reap( main, tree )

    assert result[ "ignored_blockers" ] == [], result
    assert result[ "removed" ] is True, result


def test_run_output_beside_real_data_in_io_blocks_on_the_data_alone( repo_and_tree ):
    """io/ is expanded and judged file by file: the run output passes, the data blocks."""
    main, tree, _ = repo_and_tree
    ( tree / "io" / "test-suite" ).mkdir( parents=True )
    ( tree / "io" / "test-suite" / "r.json" ).write_text( "x\n" )
    ( tree / "io" / "census-by-hand.tsv" ).write_text( "x\n" )
    result = _reap( main, tree )
    assert result[ "ignored_blockers" ] == [ "io/census-by-hand.tsv" ]


def test_the_legacy_memento_slot_blocks_because_it_has_no_mirror_guarantee( repo_and_tree ):
    main, tree, _ = repo_and_tree
    ( tree / ".claude-memento.md" ).write_text( "# old memento\n" )
    result = _reap( main, tree )
    assert result[ "skipped_reason" ] == "ignored_files_present"
    assert ( tree / ".claude-memento.md" ).exists()


def test_a_tree_with_nothing_ignored_is_still_reaped( repo_and_tree ):
    """CONTROL — the refusal must not turn into "never reap anything"."""
    main, tree, _ = repo_and_tree
    result = _reap( main, tree )
    assert result[ "removed" ] is True, result
    assert not tree.exists()


def test_build_artifacts_and_symlinks_never_block( repo_and_tree ):
    main, tree, _ = repo_and_tree
    ( tree / "node_modules" / "tsx" ).mkdir( parents=True )
    ( tree / "node_modules" / "tsx" / "index.js" ).write_text( "x\n" )
    ( tree / "io" ).symlink_to( main )        # a borrowed artifact is a symlink
    result = _reap( main, tree )
    assert result[ "removed" ] is True, result
    assert main.exists(), "removing a symlink must never touch its target"


# ---------------------------------------------------------------------------
# THE ROOT-SLOT MEMENTO — written for real, from inside the worktree
# ---------------------------------------------------------------------------
@needs_memento_io
def test_a_real_root_slot_memento_with_its_mirror_does_not_block( repo_and_tree ):
    main, tree, home = repo_and_tree
    wrote = _memento_write( tree, home )
    assert wrote.returncode == 0, wrote.stderr
    assert ( tree / ".claude-memento-maria-ee680ab6.md" ).is_file(), "premise: the root slot lands in the tree"
    assert ( tree / ".claude-memento-maria.md" ).is_file(),          "premise: its pointer lands beside it"

    result = _reap( main, tree )

    assert result[ "ignored_blockers" ] == [], result
    assert result[ "removed" ] is True, result


@needs_memento_io
def test_a_record_whose_mirror_differs_blocks( repo_and_tree ):
    main, tree, home = repo_and_tree
    assert _memento_write( tree, home ).returncode == 0
    mirror = home / ".claude" / "mementos" / "lupin" / ".claude-memento-maria-ee680ab6.md"
    assert mirror.is_file(), "premise: the mirror is keyed on the MAIN checkout's basename"
    mirror.write_text( "diverged\n" )

    result = _reap( main, tree )

    assert result[ "skipped_reason" ] == "ignored_files_present"
    assert ".claude-memento-maria-ee680ab6.md" in result[ "ignored_blockers" ]


@needs_memento_io
def test_a_pointer_clears_only_when_the_record_it_names_cleared( repo_and_tree ):
    """Mr. Radio's refinement: not merely "some record for this persona cleared"."""
    main, tree, home = repo_and_tree
    assert _memento_write( tree, home ).returncode == 0
    pointer = tree / ".claude-memento-maria.md"
    lines   = pointer.read_text().splitlines( keepends=True )
    assert lines[ 1 ].startswith( "<!-- current: " ), "premise: memento_io's pointer header shape"
    lines[ 1 ] = "<!-- current: .claude-memento-maria-00000000.md -->\n"
    pointer.write_text( "".join( lines ) )

    result = _reap( main, tree )

    assert result[ "ignored_blockers" ] == [ ".claude-memento-maria.md" ]
