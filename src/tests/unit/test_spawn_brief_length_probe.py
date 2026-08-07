#!/usr/bin/env python3
"""
Unit tests: the dry_run brief-length probe in start-cc-with-tmux.sh (row
9c5dccd4 — spawn_sessions failed silently over a too-large brief).

THE DEFECT: a brief too large for tmux's command-length limit makes the real
`tmux new-session` die "command too long". The live spawn path now surfaces
that verbatim (session_spawner reads the failed child's stderr into `reason`),
but dry_run exits ABOVE that call — so before this probe an oversized brief
dry-ran clean and lied about a spawn that would fail. dry_run is exactly the
tool a manager uses to check a brief BEFORE committing a fleet to it.

THE PROBE (dry_run only): fire the same tmux invocation shape as a no-op into a
uniquely-named throwaway session, at the byte-length of the real assembled
command, and read the box's OWN tmux verdict — no baked constant, which would
be wrong on a box with a different tmux build or env size. Kill the throwaway;
report ok / FAIL / could-not-verify.

DELETE-THE-STEP GUARD: remove the probe block from start-cc-with-tmux.sh and
`test_oversized_dry_run_fails_loud` reverts to a clean exit 0 and fails — the
test measures the probe, not incidental script behavior.

Venue: :7999-eligible / local — no server, no DB, no persistent state (dry_run;
the throwaway tmux session self-exits and is killed), a few seconds. Requires
bash + tmux; skips cleanly without them.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

LUPIN_ROOT = os.environ.get( "LUPIN_ROOT" )
SCRIPT     = Path( _src_path ) / "scripts" / "start-cc-with-tmux.sh"

_requires_tmux = pytest.mark.skipif(
    shutil.which( "tmux" ) is None or shutil.which( "bash" ) is None or not LUPIN_ROOT,
    reason="bash + tmux + LUPIN_ROOT required for the live dry_run probe"
)


def _dry_run( prompt, session_name, path_prefix=None ):
    """
    Invoke start-cc-with-tmux.sh --headless --dry-run with `prompt` and return
    (returncode, combined_stdout_stderr).

    Requires:
        - SCRIPT exists; LUPIN_ROOT is set; tmux + bash on PATH
        - prompt is the rendered brief; session_name is a unique tmux name
        - path_prefix, when given, is prepended to PATH (used to shadow `tmux`
          with a stub that fails for a non-length reason)

    Ensures:
        - runs the REAL script (same argv shape as build_spawn_argv), dry_run
        - returns the exit code and merged output; never raises on non-zero
    """
    env = { **os.environ, "PYTHONPATH": _src_path + os.pathsep + os.environ.get( "PYTHONPATH", "" ) }
    if path_prefix is not None:
        env[ "PATH" ] = str( path_prefix ) + os.pathsep + env.get( "PATH", "" )
    proc = subprocess.run(
        [ "bash", str( SCRIPT ), "--headless", "--dry-run", session_name, "--prompt", prompt ],
        capture_output=True, text=True, timeout=60, env=env
    )
    return proc.returncode, proc.stdout + proc.stderr


def _lingering_probe_sessions():
    """Count throwaway __lenprobe sessions still alive (should always be 0)."""
    out = subprocess.run( [ "tmux", "ls" ], capture_output=True, text=True ).stdout
    return sum( 1 for line in out.splitlines() if "__lenprobe" in line )


@_requires_tmux
class TestBriefLengthProbe:
    def test_undersized_dry_run_passes( self ):
        # A small brief fits tmux → dry_run reports ok and exits 0, exactly as
        # before the probe existed (the probe must not break the common case).
        rc, out = _dry_run( "do the review", "probe-test-small" )
        assert rc == 0
        assert "BRIEF-LENGTH-PROBE: ok" in out
        assert _lingering_probe_sessions() == 0   # throwaway cleaned up

    def test_oversized_dry_run_fails_loud( self ):
        # THE FIX: a 30 KB brief exceeds tmux's command-length limit. dry_run
        # must fail non-zero, name tmux's own verdict, and report the measured
        # byte count — never a quiet pass. (Delete the probe block → this reverts
        # to exit 0 and fails.)
        rc, out = _dry_run( "OVERSIZED " + ( "x" * 30000 ), "probe-test-big" )
        assert rc != 0
        assert "BRIEF-LENGTH-PROBE: FAIL" in out
        assert "command too long" in out
        assert "bytes" in out                     # the measured number is in the message
        assert _lingering_probe_sessions() == 0   # a failed create leaves nothing

    def test_probe_reports_the_assembled_byte_count_not_the_brief( self ):
        # Cheech's correction: the probe measures the ASSEMBLED command (INNER +
        # forwarded flags), which is strictly larger than the brief alone. A
        # 30 KB brief must report MORE than 30000 bytes.
        rc, out = _dry_run( "y" * 30000, "probe-test-assembled" )
        assert rc != 0
        digits = [ int( tok ) for tok in out.replace( ";", " " ).split() if tok.isdigit() ]
        assert any( n > 30000 for n in digits ), f"no assembled byte-count > 30000 in: {out!r}"

    def test_probe_cannot_verify_reports_and_does_not_pass( self, tmp_path ):
        # The else branch (Cheech's dry_run mandate): when the probe tmux call
        # fails for a reason OTHER than "command too long" — here a stub `tmux`
        # that exits non-zero with an unrelated error — dry_run must SAY it could
        # not verify and exit non-zero, never pass quietly on an unproven brief.
        stub_dir = tmp_path / "bin"
        stub_dir.mkdir()
        stub = stub_dir / "tmux"
        # Fail every tmux call with a non-length error → drives the else branch.
        stub.write_text( "#!/usr/bin/env bash\necho 'tmux: connection refused' >&2\nexit 1\n" )
        stub.chmod( 0o755 )
        rc, out = _dry_run( "do the review", "probe-test-cannot", path_prefix=stub_dir )
        assert rc != 0
        assert "BRIEF-LENGTH-PROBE: could NOT verify" in out
        assert "connection refused" in out        # the real reason is surfaced, not swallowed
