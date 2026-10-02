"""
The janitor empties a tree instead of refusing it, and archives a branch instead of
keeping it forever (row aec2319f, Rick's rulings of 2026-10-02).

Measured that day in lupin: 6 of 6 remaining seat trees were refused for holding ignored
files, and 6 extra branches read as unmerged with nobody owning them. Four of the six
forked from a line that PR 22 squash-merged, so ancestry would call them unmerged forever.

What these tests hold the reaper to, against real git:
    - ignored data is MOVED to a dated folder outside the tree, never deleted with it
    - an unmerged branch leaves `git branch` and its tip stays reachable under refs/archive
    - the outcome says whether the work had already landed by content
    - the 14-day sweep deletes only dated archive refs and dated evacuation folders past
      the window
"""

import os
import subprocess
import time
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

import cosa.agents.shared.worktree_reaper as wr


NOW = datetime( 2026, 10, 2, 15, 0, 0, tzinfo=timezone.utc )


def _git( cwd, *args ):
    return subprocess.run( [ "git", *args ], cwd=cwd, capture_output=True, text=True, timeout=60 )


def _out( cwd, *args ):
    done = _git( cwd, *args )
    assert done.returncode == 0, done.stderr
    return done.stdout.strip()


def _commit( cwd, name, text="x\n" ):
    ( cwd / name ).write_text( text )
    _out( cwd, "add", "-A" )
    _out( cwd, "commit", "-q", "-m", f"add {name}" )
    return _out( cwd, "rev-parse", "HEAD" )


def _has_branch( repo, branch ):
    return _git( repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}" ).returncode == 0


def _refs( repo, prefix ):
    return _out( repo, "for-each-ref", "--format=%(refname) %(objectname)", prefix ).splitlines()


@pytest.fixture
def repo( tmp_path, monkeypatch ):
    """A real repo on a WIP branch, ignoring io/ and *.log, with a janitor lane."""
    monkeypatch.setenv( "LUPIN_MEMENTO_MIRROR_HOME", str( tmp_path / "no-mirror" ) )
    root = tmp_path / "repo"
    root.mkdir()
    _out( root, "init", "-q", "-b", "wip-v9" )
    _out( root, "config", "user.email", "t@example.com" )
    _out( root, "config", "user.name", "T" )
    ( root / ".gitignore" ).write_text( "io/\n*.log\n.claude/\nsrc/docs/index/\n" )
    _commit( root, "README.md", "seed\n" )
    ( root / ".claude" / "worktrees" ).mkdir( parents=True )
    return root


def _tree( repo, name, branch=None ):
    path = repo / ".claude" / "worktrees" / name
    args = [ "worktree", "add", "-q" ] + ( [ "-b", branch ] if branch else [ "--detach" ] ) + [ str( path ), "HEAD" ]
    _out( repo, *args )
    return path


def _age( path, hours=7 ):
    # Aged against NOW, the clock the janitor is handed, never the wall clock. Measured against
    # time.time() this drifted: 7h before the real time is under 6h before NOW once the real
    # time passes NOW + 1h, and the tree stopped being swept (red from 12:00 EDT 2026-10-02).
    old = NOW.timestamp() - hours * 3600
    for p in path.rglob( "*" ):
        if p.is_file() and p.name != ".git":
            os.utime( p, ( old, old ) )


def _data( tree ):
    """Two ignored data files and one piece of regenerable output, as a seat leaves them."""
    ( tree / "io" / "write-ups" ).mkdir( parents=True )
    ( tree / "io" / "write-ups" / "finding.md" ).write_text( "a real finding\n" )
    ( tree / "notes.log" ).write_text( "kept by hand\n" )
    ( tree / "src" / "docs" / "index" ).mkdir( parents=True )
    ( tree / "src" / "docs" / "index" / "symbols.md" ).write_text( "generated\n" )


# ── evacuation ───────────────────────────────────────────────────────────────

def test_without_an_evacuation_root_the_drain_still_refuses_and_touches_nothing( repo ):
    tree = _tree( repo, "seat-a", "feat-a" )
    _data( tree )

    result = wr.drain_then_remove( str( tree ), project_root=str( repo ), now=NOW )

    assert ( result[ "removed" ], result[ "skipped_reason" ] ) == ( False, "ignored_files_present" )
    assert sorted( result[ "ignored_blockers" ] ) == [ "io/write-ups/finding.md", "notes.log" ]
    assert ( result[ "evacuated_to" ], result[ "evacuated" ] ) == ( None, [] )
    assert ( tree / "notes.log" ).read_text() == "kept by hand\n"


def test_with_an_evacuation_root_the_data_moves_out_and_the_tree_goes( repo, tmp_path ):
    tree = _tree( repo, "seat-a", "feat-a" )
    _data( tree )
    evac = tmp_path / "evacuated"

    result = wr.drain_then_remove( str( tree ), project_root=str( repo ), now=NOW, evacuation_root=str( evac ) )

    dest = evac / "2026-10-02-seat-a-20261002T150000Z"
    assert result[ "removed" ] is True and not tree.exists()
    assert result[ "evacuated_to" ] == str( dest )
    assert sorted( result[ "evacuated" ] ) == [ "io/write-ups/finding.md", "notes.log" ]
    assert ( dest / "io" / "write-ups" / "finding.md" ).read_text() == "a real finding\n"
    assert ( dest / "notes.log" ).read_text() == "kept by hand\n"
    assert not ( dest / "src" ).exists(), "the generated index is regenerable: it goes with the tree, it is not evacuated"
    assert [ p.name for p in evac.iterdir() ] == [ dest.name ]


def test_a_clean_tree_is_removed_and_no_evacuation_folder_is_made( repo, tmp_path ):
    tree = _tree( repo, "seat-clean", "feat-clean" )
    evac = tmp_path / "evacuated"

    result = wr.drain_then_remove( str( tree ), project_root=str( repo ), now=NOW, evacuation_root=str( evac ) )

    assert result[ "removed" ] is True
    assert ( result[ "evacuated_to" ], result[ "evacuated" ] ) == ( None, [] )
    assert not evac.exists()


def test_an_existing_evacuation_folder_is_never_merged_into_and_the_tree_stays( repo, tmp_path ):
    tree = _tree( repo, "seat-a", "feat-a" )
    _data( tree )
    evac  = tmp_path / "evacuated"
    taken = evac / "2026-10-02-seat-a-20261002T150000Z"
    taken.mkdir( parents=True )
    ( taken / "earlier.txt" ).write_text( "from an earlier reap\n" )

    result = wr.drain_then_remove( str( tree ), project_root=str( repo ), now=NOW, evacuation_root=str( evac ) )

    assert ( result[ "removed" ], result[ "skipped_reason" ] ) == ( False, "evacuation_failed" )
    assert "already exists" in result[ "errors" ][ 0 ]
    assert result[ "evacuated" ] == []
    assert sorted( result[ "ignored_blockers" ] ) == [ "io/write-ups/finding.md", "notes.log" ]
    assert tree.exists() and ( tree / "notes.log" ).exists()
    assert [ p.name for p in taken.iterdir() ] == [ "earlier.txt" ]
    assert not _has_branch( repo, "wt-rescue/seat-a-20261002T150000Z" )


def test_a_move_that_fails_partway_reports_what_moved_and_leaves_the_rest( tmp_path, monkeypatch ):
    tree = tmp_path / "tree"
    tree.mkdir()
    ( tree / "a.txt" ).write_text( "a\n" )
    ( tree / "b.txt" ).write_text( "b\n" )
    real_move = wr.shutil.move

    def flaky( src, dst ):
        if src.endswith( "b.txt" ):
            raise OSError( "disk full" )
        return real_move( src, dst )
    monkeypatch.setattr( wr.shutil, "move", flaky )

    out = wr.evacuate_blockers( str( tree ), [ "a.txt", "b.txt" ], str( tmp_path / "evac" ), "20261002T150000Z" )

    assert out[ "ok" ] is False
    assert out[ "moved" ] == [ "a.txt" ]
    assert out[ "error" ] == "could not move b.txt: disk full"
    assert ( tree / "b.txt" ).exists() and not ( tree / "a.txt" ).exists()
    assert ( tmp_path / "evac" / "2026-10-02-tree-20261002T150000Z" / "a.txt" ).read_text() == "a\n"


def test_a_directory_blocker_moves_whole( tmp_path ):
    tree = tmp_path / "tree"
    ( tree / "data" / "deep" ).mkdir( parents=True )
    ( tree / "data" / "deep" / "f.txt" ).write_text( "f\n" )

    out = wr.evacuate_blockers( str( tree ), [ "data/" ], str( tmp_path / "evac" ), "20261002T150000Z" )

    assert ( out[ "ok" ], out[ "moved" ] ) == ( True, [ "data/" ] )
    assert ( tmp_path / "evac" / "2026-10-02-tree-20261002T150000Z" / "data" / "deep" / "f.txt" ).read_text() == "f\n"
    assert not ( tree / "data" ).exists()


def test_the_janitor_evacuates_into_the_main_trees_io_by_default( repo ):
    tree = _tree( repo, "seat-b", "feat-b" )
    _data( tree )
    _out( repo, "merge", "-q", "--ff-only", "feat-b" )
    _age( tree )

    out = wr.reconcile_worktrees( project_root=str( repo ), age_threshold_hours=6.0, now=NOW )

    assert wr.default_evacuation_root( str( repo ) ) == str( repo / "io" / "worktree-evacuated" )
    result = out[ "swept" ][ 0 ][ "result" ]
    assert result[ "removed" ] is True and not tree.exists()
    assert result[ "evacuated_to" ] == str( repo / "io" / "worktree-evacuated" / "2026-10-02-seat-b-20261002T150000Z" )
    assert ( repo / "io" / "worktree-evacuated" / "2026-10-02-seat-b-20261002T150000Z" / "notes.log" ).exists()
    assert out[ "errors" ] == []


def test_an_injected_drain_is_called_exactly_as_before( repo ):
    tree = _tree( repo, "seat-c", "feat-c" )
    _age( tree )
    seen = []

    def drain_fn( path, project_root=None, run=None, now=None, debug=False ):
        seen.append( path )
        return { "removed": False }

    wr.reconcile_worktrees( project_root=str( repo ), age_threshold_hours=6.0, drain_fn=drain_fn )
    assert seen == [ str( tree ) ]


# ── archive ──────────────────────────────────────────────────────────────────

def test_an_unmerged_branch_is_archived_with_its_tip_and_marked_not_landed( repo ):
    tree = _tree( repo, "seat-d", "feat-d" )
    tip  = _commit( tree, "work.txt" )
    _out( repo, "worktree", "remove", str( tree ) )

    outcome = wr.retire_branch( str( repo ), "feat-d", "wip-v9", now=NOW )

    assert ( outcome[ "deleted" ], outcome[ "kept_reason" ], outcome[ "commits_ahead" ] ) == ( False, "archived", 1 )
    assert outcome[ "archive_ref" ] == "refs/archive/2026-10-02/feat-d"
    assert ( outcome[ "sha" ], outcome[ "landed" ], outcome[ "error" ] ) == ( tip, False, None )
    assert not _has_branch( repo, "feat-d" )
    assert _refs( repo, "refs/archive" ) == [ f"refs/archive/2026-10-02/feat-d {tip}" ]
    # the documented restore brings it back whole
    _out( repo, "update-ref", "refs/heads/feat-d", tip )
    assert _out( repo, "show", "feat-d:work.txt" ) == "x"


def test_work_that_landed_by_cherry_pick_is_archived_and_marked_landed( repo ):
    tree = _tree( repo, "seat-e", "feat-e" )
    tip  = _commit( tree, "picked.txt" )
    _out( repo, "worktree", "remove", str( tree ) )
    _commit( repo, "elsewhere.txt" )                 # the line moves on, so the pick is a new commit
    _out( repo, "cherry-pick", tip )

    outcome = wr.retire_branch( str( repo ), "feat-e", "wip-v9", now=NOW )

    assert ( outcome[ "kept_reason" ], outcome[ "landed" ] ) == ( "archived", True )
    assert wr.merge_verdict( str( repo ), tip, "refs/heads/wip-v9", wr._default_run )[ "verdict" ] == "unmerged"


def test_a_merged_or_protected_branch_takes_the_old_path_and_nothing_is_archived( repo ):
    tree = _tree( repo, "seat-f", "feat-f" )
    _commit( tree, "done.txt" )
    _out( repo, "worktree", "remove", str( tree ) )
    _out( repo, "merge", "-q", "--ff-only", "feat-f" )
    _out( repo, "branch", "wip-old-line" )

    merged    = wr.retire_branch( str( repo ), "feat-f", "wip-v9", now=NOW )
    protected = wr.retire_branch( str( repo ), "wip-old-line", "wip-v9", now=NOW )

    assert ( merged[ "deleted" ], merged[ "kept_reason" ] ) == ( True, None )
    assert protected[ "kept_reason" ] == "protected" and _has_branch( repo, "wip-old-line" )
    assert "archive_ref" not in merged and "archive_ref" not in protected
    assert _refs( repo, "refs/archive" ) == []


def test_a_second_archive_of_the_same_name_on_one_day_does_not_overwrite_the_first( repo ):
    first = _commit( repo, "one.txt" )
    _out( repo, "branch", "again", first )
    _out( repo, "reset", "-q", "--hard", "HEAD~1" )
    a = wr.archive_branch( str( repo ), "again", wr._default_run, now=NOW )

    second = _commit( repo, "two.txt" )
    _out( repo, "branch", "again", second )
    _out( repo, "reset", "-q", "--hard", "HEAD~1" )
    b = wr.archive_branch( str( repo ), "again", wr._default_run, now=NOW )

    assert ( a[ "archived" ], a[ "archive_ref" ] ) == ( True, "refs/archive/2026-10-02/again" )
    assert ( b[ "archived" ], b[ "archive_ref" ] ) == ( True, f"refs/archive/2026-10-02/again-{second[ :9 ]}" )
    assert sorted( _refs( repo, "refs/archive" ) ) == sorted( [
        f"refs/archive/2026-10-02/again {first}",
        f"refs/archive/2026-10-02/again-{second[ :9 ]} {second}",
    ] )


def test_re_archiving_the_same_tip_reuses_the_ref( repo ):
    tip = _out( repo, "rev-parse", "HEAD" )
    _out( repo, "update-ref", "refs/archive/2026-10-02/same", tip )
    _out( repo, "branch", "same", tip )

    out = wr.archive_branch( str( repo ), "same", wr._default_run, now=NOW )

    assert ( out[ "archived" ], out[ "archive_ref" ] ) == ( True, "refs/archive/2026-10-02/same" )
    assert not _has_branch( repo, "same" )


def test_archiving_a_branch_that_does_not_exist_reports_it( repo ):
    out = wr.archive_branch( str( repo ), "no-such-branch", wr._default_run, now=NOW )
    assert ( out[ "archived" ], out[ "archive_ref" ], out[ "sha" ] ) == ( False, None, None )
    assert out[ "error" ].startswith( "cannot resolve refs/heads/no-such-branch" )


def _scripted( replies ):
    """A git runner that answers by the first two words of the command; anything else succeeds empty."""
    calls = []

    def run( argv, cwd=None, timeout=60 ):
        calls.append( argv[ 1: ] )
        for key, ( code, text ) in replies.items():
            if tuple( argv[ 1:1 + len( key ) ] ) == key:
                return SimpleNamespace( returncode=code, stdout=text, stderr="scripted failure" if code else "" )
        return SimpleNamespace( returncode=0, stdout="", stderr="" )
    return run, calls


def test_a_failed_archive_write_leaves_the_branch_alone():
    run, calls = _scripted( { ( "rev-parse", "--verify", "-q", "refs/heads/b" ): ( 0, "abc123456789" ),
                              ( "rev-parse", "--verify", "-q", "refs/archive/2026-10-02/b" ): ( 1, "" ),
                              ( "update-ref", "refs/archive/2026-10-02/b" ): ( 1, "" ) } )

    out = wr.archive_branch( "/repo", "b", run, now=NOW )

    assert out[ "archived" ] is False and out[ "archive_ref" ] is None
    assert out[ "error" ] == "could not write refs/archive/2026-10-02/b: scripted failure"
    assert [ "update-ref", "-d", "refs/heads/b", "abc123456789" ] not in calls


def test_a_read_back_that_does_not_match_leaves_the_branch_alone():
    answers = iter( [ "abc123456789", "", "somethingelse" ] )

    def run( argv, cwd=None, timeout=60 ):
        text = next( answers ) if argv[ 1 ] == "rev-parse" else ""
        return SimpleNamespace( returncode=0, stdout=text, stderr="" )

    out = wr.archive_branch( "/repo", "b", run, now=NOW )
    assert out[ "archived" ] is False
    assert out[ "error" ] == "could not write refs/archive/2026-10-02/b: read-back mismatch"


def test_a_branch_that_moved_during_the_archive_is_kept_and_says_so():
    answers = iter( [ "abc123456789", "", "abc123456789" ] )

    def run( argv, cwd=None, timeout=60 ):
        if argv[ 1 ] == "rev-parse":
            return SimpleNamespace( returncode=0, stdout=next( answers ), stderr="" )
        failed = argv[ 1:3 ] == [ "update-ref", "-d" ]
        return SimpleNamespace( returncode=1 if failed else 0, stdout="", stderr="ref moved" if failed else "" )

    out = wr.archive_branch( "/repo", "b", run, now=NOW )
    assert out[ "archived" ] is False
    assert out[ "archive_ref" ] == "refs/archive/2026-10-02/b"
    assert out[ "error" ] == "archived at refs/archive/2026-10-02/b but could not remove the branch: ref moved"


def test_retire_reports_a_failed_archive_and_an_unreadable_content_check( repo ):
    tree = _tree( repo, "seat-g", "feat-g" )
    _commit( tree, "work.txt" )
    _out( repo, "worktree", "remove", str( tree ) )

    def run( argv, cwd=None, timeout=60 ):
        if argv[ 1 ] in ( "cherry", "update-ref" ):
            return SimpleNamespace( returncode=1, stdout="", stderr="scripted failure" )
        return wr._default_run( argv, cwd=cwd, timeout=timeout )

    outcome = wr.retire_branch( str( repo ), "feat-g", "wip-v9", run=run, now=NOW )

    assert ( outcome[ "kept_reason" ], outcome[ "landed" ] ) == ( "archive_failed", None )
    assert outcome[ "error" ] == "could not write refs/archive/2026-10-02/feat-g: scripted failure"
    assert _has_branch( repo, "feat-g" )


# ── the branch sweep reaches unmerged branches, then expires the archive ─────

def test_the_sweep_archives_an_old_unmerged_branch_and_skips_a_young_one( repo ):
    tip = _commit( repo, "orphan.txt" )
    _out( repo, "branch", "old-orphan", tip )
    _out( repo, "branch", "young-orphan", tip )
    _out( repo, "reset", "-q", "--hard", "HEAD~1" )
    ages = { "old-orphan": 0.0, "young-orphan": NOW.timestamp() - 3600 }

    real = wr.branch_created_ts
    try:
        wr.branch_created_ts = lambda root, branch, run: ages[ branch ]
        out = wr.sweep_merged_branches( project_root=str( repo ), now_ts=NOW.timestamp() )
    finally:
        wr.branch_created_ts = real

    assert out[ "error" ] is None and out[ "deleted" ] == []
    assert [ ( k[ "branch" ], k[ "kept_reason" ] ) for k in out[ "kept" ] ] == [ ( "old-orphan", "archived" ) ]
    assert not _has_branch( repo, "old-orphan" ) and _has_branch( repo, "young-orphan" )
    assert out[ "archive_sweep" ] == { "refs_deleted": [], "folders_deleted": [], "errors": [] }


def test_the_archive_sweep_deletes_only_dated_entries_past_the_window( repo, tmp_path ):
    tip = _out( repo, "rev-parse", "HEAD" )
    for ref in ( "refs/archive/2026-09-17/expired", "refs/archive/2026-09-18/on-the-line",
                 "refs/archive/2026-10-02/fresh", "refs/archive/undated/by-hand" ):
        _out( repo, "update-ref", ref, tip )
    evac = tmp_path / "evac"
    for name in ( "2026-09-17-seat-a-20260917T010203Z", "2026-09-18-seat-b-20260918T010203Z",
                  "2026-10-02-seat-c-20261002T150000Z", "keep-me" ):
        ( evac / name ).mkdir( parents=True )
        ( evac / name / "f.txt" ).write_text( "f\n" )
    ( evac / "2026-01-01-a-file-not-a-folder" ).write_text( "left alone\n" )
    os.symlink( str( evac / "keep-me" ), str( evac / "2026-01-02-a-link" ) )

    out = wr.sweep_archive( str( repo ), now=NOW, evacuation_root=str( evac ) )

    # 14 days before 2026-10-02 is 2026-09-18: that day is still inside the window
    assert out == { "refs_deleted": [ "refs/archive/2026-09-17/expired" ],
                    "folders_deleted": [ str( evac / "2026-09-17-seat-a-20260917T010203Z" ) ], "errors": [] }
    assert [ r.split()[ 0 ] for r in _refs( repo, "refs/archive" ) ] == [
        "refs/archive/2026-09-18/on-the-line", "refs/archive/2026-10-02/fresh", "refs/archive/undated/by-hand" ]
    assert sorted( p.name for p in evac.iterdir() ) == [
        "2026-01-01-a-file-not-a-folder", "2026-01-02-a-link", "2026-09-18-seat-b-20260918T010203Z",
        "2026-10-02-seat-c-20261002T150000Z", "keep-me" ]
    assert wr.ARCHIVE_RETENTION_DAYS == 14


def test_the_archive_sweep_with_nothing_to_do_and_no_folder_is_quiet( repo ):
    assert wr.sweep_archive( str( repo ), now=NOW ) == { "refs_deleted": [], "folders_deleted": [], "errors": [] }


def test_the_archive_sweep_reports_what_it_could_not_do( tmp_path, monkeypatch ):
    evac = tmp_path / "evac"
    ( evac / "2026-09-01-seat-a-x" ).mkdir( parents=True )
    run, _ = _scripted( { ( "for-each-ref", ): ( 0, "refs/archive/2026-09-01/a\nrefs/archive/2026-09-01/b" ),
                          ( "update-ref", "-d", "refs/archive/2026-09-01/b" ): ( 1, "" ) } )
    monkeypatch.setattr( wr.shutil, "rmtree", lambda path: ( _ for _ in () ).throw( OSError( "busy" ) ) )

    out = wr.sweep_archive( "/repo", run=run, now=NOW, evacuation_root=str( evac ) )

    assert out[ "refs_deleted" ] == [ "refs/archive/2026-09-01/a" ]
    assert out[ "folders_deleted" ] == []
    assert out[ "errors" ] == [ "could not delete refs/archive/2026-09-01/b: scripted failure",
                                f"could not remove {evac / '2026-09-01-seat-a-x'}: busy" ]


def test_the_archive_sweep_survives_unlistable_refs_and_an_unlistable_folder( tmp_path, monkeypatch ):
    evac = tmp_path / "evac"
    evac.mkdir()
    run, _ = _scripted( { ( "for-each-ref", ): ( 1, "" ) } )
    monkeypatch.setattr( wr.os, "listdir", lambda path: ( _ for _ in () ).throw( OSError( "denied" ) ) )

    out = wr.sweep_archive( "/repo", run=run, now=NOW, evacuation_root=str( evac ) )

    assert out[ "refs_deleted" ] == [] and out[ "folders_deleted" ] == []
    assert out[ "errors" ] == [ "could not list refs/archive: scripted failure", f"could not list {evac}: denied" ]


# ── a failed evacuation is still reported as a refusal ───────────────────────

def test_a_tree_whose_evacuation_failed_is_in_the_refused_set():
    from cosa.agents.shared.worktree_refusal_ledger import refused_set

    out = { "swept": [
        { "path": "/r/.claude/worktrees/a", "result": { "skipped_reason": "evacuation_failed", "ignored_blockers": [ "b.txt", "a.txt" ] } },
        { "path": "/r/.claude/worktrees/b", "result": { "removed": True, "skipped_reason": None, "evacuated": [ "c.txt" ] } },
    ], "skipped": [] }

    assert refused_set( out ) == { "/r/.claude/worktrees/a": [ "a.txt", "b.txt" ] }


# ── an archived branch that never landed gets one row for its manager ────────

class _Store:
    def __init__( self, existing=(), fail_on=None ):
        self.open, self.created, self.fail_on = set( existing ), [], fail_on

    def find_open( self, key ):
        if key == self.fail_on:
            raise RuntimeError( "db down" )
        return "row-1" if key in self.open else None

    def create( self, **row ):
        self.created.append( row )
        return "row-new"


def _archived( branch, landed, root="/repos/lupin-mobile", **extra ):
    return { "branch": branch, "target": "wip-v9", "kept_reason": "archived", "commits_ahead": 3,
             "archive_ref": f"refs/archive/2026-10-02/{branch}", "sha": "abc123", "landed": landed,
             "repo_root": root, **extra }


def test_one_row_per_archived_branch_that_did_not_land_and_none_for_one_that_did():
    from cosa.agents.shared import worktree_straggler_tickets as st
    store, events = _Store(), []
    kept = [
        _archived( "wt-rescue/seat-cc-author-cheech-2-20261002T135947Z", False ),
        _archived( "wt-rescue/landed-by-pick-20261002T135947Z", True ),
        _archived( "krishna-door18", None, root=None ),
        { "branch": "feat-live", "kept_reason": "checked_out" },
    ]

    out = st.open_archive_tickets( kept, store, lambda name, **kw: events.append( ( name, kw ) ) )

    refs = [ "refs/archive/2026-10-02/wt-rescue/seat-cc-author-cheech-2-20261002T135947Z",
             "refs/archive/2026-10-02/krishna-door18" ]
    assert out == { "opened": refs, "adopted": [], "errors": [] }
    assert events == [ ( "worktree_archive_tickets", { "opened": refs, "adopted": [] } ) ]

    seat, stray = store.created
    assert ( seat[ "owner" ], seat[ "accountable" ], seat[ "project" ] ) == ( "cheech", "cheech", "lupin-mobile" )
    assert seat[ "correlation_key" ] == "archive:" + refs[ 0 ]
    assert seat[ "title" ] == "[LUPIN-MOBILE] Archived unmerged branch: wt-rescue/seat-cc-author-cheech-2-20261002T135947Z"
    assert "3 commits ahead of `wip-v9` and holds commits whose content is not on the working branch" in seat[ "body" ]
    assert "git update-ref refs/heads/wt-rescue/seat-cc-author-cheech-2-20261002T135947Z abc123" in seat[ "body" ]
    assert "No creator recorded" not in seat[ "body" ]

    assert ( stray[ "owner" ], stray[ "project" ] ) == ( st.NO_CREATOR_OWNER, "lupin" )
    assert "could not be checked for content already on the working branch" in stray[ "body" ]
    assert "No creator recorded" in stray[ "body" ]


def test_an_open_row_is_adopted_and_a_store_failure_does_not_stop_the_rest():
    from cosa.agents.shared import worktree_straggler_tickets as st
    kept   = [ _archived( "a", False ), _archived( "b", False ), _archived( "c", False, commits_ahead=None ) ]
    store  = _Store( existing={ "archive:refs/archive/2026-10-02/a" }, fail_on="archive:refs/archive/2026-10-02/b" )
    events = []

    out = st.open_archive_tickets( kept, store, lambda name, **kw: events.append( name ) )

    assert out == { "opened": [ "refs/archive/2026-10-02/c" ], "adopted": [ "refs/archive/2026-10-02/a" ],
                    "errors": [ "refs/archive/2026-10-02/b: open failed: db down" ] }
    assert events == [ "worktree_archive_ticket_failed", "worktree_archive_tickets" ]
    assert "an unknown number of commits ahead" in store.created[ 0 ][ "body" ]


def test_a_poll_with_nothing_archived_opens_nothing_and_logs_nothing():
    from cosa.agents.shared import worktree_straggler_tickets as st
    events = []
    assert st.open_archive_tickets( None, _Store(), lambda name, **kw: events.append( name ) ) == \
        { "opened": [], "adopted": [], "errors": [] }
    assert events == []
