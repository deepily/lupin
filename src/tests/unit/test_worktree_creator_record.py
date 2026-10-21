"""
The PreToolUse hook records the spawning manager when a worker runs `git worktree add`.

Without the record, the janitor sees only a tree name such as rev-c9 after the worker is gone.
The archive row for it then lands on maria.
"""
import contextlib
import json
import os
from unittest.mock import MagicMock, patch

import pytest

from lupin_cli.claude_code.hooks import pre_tool_use as ptu
from lupin_cli.claude_code.hooks.lib import worktree_creator_record as wcr

CWD = "/repos/lupin"


@pytest.fixture( autouse=True )
def data_root( tmp_path, monkeypatch ):
    """Point the fleet data root at a temp folder, so no test writes the real ledger."""
    monkeypatch.setenv( "DEEPILY_DATA_DIR", str( tmp_path / "data" ) )
    return tmp_path / "data"


def _paths( command, cwd=CWD ): return [ ( a[ "path" ], a[ "branch" ] ) for a in wcr.parse_worktree_adds( command, cwd ) ]


# ── reading the command ─────────────────────────────────────────────────────

@pytest.mark.parametrize( "command, expected", [
    ( "git worktree add .claude/worktrees/rev-c9", [ ( "/repos/lupin/.claude/worktrees/rev-c9", None ) ] ),
    ( "git worktree add --detach .claude/worktrees/rev-c9 HEAD", [ ( "/repos/lupin/.claude/worktrees/rev-c9", None ) ] ),
    ( "git worktree add -b feat-x /abs/arnold-review-1 main", [ ( "/abs/arnold-review-1", "feat-x" ) ] ),
    ( "git worktree add -B feat-y -f ../t", [ ( "/repos/t", "feat-y" ) ] ),
    ( "git worktree add --reason why --lock -q t1", [ ( "/repos/lupin/t1", None ) ] ),
    ( "cd /work && git worktree add t2", [ ( "/work/t2", None ) ] ),
    ( "git -C /other -c core.x=1 worktree add t3", [ ( "/other/t3", None ) ] ),
    ( "/usr/bin/git worktree add t4; git worktree add t5", [ ( "/repos/lupin/t4", None ), ( "/repos/lupin/t5", None ) ] ),
    ( "git worktree list", [] ),
    ( "git worktree add", [] ),
    ( "echo hello", [] ),
    ( "git worktree add 'unterminated", [] ),
] )
def test_the_command_reader_finds_every_worktree_add( command, expected ):
    assert _paths( command ) == expected


# ── recording ───────────────────────────────────────────────────────────────

def _ledger( data_root, repo="/repos/lupin" ):
    with open( os.path.join( str( data_root ), os.path.basename( repo ), wcr.LEDGER_NAME ) ) as f: return json.load( f )


def test_a_worker_tree_is_recorded_under_its_spawning_manager( data_root ):
    env  = { wcr.SPAWNED_BY_ENV: "Mr. Radio" }
    done = wcr.record_worktree_creator( "Bash", { "command": "git worktree add /repos/lupin/.claude/worktrees/rev-c9 -b rev-c9-br" }, CWD, environ=env, now=1000.0 )
    assert done == [ "/repos/lupin/.claude/worktrees/rev-c9" ]
    ledger = _ledger( data_root )
    assert ledger[ "trees" ][ "/repos/lupin/.claude/worktrees/rev-c9" ] == { "manager": "mr radio", "branch": "rev-c9-br", "ts": 1000.0 }
    assert ledger[ "branches" ][ "rev-c9-br" ][ "manager" ] == "mr radio"


def test_entries_older_than_the_retention_window_are_dropped_on_the_next_write( data_root ):
    env = { wcr.SPAWNED_BY_ENV: "tiberius" }
    wcr.record_worktree_creator( "Bash", { "command": "git worktree add /repos/lupin/.claude/worktrees/old -b old-br" }, CWD, environ=env, now=1000.0 )
    wcr.record_worktree_creator( "Bash", { "command": "git worktree add /repos/lupin/.claude/worktrees/new" }, CWD, environ=env, now=1000.0 + 61 * 86400 )
    ledger = _ledger( data_root )
    assert list( ledger[ "trees" ] ) == [ "/repos/lupin/.claude/worktrees/new" ] and ledger[ "branches" ] == {}


def test_a_seat_with_only_the_manager_session_id_is_attributed_through_that_managers_bridge( data_root, monkeypatch ):
    import lupin_cli.claude_code.hooks.lib.session_bridge as sb
    monkeypatch.setattr( sb, "get_voice_persona", lambda sid: { "name": "mr radio", "voice_id": "v" } if sid == "mgr-uuid" else None )
    env = { wcr.SPAWNER_ID_ENV: "mgr-uuid" }
    assert wcr.spawning_manager( env ) == "mr radio"
    assert wcr.spawning_manager( { wcr.SPAWNER_ID_ENV: "unknown" } ) is None
    monkeypatch.setattr( sb, "get_voice_persona", lambda sid: { "name": "  " } )
    assert wcr.spawning_manager( env ) is None
    assert wcr.spawning_manager( {} ) is None


@pytest.mark.parametrize( "tool, tool_input, env", [
    ( "Edit", { "command": "git worktree add t" }, { wcr.SPAWNED_BY_ENV: "tiberius" } ),
    ( "Bash", "not a dict", { wcr.SPAWNED_BY_ENV: "tiberius" } ),
    ( "Bash", { "command": 7 }, { wcr.SPAWNED_BY_ENV: "tiberius" } ),
    ( "Bash", { "command": "ls" }, { wcr.SPAWNED_BY_ENV: "tiberius" } ),
    ( "Bash", { "command": "git worktree list" }, { wcr.SPAWNED_BY_ENV: "tiberius" } ),
    ( "Bash", { "command": "git worktree add t" }, {} ),                                  # a seat no manager spawned
] )
def test_nothing_is_recorded_when_the_call_is_not_a_worker_adding_a_tree( data_root, tool, tool_input, env ):
    assert wcr.record_worktree_creator( tool, tool_input, CWD, environ=env ) == []
    assert not data_root.exists()


def test_a_failing_ledger_never_blocks_the_call( data_root, monkeypatch ):
    monkeypatch.setattr( wcr, "write_entries", lambda *a, **k: ( _ for _ in () ).throw( OSError( "disk full" ) ) )
    assert wcr.record_worktree_creator( "Bash", { "command": "git worktree add /repos/lupin/.claude/worktrees/t" }, CWD, environ={ wcr.SPAWNED_BY_ENV: "tiberius" } ) == []


def test_a_tree_outside_the_sandbox_is_filed_under_the_repo_of_the_working_directory( data_root, tmp_path ):
    import subprocess
    repo = tmp_path / "somerepo"; repo.mkdir()
    subprocess.run( [ "git", "init", "-q", str( repo ) ], check=True )
    env = { wcr.SPAWNED_BY_ENV: "tiberius" }
    assert wcr.record_worktree_creator( "Bash", { "command": f"git worktree add {tmp_path}/elsewhere" }, str( repo ), environ=env ) == [ f"{tmp_path}/elsewhere" ]
    assert _ledger( data_root, str( repo ) )[ "trees" ][ f"{tmp_path}/elsewhere" ][ "manager" ] == "tiberius"
    not_git = tmp_path / "plain"; not_git.mkdir()
    assert wcr._repo_of( "/x/y", str( not_git ) ) == str( not_git )                         # no git toplevel: the working directory itself


# ── the hook itself ─────────────────────────────────────────────────────────

def test_the_pre_tool_use_hook_records_the_creator_and_still_allows_the_call( data_root, monkeypatch ):
    monkeypatch.setenv( wcr.SPAWNED_BY_ENV, "Mr. Radio" )
    payload = { "session_id": "s1", "cwd": CWD, "tool_name": "Bash",
                "tool_input": { "command": "git worktree add /repos/lupin/.claude/worktrees/rev-c9 HEAD" } }
    emit = MagicMock()
    mod  = "lupin_cli.claude_code.hooks.pre_tool_use"
    with contextlib.ExitStack() as stack:
        for target, kw in ( ( f"{mod}.read_hook_input", { "return_value": payload } ), ( f"{mod}.log_payload", {} ), ( f"{mod}.touch_bridge_mtime", {} ),
                            ( f"{mod}.resolve_stable_session_id", { "return_value": "s1" } ), ( f"{mod}.get_claude_session_id", { "return_value": "s1" } ),
                            ( f"{mod}.drain_and_acknowledge", { "return_value": [] } ), ( f"{mod}.emit_json", { "new": emit } ) ):
            stack.enter_context( patch( target, **kw ) )
        ptu.main()
    emit.assert_called_once_with( {} )
    assert _ledger( data_root )[ "trees" ][ "/repos/lupin/.claude/worktrees/rev-c9" ][ "manager" ] == "mr radio"
