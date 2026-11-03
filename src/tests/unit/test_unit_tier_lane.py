"""
Pins the unit-tier lane in `src/scripts/lib/jstest-slice.sh`, from the memory row.

An OOM kill inside the scope exits 72 with an out-of-memory banner. Before this, the same
kill read as an ordinary failing test run.

The control arm runs the same allocator under a higher ceiling and is not reported as OOM.
A real test failure keeps its own status and prints no OOM banner.
A passing run that saw a kill keeps 0 and warns.
The runner wires the lane in, and refuses when systemd-run is missing.

The subjects are a synthetic allocator, `true` and `bash`. Nothing here runs the unit tier.
"""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from tests.collected_count_guard import assert_every_declared_test_is_collected

ROOT   = Path( os.environ[ "LUPIN_ROOT" ] )
LIB    = ROOT / "src" / "scripts" / "lib" / "jstest-slice.sh"
RUNNER = ROOT / "src" / "tests" / "run-unit-tests.sh"

HAS_SYSTEMD_RUN = os.path.exists( "/usr/bin/systemd-run" )

# Stops at 1 GB so the control arm can raise the cap above it without a real runaway.
_HOG_SRC = (
    "import sys\n"
    "chunks = []\n"
    "while True:\n"
    "    chunks.append( bytearray( 8 * 1024 * 1024 ) )\n"
    "    if len( chunks ) > 128: sys.exit( 99 )\n"
)


def _run_lane( args, mem_max, tmp_path ):
    """Source the lane and run unit_scope_exec on `args` under `mem_max`."""
    script = 'source "%s"\nunit_scope_exec %s' % ( LIB, " ".join( args ) )
    env    = dict( os.environ )
    env.update( { "UNIT_MEM_MAX": mem_max, "UNIT_RUNTIME_MAX": "60", "UNIT_SLICE": "unittier.slice" } )
    return subprocess.run( [ "bash", "-c", script ], capture_output=True, text=True, env=env, timeout=90 )


def _hog( tmp_path ):
    hog = tmp_path / "hog.py"
    hog.write_text( _HOG_SRC, encoding="utf-8" )
    return hog


@pytest.mark.skipif( not HAS_SYSTEMD_RUN, reason="systemd-run absent" )
class TestOomIsReportedAsOom:

    def test_a_kill_exits_72_with_the_out_of_memory_banner( self, tmp_path ):
        r = _run_lane( [ sys.executable, str( _hog( tmp_path ) ) ], "256M", tmp_path )
        assert r.returncode == 72, "rc=%r\nstderr=%s" % ( r.returncode, r.stderr )
        assert "OUT OF MEMORY" in r.stderr
        assert "MemoryMax=256M" in r.stderr

    def test_control_the_same_hog_under_a_high_ceiling_is_not_reported_as_oom( self, tmp_path ):
        r = _run_lane( [ sys.executable, str( _hog( tmp_path ) ) ], "4G", tmp_path )
        assert r.returncode == 99, "rc=%r\nstderr=%s" % ( r.returncode, r.stderr )
        assert "OUT OF MEMORY" not in r.stderr

    def test_a_real_failure_keeps_its_own_status_and_prints_no_oom_banner( self, tmp_path ):
        r = _run_lane( [ "bash", "-c", "'exit 3'" ], "256M", tmp_path )
        assert r.returncode == 3
        assert "OUT OF MEMORY" not in r.stderr

    def test_a_pass_returns_zero( self, tmp_path ):
        r = _run_lane( [ "true" ], "256M", tmp_path )
        assert r.returncode == 0
        assert "OUT OF MEMORY" not in r.stderr

    def test_a_pass_that_saw_a_kill_keeps_zero_and_warns( self, tmp_path ):
        hog = _hog( tmp_path )
        r   = _run_lane( [ "bash", "-c", "'( %s %s ) ; exit 0'" % ( sys.executable, hog ) ], "256M", tmp_path )
        assert r.returncode == 0, "rc=%r\nstderr=%s" % ( r.returncode, r.stderr )
        assert "yet the tier passed" in r.stderr

    def test_the_child_lands_in_the_unit_tier_slice( self, tmp_path ):
        r = _run_lane( [ "cat", "/proc/self/cgroup" ], "256M", tmp_path )
        assert "unittier.slice" in r.stdout, "stdout=%s\nstderr=%s" % ( r.stdout, r.stderr )


class TestTheLaneSettings:

    def test_the_default_ceiling_is_16G_and_never_a_MemoryHigh( self ):
        text = LIB.read_text( encoding="utf-8" )
        assert 'UNIT_MEM_MAX="${UNIT_MEM_MAX:-16G}"' in text
        assert "-p MemoryHigh" not in text

    def test_the_oom_status_is_72( self ):
        r = subprocess.run( [ "bash", "-c", 'source "%s"; echo $UNIT_OOM_EXIT' % LIB ], capture_output=True, text=True )
        assert r.stdout.strip() == "72"


class TestTheRunnerIsWiredToTheLane:

    def test_the_runner_calls_the_lane_before_resolving_pytest( self ):
        text = RUNNER.read_text( encoding="utf-8" )
        assert text.count( "unit_scope_exec" ) == 1
        assert text.index( "unit_scope_exec" ) < text.index( "resolve_venv_pytest ||" )

    def test_without_systemd_run_the_runner_refuses_with_70_before_pytest( self, tmp_path ):
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        for tool in ( "bash", "dirname", "cat", "sed", "awk" ):
            for root in ( "/usr/bin", "/bin" ):
                src = os.path.join( root, tool )
                if os.path.exists( src ) and not ( bin_dir / tool ).exists():
                    os.symlink( src, bin_dir / tool )
        env = dict( os.environ )
        env[ "PATH" ] = str( bin_dir )
        env.pop( "LUPIN_UNIT_SCOPED", None )
        env.pop( "LUPIN_UNIT_SCOPE", None )
        if os.path.exists( "/.dockerenv" ): pytest.skip( "container skips the scope by design" )
        r = subprocess.run( [ "/bin/bash", str( RUNNER ), "--collect-only", "-q" ], capture_output=True, text=True, env=env, timeout=60 )
        assert r.returncode == 70, "rc=%r\nstderr=%s" % ( r.returncode, r.stderr )
        assert "systemd-run NOT FOUND" in r.stderr
        assert "using pytest at" not in r.stderr

    def test_the_off_switch_skips_the_scope( self ):
        text = RUNNER.read_text( encoding="utf-8" )
        assert 'LUPIN_UNIT_SCOPE:-on}" != "off"' in text


def test_every_test_this_file_declares_is_actually_collected( request ):
    assert_every_declared_test_is_collected( request, __file__ )
