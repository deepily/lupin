"""
install-git-hooks.sh links the two git hooks a checkout ships.

The real script is copied into a scratch git repository beside two stub chain scripts.
It runs there, so no test touches a real hooks folder. `pfv_git_hook_status` from the preflight library
is the independent judge of "both links right".

Each refusal is proven by the test named beside it in the module's mutation notes:
  - in the way, no --replace      test_regular_file_in_the_way_is_reported_and_kept
  - missing chain script          test_missing_chain_script_makes_no_link_for_either_hook
  - not a git tree                test_not_a_git_tree_exits_2

Venue: :7999-eligible. No SSH, no network, no real docker.
"""
import os
import shutil
import subprocess

import pytest

import cosa.utils.util as cu

ROOT      = cu.get_project_root()
INSTALLER = f"{ROOT}/src/scripts/install-git-hooks.sh"
LIB       = f"{ROOT}/src/scripts/lib/preflight-vm-lib.sh"
LUPIN_VM  = f"{ROOT}/src/scripts/lupin-vm.sh"

HOOKS = ( ( "pre-commit", "pre-commit-chain.sh" ), ( "pre-push", "pre-push-chain.sh" ) )


def _git( cwd, *args ):
    return subprocess.run( [ "git", "-C", str( cwd ), *args ], capture_output=True, text=True, check=True ).stdout.strip()


def _scratch( tmp_path, with_chains=True, git=True ):
    """A scratch tree holding a copy of the installer and, optionally, both stub chain scripts."""
    repo    = tmp_path / "repo"
    scripts = repo / "src" / "scripts"
    scripts.mkdir( parents=True )
    shutil.copy( INSTALLER, scripts / "install-git-hooks.sh" )
    if with_chains:
        for _, script in HOOKS:
            ( scripts / script ).write_text( "#!/usr/bin/env bash\nexit 0\n" )
            ( scripts / script ).chmod( 0o755 )
    if git: subprocess.run( [ "git", "init", "-q", str( repo ) ], check=True )
    return repo


def _run( repo, *args, env=None ):
    full_env = { **os.environ, **( env or {} ) }
    return subprocess.run( [ "bash", str( repo / "src" / "scripts" / "install-git-hooks.sh" ), *args ],
                           capture_output=True, text=True, timeout=30, env=full_env )


def _status( hooks_dir, repo, hook, script ):
    r = subprocess.run( [ "bash", "-c", f"source '{LIB}'; pfv_git_hook_status '{hooks_dir}' '{hook}' '{repo}/src/scripts/{script}'" ],
                        capture_output=True, text=True, timeout=30 )
    return r.stdout.strip()


def _hooks_dir( repo ):
    return repo / ".git" / "hooks"


# ── the happy paths ──────────────────────────────────────────────────────────

def test_fresh_repository_gets_both_links_and_the_preflight_agrees( tmp_path ):
    repo = _scratch( tmp_path )
    r    = _run( repo )
    assert r.returncode == 0, r.stdout + r.stderr
    for hook, script in HOOKS:
        assert os.readlink( _hooks_dir( repo ) / hook ) == f"{repo}/src/scripts/{script}"
        assert _status( _hooks_dir( repo ), repo, hook, script ) == "MATCH"
    assert r.stdout.count( "linked" ) == 2 and r.stdout.strip().splitlines()[ -1 ].startswith( "install-git-hooks: both hooks" )


def test_second_run_changes_nothing( tmp_path ):
    repo = _scratch( tmp_path )
    _run( repo )
    before = { h: ( os.readlink( _hooks_dir( repo ) / h ), os.lstat( _hooks_dir( repo ) / h ).st_mtime_ns ) for h, _ in HOOKS }
    r      = _run( repo )
    after  = { h: ( os.readlink( _hooks_dir( repo ) / h ), os.lstat( _hooks_dir( repo ) / h ).st_mtime_ns ) for h, _ in HOOKS }
    assert r.returncode == 0 and before == after
    assert r.stdout.count( "already there" ) == 2


# ── something in the way ─────────────────────────────────────────────────────

def test_regular_file_in_the_way_is_reported_and_kept( tmp_path ):
    repo = _scratch( tmp_path )
    ( _hooks_dir( repo ) / "pre-push" ).write_text( "mine\n" )
    r = _run( repo )
    assert r.returncode == 1
    assert "pre-push: IN THE WAY" in r.stdout and "regular file" in r.stdout
    assert ( _hooks_dir( repo ) / "pre-push" ).read_text() == "mine\n"
    assert not ( _hooks_dir( repo ) / "pre-commit" ).exists(), "a blocked run must make no partial install"


def test_regular_file_in_the_way_with_replace_is_moved_aside( tmp_path ):
    repo = _scratch( tmp_path )
    ( _hooks_dir( repo ) / "pre-push" ).write_text( "mine\n" )
    r = _run( repo, "--replace" )
    assert r.returncode == 0, r.stdout + r.stderr
    baks = list( _hooks_dir( repo ).glob( "pre-push.bak-*" ) )
    assert len( baks ) == 1 and baks[ 0 ].read_text() == "mine\n"
    assert baks[ 0 ].name.split( "bak-" )[ 1 ].isdigit()
    assert "moved the old one aside" in r.stdout
    assert _status( _hooks_dir( repo ), repo, "pre-push", "pre-push-chain.sh" ) == "MATCH"


def test_link_to_another_file_in_the_way_is_reported_and_kept( tmp_path ):
    repo  = _scratch( tmp_path )
    other = tmp_path / "other.sh"; other.write_text( "x\n" )
    os.symlink( other, _hooks_dir( repo ) / "pre-commit" )
    r = _run( repo )
    assert r.returncode == 1
    assert "pre-commit: IN THE WAY" in r.stdout and str( other ) in r.stdout
    assert os.readlink( _hooks_dir( repo ) / "pre-commit" ) == str( other )


def test_link_to_another_file_in_the_way_with_replace_is_moved_aside( tmp_path ):
    repo  = _scratch( tmp_path )
    other = tmp_path / "other.sh"; other.write_text( "x\n" )
    os.symlink( other, _hooks_dir( repo ) / "pre-commit" )
    r = _run( repo, "--replace" )
    assert r.returncode == 0, r.stdout + r.stderr
    baks = list( _hooks_dir( repo ).glob( "pre-commit.bak-*" ) )
    assert len( baks ) == 1 and os.readlink( baks[ 0 ] ) == str( other )
    assert _status( _hooks_dir( repo ), repo, "pre-commit", "pre-commit-chain.sh" ) == "MATCH"


# ── where the folder is ──────────────────────────────────────────────────────

def test_core_hookspath_absolute( tmp_path ):
    repo   = _scratch( tmp_path )
    folder = tmp_path / "abs-hooks"
    _git( repo, "config", "core.hooksPath", str( folder ) )
    assert _run( repo ).returncode == 0
    for hook, script in HOOKS:
        assert os.readlink( folder / hook ) == f"{repo}/src/scripts/{script}"
    assert not _hooks_dir( repo ).joinpath( "pre-push" ).exists()


def test_core_hookspath_relative( tmp_path ):
    repo = _scratch( tmp_path )
    _git( repo, "config", "core.hooksPath", "rel-hooks" )
    assert _run( repo ).returncode == 0
    for hook, script in HOOKS:
        assert os.readlink( repo / "rel-hooks" / hook ) == f"{repo}/src/scripts/{script}"


def test_a_missing_hooks_folder_is_created( tmp_path ):
    repo = _scratch( tmp_path )
    shutil.rmtree( _hooks_dir( repo ) )
    assert _run( repo ).returncode == 0
    assert ( _hooks_dir( repo ) / "pre-push" ).is_symlink()


def test_unmakeable_hooks_folder_exits_2( tmp_path ):
    repo = _scratch( tmp_path )
    shutil.rmtree( _hooks_dir( repo ) )
    _hooks_dir( repo ).write_text( "a file where the folder should be\n" )
    r = _run( repo )
    assert r.returncode == 2 and "could not create" in r.stderr


# ── what is in the way is named, and the script is found through a link ─────

def test_a_directory_in_the_way_is_named_a_directory( tmp_path ):
    """Kills the mutant that calls every thing in the way "a regular file"."""
    repo = _scratch( tmp_path )
    ( _hooks_dir( repo ) / "pre-push" ).mkdir()
    r = _run( repo )
    assert r.returncode == 1
    assert "pre-push: IN THE WAY — a directory at" in r.stdout and "regular file" not in r.stdout
    assert ( _hooks_dir( repo ) / "pre-push" ).is_dir()


def test_reached_through_a_symlink_the_tree_is_the_real_checkout( tmp_path ):
    """Kills the mutant that takes the tree from the link, not the script's real path."""
    repo   = _scratch( tmp_path )
    away   = tmp_path / "elsewhere" / "deeper" / "x"
    away.mkdir( parents=True )
    os.symlink( repo / "src" / "scripts" / "install-git-hooks.sh", away / "install-git-hooks.sh" )
    r = subprocess.run( [ "bash", str( away / "install-git-hooks.sh" ) ], capture_output=True, text=True, timeout=30 )
    assert r.returncode == 0, r.stdout + r.stderr
    for hook, script in HOOKS:
        assert os.readlink( _hooks_dir( repo ) / hook ) == f"{repo}/src/scripts/{script}"


# ── a hooks folder that cannot be written ────────────────────────────────────

needs_non_root = pytest.mark.skipif( os.geteuid() == 0, reason="root ignores a read-only folder, so the write cannot fail" )


@needs_non_root
def test_a_failed_move_aside_exits_2_and_keeps_the_file( tmp_path ):
    """Kills the mutant that lets the move-aside failure branch fall through to the link."""
    repo = _scratch( tmp_path )
    ( _hooks_dir( repo ) / "pre-commit" ).write_text( "mine\n" )
    _hooks_dir( repo ).chmod( 0o555 )
    try:
        r = _run( repo, "--replace" )
        assert r.returncode == 2 and "could not move" in r.stderr
        assert ( _hooks_dir( repo ) / "pre-commit" ).read_text() == "mine\n"
    finally:
        _hooks_dir( repo ).chmod( 0o755 )


@needs_non_root
def test_a_failed_link_exits_2_and_says_which_hook( tmp_path ):
    """Kills the mutant that lets the link failure branch report success."""
    repo = _scratch( tmp_path )
    _hooks_dir( repo ).chmod( 0o555 )
    try:
        r = _run( repo )
        assert r.returncode == 2 and "could not link" in r.stderr and "pre-commit" in r.stderr
        assert not ( _hooks_dir( repo ) / "pre-commit" ).is_symlink()
        assert "both hooks are links" not in r.stdout
    finally:
        _hooks_dir( repo ).chmod( 0o755 )


# ── refusals that make no link ───────────────────────────────────────────────

@pytest.mark.parametrize( "missing", [ "pre-commit-chain.sh", "pre-push-chain.sh" ] )
def test_missing_chain_script_makes_no_link_for_either_hook( tmp_path, missing ):
    repo = _scratch( tmp_path )
    ( repo / "src" / "scripts" / missing ).unlink()
    r = _run( repo )
    assert r.returncode == 2
    assert "predates the hook" in r.stderr and missing in r.stderr
    for hook, _ in HOOKS:
        assert not ( _hooks_dir( repo ) / hook ).exists() and not ( _hooks_dir( repo ) / hook ).is_symlink()


def test_not_a_git_tree_exits_2( tmp_path ):
    repo = _scratch( tmp_path, git=False )
    r    = _run( repo )
    assert r.returncode == 2 and "not a git tree" in r.stderr
    assert not ( repo / ".git" ).exists() and not ( repo / "hooks" ).exists()


# ── a linked worktree shares the main checkout's hooks folder ────────────────

def _listing( folder ):
    return sorted( ( p.name, os.readlink( p ) if p.is_symlink() else p.read_text(), p.lstat().st_mtime_ns ) for p in folder.iterdir() )


@pytest.mark.parametrize( "args", [ [], [ "--replace" ] ] )
def test_a_linked_worktree_is_refused_and_the_shared_hooks_folder_is_untouched( tmp_path, args ):
    repo = _scratch( tmp_path )
    git  = [ "git", "-c", "user.name=t", "-c", "user.email=t@t", "-C", str( repo ) ]
    subprocess.run( [ *git, "add", "-A" ], check=True )
    subprocess.run( [ *git, "commit", "-q", "-m", "scratch" ], check=True )
    linked = tmp_path / "linked"
    subprocess.run( [ *git, "worktree", "add", "-q", "--detach", str( linked ) ], check=True )
    ( _hooks_dir( repo ) / "pre-push" ).write_text( "mine\n" )
    before = _listing( _hooks_dir( repo ) )
    r      = _run( linked, *args )
    assert r.returncode == 2, r.stdout + r.stderr
    assert "linked worktree" in r.stderr and "main checkout" in r.stderr
    assert _listing( _hooks_dir( repo ) ) == before
    assert not ( linked / "hooks" ).exists()


def test_a_refused_linked_worktree_run_leaves_a_missing_shared_hooks_folder_missing( tmp_path ):
    """Kills the mutant that creates the hooks folder before the linked-worktree refusal."""
    repo = _scratch( tmp_path )
    git  = [ "git", "-c", "user.name=t", "-c", "user.email=t@t", "-C", str( repo ) ]
    subprocess.run( [ *git, "add", "-A" ], check=True )
    subprocess.run( [ *git, "commit", "-q", "-m", "scratch" ], check=True )
    linked = tmp_path / "linked"
    subprocess.run( [ *git, "worktree", "add", "-q", "--detach", str( linked ) ], check=True )
    shutil.rmtree( _hooks_dir( repo ) )
    r = _run( linked )
    assert r.returncode == 2 and "linked worktree" in r.stderr
    assert not _hooks_dir( repo ).exists()


def test_the_main_checkout_of_a_repository_with_a_linked_worktree_still_installs( tmp_path ):
    repo = _scratch( tmp_path )
    git  = [ "git", "-c", "user.name=t", "-c", "user.email=t@t", "-C", str( repo ) ]
    subprocess.run( [ *git, "add", "-A" ], check=True )
    subprocess.run( [ *git, "commit", "-q", "-m", "scratch" ], check=True )
    subprocess.run( [ *git, "worktree", "add", "-q", "--detach", str( tmp_path / "linked" ) ], check=True )
    assert _run( repo ).returncode == 0


# ── nothing can point a link elsewhere ───────────────────────────────────────

@pytest.mark.parametrize( "args", [
    [ "/etc/passwd" ], [ "pre-push=/tmp/x" ], [ "--replace=/tmp/x" ], [ "--target", "/tmp/x" ], [ "--replace", "/tmp/x" ],
] )
def test_no_argument_can_name_a_target( tmp_path, args ):
    repo = _scratch( tmp_path )
    r    = _run( repo, *args )
    assert r.returncode == 2
    assert not ( _hooks_dir( repo ) / "pre-push" ).is_symlink()


def test_no_environment_variable_can_name_a_target_or_move_the_folder( tmp_path ):
    """Tried five variables: three name a decoy path, two point git at a decoy repository."""
    repo  = _scratch( tmp_path )
    decoy = tmp_path / "decoy"; subprocess.run( [ "git", "init", "-q", str( decoy ) ], check=True )
    env   = { "LUPIN_ROOT": str( decoy ), "HOOKS_DIR": str( decoy / "h" ), "HOOK_TARGET": "/tmp/x",
              "GIT_DIR": str( decoy / ".git" ), "GIT_WORK_TREE": str( decoy ) }
    r = _run( repo, env=env )
    assert r.returncode == 0, r.stdout + r.stderr
    for hook, script in HOOKS:
        assert os.readlink( _hooks_dir( repo ) / hook ) == f"{repo}/src/scripts/{script}"
    assert [ p for p in ( decoy / ".git" / "hooks" ).glob( "pre-*" ) if not p.name.endswith( ".sample" ) ] == [], "the decoy repository must be left untouched"
    assert not ( decoy / "h" ).exists()


# ── lupin-vm.sh ──────────────────────────────────────────────────────────────

def _vm( *args ):
    env = { **os.environ, "LUPIN_GCP_PROJECT_ID": "dry-run-project", "LUPIN_SKIP_PREFLIGHT": "1" }
    return subprocess.run( [ "bash", LUPIN_VM, "--dry-run", *args ], capture_output=True, text=True, timeout=60, env=env )


def test_install_hooks_verb_dry_run_prints_the_installer_step_and_runs_nothing():
    r   = _vm( "install-hooks" )
    out = r.stdout + r.stderr
    assert r.returncode == 0, out
    assert "bash src/scripts/install-git-hooks.sh" in out
    assert "(dry-run) not executed" in out


def test_deploy_dry_run_prints_the_installer_step_before_the_post_deploy_preflight():
    r   = _vm( "deploy" )
    out = r.stdout + r.stderr
    assert r.returncode == 0, out
    assert "bash src/scripts/install-git-hooks.sh" in out
    assert out.index( "install-git-hooks.sh" ) < out.index( "POST-deploy preflight (--phase post)" )


def test_usage_lists_the_verb():
    r = subprocess.run( [ "bash", LUPIN_VM ], capture_output=True, text=True, timeout=30 )
    assert "install-hooks" in r.stdout + r.stderr
