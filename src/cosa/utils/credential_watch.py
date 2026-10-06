"""
Pure decision logic for the container OAuth credential watcher.

Claude Code's access token lives 8 hours and is replaced on refresh, which mints a new
inode. The host follows the new file. A docker single-file bind resolved at container
start does not. So both Lupin containers strand on a dead token about three times a
day. Every bounded-CC path in them goes dark until someone restarts them. Those paths
are podcast, BFE, TFE, deep research and presentation.

This is a watcher and not a timer. The refresh fires 8 hours after the last refresh,
which moves whenever the host calls at a different hour. A fixed schedule drifts out
of alignment and then does the worst of both things. It restarts while the token is
still good, which is a free outage on the fleet's notify channel. It also sleeps
through the hours after a token has died. Watching the inode fires when, and only
when, the event we care about has happened.

This is a bridge, not the fix. The fix is a dedicated-directory mount. A directory
bind resolves through on every open, so the container sees the host's current
credential with no restart at all. Once that lands, this watcher has nothing left to
do and should be retired, not maintained.

All I/O (docker, filesystem, clock, sleep) lives in
src/scripts/credential-refresh-watcher.py. Everything here is pure so it can be tested
without a container.
"""

from typing import Optional, Tuple


# A restart is pointless if the freshly-seen token is already dead or about to
# be: the container would re-resolve to a credential that fails on first use.
# 120s of headroom covers the restart itself plus health-poll settle.
MIN_REMAINING_SECONDS = 120.0


def should_restart_containers(
    previous_inode  : Optional[ int ],
    current_inode   : Optional[ int ],
    expires_at_ms   : Optional[ int ],
    now_ms          : float,
    min_remaining_s : float = MIN_REMAINING_SECONDS,
) -> Tuple[ bool, str ]:
    """
    Decide whether the host credential changed into something worth acting on.

    Requires:
        - now_ms is epoch milliseconds
        - previous_inode is None on the watcher's first observation

    Ensures:
        - returns ( act, reason ); reason is always non-empty and names why,
          so the log says what the watcher saw rather than only what it did
        - returns False on the first observation, because there is nothing to compare
          against and a watcher that acts on startup would bounce the fleet every
          time systemd restarted it
        - returns False when the inode is unchanged
        - returns False when the new token is already expired or expires within
          min_remaining_s — restarting onto a dead credential is the failure
          this watcher exists to prevent, not a milder version of it

    Raises:
        - None
    """
    if current_inode is None:
        return False, "credential file unreadable — nothing to act on"

    if previous_inode is None:
        return False, f"first observation (inode {current_inode}) — baseline only, not acting"

    if current_inode == previous_inode:
        return False, f"inode unchanged ({current_inode})"

    if expires_at_ms is None:
        return False, f"inode {previous_inode} -> {current_inode} but no expiry in the file — refusing to act on an unreadable credential"

    remaining_s = ( expires_at_ms - now_ms ) / 1000.0
    if remaining_s <= min_remaining_s:
        return False, (
            f"inode {previous_inode} -> {current_inode} but the new token has only "
            f"{remaining_s:.0f}s left (need > {min_remaining_s:.0f}s) — restarting onto it would strand again"
        )

    return True, f"inode {previous_inode} -> {current_inode}, new token good for {remaining_s / 3600.0:.1f}h"


# Markers for work we must not interrupt. `docker exec <c> ps -ef` output is
# scanned for these; a match defers the restart to the next cycle rather than
# killing someone's suite. Deliberately NOT a general "is anything running"
# check — the container always runs its own server process.
BUSY_PROCESS_MARKERS = ( "pytest", "playwright", "run-integration-tests", "run-e2e-ui-tests" )


def container_is_busy( ps_output: str, markers = BUSY_PROCESS_MARKERS ) -> Tuple[ bool, str ]:
    """
    Decide whether a container is running work a restart would destroy.

    Requires:
        - ps_output is the raw text of `ps -ef` from inside the container
          (an empty string is treated as "could not tell", which counts as busy)

    Ensures:
        - returns ( busy, reason )
        - fails safe: an empty or unreadable ps_output returns busy=True.
          A watcher that cannot see inside a container must not assume the
          container is free, because "I saw nothing" and "there is nothing" are
          different states

    Raises:
        - None
    """
    if not ps_output.strip():
        return True, "could not read process list — treating as busy (fail-safe)"

    for marker in markers:
        if marker in ps_output:
            return True, f"work in flight ({marker}) — deferring"

    return False, "idle"
