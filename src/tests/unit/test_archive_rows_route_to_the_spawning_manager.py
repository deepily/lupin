"""
An archived rescue branch goes to the manager who spawned its worker.

Before the fix, 24 of 25 overnight archive rows landed on maria. Only a seat-cc-<role>-<manager>-<n> name resolved.
The tests hold the lookups in order. First the stamp on the branch, then a seat tree's name.
Last, the spawn registry for a name that begins with a worker persona.
"""
import subprocess
from datetime import datetime, timezone

import pytest

import cosa.agents.shared.worktree_reaper as wr
import cosa.agents.shared.worktree_straggler_tickets as st

NOW    = datetime( 2026, 10, 19, 1, 15, 0, tzinfo=timezone.utc )
STAMPS = "-20261019T011500Z"
REGISTRY = { "arnold": "mr radio", "clayton": "mr radio", "maya": "tiberius" }


def registry( persona ): return REGISTRY.get( persona )


def _outcome( branch, root=None ):
    return { "branch": branch, "target": "wip-v9", "kept_reason": "archived", "commits_ahead": 2, "landed": False,
             "archive_ref": f"refs/archive/2026-10-19/{branch}", "sha": "abc123", "repo_root": root }


@pytest.fixture
def live_registry( monkeypatch ):
    monkeypatch.setattr( st, "spawn_registry_manager", registry )


def _g( cwd, *args ):
    done = subprocess.run( [ "git", *args ], cwd=cwd, capture_output=True, text=True, timeout=60 )
    assert done.returncode == 0, done.stderr
    return done.stdout.strip()


@pytest.fixture
def repo( tmp_path, monkeypatch ):
    monkeypatch.setenv( "LUPIN_MEMENTO_MIRROR_HOME", str( tmp_path / "no-mirror" ) )
    root = tmp_path / "repo"; root.mkdir()
    _g( root, "init", "-q", "-b", "wip-v9" )
    _g( root, "config", "user.email", "t@example.com" ); _g( root, "config", "user.name", "T" )
    ( root / ".gitignore" ).write_text( ".claude/\n" )
    ( root / "README.md" ).write_text( "seed\n" )
    _g( root, "add", "-A" ); _g( root, "commit", "-q", "-m", "seed" )
    ( root / ".claude" / "worktrees" ).mkdir( parents=True )
    return root


# ── the lookups, in order ───────────────────────────────────────────────────

def test_a_stamped_branch_goes_to_its_stamped_manager( repo, live_registry ):
    branch = f"wt-rescue/rev-c9{STAMPS}"                                    # a bare name no other lookup can read
    assert st.write_stamp( str( repo ), branch, "tiberius" ) is True
    who = st.owner_for_branch( branch, project_root=str( repo ) )
    assert ( who[ "owner" ], who[ "accountable" ], who[ "creator_recorded" ], who[ "source" ] ) == ( "tiberius", "tiberius", True, "branch stamp" )


def test_the_stamp_wins_over_a_worker_name( repo, live_registry ):
    branch = f"wt-rescue/arnold-review-ab12cd3{STAMPS}"
    st.write_stamp( str( repo ), branch, "cheech" )
    assert st.owner_for_branch( branch, project_root=str( repo ) )[ "owner" ] == "cheech"


def test_a_worker_named_branch_goes_to_the_manager_who_spawned_that_worker( repo, live_registry ):
    who = st.owner_for_branch( f"wt-rescue/arnold-review-ab12cd3{STAMPS}", project_root=str( repo ) )
    assert ( who[ "owner" ], who[ "source" ] ) == ( "mr radio", "spawn registry" )
    assert st.owner_for_branch( f"clayton-twin-ab12cd3{STAMPS}", project_root=str( repo ) )[ "owner" ] == "mr radio"
    assert st.owner_for_branch( f"maya-review-a1{STAMPS}", project_root=str( repo ) )[ "owner" ] == "tiberius"


def test_a_bare_name_without_a_stamp_stays_with_maria_and_the_row_lists_the_lookups( repo, live_registry ):
    who = st.owner_for_branch( f"wt-rescue/rev-c9{STAMPS}", project_root=str( repo ) )
    assert ( who[ "owner" ], who[ "creator_recorded" ], who[ "source" ] ) == ( st.NO_CREATOR_OWNER, False, None )
    assert who[ "tried" ] == [ "branch stamp", "seat tree name", "spawn registry for 'rev'" ]
    body = st.compose_archive_row( _outcome( f"wt-rescue/rev-c9{STAMPS}", str( repo ) ) )[ "body" ]
    assert "No creator recorded" in body and "branch stamp; seat tree name; spawn registry for 'rev'" in body


def test_the_seat_cc_case_is_unchanged( repo, live_registry ):
    who = st.owner_for_branch( f"wt-rescue/seat-cc-author-mr-radio-2{STAMPS}", project_root=str( repo ) )
    assert ( who[ "owner" ], who[ "source" ] ) == ( "mr radio", "seat tree name" )
    assert st.owner_for_tree( "/r/.claude/worktrees/seat-cc-author-cheech-2" )[ "owner" ] == "cheech"


def test_an_archive_row_for_a_worker_branch_is_owned_by_the_manager_and_says_where_that_came_from( repo, live_registry ):
    row = st.compose_archive_row( _outcome( f"wt-rescue/arnold-review-ab12cd3{STAMPS}", str( repo ) ) )
    assert ( row[ "owner" ], row[ "accountable" ] ) == ( "mr radio", "mr radio" )
    assert "Creator: mr radio, from the spawn registry." in row[ "body" ] and "No creator recorded" not in row[ "body" ]


def test_a_straggler_tree_named_after_a_worker_routes_the_same_way( live_registry ):
    row = st.compose_row( "/r/.claude/worktrees/arnold-review-ab12cd3", [ "io/x" ], "t", False )
    assert ( row[ "owner" ], row[ "accountable" ] ) == ( "mr radio", "mr radio" )


# ── the pieces ──────────────────────────────────────────────────────────────

def test_a_registry_that_raises_or_is_silent_gives_no_creator():
    def boom( persona ): raise RuntimeError( "registry down" )
    assert st.resolve_creator( "arnold-x", registry_fn=boom )[ "manager" ] is None
    assert st.resolve_creator( "-x", registry_fn=registry )[ "manager" ] is None             # an empty first segment asks nobody
    assert st.resolve_creator( "x", branch="b", registry_fn=registry )[ "tried" ][ 0 ] == "branch stamp (no branch or repo root given)"


def test_stamp_helpers_survive_a_failing_runner():
    def boom( argv, cwd=None, timeout=60 ): raise OSError( "no git" )
    class Fail:
        returncode, stdout, stderr = 1, "", "fatal"
    assert st.read_stamp( "/r", "b", run=boom ) is None and st.write_stamp( "/r", "b", "m", run=boom ) is False
    assert st.read_stamp( "/r", "b", run=lambda *a, **k: Fail ) is None and st.write_stamp( "/r", "b", "m", run=lambda *a, **k: Fail ) is False


def _bridge( persona, by ): return ( None, { "voice_persona": { "name": persona }, "spawned_by_persona": by }, [] )


def test_the_spawn_registry_reads_live_bridges_and_refuses_to_guess( monkeypatch ):
    import lupin_cli.claude_code.hooks.lib.session_bridge as sb
    def set_bridges( *rows ): monkeypatch.setattr( sb, "iter_live_bridges", lambda: iter( rows ) )
    set_bridges( _bridge( "Arnold", "Mr. Radio" ), _bridge( "Maya", "Tiberius" ), ( None, { "voice_persona": { "name": "Rio" } }, [] ), ( None, { "voice_persona": "x" }, [] ) )
    assert st.spawn_registry_manager( "arnold" ) == "mr radio"                    # the same worker twice reads as one manager
    assert st.spawn_registry_manager( "rio" ) is None                             # a bridge with no frozen manager
    assert st.spawn_registry_manager( "nobody" ) is None
    set_bridges( _bridge( "Arnold", "Mr. Radio" ), _bridge( "Arnold", "Tiberius" ) )
    assert st.spawn_registry_manager( "arnold" ) is None                          # two managers: ambiguous
    monkeypatch.setattr( sb, "iter_live_bridges", lambda: (_ for _ in ()).throw( OSError( "gone" ) ) )
    assert st.spawn_registry_manager( "arnold" ) is None


# ── create, reap, archive ───────────────────────────────────────────────────

def test_the_reaper_stamps_a_worker_tree_and_the_archive_row_goes_to_the_manager( repo, live_registry, monkeypatch ):
    tree = repo / ".claude" / "worktrees" / "arnold-review-ab12cd3"
    _g( repo, "worktree", "add", "-q", "--detach", str( tree ), "HEAD" )                  # create: a worker makes its own tree
    ( tree / "finding.md" ).write_text( "a review\n" )
    _g( tree, "add", "-A" ); _g( tree, "commit", "-q", "-m", "review notes" )

    reaped = wr.drain_then_remove( str( tree ), project_root=str( repo ), now=NOW )          # reap

    branch = reaped[ "rescue_branch" ]
    assert reaped[ "removed" ] is True and branch == f"wt-rescue/arnold-review-ab12cd3{STAMPS}"
    assert reaped[ "creator_stamped" ] == "mr radio"
    assert _g( repo, "config", "--get", f"branch.{branch}.lupin-manager" ) == "mr radio"      # the stamp is on disk, in repo config

    retired = wr.retire_branch( str( repo ), branch, "wip-v9", now=NOW )                      # archive
    assert retired[ "kept_reason" ] == "archived"
    assert _g( repo, "for-each-ref", "--format=%(refname)", "refs/archive" ) == f"refs/archive/2026-10-19/{branch}"
    assert subprocess.run( [ "git", "rev-parse", "--verify", "-q", f"refs/heads/{branch}" ], cwd=repo ).returncode != 0     # the branch itself is gone

    # the registry now knows nobody: only the stamp, read from repo config, can route the row
    monkeypatch.setattr( st, "spawn_registry_manager", lambda persona: None )
    row = st.compose_archive_row( { **retired, "repo_root": str( repo ) } )
    assert ( row[ "owner" ], row[ "accountable" ] ) == ( "mr radio", "mr radio" )
    assert "Creator: mr radio, from the branch stamp." in row[ "body" ]


def test_a_tree_the_reaper_cannot_attribute_is_reaped_unstamped( repo, live_registry ):
    tree = repo / ".claude" / "worktrees" / "rev-c9"
    _g( repo, "worktree", "add", "-q", "--detach", str( tree ), "HEAD" )
    ( tree / "f.md" ).write_text( "x\n" ); _g( tree, "add", "-A" ); _g( tree, "commit", "-q", "-m", "x" )
    reaped = wr.drain_then_remove( str( tree ), project_root=str( repo ), now=NOW )
    assert reaped[ "removed" ] is True and reaped[ "creator_stamped" ] is None
    assert subprocess.run( [ "git", "config", "--get", f"branch.{reaped[ 'rescue_branch' ]}.lupin-manager" ], cwd=repo ).returncode != 0


def test_a_failed_stamp_is_reported_and_does_not_block_the_reap( repo, live_registry, monkeypatch ):
    monkeypatch.setattr( st, "write_stamp", lambda *a, **k: False )
    tree = repo / ".claude" / "worktrees" / "arnold-review-ab12cd3"
    _g( repo, "worktree", "add", "-q", "--detach", str( tree ), "HEAD" )
    reaped = wr.drain_then_remove( str( tree ), project_root=str( repo ), now=NOW )
    assert reaped[ "removed" ] is True and reaped[ "creator_stamped" ] is None
    assert any( "could not stamp" in e for e in reaped[ "errors" ] )
