"""
An archived rescue branch goes to the manager who spawned its worker.

Before the fix, 24 of 25 overnight archive rows landed on maria. Only a seat-cc-<role>-<manager>-<n> name resolved.
The tests hold the lookups in order. First the stamp on the branch, then a seat tree's name.
Last, the spawn registry for a name that begins with a worker persona.
"""
import json
import os
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
    assert who[ "tried" ] == [ "branch stamp", "creator ledger", "seat tree name", "spawn registry for 'rev'" ]
    body = st.compose_archive_row( _outcome( f"wt-rescue/rev-c9{STAMPS}", str( repo ) ) )[ "body" ]
    assert "No creator recorded" in body and "branch stamp; creator ledger; seat tree name; spawn registry for 'rev'" in body


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


# ── real-shaped bridges and manifests ───────────────────────────────────────
#
# The bridge keys below are the ones a live spawned worker's bridge file carries (listed from the live
# session folder on 2026-10-20): `spawned_by` holds the manager's session id, and `spawned_by_persona` is absent
# on a bridge written before the persona was frozen at spawn.

def _live_bridge( persona, session_id, spawned_by=None, tmux=None, frozen=None, pid=0 ):
    bridge = { "cc_pid": pid, "cwd": "/repos/lupin", "headless": spawned_by is not None, "role": "reviewer", "session_id": session_id,
               "session_ids": [ session_id ], "stable_session_id": session_id, "speakerphone_on": False, "tmux_session": tmux,
               "voice_persona": { "name": persona, "voice_id": "v", "icon": "x", "color": "#fff", "borrowed": False, "assigned_at": "2026-10-20T12:00:00+00:00" } }
    if spawned_by: bridge[ "spawned_by" ] = spawned_by
    if frozen: bridge[ "spawned_by_persona" ] = frozen
    return bridge


FAKE_PIDS = tuple( range( 910001, 910009 ) )     # no real process: a run's parents differ with how it was launched, and pid 1 cannot be signalled


@pytest.fixture
def sessions( tmp_path, monkeypatch ):
    """A session folder the bridge reader and the manager resolver both look in."""
    import lupin_cli.claude_code.hooks.lib.session_bridge as sb
    from cosa.agents.heartbeat_arbiter import manager_resolver as mr
    folder = tmp_path / "sessions"; folder.mkdir()
    monkeypatch.setattr( sb, "SESSION_DIR", folder )
    monkeypatch.setattr( mr, "SESSION_DIR", folder )
    monkeypatch.setitem( mr.resolve_manager.__kwdefaults__, "session_dir", folder )
    live = set()
    monkeypatch.setattr( sb, "_can_trust_host_pids", lambda: True )                        # the pid check runs, whatever the launch
    monkeypatch.setattr( sb, "_is_pid_alive", lambda pid: pid in live )                    # a bridge of a dead pid is skipped
    class Folder:
        path, pids = folder, iter( FAKE_PIDS )
        def _write( self, *a, **kw ):
            data = _live_bridge( *a, pid=next( self.pids ), **kw )
            ( folder / f"cc-{data[ 'cc_pid' ]}.json" ).write_text( json.dumps( data ) )
            return data[ "cc_pid" ]
        def bridge( self, *a, **kw ): live.add( self._write( *a, **kw ) )
        def dead_bridge( self, *a, **kw ): self._write( *a, **kw )
        def manifest( self, manager_session_id, *session_names ):
            ( folder / f"spawned-{manager_session_id}.json" ).write_text( json.dumps( [ { "session_name": n, "status": "spawned" } for n in session_names ] ) )
    return Folder()


def test_a_worker_bridge_with_only_spawned_by_resolves_through_the_managers_bridge( sessions ):
    sessions.bridge( "mr radio", "mgr-1111", None )
    sessions.bridge( "arnold", "wrk-2222", spawned_by="mgr-1111", tmux="cc-reviewer-mr-radio-1" )
    assert st.spawn_registry_manager( "arnold" ) == "mr radio"


def test_a_frozen_spawned_by_persona_wins_over_the_managers_current_persona( sessions ):
    sessions.bridge( "tiberius", "mgr-1111", None )                                      # the manager session was recycled under another persona
    sessions.bridge( "arnold", "wrk-2222", spawned_by="mgr-1111", frozen="Mr. Radio" )
    assert st.spawn_registry_manager( "arnold" ) == "mr radio"


def test_a_legacy_bridge_resolves_through_the_spawn_manifest( sessions ):
    sessions.bridge( "mr radio", "mgr-1111", None )
    sessions.bridge( "clayton", "wrk-3333", tmux="cc-reviewer-mr-radio-2" )              # no spawned_by: written before the field
    sessions.manifest( "mgr-1111", "cc-reviewer-mr-radio-2" )
    assert st.spawn_registry_manager( "clayton" ) == "mr radio"


def test_two_live_workers_of_one_persona_under_different_managers_resolve_to_nobody( sessions ):
    sessions.bridge( "mr radio", "mgr-1111", None )
    sessions.bridge( "tiberius", "mgr-4444", None )
    sessions.bridge( "arnold", "wrk-2222", spawned_by="mgr-1111" )
    sessions.bridge( "arnold", "wrk-5555", spawned_by="mgr-4444" )
    assert st.spawn_registry_manager( "arnold" ) is None


def test_the_lookup_does_not_depend_on_how_the_run_was_launched( sessions, monkeypatch ):
    def refuse( pid, sig ): raise PermissionError( pid )
    monkeypatch.setattr( os, "kill", refuse )                                            # as for pid 1, or any parent another user owns
    sessions.bridge( "mr radio", "mgr-1111", None )
    sessions.bridge( "arnold", "wrk-2222", spawned_by="mgr-1111" )
    assert st.spawn_registry_manager( "arnold" ) == "mr radio"


def test_a_bridge_of_a_dead_pid_is_skipped( sessions ):
    sessions.bridge( "mr radio", "mgr-1111", None )
    sessions.bridge( "tiberius", "mgr-4444", None )
    sessions.bridge( "arnold", "wrk-2222", spawned_by="mgr-1111" )
    sessions.dead_bridge( "arnold", "wrk-5555", spawned_by="mgr-4444" )
    assert st.spawn_registry_manager( "arnold" ) == "mr radio"


def test_the_pid_check_runs_inside_a_container_too( sessions, monkeypatch ):
    import pathlib
    import lupin_cli.claude_code.hooks.lib.session_bridge as sb
    real = pathlib.Path.exists
    monkeypatch.setattr( pathlib.Path, "exists", lambda self: str( self ) == "/.dockerenv" or real( self ) )   # as in a container: host pids are not trusted
    sessions.bridge( "mr radio", "mgr-1111", None )
    sessions.dead_bridge( "arnold", "wrk-5555", spawned_by="mgr-1111" )
    assert [ data[ "session_id" ] for _, data, _ in sb.iter_live_bridges() ] == [ "mgr-1111" ]


def test_an_unspawned_or_unknown_persona_resolves_to_nobody( sessions ):
    sessions.bridge( "maria", "mgr-1111", None )
    assert st.spawn_registry_manager( "maria" ) is None and st.spawn_registry_manager( "nobody" ) is None


def test_a_broken_bridge_reader_resolves_to_nobody( monkeypatch ):
    import lupin_cli.claude_code.hooks.lib.session_bridge as sb
    monkeypatch.setattr( sb, "iter_live_bridges", lambda: ( _ for _ in () ).throw( OSError( "gone" ) ) )
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


# ── the whole path: the worker makes the tree, the worker is gone, the janitor archives it ──

def test_a_bare_worker_tree_is_recorded_at_creation_and_routed_after_the_worker_and_its_bridge_are_gone( repo, tmp_path, monkeypatch ):
    from lupin_cli.claude_code.hooks.lib import worktree_creator_record as wcr
    monkeypatch.setenv( "DEEPILY_DATA_DIR", str( tmp_path / "data" ) )
    monkeypatch.setattr( st, "spawn_registry_manager", lambda persona: None )                 # no live bridge, no manifest: nothing else can answer
    tree = repo / ".claude" / "worktrees" / "rev-c9"

    # create: the worker's hook runs before its Bash call; the seat carries the manager's persona in its environment
    recorded = wcr.record_worktree_creator( "Bash", { "command": f"git worktree add --detach {tree} HEAD" }, str( repo ),
                                            environ={ wcr.SPAWNED_BY_ENV: "Mr. Radio" } )
    assert recorded == [ str( tree ) ]
    _g( repo, "worktree", "add", "-q", "--detach", str( tree ), "HEAD" )
    ( tree / "finding.md" ).write_text( "a review\n" )
    _g( tree, "add", "-A" ); _g( tree, "commit", "-q", "-m", "review notes" )

    # reap, then archive
    reaped = wr.drain_then_remove( str( tree ), project_root=str( repo ), now=NOW )
    assert reaped[ "removed" ] is True and reaped[ "creator_stamped" ] == "mr radio"
    retired = wr.retire_branch( str( repo ), reaped[ "rescue_branch" ], "wip-v9", now=NOW )
    assert retired[ "kept_reason" ] == "archived"

    row = st.compose_archive_row( { **retired, "repo_root": str( repo ) } )
    assert ( row[ "owner" ], row[ "accountable" ] ) == ( "mr radio", "mr radio" )
    assert "from the branch stamp" in row[ "body" ] and "No creator recorded" not in row[ "body" ]


def test_the_same_bare_tree_made_by_a_seat_no_manager_spawned_stays_with_maria( repo, tmp_path, monkeypatch ):
    from lupin_cli.claude_code.hooks.lib import worktree_creator_record as wcr
    monkeypatch.setenv( "DEEPILY_DATA_DIR", str( tmp_path / "data" ) )
    monkeypatch.setattr( st, "spawn_registry_manager", lambda persona: None )
    tree = repo / ".claude" / "worktrees" / "rev-c9"
    assert wcr.record_worktree_creator( "Bash", { "command": f"git worktree add --detach {tree} HEAD" }, str( repo ), environ={} ) == []
    _g( repo, "worktree", "add", "-q", "--detach", str( tree ), "HEAD" )
    ( tree / "f.md" ).write_text( "x\n" ); _g( tree, "add", "-A" ); _g( tree, "commit", "-q", "-m", "x" )
    retired = wr.retire_branch( str( repo ), wr.drain_then_remove( str( tree ), project_root=str( repo ), now=NOW )[ "rescue_branch" ], "wip-v9", now=NOW )
    row = st.compose_archive_row( { **retired, "repo_root": str( repo ) } )
    assert row[ "owner" ] == st.NO_CREATOR_OWNER and "creator ledger" in row[ "body" ]


def test_a_straggler_tree_is_routed_by_the_ledger_too( repo, tmp_path, monkeypatch ):
    from lupin_cli.claude_code.hooks.lib import worktree_creator_record as wcr
    monkeypatch.setenv( "DEEPILY_DATA_DIR", str( tmp_path / "data" ) )
    tree = repo / ".claude" / "worktrees" / "rev-c9"
    wcr.record_worktree_creator( "Bash", { "command": f"git worktree add {tree}" }, str( repo ), environ={ wcr.SPAWNED_BY_ENV: "tiberius" } )
    assert st.owner_for_tree( str( tree ) )[ "owner" ] == "tiberius"
    assert st.owner_for_tree( str( repo / ".claude" / "worktrees" / "rev-zz" ) )[ "owner" ] == st.NO_CREATOR_OWNER


def test_the_ledger_reader_ignores_a_missing_or_malformed_ledger( repo, tmp_path, monkeypatch ):
    from lupin_cli.claude_code.hooks.lib import worktree_creator_record as wcr
    monkeypatch.setenv( "DEEPILY_DATA_DIR", str( tmp_path / "data" ) )
    assert st.read_creator_record( str( repo ), "/x", "b" ) is None
    ledger = wcr.ledger_path( str( repo ) )
    os.makedirs( os.path.dirname( ledger ) )
    for text in ( "not json", json.dumps( { "trees": { "/x": "oops" } } ), json.dumps( { "branches": {} } ) ):
        open( ledger, "w" ).write( text )
        assert st.read_creator_record( str( repo ), "/x", "b" ) is None
