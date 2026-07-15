"""
OSQ-6 (EXISTING-server half) + §5c row 2 — the launcher refuses a TAINTED tmux server.

Design: src/rnd/v0.1.9/2026.07.13-vertex-model-garden-toggle-search-and-logging.md
Finding: Rio's C1 (store item b0e7142c) — "the guard runs in the WRONG PROCESS."

THE EXPLOIT THIS FILE KILLS, verbatim from the finding: a tainted server env holding
VERTEX_REGION_CLAUDE_4_8_OPUS=us-east5 → the launcher shell is clean → the launcher-side
assert_no_hostile_env PASSES (wrong process) → the key is not in the -e list but -e ADDS
AND SUBTRACTS NOTHING → the pane inherits it → Opus alone routes to us-east5, where it
runs, bills, and logs nothing — with every guard green.

So this file taints a PRIVATE, ISOLATED probe server the only way that actually taints
(`tmux new-session` — `start-server` propagates NOTHING, measured, plan §2.5), PROVES the
taint before trusting any refusal (an unproven taint makes every refusal unattributable —
the memento protocol), then runs the REAL launcher --vertex against it and demands a
NON-ZERO exit that NAMES the variable.

VENUE: :7999-eligible / AI-discretionary — no persistent state, no network, no GCP, no
spend, no server monopoly. Private tmux server on a temp socket, killed on teardown.
ISOLATION: every tmux touch strips TMUX_ISOLATION_STRIP_KEYS and pins TMUX_TMPDIR —
never the fleet's default socket (the 2026-07-14 fleet-killer class).
"""

import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

import cosa.utils.util as cu
from cosa.utils.vertex_env import (
    MAX_PANE_UNSET_KEYS,
    SERVER_TAINT_REFUSAL_KEYS,
    VERTEX_REGION_ENV_KEY,
)
from tests.smoke.tmux_isolation import TMUX_ISOLATION_STRIP_KEYS


LAUNCHER = Path( cu.get_project_root() ) / "src" / "scripts" / "start-cc-with-tmux.sh"

# Rio's exploit key, exactly: a per-model override frozen into the server env. It is in
# HOSTILE_ENV_KEYS but NOT in VERTEX_SESSION_KEYS — so the old F-A11/OSQ-6 toggle-only
# reasoning never looked at it, which is what made it the exploit.
EXPLOIT_KEY   = "VERTEX_REGION_CLAUDE_4_8_OPUS"
EXPLOIT_VALUE = "us-east5"

# Synthetic compose inputs so --vertex composes deterministically with ZERO GCP contact:
# compose_vertex_env() is pure env composition, and the fake `claude` only parks.
SYNTHETIC_VERTEX_ENV = {
    "LUPIN_GCP_PROJECT_ID" : "probe-project-nobody-bills",
    VERTEX_REGION_ENV_KEY  : "global",
}


def _clean_base_env( socket_dir ):
    """
    A launcher/tmux base env that is (a) ISOLATED — never the fleet socket — and
    (b) CLEAN of every key this suite reasons about, so the only taint present is
    the taint a test deliberately plants. The launcher SHELL being clean is not a
    convenience: it is the PRECONDITION of Rio's exploit (the launcher-side guard
    must be green while the server is dirty).
    """
    env = dict( os.environ )
    for key in TMUX_ISOLATION_STRIP_KEYS:
        env.pop( key, None )    # $TMUX beats TMUX_TMPDIR — never inherit the pane's socket (plan §2.5)
    for key in MAX_PANE_UNSET_KEYS:
        env.pop( key, None )
    env[ "TMUX_TMPDIR" ] = str( socket_dir )
    return env


def _tmux( socket_dir, *args ):
    """Run tmux against the ISOLATED probe server only."""
    return subprocess.run(
        [ "tmux", *args ],
        capture_output=True, text=True, env=_clean_base_env( socket_dir ), timeout=30
    )


def _birth_tainted_server( socket_dir, taint ):
    """
    Birth the probe server ALREADY TAINTED — via `new-session`, the only invocation
    that freezes the caller's env into the server (start-server propagates nothing;
    a start-server "taint" would make every later green free — plan §2.5).
    """
    env = _clean_base_env( socket_dir )
    env.update( taint )
    return subprocess.run(
        [ "tmux", "new-session", "-d", "-s", "taint-birth", "sleep 30" ],
        capture_output=True, text=True, env=env, timeout=30
    )


def _launch_vertex( socket_dir, fake_bin ):
    """Run the REAL launcher, --vertex + headless, on the isolated socket, clean shell."""
    env = _clean_base_env( socket_dir )
    env[ "PATH" ]       = f"{fake_bin}:{env[ 'PATH' ]}"
    env[ "LUPIN_ROOT" ] = cu.get_project_root()
    env.update( SYNTHETIC_VERTEX_ENV )
    return subprocess.run(
        [ "bash", str( LAUNCHER ), "--headless", "--vertex", "probe-vertex-sess" ],
        capture_output=True, text=True, env=env, timeout=120
    )


@pytest.fixture
def rig( tmp_path ):
    """An isolated tmux socket + a fake `claude` that parks, so no real CC ever spawns."""
    socket_dir = tmp_path / "tmux"
    fake_bin   = tmp_path / "bin"
    socket_dir.mkdir()
    fake_bin.mkdir()

    fake_claude = fake_bin / "claude"
    fake_claude.write_text( "#!/usr/bin/env bash\nsleep 20\n" )
    fake_claude.chmod( 0o755 )

    yield socket_dir, fake_bin

    _tmux( socket_dir, "kill-server" )


@pytest.mark.skipif( not shutil.which( "tmux" ), reason="tmux is not installed" )
def test_a_tainted_existing_server_refuses_a_vertex_launch( rig ):
    """
    🔴 RIO'S C1 RED-FIRST TEST, AS DEMANDED: seed a hostile key into an isolated
    probe tmux server env, launch --vertex, assert NON-ZERO + the variable NAMED.

    Written and run RED against the pre-fix launcher (which has no OSQ-6
    existing-server check at all), so the green that follows the wiring is
    attributable to the wiring and nothing else.
    """
    socket_dir, fake_bin = rig

    birth = _birth_tainted_server( socket_dir, { EXPLOIT_KEY: EXPLOIT_VALUE } )
    assert birth.returncode == 0, f"could not birth the probe server: {birth.stderr}"

    # PROVE THE TAINT before trusting any refusal (memento protocol: a refusal
    # against an unproven taint is unattributable — the server could simply have
    # been clean, and the "guard" never asked a question it could get wrong).
    frozen = _tmux( socket_dir, "show-environment", "-g", EXPLOIT_KEY )
    assert frozen.returncode == 0 and frozen.stdout.strip() == f"{EXPLOIT_KEY}={EXPLOIT_VALUE}", (
        f"THE TAINT DID NOT TAKE ({frozen.stdout!r} / {frozen.stderr!r}) — the probe server "
        f"is not carrying the exploit key, so a refusal below would prove nothing."
    )

    result = _launch_vertex( socket_dir, fake_bin )

    assert result.returncode != 0, (
        f"RIO'S EXPLOIT IS ALIVE: the launcher exited 0 against a server whose frozen env "
        f"carries {EXPLOIT_KEY}={EXPLOIT_VALUE}. The launcher shell was clean, so every "
        f"launcher-side guard was green — and the pane would have inherited the override, "
        f"routing Opus alone to {EXPLOIT_VALUE}, where it runs, bills, and logs nothing."
    )
    assert EXPLOIT_KEY in result.stderr, (
        f"The refusal fired but did not NAME the variable. stderr: {result.stderr[:400]!r} — "
        f"an unnamed refusal sends the operator hunting through 21 candidate keys."
    )


@pytest.mark.skipif( not shutil.which( "tmux" ), reason="tmux is not installed" )
def test_a_clean_existing_server_still_launches( rig ):
    """
    POSITIVE CONTROL — the guard must be able to NOT fire. A clean pre-existing
    server plus a clean launcher shell must launch --vertex successfully; without
    this, the refusal above is indistinguishable from a launcher that refuses
    everything.
    """
    socket_dir, fake_bin = rig

    birth = _birth_tainted_server( socket_dir, {} )    # same vector, zero taint
    assert birth.returncode == 0, f"could not birth the clean probe server: {birth.stderr}"

    # Prove the probe server is genuinely clean of the whole refusal set — the
    # control is only a control if its precondition is the opposite of the test's.
    global_env = _tmux( socket_dir, "show-environment", "-g" )
    assert global_env.returncode == 0
    for key in SERVER_TAINT_REFUSAL_KEYS:
        assert f"\n{key}=" not in "\n" + global_env.stdout, (
            f"the 'clean' probe server carries {key} — the positive control is compromised"
        )

    result = _launch_vertex( socket_dir, fake_bin )
    assert result.returncode == 0, (
        f"A CLEAN server refused a --vertex launch (stderr: {result.stderr[:400]!r}). A guard "
        f"that fires on a valid configuration teaches people to disable guards."
    )
