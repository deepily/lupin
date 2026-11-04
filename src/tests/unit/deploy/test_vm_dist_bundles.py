"""
Tests for shipping and checking the built dist bundles on the VM.

The VM bind-mounts its checkout's ./src over the image, so the image's bundles are hidden.
The dist folder is gitignored, so the checkout only has the bundles if push-dist put them there.
"""
import json
import os
import re
import subprocess
from pathlib import Path

ROOT      = Path( os.environ.get( "LUPIN_ROOT", os.getcwd() ) )
VM_SCRIPT = ROOT / "src" / "scripts" / "lupin-vm.sh"
LIB       = ROOT / "src" / "scripts" / "lib" / "preflight-vm-lib.sh"
PREFLIGHT = ROOT / "src" / "scripts" / "preflight-vm.sh"


def declared_bundles():
    """Read the bundle folders the build script writes, from package.json."""
    build = json.loads( ( ROOT / "package.json" ).read_text() )[ "scripts" ][ "build" ]
    names = []
    for script in re.findall( r"bash (src/scripts/build-[a-z-]+\.sh)", build ):
        out = re.search( r'^OUTDIR="src/lupin_app/static/dist/([a-z-]+)"', ( ROOT / script ).read_text(), re.M ).group( 1 )
        if out not in names: names.append( out )
    return names


def lib( snippet ):
    return subprocess.run( [ "bash", "-c", f'source "{LIB}"; {snippet}' ], capture_output=True, text=True )


def test_the_three_bundle_lists_are_the_ones_the_build_script_writes():
    built = declared_bundles()
    assert built == [ "multiplexer", "console", "doc-podcast" ]
    assert f'DIST_BUNDLES="{" ".join( built )}"' in VM_SCRIPT.read_text()
    assert f'DIST_REQUIRED="{" ".join( built )}"' in PREFLIGHT.read_text()


def test_dist_status_is_ok_only_when_every_required_bundle_is_present():
    done = lib( 'pfv_dist_status "multiplexer console doc-podcast" "doc-podcast console multiplexer"; echo " rc=$?"' )
    assert done.stdout.split() == [ "OK", "rc=0" ]


def test_dist_status_names_every_absent_bundle_in_the_required_order():
    done = lib( 'pfv_dist_status "multiplexer console doc-podcast" "multiplexer"; echo " rc=$?"' )
    assert done.stdout.split() == [ "MISSING:", "console", "doc-podcast", "rc=1" ]
    assert lib( 'pfv_dist_status "multiplexer console" ""' ).stdout.strip() == "MISSING: multiplexer console"


def test_dist_status_does_not_match_a_name_that_only_contains_a_required_one():
    assert lib( 'pfv_dist_status "console" "console-old"' ).stdout.strip() == "MISSING: console"


def test_the_preflight_blocks_after_a_deploy_and_only_warns_before_one():
    text = PREFLIGHT.read_text()
    assert 'dist_tier="BLOCK"; [ "$PHASE" = "pre" ] && dist_tier="WARN"' in text
    assert 'report fail "$dist_tier" "built bundles absent' in text


def test_the_preflight_reports_the_check_after_the_deployed_ref_check_and_names_the_fix():
    text = PREFLIGHT.read_text()
    assert text.index( "# B7 — the built" ) > text.index( "# B6 — the `.deployed-ref`" )
    assert 'pfv_dist_status "$DIST_REQUIRED" "$dist_present"' in text and "lupin-vm.sh push-dist" in text


def scratch_checkout( tmp_path, built ):
    """A copy of lupin-vm.sh in a tree whose dist holds the named bundles."""
    ( tmp_path / "src" / "scripts" ).mkdir( parents=True )
    ( tmp_path / "src" / "scripts" / "lupin-vm.sh" ).write_text( VM_SCRIPT.read_text() )
    for name in built:
        d = tmp_path / "src" / "lupin_app" / "static" / "dist" / name
        d.mkdir( parents=True )
        ( d / "manifest.json" ).write_text( "{}" )
    return tmp_path / "src" / "scripts" / "lupin-vm.sh"


def push_dist( script, *flags ):
    env = { "PATH": os.environ[ "PATH" ], "HOME": "/nonexistent", "LUPIN_GCP_PROJECT_ID": "proj-x" }
    return subprocess.run( [ "bash", str( script ), *flags, "push-dist" ], capture_output=True, text=True, env=env )


def test_push_dist_with_every_bundle_built_would_archive_them_and_extract_on_the_vm_checkout( tmp_path ):
    done = push_dist( scratch_checkout( tmp_path, declared_bundles() ), "--dry-run" )
    text = done.stdout + done.stderr
    assert done.returncode == 0
    assert "tar -czf dist.tar.gz multiplexer console doc-podcast" in text
    assert "sudo tar -xzf -C /mnt/lupin-data/lupin/src/lupin_app/static/dist" in text


def test_push_dist_refuses_naming_each_unbuilt_bundle_and_sends_nothing( tmp_path ):
    done = push_dist( scratch_checkout( tmp_path, [ "multiplexer" ] ), "--dry-run" )
    assert done.returncode == 1
    assert "not built" in done.stderr and "console doc-podcast" in done.stderr and "Nothing was sent" in done.stderr
    assert "tar -czf" not in done.stdout + done.stderr


def test_a_bundle_folder_without_its_manifest_counts_as_not_built( tmp_path ):
    script = scratch_checkout( tmp_path, declared_bundles() )
    ( tmp_path / "src" / "lupin_app" / "static" / "dist" / "console" / "manifest.json" ).unlink()
    done = push_dist( script, "--dry-run" )
    assert done.returncode == 1 and "not built" in done.stderr and "console" in done.stderr


def test_a_real_push_dist_ships_the_archive_with_the_built_folders_to_the_vm_checkout( tmp_path ):
    script = scratch_checkout( tmp_path, declared_bundles() )
    bindir, calls = tmp_path / "bin", tmp_path / "calls.log"
    bindir.mkdir()
    ( bindir / "gcloud" ).write_text( '#!/bin/bash\necho "$*" >> "$STUB_CALLS"\nexit 0\n' )
    ( bindir / "gcloud" ).chmod( 0o755 )
    env = { "PATH": f"{bindir}:{os.environ[ 'PATH' ]}", "HOME": str( tmp_path ), "LUPIN_GCP_PROJECT_ID": "proj-x", "STUB_CALLS": str( calls ) }
    done = subprocess.run( [ "bash", str( script ), "push-dist" ], capture_output=True, text=True, env=env )
    log = calls.read_text()
    assert done.returncode == 0
    assert "compute scp" in log and "lupin-dist.tar.gz" in log
    assert "tar -xzf /tmp/lupin-dist.tar.gz -C /mnt/lupin-data/lupin/src/lupin_app/static/dist" in log and "chown -R 1001:1001" in log


def test_deploy_runs_push_dist_after_the_code_sync():
    text = VM_SCRIPT.read_text()
    assert text.index( "do_push_bundle \"$DEPLOY_BRANCH\"" ) < text.index( "push-dist" , text.index( "# 1c." ) )
    assert "WARN: push-dist FAILED" in text


def test_dist_present_lists_only_bundles_holding_a_manifest_file( tmp_path ):
    ( tmp_path / "multiplexer" ).mkdir()
    ( tmp_path / "multiplexer" / "manifest.json" ).write_text( "{}" )
    ( tmp_path / "console" ).mkdir()
    ( tmp_path / "doc-podcast" ).mkdir()
    ( tmp_path / "doc-podcast" / "manifest.json" ).mkdir()
    done = lib( f'pfv_dist_present "{tmp_path}" "multiplexer console doc-podcast absent"' )
    assert done.stdout.split() == [ "multiplexer" ]


def test_the_preflight_asks_the_lib_which_bundles_are_present():
    assert 'dist_present="$( pfv_dist_present "$REPO_ROOT/src/lupin_app/static/dist" "$DIST_REQUIRED" )"' in PREFLIGHT.read_text()


def stamp( tmp_path, built ):
    """Give each bundle in a scratch checkout a built time, and one TypeScript source a time."""
    script = scratch_checkout( tmp_path, declared_bundles() )
    for name in declared_bundles():
        ( tmp_path / "src" / "lupin_app" / "static" / "dist" / name / "manifest.json" ).write_text( f'{{ "built" : "{built}" }}' )
    ts = tmp_path / "src" / "lupin_app" / "static" / "js" / "a.ts"
    ts.parent.mkdir( parents=True )
    ts.write_text( "" )
    when = 1760000000
    os.utime( ts, ( when, when ) )
    return script


def test_push_dist_prints_each_bundles_build_time_beside_the_newest_source_time( tmp_path ):
    done = push_dist( stamp( tmp_path, "2026-12-01T00:00:00Z" ), "--dry-run" )
    text = done.stdout + done.stderr
    assert done.returncode == 0 and "WARN" not in text
    for name in declared_bundles():
        assert f"bundle {name}: built 2026-12-01T00:00:00Z, newest source 2025-10-09T08:53:20Z" in text


def test_push_dist_warns_but_still_ships_a_bundle_built_before_the_newest_source( tmp_path ):
    done = push_dist( stamp( tmp_path, "2025-01-01T00:00:00Z" ), "--dry-run" )
    text = done.stdout + done.stderr
    assert done.returncode == 0 and text.count( "WARN: older than the newest source; run npm run build" ) == 3
    assert "tar -czf dist.tar.gz" in text


def test_push_dist_with_no_source_files_says_unknown_and_does_not_warn( tmp_path ):
    done = push_dist( scratch_checkout( tmp_path, declared_bundles() ), "--dry-run" )
    text = done.stdout + done.stderr
    assert "newest source unknown" in text and "WARN" not in text and "built unknown" in text
