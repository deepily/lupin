"""
Cover `cosa.utils.worktree_venv.provision_worktree_venv` — the helper that gives a
newly-created worktree a `.venv` (row 9b2abfb7).

⚠️ EVERY FIXTURE HERE HONOURS ITS INPUT, DELIBERATELY. The fake scripts echo the
argument they were handed and exit with a code the test chose. A fake that returned a
canned string whatever it was asked would make every assertion below unfalsifiable:
passing the wrong path, or no path at all, would produce byte-identical output and the
suite would stay green while the helper provisioned the wrong tree. That is the exact
failure this repo has hit three times in other guises, so the tests assert on the
TARGET the script actually received, not merely on the status the helper returned.
"""

import os
import subprocess

import pytest

from cosa.utils import worktree_venv
from cosa.utils.worktree_venv import provision_worktree_venv


def _make_tree( root, exit_code=0, stdout_line="linked", stderr_line="" ):
    """
    Build a directory that looks like a repo, holding a fake part-1 script.

    Ensures:
        - the script echoes the argument it was given, so a caller passing the wrong
          path (or none) produces visibly different output
        - the script exits with `exit_code`
        - returns the tree root as a string
    """
    script_dir = root / "src" / "scripts"
    script_dir.mkdir( parents=True, exist_ok=True )
    script = script_dir / "link-worktree-venv.sh"
    body   = [ "#!/usr/bin/env bash" ]
    if stdout_line: body.append( f'echo "{stdout_line} arg=$1"' )
    if stderr_line: body.append( f'echo "{stderr_line} arg=$1" >&2' )
    body.append( f"exit {exit_code}" )
    script.write_text( "\n".join( body ) + "\n" )
    script.chmod( 0o755 )
    return str( root )


class TestNoOpPaths:

    @pytest.mark.parametrize( "target", [ None, "", 0 ] )
    def test_a_falsy_target_is_a_no_op_rather_than_an_error( self, target ):
        """An explicit project=None spawn has no work_dir; guessing at one would be worse."""
        result = provision_worktree_venv( target )
        assert result[ "status" ]      == "no_target"
        assert result[ "provisioned" ] is False
        assert result[ "target" ]      is None
        assert result[ "exit_code" ]   is None

    def test_a_tree_with_no_provisioning_script_is_a_no_op_and_names_the_path( self, tmp_path ):
        """A foreign repo or an old checkout simply has nothing to call — not an error."""
        result = provision_worktree_venv( str( tmp_path ) )
        assert result[ "status" ]      == "script_absent"
        assert result[ "provisioned" ] is False
        assert result[ "target" ]      == str( tmp_path )
        # The detail must name the path it looked for, or a reader cannot tell WHICH
        # tree came up short.
        assert str( tmp_path ) in result[ "detail" ]
        assert "link-worktree-venv.sh" in result[ "detail" ]

    def test_the_missing_script_path_is_reported_in_debug( self, tmp_path, capsys ):
        provision_worktree_venv( str( tmp_path ), debug=True )
        assert "no part-1 script" in capsys.readouterr().out


class TestTheTargetIsActuallyPassedToTheScript:
    """
    The discriminating cases. If the helper passed `$PWD`, or nothing at all, the
    script would still run and still exit 0 — so a test that only checked the status
    would pass against a broken helper. These check the argument the script SAW.
    """

    def test_a_successful_provision_reports_ok_and_hands_the_script_the_target( self, tmp_path ):
        tree   = _make_tree( tmp_path / "wt", stdout_line="Linked:" )
        result = provision_worktree_venv( tree )
        assert result[ "status" ]      == "ok"
        assert result[ "provisioned" ] is True
        assert result[ "exit_code" ]   == 0
        assert result[ "target" ]      == tree
        # THE ASSERTION THAT DISCRIMINATES: the script echoed its own $1.
        assert f"arg={tree}" in result[ "detail" ]

    def test_the_target_passed_is_not_merely_the_working_directory( self, tmp_path, monkeypatch ):
        """
        Stand the process somewhere else entirely, then provision a different tree.
        A helper that leaned on cwd would echo the cwd here and fail this test.
        """
        tree      = _make_tree( tmp_path / "wt" )
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        monkeypatch.chdir( elsewhere )
        result = provision_worktree_venv( tree )
        assert f"arg={tree}" in result[ "detail" ]
        assert str( elsewhere ) not in result[ "detail" ]


class TestOutcomesThatAreNotSuccess:

    def test_the_main_checkout_is_a_no_op_not_a_failure( self, tmp_path, caplog ):
        """
        Exit 3 is the script refusing to link the main repo to itself. That is the
        correct answer, so it must not be reported as a failure and must not log a
        warning — a warning on every ordinary main-repo spawn is noise that trains
        readers to ignore the channel.
        """
        tree   = _make_tree( tmp_path / "main", exit_code=3, stdout_line="REFUSING:" )
        with caplog.at_level( "WARNING" ):
            result = provision_worktree_venv( tree )
        assert result[ "status" ]      == "main_repo"
        assert result[ "provisioned" ] is False
        assert result[ "exit_code" ]   == 3
        assert caplog.records == []

    def test_the_main_repo_no_op_is_reported_in_debug( self, tmp_path, capsys ):
        tree = _make_tree( tmp_path / "main", exit_code=3 )
        provision_worktree_venv( tree, debug=True )
        assert "main checkout" in capsys.readouterr().out

    def test_a_successful_provision_is_reported_in_debug( self, tmp_path, capsys ):
        tree = _make_tree( tmp_path / "wt", stdout_line="Linked:" )
        provision_worktree_venv( tree, debug=True )
        assert "Linked:" in capsys.readouterr().out

    @pytest.mark.parametrize( "exit_code", [ 2, 4, 5, 6 ] )
    def test_an_unfinishable_run_is_reported_failed_and_logged_loudly( self, tmp_path, caplog, exit_code ):
        """
        Exit 4/5/6 mean the script could not finish. The whole point of this row is
        that a tree without an interpreter looks fine until a test tier disagrees, so
        these must be audible and must name the tree AND the code.
        """
        tree = _make_tree( tmp_path / "wt", exit_code=exit_code, stdout_line="", stderr_line="ERROR:" )
        with caplog.at_level( "WARNING" ):
            result = provision_worktree_venv( tree )
        assert result[ "status" ]      == "failed"
        assert result[ "provisioned" ] is False
        assert result[ "exit_code" ]   == exit_code
        assert len( caplog.records ) == 1
        logged = caplog.records[ 0 ].getMessage()
        assert tree               in logged
        assert f"exit {exit_code}" in logged

    def test_stderr_carries_the_detail_when_the_script_is_silent_on_stdout( self, tmp_path ):
        """The script writes its errors to stderr, so a stdout-only reader loses them."""
        tree   = _make_tree( tmp_path / "wt", exit_code=4, stdout_line="", stderr_line="ERROR: no venv" )
        result = provision_worktree_venv( tree )
        assert "ERROR: no venv" in result[ "detail" ]

    def test_a_script_producing_no_output_at_all_still_returns_a_dict( self, tmp_path ):
        tree   = _make_tree( tmp_path / "wt", exit_code=0, stdout_line="", stderr_line="" )
        result = provision_worktree_venv( tree )
        assert result[ "status" ] == "ok"
        assert result[ "detail" ] == ""


class TestItFailsOpen:
    """
    A spawn that dies because provisioning failed is worse than a seat without a venv.
    Same shape as stash_guard.py.
    """

    @pytest.mark.parametrize( "boom", [
        OSError( "exec format error" ),
        subprocess.TimeoutExpired( cmd="link-worktree-venv.sh", timeout=30 ),
        subprocess.SubprocessError( "something else" ),
    ] )
    def test_a_script_that_cannot_run_never_raises( self, tmp_path, monkeypatch, caplog, boom ):
        tree = _make_tree( tmp_path / "wt" )

        def _explode( *a, **k ): raise boom
        monkeypatch.setattr( worktree_venv.subprocess, "run", _explode )

        with caplog.at_level( "WARNING" ):
            result = provision_worktree_venv( tree )   # must NOT raise
        assert result[ "status" ]      == "failed"
        assert result[ "provisioned" ] is False
        assert result[ "exit_code" ]   is None
        assert type( boom ).__name__ in result[ "detail" ]
        assert tree in caplog.records[ 0 ].getMessage()


class TestTheScriptPathIsResolvedFromTheTargetNotTheEnvironment:
    """
    The wrong-tree family. `purge-pycache.sh` and the checked-hash verifier both
    resolve their tree from LUPIN_ROOT, so a shell standing in a worktree acts on the
    MAIN repo and prints a success banner about it. This helper must not join them.
    """

    def test_lupin_root_does_not_steer_which_tree_is_provisioned( self, tmp_path, monkeypatch ):
        tree      = _make_tree( tmp_path / "wt" )
        decoy     = _make_tree( tmp_path / "decoy", stdout_line="DECOY" )
        monkeypatch.setenv( "LUPIN_ROOT", decoy )
        result = provision_worktree_venv( tree )
        assert f"arg={tree}" in result[ "detail" ]
        assert "DECOY" not in result[ "detail" ]

    def test_the_script_is_looked_for_inside_the_target( self ):
        assert worktree_venv._SCRIPT_REL_PATH == os.path.join( "src", "scripts", "link-worktree-venv.sh" )
        assert not os.path.isabs( worktree_venv._SCRIPT_REL_PATH )


class TestTheSpawnPathProvisionsTheSeatItIsAboutToCreate:
    """
    The wiring in `spawn_sessions`. These assert on the TARGET handed to the helper,
    not merely that it was called: a spawner that provisioned the manager's own tree
    instead of the child's would call it exactly as often and pass this test if the
    argument went unchecked.
    """

    def _spawn( self, monkeypatch, tmp_path, project, resolved_root, seen ):
        from lupin_mcp import session_spawner

        monkeypatch.setattr( session_spawner, "_resolve_project_root", lambda p: resolved_root )
        monkeypatch.setattr( session_spawner, "provision_worktree_venv",
                             lambda target, *a, **k: seen.append( target ) )

        class _Runner:
            def __call__( self, argv, env=None ):
                class _R: returncode = 0; stdout = ""; stderr = ""
                return _R()

        return session_spawner.spawn_sessions(
            1, "task", "mgr-sid", script_path="x", project=project,
            runner=_Runner(), session_dir=tmp_path, dry_run=True,
        )

    def test_the_child_s_own_work_dir_is_what_gets_provisioned( self, monkeypatch, tmp_path ):
        seen = []
        self._spawn( monkeypatch, tmp_path, "lupin", "/somewhere/lupin-wt-child", seen )
        assert seen == [ "/somewhere/lupin-wt-child" ]

    def test_an_explicit_project_none_provisions_nothing( self, monkeypatch, tmp_path ):
        """
        project=None means the child inherits the caller's own cwd, which this code
        does not know. Guessing at it would provision the wrong tree — the exact
        failure mode this row exists to close.
        """
        seen = []
        self._spawn( monkeypatch, tmp_path, None, None, seen )
        assert seen == [ None ]
        assert provision_worktree_venv( None )[ "status" ] == "no_target"

    def test_an_unresolvable_project_still_refuses_before_provisioning( self, monkeypatch, tmp_path ):
        """
        The pre-existing refusal must keep firing FIRST. Provisioning a path that did
        not resolve would be acting on a guess.
        """
        seen = []
        with pytest.raises( ValueError, match="cannot spawn into project" ):
            self._spawn( monkeypatch, tmp_path, "no-such-project", None, seen )
        assert seen == []


class TestAFailedProvisionIsVisibleAtSpawnTime:
    """
    Rio's finding, reviewing this change: the first cut CALLED the helper and threw its
    answer away, so a spawn reported success while the seat it had just created could
    not run its own tier. A clean exit is not evidence the work happened.

    The alarm is TOP-LEVEL for the reason the reap already learned (row 3b0c5f90): its
    per-seat verdicts were honest, nested, and missed, because a caller reads the top
    of a result.
    """

    def _spawn( self, monkeypatch, tmp_path, provisioning ):
        from lupin_mcp import session_spawner
        monkeypatch.setattr( session_spawner, "_resolve_project_root", lambda p: "/some/tree" )
        monkeypatch.setattr( session_spawner, "provision_worktree_venv", lambda *a, **k: provisioning )

        class _Runner:
            def __call__( self, argv, env=None ):
                class _R: returncode = 0; stdout = ""; stderr = ""
                return _R()

        return session_spawner.spawn_sessions(
            1, "task", "mgr-sid", script_path="x", project="lupin",
            runner=_Runner(), session_dir=tmp_path, dry_run=True,
        )

    def test_a_failed_provision_raises_a_top_level_alarm_on_the_spawn_payload( self, monkeypatch, tmp_path ):
        res = self._spawn( monkeypatch, tmp_path, {
            "provisioned": False, "status": "failed", "exit_code": 4,
            "target": "/some/tree", "detail": "ERROR: the main repo has no usable venv",
        } )
        # The spawn still succeeds — fail open — but it no longer does so SILENTLY.
        assert res[ "spawned" ][ 0 ][ "status" ] == "spawned"
        assert res[ "venv_alarm" ] is not None
        assert "/some/tree" in res[ "venv_alarm" ]
        assert "exit 4"     in res[ "venv_alarm" ]
        assert "no usable venv" in res[ "venv_alarm" ]
        assert res[ "venv_provisioning" ][ "status" ] == "failed"

    def test_a_successful_provision_raises_no_alarm( self, monkeypatch, tmp_path ):
        """A line that appears on every ordinary spawn is a line readers learn to skip."""
        res = self._spawn( monkeypatch, tmp_path, {
            "provisioned": True, "status": "ok", "exit_code": 0,
            "target": "/some/tree", "detail": "Linked: ...",
        } )
        assert res[ "venv_alarm" ] is None
        assert res[ "venv_provisioning" ][ "provisioned" ] is True

    @pytest.mark.parametrize( "status", [ "no_target", "script_absent", "main_repo" ] )
    def test_the_three_legitimate_no_ops_raise_no_alarm( self, monkeypatch, tmp_path, status ):
        """
        Nothing-to-do is not a failure. project=None, a foreign repo with no script,
        and the main checkout refusing to link to itself are all correct outcomes.
        """
        res = self._spawn( monkeypatch, tmp_path, {
            "provisioned": False, "status": status, "exit_code": None,
            "target": None, "detail": "",
        } )
        assert res[ "venv_alarm" ] is None


class TestTheAlarmHelperOnItsOwn:

    def test_none_in_none_out( self ):
        from lupin_mcp.session_spawner import venv_alarm
        assert venv_alarm( None ) is None

    def test_an_empty_dict_is_not_an_alarm( self ):
        from lupin_mcp.session_spawner import venv_alarm
        assert venv_alarm( {} ) is None

    def test_a_failure_names_the_tree_the_code_and_the_consequence( self ):
        from lupin_mcp.session_spawner import venv_alarm
        line = venv_alarm( { "status": "failed", "exit_code": 5,
                             "target": "/t", "detail": "already exists" } )
        # The three things a reader needs to act: which tree, why, and what it costs.
        assert "/t"              in line
        assert "exit 5"          in line
        assert "already exists"  in line
        assert "fail unit tests" in line
