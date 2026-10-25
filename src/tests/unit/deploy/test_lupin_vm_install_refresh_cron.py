"""
Tests for the install-refresh-cron verb and the deploy sync step in lupin-vm.sh.

All runs are --dry-run, so no gcloud is called: the verb prints the exact command it would send.
"""
import os
import subprocess
from pathlib import Path

SCRIPT = Path( os.environ.get( "LUPIN_ROOT", os.getcwd() ) ) / "src" / "scripts" / "lupin-vm.sh"


def vm( *args, env=None ):
    base = { "PATH": os.environ[ "PATH" ], "HOME": "/nonexistent", "LUPIN_GCP_PROJECT_ID": "proj-x" }
    return subprocess.run( [ "bash", str( SCRIPT ), "--dry-run", *args ], capture_output=True, text=True, env={ **base, **( env or {} ) } )


def test_the_vm_install_sets_all_three_variables_from_the_known_vm_paths_and_not_from_the_callers_shell():
    done = vm( "install-refresh-cron", "vm", env={ "DEEPILY_DATA_DIR": "/dev/box", "PLANNING_IS_PROMPTING_ROOT": "/dev/pip" } )
    assert done.returncode == 0
    assert "export LUPIN_ROOT='/mnt/lupin-data/lupin' DEEPILY_DATA_DIR='/mnt/lupin-data/projects-data' PLANNING_IS_PROMPTING_ROOT='/mnt/lupin-data/planning-is-prompting'" in done.stderr + done.stdout
    assert "/dev/box" not in done.stdout + done.stderr
    assert "reuse-vector-refresh.sh --install" in done.stdout + done.stderr and "reuse-vector-refresh.sh --status" in done.stdout + done.stderr


def test_the_install_warns_when_the_test_login_file_is_missing_and_names_the_verb_that_writes_it():
    out = vm( "install-refresh-cron", "vm" )
    assert "push-test-mock-login vm" in out.stdout + out.stderr


def test_local_carries_the_callers_two_variables_and_the_checkout_it_runs_from():
    done = vm( "install-refresh-cron", env={ "DEEPILY_DATA_DIR": "/d", "PLANNING_IS_PROMPTING_ROOT": "/p" } )
    text = done.stdout + done.stderr
    assert done.returncode == 0 and f"DEEPILY_DATA_DIR='/d' PLANNING_IS_PROMPTING_ROOT='/p'" in text
    assert f"LUPIN_ROOT='{SCRIPT.parent.parent.parent}'" in text and "push-test-mock-login local" in text


def test_local_refuses_naming_the_missing_variable():
    one = vm( "install-refresh-cron", "local", env={ "PLANNING_IS_PROMPTING_ROOT": "/p" } )
    assert one.returncode == 1 and "needs DEEPILY_DATA_DIR" in one.stderr
    two = vm( "install-refresh-cron", "local", env={ "DEEPILY_DATA_DIR": "/d" } )
    assert two.returncode == 1 and "needs PLANNING_IS_PROMPTING_ROOT" in two.stderr


def test_the_vm_install_creates_the_handoff_folder_for_both_users_before_installing():
    text = vm( "install-refresh-cron", "vm" ).stderr + vm( "install-refresh-cron", "vm" ).stdout
    create = 'sudo install -d -m 2775 -o 1001 -g "$( id -g )" "/mnt/lupin-data/lupin/$HANDOFF"'
    assert create in text and "reuse candidate purpose handoff subdir" in text
    assert text.index( create ) < text.index( "reuse-vector-refresh.sh --install" )


def test_the_handoff_step_reads_the_real_ini_key_and_refuses_when_it_is_absent( tmp_path ):
    # Run the printed lines in a scratch checkout with sudo stubbed, once with the key and once without.
    printed = vm( "install-refresh-cron", "vm" ).stdout
    lines   = [ l.strip() for l in printed.splitlines() if "HANDOFF" in l ]
    assert len( lines ) == 3
    script  = "\n".join( lines )
    ( tmp_path / "bin" ).mkdir()
    ( tmp_path / "bin" / "sudo" ).write_text( '#!/bin/bash\necho "SUDO $*"\n' )
    ( tmp_path / "bin" / "sudo" ).chmod( 0o755 )
    ( tmp_path / "src" / "conf" ).mkdir( parents=True )
    env = { "PATH": f"{tmp_path / 'bin'}:{os.environ[ 'PATH' ]}" }
    ( tmp_path / "src" / "conf" / "lupin-app.ini" ).write_text( "reuse candidate purpose handoff subdir          = io/reuse-candidate-purpose\n" )
    ok = subprocess.run( [ "bash", "-c", script ], cwd=tmp_path, capture_output=True, text=True, env=env )
    assert ok.returncode == 0 and "-o 1001" in ok.stdout and "/mnt/lupin-data/lupin/io/reuse-candidate-purpose" in ok.stdout
    ( tmp_path / "src" / "conf" / "lupin-app.ini" ).write_text( "other = 1\n" )
    bad = subprocess.run( [ "bash", "-c", script ], cwd=tmp_path, capture_output=True, text=True, env=env )
    assert bad.returncode == 1 and "has no reuse candidate purpose handoff subdir" in bad.stdout and "SUDO" not in bad.stdout


def test_the_local_install_does_not_touch_the_handoff_folder():
    done = vm( "install-refresh-cron", "local", env={ "DEEPILY_DATA_DIR": "/d", "PLANNING_IS_PROMPTING_ROOT": "/p" } )
    assert "sudo install" not in done.stdout + done.stderr


def test_a_host_other_than_local_or_vm_is_refused():
    done = vm( "install-refresh-cron", "mars" )
    assert done.returncode == 1 and "takes local or vm, not 'mars'" in done.stderr


def test_the_usage_lists_the_verb():
    assert "install-refresh-cron [local|vm]" in vm( "help" ).stdout + vm( "help" ).stderr


# ── deploy refreshes the sibling planning-is-prompting copy ──


def pip_repo( tmp_path ):
    repo = tmp_path / "pip"
    repo.mkdir()
    subprocess.run( [ "git", "init", "-q", str( repo ) ], check=True )
    subprocess.run( [ "git", "-C", str( repo ), "-c", "user.email=a@b", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "x" ], check=True )
    return repo


def deploy( env ):
    # LUPIN_SKIP_PREFLIGHT keeps the dry run off the VM; the bundle step is a dry run too.
    return vm( "deploy", env={ "LUPIN_SKIP_PREFLIGHT": "1", **env } )


def test_deploy_pushes_the_local_planning_is_prompting_to_the_vms_sibling_path( tmp_path ):
    repo = pip_repo( tmp_path )
    done = deploy( { "PLANNING_IS_PROMPTING_ROOT": str( repo ) } )
    text = done.stdout + done.stderr
    assert f"archiving {repo} @ HEAD -> planning-is-prompting.tar.gz" in text
    assert "refreshing the VM's planning-is-prompting" in text


def test_deploy_warns_loudly_when_there_is_no_local_checkout_to_push( tmp_path ):
    done = deploy( { "PLANNING_IS_PROMPTING_ROOT": str( tmp_path ) } )
    assert "was NOT refreshed" in done.stdout + done.stderr
    assert "archiving" not in done.stdout + done.stderr
    assert "was NOT refreshed" in deploy( {} ).stdout + deploy( {} ).stderr


def test_deploy_skips_the_refresh_on_request( tmp_path ):
    done = deploy( { "PLANNING_IS_PROMPTING_ROOT": str( pip_repo( tmp_path ) ), "LUPIN_SKIP_PIP_SYNC": "1" } )
    assert "planning-is-prompting sync SKIPPED" in done.stdout + done.stderr and "archiving" not in done.stdout + done.stderr


def test_deploy_carries_on_to_the_restart_when_the_planning_is_prompting_sync_fails( tmp_path ):
    # A real (not dry) run in a tiny scratch repo, with a gcloud stub that fails only the planning-is-prompting copy.
    repo = tmp_path / "lupin"
    ( repo / "src" / "scripts" ).mkdir( parents=True )
    ( repo / "src" / "scripts" / "lupin-vm.sh" ).write_text( SCRIPT.read_text() )
    git = [ "git", "-C", str( repo ), "-c", "user.email=a@b", "-c", "user.name=t" ]
    subprocess.run( [ "git", "init", "-q", "-b", "main", str( repo ) ], check=True )
    subprocess.run( [ *git, "add", "." ], check=True )
    subprocess.run( [ *git, "commit", "-q", "-m", "x" ], check=True )
    bindir, calls = tmp_path / "bin", tmp_path / "calls.log"
    bindir.mkdir()
    ( bindir / "gcloud" ).write_text( '#!/bin/bash\necho "$*" >> "$STUB_CALLS"\ncase "$*" in *planning-is-prompting.tar.gz*) exit 1;; esac\nexit 0\n' )
    ( bindir / "gcloud" ).chmod( 0o755 )
    env = { "PATH": f"{bindir}:{os.environ[ 'PATH' ]}", "HOME": str( tmp_path ), "LUPIN_GCP_PROJECT_ID": "proj-x", "LUPIN_SKIP_PREFLIGHT": "1",
            "PLANNING_IS_PROMPTING_ROOT": str( pip_repo( tmp_path ) ), "STUB_CALLS": str( calls ) }
    done = subprocess.run( [ "bash", str( repo / "src" / "scripts" / "lupin-vm.sh" ), "deploy", "main" ], capture_output=True, text=True, env=env )
    text = done.stdout + done.stderr
    assert "WARN: the planning-is-prompting refresh FAILED" in text
    assert done.returncode == 0 and "restarting :7999 rest" in text
    assert "docker compose" in calls.read_text()
    assert "WARN: push-dist FAILED" in text
