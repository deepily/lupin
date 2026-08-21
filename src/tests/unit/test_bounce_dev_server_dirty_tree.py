"""
Row 7de5a09f — bounce-dev-server.sh must WARN before a bounce when the working
tree is dirty, because with auto-reload off and the repo bind-mounted a restart
serves EVERY saved file in the tree (committed or not, from every session), not
just the bouncer's work (observed live boot #12).

Gate ruling (first pass): the warning must NEVER refuse a non-interactive caller.
Every Claude session invokes bash without a TTY and the tree is essentially always
dirty, so an abort-by-default would make the sanctioned path refuse the fleet's
most common bouncer. So the behaviour is split by whether stdin is a terminal:

  - clean tree             → no notice, proceeds
  - dirty + a TERMINAL     → names the files + y/N; 'y' proceeds, 'n' aborts (exit 3)
                             BEFORE the warn broadcast
  - dirty + NON-interactive→ names the files and PROCEEDS (no --force needed); the
                             dirty list is exported as BOUNCE_DIRTY_FILES so the warn
                             broadcast can name it to the owning seat
  - dirty + --force        → skips the human prompt (recovery)
  - non-git tree           → treated clean (recovery never blocked)

This drives BOTH sides plus the TTY-vs-not pair the gate demands. The TTY arms use
a real pty so `[ -t 0 ]` is true; the non-TTY arms use a plain pipe.

No real bounce happens: LUPIN_ROOT points at a throwaway git repo, a FAKE
bounce_dev_warn.py stands in for the broadcast, and fake `docker`/`curl` on PATH
make the restart + health poll succeed instantly.
"""

import os
import pty
import subprocess
import tempfile
import unittest
from pathlib import Path

import cosa.utils.util as cu

_SCRIPT = cu.get_project_root() + "/src/scripts/bounce-dev-server.sh"

# Fake warn helper that records the BOUNCE_DIRTY_FILES it was handed, then exits 0.
# Lets a test prove the shell→broadcast wiring without a live server.
_RECORDING_WARN = (
    "import os, sys\n"
    "sink = os.environ.get( 'DIRTY_SINK' )\n"
    "if sink:\n"
    "    open( sink, 'w' ).write( os.environ.get( 'BOUNCE_DIRTY_FILES', '<unset>' ) )\n"
    "sys.exit( 0 )\n"
)


def _make_tree( *, git=True, dirty=False, warn_body="import sys\nsys.exit( 0 )\n" ):
    """Build a throwaway LUPIN_ROOT tree; return (tmp_path, env)."""
    tmp     = tempfile.mkdtemp()
    scripts = Path( tmp ) / "src" / "scripts"
    scripts.mkdir( parents=True )
    ( scripts / "bounce_dev_warn.py" ).write_text( warn_body )
    # Busy probe: IDLE. The script runs "${LUPIN_ROOT}/src/scripts/bounce_busy_probe.py"
    # since 2026-08-21 (4b0c621c); without this file python3 exits 2, the guard fails
    # OPEN by design, and the run proceeds to the restart — which is not what these
    # tests are about. Provision it so the guard is satisfied, not bypassed.
    ( scripts / "bounce_busy_probe.py" ).write_text( "import sys\nsys.exit( 0 )\n" )
    # Fake docker + curl so `docker restart` and the health poll succeed at once.
    #
    # docker CANNOT be a bare `exit 0` any more. Since 2026-08-21 the script also waits for
    # the container's own StartedAt to be newer than the restart it issued (the identity
    # guard, row 1c36199e) — a bare stub prints nothing, the wait can never be satisfied,
    # and the 30s subprocess timeout kills the test for a reason that has nothing to do
    # with the dirty tree. So the stub answers `inspect` with a start time of NOW, which is
    # what a real restart would report, and keeps exiting 0 for `restart` and `logs`.
    # The fake sits FIRST on PATH, so no arm here ever reaches the real container.
    fakebin = Path( tmp ) / "bin"
    fakebin.mkdir()
    ( fakebin / "docker" ).write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = \"inspect\" ]; then date -u +%Y-%m-%dT%H:%M:%S.000000000Z; fi\n"
        "exit 0\n"
    )
    ( fakebin / "docker" ).chmod( 0o755 )
    ( fakebin / "curl" ).write_text( "#!/bin/sh\nexit 0\n" )
    ( fakebin / "curl" ).chmod( 0o755 )

    if git:
        subprocess.run( [ "git", "init", "-q", tmp ], check=True )
        tracked = Path( tmp ) / "tracked.txt"
        tracked.write_text( "baseline\n" )
        # Commit EVERYTHING so the baseline is genuinely clean — otherwise the
        # scaffolding itself reads as untracked and every case would look dirty.
        subprocess.run( [ "git", "-C", tmp, "add", "-A" ], check=True )
        subprocess.run(
            [ "git", "-C", tmp, "-c", "user.email=t@t", "-c", "user.name=t",
              "commit", "-qm", "base" ],
            check=True,
        )
        if dirty:
            tracked.write_text( "changed after commit\n" )   # now modified → dirty

    env = dict( os.environ )
    env[ "LUPIN_ROOT" ]          = tmp
    env[ "PATH" ]                = str( fakebin ) + os.pathsep + env[ "PATH" ]
    env[ "UNWARNED_PAUSE_SECS" ] = "0"
    return tmp, env


def _run_pipe( *, git=True, dirty=False, extra_args=(), stdin="", warn_body="import sys\nsys.exit( 0 )\n", env_extra=None ):
    """Run with stdin as a PIPE (NON-interactive — `[ -t 0 ]` is false)."""
    _, env = _make_tree( git=git, dirty=dirty, warn_body=warn_body )
    if env_extra:
        env.update( env_extra )
    return subprocess.run(
        [ "bash", _SCRIPT, *extra_args ],
        env=env, input=stdin, capture_output=True, text=True, timeout=30,
    )


def _run_tty( reply, *, dirty=True, extra_args=() ):
    """Run with stdin as a real pty (INTERACTIVE — `[ -t 0 ]` is true)."""
    _, env = _make_tree( git=True, dirty=dirty )
    master, slave = pty.openpty()
    os.write( master, reply.encode() )                 # pre-fill the answer line
    try:
        proc = subprocess.run(
            [ "bash", _SCRIPT, *extra_args ],
            env=env, stdin=slave,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=30,
        )
    finally:
        os.close( slave )
        os.close( master )
    return proc


class TestBounceDirtyTree( unittest.TestCase ):

    # ── clean side ────────────────────────────────────────────────────────────
    def test_clean_tree_says_nothing_and_proceeds( self ):
        r = _run_pipe( git=True, dirty=False, stdin="" )
        self.assertEqual( r.returncode, 0 )
        self.assertNotIn( "DIRTY", r.stdout )
        self.assertIn( "Restarting container", r.stdout )

    # ── dirty + non-interactive: PROCEEDS, never refuses an agent ─────────────
    def test_dirty_non_interactive_names_files_and_proceeds_without_force( self ):
        r = _run_pipe( git=True, dirty=True, stdin="" )
        self.assertEqual( r.returncode, 0 )                # NOT an abort
        self.assertIn( "DIRTY", r.stdout )
        self.assertIn( "tracked.txt", r.stdout )           # names names
        self.assertIn( "Non-interactive caller", r.stdout )
        self.assertNotIn( "Proceed with the bounce anyway", r.stdout )   # no prompt to an agent
        self.assertIn( "Restarting container", r.stdout )

    # ── dirty + non-interactive: the list rides the broadcast ─────────────────
    def test_dirty_list_is_exported_to_the_warn_broadcast( self ):
        tmp = tempfile.mkdtemp()
        sink = Path( tmp ) / "seen.txt"
        r = _run_pipe(
            git=True, dirty=True, stdin="",
            warn_body=_RECORDING_WARN,
            env_extra={ "DIRTY_SINK": str( sink ) },
        )
        self.assertEqual( r.returncode, 0 )
        # The warn helper saw the dirty list in BOUNCE_DIRTY_FILES.
        self.assertIn( "tracked.txt", sink.read_text() )

    # ── dirty + TERMINAL, confirmed ───────────────────────────────────────────
    def test_dirty_tty_prompts_and_proceeds_on_yes( self ):
        r = _run_tty( "y\n", dirty=True )
        self.assertEqual( r.returncode, 0 )
        self.assertIn( "Proceed with the bounce anyway", r.stdout )
        self.assertIn( "Proceeding on a dirty tree by confirmation", r.stdout )
        self.assertIn( "Restarting container", r.stdout )

    # ── dirty + TERMINAL, refused ─────────────────────────────────────────────
    def test_dirty_tty_aborts_on_no_before_the_warn_broadcast( self ):
        r = _run_tty( "n\n", dirty=True )
        self.assertEqual( r.returncode, 3 )                # dedicated abort code
        self.assertIn( "Aborted", r.stderr )
        self.assertNotIn( "Warning the fleet", r.stdout )  # no false alarm
        self.assertNotIn( "Restarting container", r.stdout )

    # ── recovery: --force skips the human prompt on a dirty tree ──────────────
    def test_force_skips_the_prompt_on_a_dirty_tree( self ):
        r = _run_pipe( git=True, dirty=True, extra_args=( "--force", ), stdin="" )
        self.assertEqual( r.returncode, 0 )
        self.assertIn( "--force given", r.stdout )
        self.assertNotIn( "Proceed with the bounce anyway", r.stdout )
        self.assertIn( "Restarting container", r.stdout )

    # ── recovery: a non-git tree is treated clean, never an error ─────────────
    def test_non_git_tree_treated_clean_and_proceeds( self ):
        r = _run_pipe( git=False, stdin="" )
        self.assertEqual( r.returncode, 0 )
        self.assertNotIn( "DIRTY", r.stdout )
        self.assertIn( "Restarting container", r.stdout )


if __name__ == "__main__":
    unittest.main()
