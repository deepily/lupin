"""
Unit tests for the fix-branch push and its INI flag in the TFE multi-cluster git path.

GitOps.push_branch pushes one named fix branch to origin and nothing else.
GitStrategist.commit_and_pr_multi calls it only when push_enabled is true. With the flag off
it says nothing was pushed and opens no pull request. The flag is the INI key
"test fix expediter push fix branch enabled", off by default.
"""

import asyncio
import configparser
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import cosa.utils.util as cu
from cosa.agents.bug_fix_expediter.git_ops import GitOps
from cosa.agents.shared.git_strategist import GitStrategist
from cosa.agents.test_fix_expediter.config import TestFixExpediterConfig

INI_KEY = "test fix expediter push fix branch enabled"


def _git( cwd, *args ):
    """Run git in cwd with a fixed identity and return stdout."""
    cmd = [ "git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args ]
    return subprocess.run( cmd, cwd=str( cwd ), check=True, capture_output=True, text=True ).stdout.strip()


@pytest.fixture
def repo_with_origin( tmp_path ):
    """A work clone on main with a local bare origin; main has one commit that origin also has."""
    origin = tmp_path / "origin.git"
    work   = tmp_path / "work"
    subprocess.run( [ "git", "init", "--bare", "-b", "main", str( origin ) ], check=True, capture_output=True )
    subprocess.run( [ "git", "init", "-b", "main", str( work ) ], check=True, capture_output=True )
    ( work / "a.txt" ).write_text( "one\n" )
    _git( work, "add", "a.txt" )
    _git( work, "commit", "-m", "first" )
    _git( work, "remote", "add", "origin", str( origin ) )
    _git( work, "push", "origin", "main" )
    return work, origin


def _origin_refs( origin ):
    """Names of the branches the bare origin holds."""
    out = _git( origin, "for-each-ref", "--format=%(refname:short)", "refs/heads" )
    return sorted( out.split() )


# ─────────────────────────────────────────────────────────────────────────
# GitOps.push_branch
# ─────────────────────────────────────────────────────────────────────────


class TestPushBranch:

    def test_pushes_the_fix_branch_and_nothing_else( self, repo_with_origin ):
        work, origin = repo_with_origin
        _git( work, "checkout", "-b", "fix/2026-10-08-x" )
        ( work / "a.txt" ).write_text( "fixed\n" )
        _git( work, "commit", "-am", "fix" )
        _git( work, "checkout", "main" )
        ( work / "b.txt" ).write_text( "unpushed main work\n" )
        _git( work, "add", "b.txt" )
        _git( work, "commit", "-m", "main moved on" )
        main_on_origin_before = _git( origin, "rev-parse", "main" )

        result = asyncio.run( GitOps( cwd=str( work ) ).push_branch( "fix/2026-10-08-x" ) )

        assert result == { "success": True, "error": None }
        assert _origin_refs( origin ) == [ "fix/2026-10-08-x", "main" ]
        assert _git( origin, "rev-parse", "main" ) == main_on_origin_before
        assert _git( origin, "rev-parse", "fix/2026-10-08-x" ) == _git( work, "rev-parse", "fix/2026-10-08-x" )

    @pytest.mark.parametrize( "name", [ "", "main", "master", "HEAD", "feature/x", "fix", "fix/" ] )
    def test_refuses_anything_that_is_not_a_fix_branch( self, name ):
        git_ops = GitOps()
        git_ops._run_git = AsyncMock()

        result = asyncio.run( git_ops.push_branch( name ) )

        assert result[ "success" ] is False
        assert "fix branch" in result[ "error" ]
        git_ops._run_git.assert_not_called()

    def test_the_command_names_one_refspec_and_never_forces( self ):
        git_ops = GitOps()
        git_ops._run_git = AsyncMock( return_value={ "success": True, "stdout": "", "stderr": "", "returncode": 0 } )

        asyncio.run( git_ops.push_branch( "fix/2026-10-08-x" ) )

        args = git_ops._run_git.call_args.args
        assert args == ( "push", "-u", "origin", "refs/heads/fix/2026-10-08-x:refs/heads/fix/2026-10-08-x" )
        assert not {  "--force", "-f", "--all", "--tags", "--mirror", "--delete" } & set( args )

    def test_a_rejected_push_comes_back_as_an_error( self, tmp_path ):
        work = tmp_path / "w"
        subprocess.run( [ "git", "init", "-b", "main", str( work ) ], check=True, capture_output=True )
        _git( work, "commit", "--allow-empty", "-m", "x" )
        _git( work, "checkout", "-b", "fix/y" )

        result = asyncio.run( GitOps( cwd=str( work ) ).push_branch( "fix/y" ) )

        assert result[ "success" ] is False
        assert result[ "error" ].startswith( "git push failed:" )


# ─────────────────────────────────────────────────────────────────────────
# GitStrategist.commit_and_pr_multi and the flag
# ─────────────────────────────────────────────────────────────────────────


def _git_ops_mock():
    mock = MagicMock()
    mock.get_current_branch = AsyncMock( return_value="main" )
    mock.create_fix_branch  = AsyncMock( return_value={ "success": True, "branch_name": "fix/x", "error": None } )
    mock.commit_on_branch   = AsyncMock( return_value={ "success": True, "commit_hash": "abc12345", "error": None } )
    mock.push_branch        = AsyncMock( return_value={ "success": True, "error": None } )
    mock.create_pr          = AsyncMock( return_value={ "success": True, "pr_url": "http://pr/1", "error": None } )
    mock.checkout_branch    = AsyncMock( return_value={ "success": True } )
    return mock


async def _run_multi( git_ops, notes, **kwargs ):
    async def _notify( msg, priority="low" ):
        notes.append( msg )
    return await GitStrategist().commit_and_pr_multi(
        git_ops=git_ops, clusters=[ ( "C1", "t", [ "a.py" ], "m" ) ], trust_level=3,
        notify_fn=_notify, pr_title="T", pr_body="B", **kwargs )


class TestFlag:

    def test_flag_off_is_the_default_and_pushes_nothing( self ):
        git_ops, notes = _git_ops_mock(), []

        result = asyncio.run( _run_multi( git_ops, notes ) )

        git_ops.push_branch.assert_not_called()
        git_ops.create_pr.assert_not_called()
        assert result[ "git_strategy" ] == "commit_only"
        assert result[ "pr_url" ] is None
        assert "nothing was pushed" in result[ "error" ]
        assert "no pull request was opened" in result[ "error" ]
        assert INI_KEY in result[ "error" ]
        assert result[ "error" ] in notes
        git_ops.checkout_branch.assert_called_with( "main" )

    def test_flag_off_explicit_is_the_same( self ):
        git_ops = _git_ops_mock()

        result = asyncio.run( _run_multi( git_ops, [], push_enabled=False ) )

        git_ops.push_branch.assert_not_called()
        assert "nothing was pushed" in result[ "error" ]

    def test_flag_on_pushes_the_fix_branch_then_opens_the_pr( self ):
        git_ops = _git_ops_mock()

        result = asyncio.run( _run_multi( git_ops, [], push_enabled=True ) )

        git_ops.push_branch.assert_called_once()
        git_ops.create_pr.assert_called_once()
        assert result[ "git_strategy" ] == "branch_and_pr"
        assert result[ "error" ] is None

    def test_flag_on_without_push_branch_still_says_nothing_was_pushed( self ):
        git_ops = _git_ops_mock()
        del git_ops.push_branch

        result = asyncio.run( _run_multi( git_ops, [], push_enabled=True ) )

        git_ops.create_pr.assert_not_called()
        assert "nothing was pushed" in result[ "error" ]
        assert INI_KEY not in result[ "error" ]


# ─────────────────────────────────────────────────────────────────────────
# The INI key
# ─────────────────────────────────────────────────────────────────────────


class TestConfigKey:

    def test_dataclass_default_is_off( self ):
        assert TestFixExpediterConfig().push_fix_branch_enabled is False

    def test_from_config_reads_the_key_as_a_boolean( self ):
        seen = {}
        def _get( ini_key, default=None, return_type=None ):
            seen[ ini_key ] = ( default, return_type )
            return default
        mgr = MagicMock()
        mgr.get.side_effect = _get

        config = TestFixExpediterConfig.from_config( mgr )

        assert seen[ INI_KEY ] == ( False, "boolean" )
        assert config.push_fix_branch_enabled is False

    def test_the_shipped_ini_sets_it_false_and_the_splainer_explains_it( self ):
        root = Path( cu.get_project_root() )
        for name in ( "lupin-app.ini", "lupin-app-splainer.ini" ):
            parser = configparser.RawConfigParser( strict=False, delimiters=( "=", ) )
            parser.optionxform = str
            parser.read( root / "src/conf" / name )
            values = [ v for section in parser.sections() for k, v in parser.items( section ) if k.strip() == INI_KEY ]
            assert len( values ) >= 1, f"{INI_KEY} missing from {name}"
            if name == "lupin-app.ini":
                assert set( values ) == { "false" }
            else:
                assert "nothing is pushed" in values[ 0 ]
