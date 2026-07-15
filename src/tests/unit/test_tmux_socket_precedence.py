"""
AC5 — the standing tmux socket-selection precedence CANARY.

Documents (and pins) the mechanism that motivated the smoke-suite guard: on
tmux 3.2a, an inherited $TMUX BEATS TMUX_TMPDIR for socket selection when no
explicit -L/-S is given (fix plan §2.5, proven read-only). The env-strip fix
(OSQ-4: -S/-L defense-in-depth NOT adopted) is sufficient ONLY while this
precedence holds — if a tmux upgrade ever changes it, THIS test reddens
first and REOPENS OSQ-4.

SAFETY ENVELOPE (fix plan §7 hard rule): every tmux invocation here is
either read-only (`list-sessions`) or addressed to an explicit private `-S`
socket from a $TMUX-stripped env (the ratified AC5/AC6 recipe). No
destructive verb can reach the default socket: `kill-server` appears ONLY
with `-S <private throwaway>`, which overrides all env-based selection.

VENUE: :7999-eligible / AI-discretionary — private throwaway server on a
tmp_path socket, no persistent state, runtime seconds.

Design: src/rnd/v0.1.9/2026.07.14-tmux-fleet-killer-vertex-taint-test-isolation-leak-fix-plan.md (§6 AC5)
"""

import os
import shutil
import subprocess

import pytest

from tests.smoke.tmux_isolation import TMUX_ISOLATION_STRIP_KEYS


pytestmark = pytest.mark.skipif( not shutil.which( "tmux" ), reason="tmux is not installed" )


def _stripped_env():
    """A copy of os.environ with the pane context AND TMUX_TMPDIR removed — the AC5/AC6 safety recipe."""
    env = dict( os.environ )
    for key in TMUX_ISOLATION_STRIP_KEYS:
        env.pop( key, None )
    env.pop( "TMUX_TMPDIR", None )
    return env


@pytest.fixture
def throwaway_server( tmp_path ):
    """
    A private tmux server on an explicit -S socket, born from a
    $TMUX-stripped env. -S overrides all env-based socket selection, so
    neither birth nor teardown can address the fleet default socket.
    """
    sock = tmp_path / "precedence-probe.sock"
    env  = _stripped_env()

    born = subprocess.run(
        [ "tmux", "-S", str( sock ), "new-session", "-d", "-s", "precedence_probe", "sleep 300" ],
        capture_output=True, text=True, env=env, timeout=30
    )
    assert born.returncode == 0, f"could not birth the throwaway server: {born.stderr}"
    assert sock.exists(), "throwaway server born but its private socket file is missing"

    yield sock

    subprocess.run(
        [ "tmux", "-S", str( sock ), "kill-server" ],
        capture_output=True, text=True, env=env, timeout=30
    )


def test_tmux_env_var_beats_tmux_tmpdir_for_socket_selection( throwaway_server, tmp_path, monkeypatch ):
    """
    🔴 THE CANARY. $TMUX set (simulating a pane on the throwaway server) +
    TMUX_TMPDIR pointing at an empty dir: a bare `tmux list-sessions` must
    land on the $TMUX socket — proving the leak mechanism the guard strips.

    If this ever fails, tmux's precedence CHANGED: the env-strip fix's
    sufficiency argument (OSQ-4 close) no longer holds as documented —
    re-examine before trusting the guard.
    """
    empty_tmpdir = tmp_path / "empty-tmpdir"
    empty_tmpdir.mkdir()

    monkeypatch.setenv( "TMUX",        f"{throwaway_server},99999,0" )
    monkeypatch.setenv( "TMUX_TMPDIR", str( empty_tmpdir ) )
    monkeypatch.delenv( "TMUX_PANE",   raising=False )

    result = subprocess.run(
        [ "tmux", "list-sessions" ], capture_output=True, text=True, timeout=30
    )

    assert result.returncode == 0 and "precedence_probe" in result.stdout, (
        f"PRECEDENCE CHANGED: with $TMUX set, a bare tmux no longer selects "
        f"the $TMUX socket (rc={result.returncode}, stdout={result.stdout!r}, "
        f"stderr={result.stderr!r}). The env-strip guard's sufficiency "
        f"argument (OSQ-4) must be re-examined — do NOT assume isolation "
        f"semantics until this is re-proven."
    )


def test_tmux_tmpdir_wins_only_when_tmux_is_absent( throwaway_server, tmp_path, monkeypatch ):
    """
    The stripped state the guard produces: with $TMUX/$TMUX_PANE absent and
    TMUX_TMPDIR pointing at an empty dir, a bare `tmux list-sessions` finds
    NO server — neither the throwaway one (proving TMUX_TMPDIR is honored)
    nor the fleet one (proving the strip prevents default-socket reach; the
    fleet server IS live, so reaching it would have listed sessions).
    """
    empty_tmpdir = tmp_path / "empty-tmpdir-stripped"
    empty_tmpdir.mkdir()

    for key in TMUX_ISOLATION_STRIP_KEYS:
        monkeypatch.delenv( key, raising=False )
    monkeypatch.setenv( "TMUX_TMPDIR", str( empty_tmpdir ) )

    result = subprocess.run(
        [ "tmux", "list-sessions" ], capture_output=True, text=True, timeout=30
    )

    assert result.returncode != 0, (
        f"with $TMUX stripped and TMUX_TMPDIR pinned to an EMPTY dir, bare "
        f"tmux still found a server: {result.stdout!r} — the stripped state "
        f"does not isolate, the guard's whole premise is broken."
    )
    assert "precedence_probe" not in result.stdout
