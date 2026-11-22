"""
A cron deploy finds the planning-is-prompting checkout itself.

Cron has no PLANNING_IS_PROMPTING_ROOT. The function is cut out of the script and run in bash.
It runs against temporary git repos, one for the main checkout and one for its sibling. No network is used.
"""
import os
import pathlib
import re
import subprocess

SOURCE = ( pathlib.Path( os.environ[ "LUPIN_ROOT" ] ) / "src/scripts/lupin-vm.sh" ).read_text()


def _function():
    hits = re.findall( r"^resolve_pip_root\(\) \{\n.*?^\}\n", SOURCE, re.M | re.S )
    assert len( hits ) == 1, f"expected one resolve_pip_root definition, got {len( hits )}"
    return hits[ 0 ]


def _git( cwd, *args ):
    subprocess.run( [ "git", "-C", str( cwd ), "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args ], check=True, capture_output=True )


def _resolve( where, env_value=None ):
    env  = { "PATH": os.environ[ "PATH" ], "HOME": os.environ[ "HOME" ] }
    if env_value is not None: env[ "PLANNING_IS_PROMPTING_ROOT" ] = env_value
    proc = subprocess.run( [ "bash", "-c", f'{_function()}\nresolve_pip_root "{where}"' ], capture_output=True, text=True, env=env )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


def _projects( tmp_path, with_sibling=True ):
    lupin = tmp_path / "lupin"
    lupin.mkdir()
    _git( lupin, "init", "-q" )
    ( lupin / "f" ).write_text( "x" )
    _git( lupin, "add", "f" )
    _git( lupin, "commit", "-q", "-m", "base" )
    if with_sibling:
        sibling = tmp_path / "planning-is-prompting"
        sibling.mkdir()
        _git( sibling, "init", "-q" )
    return lupin


def test_the_variable_wins_when_it_is_set( tmp_path ):
    assert _resolve( _projects( tmp_path ), env_value="/elsewhere/pip" ) == "/elsewhere/pip"


def test_with_no_variable_the_checkout_beside_the_main_lupin_checkout_is_found( tmp_path ):
    lupin = _projects( tmp_path )
    assert _resolve( lupin ) == str( tmp_path / "planning-is-prompting" )


def test_a_worktree_finds_the_checkout_beside_the_main_checkout_not_beside_itself( tmp_path ):
    lupin = _projects( tmp_path )
    tree  = lupin / ".claude" / "worktrees" / "seat"
    _git( lupin, "worktree", "add", "-q", "--detach", str( tree ) )
    assert _resolve( tree ) == str( tmp_path / "planning-is-prompting" )


def test_no_sibling_or_no_repository_prints_nothing_and_does_not_fail( tmp_path ):
    bare = tmp_path / "bare"
    bare.mkdir()
    assert _resolve( _projects( bare, with_sibling=False ) ) == ""
    plain = tmp_path / "plain"
    plain.mkdir()
    assert _resolve( plain ) == ""


def test_the_deploy_resolves_the_root_before_the_planning_sync_reads_it():
    resolved, sync = SOURCE.index( 'PLANNING_IS_PROMPTING_ROOT="$( resolve_pip_root' ), SOURCE.index( "refreshing the VM's planning-is-prompting from" )
    assert resolved < sync
