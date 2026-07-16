"""
Unit tests for fix (a) of the focus-bar invisibility bug (ef10c5b6): the
start-cc-with-tmux.sh launcher forwards LUPIN_DEV_EMAIL (and HOOK_TTS_ENABLED
when set) into the pane shell's INNER export block.

Root cause recap: the SessionStart hello-world notification is a fresh Claude
Code session's ONLY birth certificate on the operator's focus bar, and
send_tts() no-ops SILENTLY when get_target_email() cannot resolve a target. A
tmux-server restart froze a non-login global env with no LUPIN_DEV_EMAIL, so
every new session went invisible until it happened to push an MCP notification.
The `tmux set-environment -g` mitigation (fix c) dies with the server; this
per-pane forward makes the launcher's own env the source of truth, so a server
restart can never again silence registration (RESTART-PROOF).

The forward is GUARDED — it exports ONLY when the launcher carries the var
non-empty — so an empty value never clobbers a value the pane would otherwise
inherit from the server's frozen global env (the seed), nor overrides a
deliberate per-session HOOK_TTS_ENABLED=false disable.

Venue: :7999 bucket — no persistent state, no tmux sessions created (--dry-run
exits before any tmux call), <2s.

See: bug ef10c5b6 · planning-is-prompting/src/rnd/2026.07.15-focus-bar-invisibility-root-cause.md
"""

import os
import subprocess

import pytest


LUPIN_ROOT  = os.environ[ "LUPIN_ROOT" ]
SCRIPT_PATH = os.path.join( LUPIN_ROOT, "src", "scripts", "start-cc-with-tmux.sh" )


def _base_env( home ):
    """Minimal hermetic env: the script sees a throwaway HOME (no fleet roster,
    no ambient LUPIN_DEV_EMAIL / HOOK_TTS_ENABLED unless a test adds them)."""
    return { "PATH": os.environ[ "PATH" ], "LUPIN_ROOT": LUPIN_ROOT, "HOME": str( home ) }


def _dry_run( env, session_name="dev-email-test-session", headless=True ):
    """Run start-cc-with-tmux.sh --dry-run and capture stdout (includes the
    expanded INNER command string on the `tmux new-session ...` line)."""
    argv = [ "bash", SCRIPT_PATH, "--dry-run" ]
    if headless:
        argv.append( "--headless" )
    argv.append( session_name )
    return subprocess.run( argv, env=env, capture_output=True, text=True, timeout=30 )


class TestLauncherForwardsDevEmail:
    """Fix (a): LUPIN_DEV_EMAIL / HOOK_TTS_ENABLED guarded INNER forward."""

    def test_script_syntax_ok( self ):
        result = subprocess.run(
            [ "bash", "-n", SCRIPT_PATH ], capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, result.stderr

    def test_forwards_dev_email_when_set_headless( self, tmp_path ):
        env = _base_env( tmp_path )
        env[ "LUPIN_DEV_EMAIL" ] = "rick@example.com"
        result = _dry_run( env, headless=True )
        assert result.returncode == 0, result.stderr
        assert "export LUPIN_DEV_EMAIL=rick@example.com" in result.stdout, result.stdout

    def test_forwards_dev_email_when_set_interactive( self, tmp_path ):
        # Interactive + headless share the SAME INNER assembly — the forward must
        # be present regardless of --headless (spawned reviewers hit this bug).
        env = _base_env( tmp_path )
        env[ "LUPIN_DEV_EMAIL" ] = "rick@example.com"
        result = _dry_run( env, headless=False )
        assert result.returncode == 0, result.stderr
        assert "export LUPIN_DEV_EMAIL=rick@example.com" in result.stdout, result.stdout

    def test_omits_dev_email_when_unset( self, tmp_path ):
        # The guard: launcher env lacks LUPIN_DEV_EMAIL → NO export emitted, so a
        # server-seeded value the pane would inherit is never clobbered to empty.
        result = _dry_run( _base_env( tmp_path ) )
        assert result.returncode == 0, result.stderr
        assert "export LUPIN_DEV_EMAIL" not in result.stdout, result.stdout

    def test_omits_dev_email_when_empty( self, tmp_path ):
        # An explicitly-empty value is still falsy under the guard → not forwarded.
        env = _base_env( tmp_path )
        env[ "LUPIN_DEV_EMAIL" ] = ""
        result = _dry_run( env )
        assert result.returncode == 0, result.stderr
        assert "export LUPIN_DEV_EMAIL" not in result.stdout, result.stdout

    def test_forwards_hook_tts_enabled_when_set( self, tmp_path ):
        env = _base_env( tmp_path )
        env[ "HOOK_TTS_ENABLED" ] = "false"
        result = _dry_run( env )
        assert result.returncode == 0, result.stderr
        assert "export HOOK_TTS_ENABLED=false" in result.stdout, result.stdout

    def test_omits_hook_tts_enabled_when_unset( self, tmp_path ):
        # Unset → NOT forwarded, so the hook's default-enabled behavior is intact
        # and a deliberate per-session disable is never manufactured.
        result = _dry_run( _base_env( tmp_path ) )
        assert result.returncode == 0, result.stderr
        assert "export HOOK_TTS_ENABLED" not in result.stdout, result.stdout

    def test_dev_email_value_is_shell_quoted( self, tmp_path ):
        # printf %q must quote a value so it survives the trip through the single
        # tmux command string intact — a plus-addressed email is a benign probe.
        env = _base_env( tmp_path )
        env[ "LUPIN_DEV_EMAIL" ] = "rick+cc@example.com"
        result = _dry_run( env )
        assert result.returncode == 0, result.stderr
        assert "export LUPIN_DEV_EMAIL=rick+cc@example.com" in result.stdout, result.stdout


if __name__ == "__main__":
    raise SystemExit( pytest.main( [ __file__, "-v" ] ) )
