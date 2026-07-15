"""
Benign killtrace-observation probe (AC5 addendum / AC6 leg-3 canary).

Proves the runbook §10 killtrace instrument observes `tmux kill-server`
events END-TO-END without ever touching the fleet default socket: birth a
throwaway tmux server on an explicit private `-S` socket from a
$TMUX-stripped env, `kill-server` THAT throwaway server, and await the
expected killtrace line for its pid.

One probe, two confirmations (fix plan AC6): the sig=15 self-SIGTERM line
(sender == target == server pid) ALSO empirically confirms the §2.1
signature rule. After the HUMAN installs the execve tracer
(src/scripts/tmux-execve-killtrace.bt), the same probe run additionally
yields a `KILLER ... kill-server` line — find_killer_line() reads it.

SAFETY ENVELOPE (fix plan §7 hard rule): every tmux invocation here uses an
explicit private `-S` socket from a $TMUX-stripped env — `-S` overrides all
env-based socket selection, so no verb here can address the fleet socket.

Design: src/rnd/v0.1.9/2026.07.14-tmux-fleet-killer-vertex-taint-test-isolation-leak-fix-plan.md (§6 AC5/AC6)
"""

import subprocess
import time

from tests.smoke.tmux_isolation import TMUX_ISOLATION_STRIP_KEYS

KILLTRACE_LOG      = "/var/log/tmux-killtrace.log"
PROBE_SESSION_NAME = "killtrace_probe"


def stripped_env( environ ):
    """
    A copy of environ with the pane context AND TMUX_TMPDIR removed.

    Requires:
        - environ is a str->str mapping (os.environ or a test dict)

    Ensures:
        - returns a NEW dict; TMUX/TMUX_PANE/TMUX_TMPDIR absent; input untouched

    Raises:
        - None
    """
    env = dict( environ )
    for key in TMUX_ISOLATION_STRIP_KEYS:
        env.pop( key, None )
    env.pop( "TMUX_TMPDIR", None )
    return env


def birth_throwaway_server( sock_path, env ):
    """
    Birth a private tmux server on an explicit -S socket; return its pid.

    Requires:
        - sock_path is a writable socket path in an EXISTING directory
        - env came from stripped_env() (no pane context)

    Ensures:
        - a detached session PROBE_SESSION_NAME lives on sock_path only
        - returns the server pid (int)

    Raises:
        - RuntimeError if tmux cannot birth or identify the server
    """
    born = subprocess.run(
        [ "tmux", "-S", str( sock_path ), "new-session", "-d", "-s", PROBE_SESSION_NAME, "sleep 300" ],
        capture_output=True, text=True, env=env, timeout=30
    )
    if born.returncode != 0:
        raise RuntimeError( f"could not birth throwaway server on {sock_path}: {born.stderr}" )

    asked = subprocess.run(
        [ "tmux", "-S", str( sock_path ), "display-message", "-p", "#{pid}" ],
        capture_output=True, text=True, env=env, timeout=30
    )
    if asked.returncode != 0 or not asked.stdout.strip():
        raise RuntimeError( f"throwaway server born but pid query failed: {asked.stderr}" )
    return int( asked.stdout.strip() )


def kill_throwaway_server( sock_path, env ):
    """
    kill-server the throwaway server — explicit -S private socket ONLY.

    Requires:
        - sock_path hosts the throwaway server born above
        - env came from stripped_env()

    Ensures:
        - the throwaway server is dead; the fleet socket is unreachable by
          construction (-S overrides all env-based selection)

    Raises:
        - None (a dead-already server is fine)
    """
    subprocess.run(
        [ "tmux", "-S", str( sock_path ), "kill-server" ],
        capture_output=True, text=True, env=env, timeout=30
    )


def find_self_sigterm_line( log_text, server_pid ):
    """
    The first-probe signature: self-directed SIGTERM where sender is the
    server itself (§2.1 rule — kill-server runs INSIDE the server process).

    Requires:
        - log_text is the killtrace log content; server_pid an int

    Ensures:
        - returns the LAST matching line, or None

    Raises:
        - None
    """
    needle = f"sig=15 target={server_pid}"
    match  = None
    for line in log_text.splitlines():
        if needle in line and "from=tmux: server" in line:
            match = line
    return match


def find_killer_line( log_text ):
    """
    The second-probe (execve tracer) signature: a KILLER line carrying
    kill-server argv. Meaningful only after the HUMAN installs
    src/scripts/tmux-execve-killtrace.bt.

    Requires:
        - log_text is the killtrace log content

    Ensures:
        - returns the LAST matching line, or None

    Raises:
        - None
    """
    match = None
    for line in log_text.splitlines():
        if "KILLER" in line and "kill-server" in line:
            match = line
    return match


def await_line( log_path, finder, timeout_s=10.0, poll_s=0.25 ):
    """
    Poll log_path until finder() names a line or the timeout lapses.

    Requires:
        - log_path is a readable file; finder maps text -> line|None

    Ensures:
        - returns the found line, or None on timeout (caller decides loudness)

    Raises:
        - OSError if log_path is unreadable (fail loud, never mask)
    """
    deadline = time.monotonic() + timeout_s
    while True:
        with open( log_path, "r", errors="replace" ) as f:
            line = finder( f.read() )
        if line is not None:
            return line
        if time.monotonic() >= deadline:
            return None
        time.sleep( poll_s )


def run_probe( sock_path, environ, log_path=KILLTRACE_LOG, timeout_s=10.0 ):
    """
    The whole benign probe: birth -> kill -> await the self-SIGTERM line.

    Requires:
        - sock_path in an existing dir; environ (usually os.environ);
          log_path readable

    Ensures:
        - returns ( server_pid, line ) — line is the killtrace receipt, or
          None if the instrument did not observe the kill within timeout_s

    Raises:
        - RuntimeError from birth; OSError from an unreadable log
    """
    env        = stripped_env( environ )
    server_pid = birth_throwaway_server( sock_path, env )
    kill_throwaway_server( sock_path, env )
    line = await_line( log_path, lambda text: find_self_sigterm_line( text, server_pid ), timeout_s=timeout_s )
    return server_pid, line
