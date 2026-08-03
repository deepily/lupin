"""
Unit tests for the single-source fleet-roster env file + its tmux-boundary
transport in start-cc-with-tmux.sh.

User-level migration (2026-06-22): the LIVE roster moved to the repo-agnostic
~/.claude/fleet-roster.env. These tests are HERMETIC — they NEVER read or write
the developer's real ~/.claude:
  • format + bash-source round-trip assertions run against the git-tracked
    versioned reference src/conf/fleet-roster.env.template (deterministic, in-repo);
  • script-behavior assertions run the script under HOME=tmp_path with the
    template copied into tmp_path/.claude/fleet-roster.env (forward) or with no
    file at all (degrade) — so the only home the script ever sees is a throwaway.

Covers the two-reader contract of ~/.claude/fleet-roster.env:
  (a) bash `source` (start-cc-with-tmux.sh, set -a auto-export) — round-trip
      asserted in a CLEAN bash (env -i), plus the --dry-run PERSONA-ENV line
      proving the sourced roster (LUPIN + the OTHER repos) survives to the
      tmux -e forward;
  (b) systemd EnvironmentFile= — format-level assertions (KEY="value" lines,
      no `export` keyword, no variable expansion) since systemd itself is not
      invocable from a unit test.

Venue: :7999 bucket — no persistent state, no tmux sessions created
(--dry-run exits before any tmux call), no real-home dependency, <2s.

See: src/rnd/v0.1.8/2026.06.11-fleet-roster-env-file-and-reserve-from-random.md
     src/rnd/2026.06.22-fleet-roster-to-user-level-migration-spec.md (PIP, María)
"""

import os
import re
import shutil
import subprocess

import pytest


LUPIN_ROOT    = os.environ[ "LUPIN_ROOT" ]
# Format + round-trip tests read the git-tracked TEMPLATE (the versioned
# reference) — NOT the live ~/.claude/fleet-roster.env (absent in repo/CI).
TEMPLATE_PATH = os.path.join( LUPIN_ROOT, "src", "conf", "fleet-roster.env.template" )
SCRIPT_PATH   = os.path.join( LUPIN_ROOT, "src", "scripts", "start-cc-with-tmux.sh" )


def _clean_env( home ):
    """
    Minimal env -i style environment for subprocess runs.

    Requires:
        - home is the throwaway HOME the script should resolve the roster under
          (NEVER the real home — keeps the suite hermetic)

    Ensures:
        - returns a dict with only PATH (tmux/bash lookup), LUPIN_ROOT (venv
          path test, inert under --dry-run), and the supplied HOME
    """
    return { "PATH": os.environ[ "PATH" ], "LUPIN_ROOT": LUPIN_ROOT, "HOME": str( home ) }


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
    """Format-level guarantees that keep the template valid for BOTH readers."""

    def test_template_exists( self ):
        assert os.path.isfile( TEMPLATE_PATH ), f"missing {TEMPLATE_PATH}"

    def test_only_comments_blanks_and_quoted_assignments( self ):
        # The bash/systemd intersection: every non-comment, non-blank line is
        # KEY="value" — no `export`, no expansion, no line continuations.
        with open( TEMPLATE_PATH ) as f:
            for line in f:
                stripped = line.strip()
                if not stripped or stripped.startswith( "#" ):
                    continue
                assert re.fullmatch( r'[A-Z][A-Z0-9_]*="[^"$\\]*"', stripped ), \
                    f"line not in KEY=\"value\" bash∩systemd form: {stripped!r}"

    def test_lupin_roster_head_is_mr_radio( self ):
        # ORDER MATTERS: roster head = declared fallback manager (Rick).
        with open( TEMPLATE_PATH ) as f:
            content = f.read()
        match = re.search( r'^COSA_VOICE_MANAGERS__LUPIN="([^"]*)"', content, re.MULTILINE )
        assert match is not None, "COSA_VOICE_MANAGERS__LUPIN line missing"
        names = [ n.strip() for n in match.group( 1 ).split( "," ) ]
        assert names[ 0 ] == "Mr. Radio", names

    def test_template_carries_full_fleet_roster( self ):
        # The versioned reference names every repo's manager — the whole point of
        # the user-level single source (no product repo owns the fleet roster).
        with open( TEMPLATE_PATH ) as f:
            content = f.read()
        for project in ( "LUPIN", "PLAN", "LOOKML", "LUPIN_MOBILE" ):
            assert re.search( rf'^COSA_VOICE_MANAGERS__{project}="[^"]+"', content, re.MULTILINE ), \
                f"roster missing COSA_VOICE_MANAGERS__{project}"

    def test_no_user_specific_values( self ):
        # LUPIN_DEV_EMAIL (and anything user-specific) stays a drop-in
        # literal — never in the roster file (Rick's carve-out).
        with open( TEMPLATE_PATH ) as f:
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
            f'set -a; source "{TEMPLATE_PATH}"; set +a; '
            f'printf "%s" "$COSA_VOICE_MANAGERS__LUPIN"',
            env=_clean_env( "/tmp" )
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout == "Mr. Radio, Tiberius"

    def test_sourced_var_is_exported_to_children( self ):
        # set -a must make the var visible to CHILD processes too (the
        # forward loop reads it in-shell, but exported keeps parity with
        # the optional ~/.bashrc usage documented in the header).
        result = _run_bash(
            f'set -a; source "{TEMPLATE_PATH}"; set +a; '
            f'bash -c \'printf "%s" "$COSA_VOICE_MANAGERS__LUPIN"\'',
            env=_clean_env( "/tmp" )
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout == "Mr. Radio, Tiberius"


class TestStartCcWithTmuxForwarding:
    """The script sources ~/.claude/fleet-roster.env and forwards across tmux -e."""

    def test_script_syntax_ok( self ):
        result = subprocess.run(
            [ "bash", "-n", SCRIPT_PATH ], capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, result.stderr

    def _seed_home_roster( self, home ):
        """Copy the versioned template into a throwaway HOME/.claude/fleet-roster.env."""
        claude_dir = home / ".claude"
        claude_dir.mkdir( parents=True )
        shutil.copyfile( TEMPLATE_PATH, claude_dir / "fleet-roster.env" )

    def _dry_run( self, env ):
        return subprocess.run(
            [ "bash", SCRIPT_PATH, "--dry-run", "--headless", "roster-test-session" ],
            env=env, capture_output=True, text=True, timeout=30
        )

    def test_dry_run_forwards_sourced_roster( self, tmp_path ):
        # HOME=tmp_path with the template copied in: the roster can only have
        # come from $HOME/.claude/fleet-roster.env (hermetic — no real home).
        self._seed_home_roster( tmp_path )
        result = self._dry_run( _clean_env( tmp_path ) )
        assert result.returncode == 0, result.stderr
        persona_env_lines = [ l for l in result.stdout.splitlines() if l.startswith( "PERSONA-ENV:" ) ]
        assert len( persona_env_lines ) == 1, result.stdout
        line = persona_env_lines[ 0 ]
        # %q-quoted flags survive the tmux -e forward. LUPIN has spaces/commas →
        # escaped; the OTHER repos prove the GENERIC forward loop ships the whole
        # multi-repo roster, not just LUPIN. The clean-ASCII repos are asserted by
        # exact value (locale-independent); PLAN ("María") is asserted by key
        # presence only — %q byte-escapes the UTF-8 under the test's C locale
        # ($'…Mar\303\255a'), so pinning the exact value would be locale-fragile.
        assert "COSA_VOICE_MANAGERS__LUPIN=Mr.\\ Radio\\,\\ Tiberius" in line, line
        assert "COSA_VOICE_MANAGERS__LOOKML=Sam"           in line, line
        assert "COSA_VOICE_MANAGERS__LUPIN_MOBILE=Tiffany" in line, line
        assert "COSA_VOICE_MANAGERS__PLAN="                in line, line  # accented value byte-escaped under C locale

    def test_dry_run_exits_before_tmux( self, tmp_path ):
        # --dry-run must remain side-effect-free: no tmux session appears.
        # Precondition: the tmux binary must be on PATH for the leaked-session probe
        # below. It is absent in the file-bind test container; this check runs on any
        # host/CI venue where tmux is installed. The dry-run-exits-0 coverage is not
        # lost when skipped here — the sibling test_dry_run_forwards_sourced_roster
        # asserts it without needing tmux.
        if shutil.which( "tmux" ) is None:
            pytest.skip( "requires the tmux binary on PATH to probe for a leaked session — not installed in the file-bind test container" )
        self._seed_home_roster( tmp_path )
        result = self._dry_run( _clean_env( tmp_path ) )
        assert result.returncode == 0, result.stderr
        assert "DRY-RUN headless=1" in result.stdout
        probe = subprocess.run(
            [ "tmux", "has-session", "-t", "roster-test-session" ],
            capture_output=True, text=True, timeout=30
        )
        assert probe.returncode != 0, "dry-run leaked a real tmux session"

    def test_missing_roster_file_degrades_to_no_managers_flag( self, tmp_path ):
        # Tolerate-missing contract: HOME=tmp_path WITHOUT .claude/fleet-roster.env
        # → script still works, no MANAGERS flag forwarded. (Mechanism is HOME-
        # based now, not LUPIN_ROOT-based — the user-level isolation upgrade.)
        result = subprocess.run(
            [ "bash", SCRIPT_PATH, "--dry-run", "--headless", "roster-degrade-session" ],
            env=_clean_env( tmp_path ), capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, result.stderr
        assert "COSA_VOICE_MANAGERS__" not in result.stdout
        assert "DRY-RUN headless=1" in result.stdout
