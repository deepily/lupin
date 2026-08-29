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

# F1 (row 0ab3c0cd): the real-tmux tests above SKIP on a box without tmux, so the
# probe's shell BRANCH logic (ok / command-too-long / could-not-verify) shipped
# GREEN and UNVERIFIED wherever tmux is absent — CI included. This gate needs only
# bash + LUPIN_ROOT, never real tmux: the branch tests drive the probe with a STUB
# `tmux`, so a regression in the shell logic FAILS on any box.
_requires_bash = pytest.mark.skipif(
    shutil.which( "bash" ) is None or not LUPIN_ROOT,
    reason="bash + LUPIN_ROOT required to drive the probe with a stub tmux"
)


def _stub_tmux_source( behavior ):
    """
    Bash source for a fake `tmux` that drives one probe branch (no real tmux).

    Requires:
        - behavior in { "ok", "too_long", "other" }

    Ensures:
        - "ok"       → new-session exits 0 (accepts); kill-session/other exit 0
        - "too_long" → new-session emits tmux's 'command too long' on stderr, exits 1
        - "other"    → new-session emits an unrelated error on stderr, exits 1
    """
    verdicts = {
        "ok"       : "exit 0",
        "too_long" : "echo 'tmux: command too long' >&2; exit 1",
        "other"    : "echo 'tmux: connection refused' >&2; exit 1",
    }
    new_session_line = verdicts[ behavior ]
    return (
        "#!/usr/bin/env bash\n"
        'case "$1" in\n'
        f"  new-session) {new_session_line} ;;\n"
        "  *) exit 0 ;;\n"       # kill-session / anything else the probe issues
        "esac\n"
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


@_requires_bash
class TestBriefLengthProbeBranchesWithStubTmux:
    """
    F1 gate (row 0ab3c0cd): exercise the probe's three shell branches with a STUB
    `tmux` so the bash half is VERIFIED on any box with bash — the coverage the
    real-tmux tests cannot give where tmux is absent. Delete a branch (or its
    verdict grep) from the script and the matching test here fails, tmux or not.
    """

    def _run_with_stub( self, tmp_path, behavior, prompt="do the review", name="probe-stub" ):
        stub_dir = tmp_path / "bin"
        stub_dir.mkdir()
        stub = stub_dir / "tmux"
        stub.write_text( _stub_tmux_source( behavior ) )
        stub.chmod( 0o755 )
        return _dry_run( prompt, name, path_prefix=stub_dir )

    def test_ok_branch_reports_ok_and_exits_zero( self, tmp_path ):
        # Stub tmux accepts the no-op → the probe reports ok and passes dry_run.
        rc, out = self._run_with_stub( tmp_path, "ok" )
        assert rc == 0
        assert "BRIEF-LENGTH-PROBE: ok" in out

    def test_command_too_long_branch_fails_loud( self, tmp_path ):
        # Stub tmux rejects with tmux's own verdict → the probe fails non-zero and
        # names it. If the 'command too long' grep is broken/removed this reverts
        # to the else branch or a quiet pass and this test catches it.
        rc, out = self._run_with_stub( tmp_path, "too_long" )
        assert rc != 0
        assert "BRIEF-LENGTH-PROBE: FAIL" in out
        assert "command too long" in out

    def test_other_error_branch_reports_cannot_verify( self, tmp_path ):
        # Stub tmux fails for a non-length reason → the probe must SAY it could not
        # verify and exit non-zero, never pass quietly on an unproven brief.
        rc, out = self._run_with_stub( tmp_path, "other" )
        assert rc != 0
        assert "BRIEF-LENGTH-PROBE: could NOT verify" in out
