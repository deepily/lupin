"""
Deploy refuses a VM checkout that has uncommitted tracked edits.

The reset step of `lupin-vm.sh deploy` discards tracked edits without a word. A deploy once wiped a
config diff that a VM session had applied live, and the repo left the doc viewer until it was redone.

Before the reset, the VM now checks `git status` for tracked edits. With no flag it stops and names
the files. With `--discard-vm-changes` it saves `git diff HEAD` under the discards directory and
names the path, then goes on.

The guard command is read from the script source and run against a temporary git repo, with `sudo`
as a pass-through function. The wiring is checked on the script text and through a stubbed `gcloud`.
This file runs on the dev server because it makes no network calls.
"""
import os
import pathlib
import re
import subprocess

import pytest


SCRIPT = pathlib.Path( os.environ[ "LUPIN_ROOT" ] ) / "src/scripts/lupin-vm.sh"
SOURCE = SCRIPT.read_text()


def _guard_definition():
    """
    Return the right-hand side of `local dirty_guard="..."` from the script source.

    Ensures:
        - fails the calling test when the definition is missing or defined twice
    """
    hits = re.findall( r'^\s*local dirty_guard="(.+)"\s*$', SOURCE, re.M )
    assert len( hits ) == 1, f"expected one dirty_guard definition, got {len( hits )}"
    return hits[ 0 ]


def _git( cwd, *args ):
    subprocess.run( [ "git", "-C", str( cwd ), "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args ],
                    check=True, capture_output=True )


@pytest.fixture
def vm_tree( tmp_path ):
    """A real git repo standing in for the VM checkout, one tracked file committed."""
    root = tmp_path / "vm-lupin"
    root.mkdir()
    _git( root, "init", "-q" )
    ( root / "tracked.ini" ).write_text( "scope = original\n" )
    _git( root, "add", "tracked.ini" )
    _git( root, "commit", "-q", "-m", "base" )
    return root


def _run_guard( root, tmp_path, discard ):
    """Run the extracted guard the way the VM's shell would, with `sudo` a no-op wrapper."""
    discards = tmp_path / "deploy-discards"
    script = (
        'sudo() { "$@"; }\n'
        f'safe=""; VM_ROOT="{root}"; VM_DISCARD_DIR="{discards}"; DISCARD_VM_CHANGES={1 if discard else 0}\n'
        f'dirty_guard="{_guard_definition()}"\n'
        f'cd "{root}" && eval "$dirty_guard"\n'
    )
    proc = subprocess.run( [ "bash", "-c", script ], capture_output=True, text=True )
    return proc, discards


def test_a_clean_tree_passes_silently( vm_tree, tmp_path ):
    proc, discards = _run_guard( vm_tree, tmp_path, discard=False )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == ""
    assert not discards.exists()


def test_untracked_files_do_not_block( vm_tree, tmp_path ):
    """Reset leaves untracked files alone, and the VM keeps its data and env files there."""
    ( vm_tree / "cloud-gpu.env" ).write_text( "X=1\n" )
    proc, _ = _run_guard( vm_tree, tmp_path, discard=False )
    assert proc.returncode == 0, proc.stdout


def test_a_dirty_tree_refuses_names_the_file_and_changes_nothing( vm_tree, tmp_path ):
    ( vm_tree / "tracked.ini" ).write_text( "scope = hand-applied\n" )
    proc, discards = _run_guard( vm_tree, tmp_path, discard=False )

    assert proc.returncode != 0, "a dirty VM tree was allowed through without --discard-vm-changes"
    assert "tracked.ini" in proc.stdout
    assert "VM_DIRTY_REFUSED" in proc.stdout
    assert ( vm_tree / "tracked.ini" ).read_text() == "scope = hand-applied\n"
    assert not discards.exists()


def test_staged_edits_count_as_dirty( vm_tree, tmp_path ):
    ( vm_tree / "tracked.ini" ).write_text( "scope = staged\n" )
    _git( vm_tree, "add", "tracked.ini" )
    proc, _ = _run_guard( vm_tree, tmp_path, discard=False )
    assert proc.returncode != 0
    assert "tracked.ini" in proc.stdout


def test_the_flag_saves_a_patch_names_it_and_lets_the_reset_go_on( vm_tree, tmp_path ):
    ( vm_tree / "tracked.ini" ).write_text( "scope = hand-applied\n" )
    proc, discards = _run_guard( vm_tree, tmp_path, discard=True )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    patches = list( discards.glob( "*.diff" ) )
    assert len( patches ) == 1
    assert str( patches[ 0 ] ) in proc.stdout, "the log line does not name the saved patch"
    assert "tracked.ini" in proc.stdout
    assert "+scope = hand-applied" in patches[ 0 ].read_text()


# ── wiring ────────────────────────────────────────────────────────────────

def test_the_guard_runs_before_the_reset_in_reset_mode_only():
    lines  = [ l for l in SOURCE.split( "\n" ) if l.lstrip().startswith( "rcmd=" ) ]
    reset  = [ l for l in lines if "RESET_CHECKED_OUT" in l ]
    checkout = [ l for l in lines if "echo CHECKED_OUT " in l ]
    assert len( reset ) == 1 and len( checkout ) == 1
    assert reset[ 0 ].index( "$dirty_guard" ) < reset[ 0 ].index( "reset --hard" )
    assert "dirty_guard" not in checkout[ 0 ], "checkout mode already aborts on drift; it needs no guard"


@pytest.fixture
def run_deploy( tmp_path ):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "gcloud"
    stub.write_text( '#!/bin/bash\necho "$@" >> "$GCLOUD_CALL_LOG"\nexit 0\n' )
    stub.chmod( 0o755 )
    log = tmp_path / "calls.txt"

    def _run( *args ):
        env = dict( os.environ )
        env[ "PATH" ]                 = f"{bin_dir}:{env[ 'PATH' ]}"
        env[ "GCLOUD_CALL_LOG" ]      = str( log )
        env[ "LUPIN_GCP_PROJECT_ID" ] = "fake-project-for-tests"
        return subprocess.run( [ "bash", str( SCRIPT ), *args ], capture_output=True, text=True, env=env, timeout=120 )

    return _run


def test_deploy_rejects_an_unknown_flag( run_deploy ):
    proc = run_deploy( "--dry-run", "deploy", "--bogus" )
    assert proc.returncode != 0
    assert "--bogus" in proc.stderr


def test_dry_run_narration_names_the_guard_when_the_flag_is_given( run_deploy ):
    proc = run_deploy( "--dry-run", "deploy", "somebranch", "--discard-vm-changes" )
    assert "discard-vm-changes" in proc.stdout + proc.stderr
    assert "deploy-discards" in proc.stdout + proc.stderr


def _tree_with_config( vm_tree ):
    """Add the two config files and a compose file to the stand-in checkout, committed clean."""
    conf = vm_tree / "src" / "conf"
    conf.mkdir( parents=True )
    for name in ( "lupin-app.ini", "lupin-app-splainer.ini" ): ( conf / name ).write_text( "k = dev\n" )
    ( vm_tree / "docker-compose.cloud-gpu.yml" ).write_text( "a: 1\n" )
    _git( vm_tree, "add", "." )
    _git( vm_tree, "commit", "-q", "-m", "config" )
    return conf


def test_an_edit_to_the_two_ini_files_alone_does_not_stop_the_deploy( vm_tree, tmp_path ):
    """Rick, 21 Nov 2026: a deploy overwrites them with dev's copy, so they never stop it."""
    conf = _tree_with_config( vm_tree )
    ( conf / "lupin-app.ini" ).write_text( "k = vm\n" )
    ( conf / "lupin-app-splainer.ini" ).write_text( "k = vm\n" )
    proc, discards = _run_guard( vm_tree, tmp_path, discard=False )
    assert proc.returncode == 0, proc.stdout
    assert proc.stdout == "" and not discards.exists()


def test_the_ini_exemption_does_not_hide_another_dirty_file( vm_tree, tmp_path ):
    conf = _tree_with_config( vm_tree )
    ( conf / "lupin-app.ini" ).write_text( "k = vm\n" )
    ( vm_tree / "docker-compose.cloud-gpu.yml" ).write_text( "a: 2\n" )
    proc, _ = _run_guard( vm_tree, tmp_path, discard=False )
    assert proc.returncode != 0
    assert "docker-compose.cloud-gpu.yml" in proc.stdout
    assert "lupin-app.ini" not in proc.stdout


def test_deploy_pushes_the_global_claude_md_after_the_planning_sync_and_preflight_checks_it():
    """The push sits after the planning sync, before the dist push; preflight checks it."""
    sync, push, dist = ( SOURCE.index( m ) for m in ( "# 1b. The VM's planning-is-prompting copy", "# 1b2. The VM's seats read ~/.claude/CLAUDE.md", "# 1c. The pages load" ) )
    assert sync < push < dist
    assert "push-file \"$PLANNING_IS_PROMPTING_ROOT/global/CLAUDE.md\" '~/.claude/CLAUDE.md'" in SOURCE
    preflight = ( SCRIPT.parent / "preflight-vm.sh" ).read_text()
    assert "# B8 — the VM's global ~/.claude/CLAUDE.md" in preflight
    assert 'cmp -s "$VM_PIP_GLOBAL" "$VM_USER_GLOBAL"' in preflight
