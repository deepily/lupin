"""
Unit tests for the single-source fleet-roster env file + its tmux-boundary
transport in start-cc-with-tmux.sh.

Covers the two-reader contract of src/conf/fleet-roster.env:
  (a) bash `source` (start-cc-with-tmux.sh, set -a auto-export) — round-trip
      asserted in a CLEAN bash (env -i), plus the --dry-run PERSONA-ENV line
      proving the sourced roster survives to the tmux -e forward;
  (b) systemd EnvironmentFile= — format-level assertions (KEY="value" lines,
      no `export` keyword, no variable expansion) since systemd itself is not
      invocable from a unit test.

Venue: :7999 bucket — no persistent state, no tmux sessions created
(--dry-run exits before any tmux call), <2s.

See: src/rnd/v0.1.8/2026.06.11-fleet-roster-env-file-and-reserve-from-random.md
"""

import os
import re
import subprocess

import pytest


LUPIN_ROOT  = os.environ[ "LUPIN_ROOT" ]
ROSTER_PATH = os.path.join( LUPIN_ROOT, "src", "conf", "fleet-roster.env" )
SCRIPT_PATH = os.path.join( LUPIN_ROOT, "src", "scripts", "start-cc-with-tmux.sh" )

# Minimal clean environment for env -i style subprocess runs: the script only
# needs PATH (tmux/bash lookup never happens under --dry-run) + LUPIN_ROOT.
_CLEAN_ENV = { "PATH": os.environ[ "PATH" ], "LUPIN_ROOT": LUPIN_ROOT, "HOME": os.environ.get( "HOME", "/tmp" ) }


def _run_bash( command, env ):
    """
    Run a bash -c command with a controlled environment.

    Requires:
        - command is a bash command string
        - env is the FULL environment dict for the subprocess

    Ensures:
        - returns CompletedProcess with captured text stdout/stderr
    """
    return subprocess.run(
        [ "bash", "-c", command ],
        env=env, capture_output=True, text=True, timeout=30
    )


class TestFleetRosterEnvFileFormat:
    """Format-level guarantees that keep the file valid for BOTH readers."""

    def test_file_exists( self ):
        assert os.path.isfile( ROSTER_PATH ), f"missing {ROSTER_PATH}"

    def test_only_comments_blanks_and_quoted_assignments( self ):
        # The bash/systemd intersection: every non-comment, non-blank line is
        # KEY="value" — no `export`, no expansion, no line continuations.
        with open( ROSTER_PATH ) as f:
            for line in f:
                stripped = line.strip()
                if not stripped or stripped.startswith( "#" ):
                    continue
                assert re.fullmatch( r'[A-Z][A-Z0-9_]*="[^"$\\]*"', stripped ), \
                    f"line not in KEY=\"value\" bash∩systemd form: {stripped!r}"

    def test_lupin_roster_head_is_mr_radio( self ):
        # ORDER MATTERS: roster head = declared fallback manager (Rick).
        with open( ROSTER_PATH ) as f:
            content = f.read()
        match = re.search( r'^COSA_VOICE_MANAGERS__LUPIN="([^"]*)"', content, re.MULTILINE )
        assert match is not None, "COSA_VOICE_MANAGERS__LUPIN line missing"
        names = [ n.strip() for n in match.group( 1 ).split( "," ) ]
        assert names[ 0 ] == "Mr. Radio", names

    def test_no_user_specific_values( self ):
        # LUPIN_DEV_EMAIL (and anything user-specific) stays a drop-in
        # literal — never in the repo file (Rick's carve-out).
        with open( ROSTER_PATH ) as f:
            content = f.read()
        assert "LUPIN_DEV_EMAIL" not in [
            line.split( "=" )[ 0 ].strip()
            for line in content.splitlines()
            if "=" in line and not line.strip().startswith( "#" )
        ]


class TestFleetRosterBashSourceRoundTrip:
    """Reader (a): bash source in a clean shell round-trips the value."""

    def test_clean_bash_source_exports_roster( self ):
        result = _run_bash(
            f'set -a; source "{ROSTER_PATH}"; set +a; '
            f'printf "%s" "$COSA_VOICE_MANAGERS__LUPIN"',
            env=_CLEAN_ENV
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout == "Mr. Radio, Tiberius"

    def test_sourced_var_is_exported_to_children( self ):
        # set -a must make the var visible to CHILD processes too (the
        # forward loop reads it in-shell, but exported keeps parity with
        # the optional ~/.bashrc usage documented in the header).
        result = _run_bash(
            f'set -a; source "{ROSTER_PATH}"; set +a; '
            f'bash -c \'printf "%s" "$COSA_VOICE_MANAGERS__LUPIN"\'',
            env=_CLEAN_ENV
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout == "Mr. Radio, Tiberius"


class TestStartCcWithTmuxForwarding:
    """The script sources the file and forwards the roster across tmux -e."""

    def test_script_syntax_ok( self ):
        result = subprocess.run(
            [ "bash", "-n", SCRIPT_PATH ], capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, result.stderr

    def _dry_run( self, env ):
        return subprocess.run(
            [ "bash", SCRIPT_PATH, "--dry-run", "--headless", "roster-test-session" ],
            env=env, capture_output=True, text=True, timeout=30
        )

    def test_dry_run_forwards_sourced_roster( self ):
        # CLEAN env: the roster can only have come from fleet-roster.env.
        result = self._dry_run( _CLEAN_ENV )
        assert result.returncode == 0, result.stderr
        persona_env_lines = [ l for l in result.stdout.splitlines() if l.startswith( "PERSONA-ENV:" ) ]
        assert len( persona_env_lines ) == 1, result.stdout
        # %q-quoted flag: -e COSA_VOICE_MANAGERS__LUPIN=Mr.\ Radio\,\ Tiberius
        assert "COSA_VOICE_MANAGERS__LUPIN=Mr.\\ Radio\\,\\ Tiberius" in persona_env_lines[ 0 ], \
            persona_env_lines[ 0 ]

    def test_dry_run_exits_before_tmux( self ):
        # --dry-run must remain side-effect-free: no tmux session appears.
        result = self._dry_run( _CLEAN_ENV )
        assert result.returncode == 0, result.stderr
        assert "DRY-RUN headless=1" in result.stdout
        probe = subprocess.run(
            [ "tmux", "has-session", "-t", "roster-test-session" ],
            capture_output=True, text=True, timeout=30
        )
        assert probe.returncode != 0, "dry-run leaked a real tmux session"

    def test_missing_roster_file_degrades_to_no_managers_flag( self, tmp_path ):
        # Tolerate-missing contract: point LUPIN_ROOT at a skeleton tree
        # without fleet-roster.env → script still works, no MANAGERS flag.
        ( tmp_path / "src" / "conf" ).mkdir( parents=True )
        ( tmp_path / "src" / "scripts" ).mkdir( parents=True )
        env = dict( _CLEAN_ENV, LUPIN_ROOT=str( tmp_path ) )
        result = subprocess.run(
            [ "bash", SCRIPT_PATH, "--dry-run", "--headless", "roster-degrade-session" ],
            env=env, capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, result.stderr
        assert "COSA_VOICE_MANAGERS__" not in result.stdout
        assert "DRY-RUN headless=1" in result.stdout
