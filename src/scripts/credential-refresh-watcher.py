#!/usr/bin/env python3
"""
Watch the host OAuth credential and re-point the containers at it when it changes.

THE PROBLEM (row c7c60896): Claude Code's access token lives exactly 8 hours and
is REPLACED on refresh, minting a new inode. The host follows it in milliseconds.
A docker single-file bind, resolved at container start, does not — so both Lupin
containers strand on a dead token ~3x/day and every bounded-CC path in them goes
dark until someone notices and restarts them.

WHAT THIS DOES: polls the host credential's inode. When it changes to a token
with real life left, it bounces :7999 through the SANCTIONED managed-bounce
script (so the fleet gets its ack-confirmed warning and the server emits its own
all-clear), then PROVES the recovery with a live `claude -p` probe rather than
assuming a restart worked.

WHAT IT DELIBERATELY DOES NOT DO: touch :8000. It only REPORTS when the test
container is stranded, and names the one-line human remedy. :8000's rule defines
verified-IDLE as nothing RUNNING **and nothing SCHEDULED**; this process can see
the first and not the second, and Rick's "anyone may bounce" grant covers :7999
only. An earlier version restarted it on process-idle alone — an unattended actor
clearing a bar the codebase sets higher (caught by Krishna 🦚 at review).

WHY NOT A TIMER — the thing Rick asked for, and why this is the same intent in a
better instrument: the refresh fires 8 hours after the LAST refresh, which moves
whenever the host happens to call at a different hour. A fixed schedule drifts,
then does the worst of both things — restarts while the token is still good (a
free outage on the fleet's notify channel) and sleeps through the hours after one
actually died. This fires on the event itself.

⚠️ THIS IS A BRIDGE. The fix is the dedicated-directory mount in c7c60896: a
directory bind resolves through on every open, so containers see the current
credential with no restart at all. When that lands, RETIRE this — do not maintain it.

Usage:
    credential-refresh-watcher.py                # run the loop (systemd ExecStart)
    credential-refresh-watcher.py --once         # one observation, then exit
    credential-refresh-watcher.py --self-test    # prove the detector can FIRE, then exit
    credential-refresh-watcher.py --poll 30      # override poll interval (default 60s)

Off switch:  systemctl --user stop lupin-credential-watcher.service
"""

import argparse
import json
import os
import subprocess
import sys
import time

# ── Bootstrap: runs before `cosa` is importable (entry-point exception) ───────
lupin_root = os.environ.get( "LUPIN_ROOT" )
if lupin_root is None:
    print( "LUPIN_ROOT not set — export LUPIN_ROOT=/path/to/project", file=sys.stderr )
    sys.exit( 2 )
src_path = os.path.join( lupin_root, "src" )
if src_path not in sys.path:
    sys.path.insert( 0, src_path )

from cosa.utils.credential_watch import should_restart_containers, container_is_busy

CREDENTIAL_PATH = os.path.expanduser( "~/.claude/.credentials.json" )
DEV_CONTAINER   = "lupin-rest-dev"
TEST_CONTAINER  = "lupin-rest-test"
BOUNCE_SCRIPT   = os.path.join( lupin_root, "src", "scripts", "bounce-dev-server.sh" )
DEFAULT_POLL_S  = 60


def log( msg ):
    """Timestamped line to stdout; systemd captures it into the journal."""
    print( f"[cred-watch {time.strftime( '%Y-%m-%d %H:%M:%S' )}] {msg}", flush=True )


def read_credential_state():
    """
    Read ( inode, expires_at_ms ) from the host credential.

    Ensures:
        - returns ( None, None ) on any read/parse failure rather than raising —
          a watcher that dies on a transient read is worse than one that skips
          a cycle and says so.
    """
    try:
        inode = os.stat( CREDENTIAL_PATH ).st_ino
        with open( CREDENTIAL_PATH ) as f:
            expires = json.load( f )[ "claudeAiOauth" ][ "expiresAt" ]
        return inode, expires
    except Exception as e:                                        # noqa: BLE001 — boundary guard
        log( f"WARN could not read credential: {e}" )
        return None, None


def docker_ps( container ):
    """Raw `ps -ef` from inside a container; empty string on any failure (=> busy)."""
    try:
        r = subprocess.run(
            [ "docker", "exec", container, "ps", "-ef" ],
            capture_output=True, text=True, timeout=20,
        )
        return r.stdout if r.returncode == 0 else ""
    except Exception:                                             # noqa: BLE001 — boundary guard
        return ""


def probe_container( container, timeout=120 ):
    """
    Live `claude -p` probe — the ONLY honest proof a container's auth works.

    `claude auth status` parses a local token's shape with no server round-trip
    and reported success against a revoked credential (c7c60896). Never use it here.
    """
    try:
        r = subprocess.run(
            [ "docker", "exec", container, "claude", "-p", "reply PONG" ],
            capture_output=True, text=True, timeout=timeout,
        )
        out = ( r.stdout + r.stderr ).strip()
        return ( "PONG" in out ), out[ -160: ]
    except Exception as e:                                        # noqa: BLE001 — boundary guard
        return False, f"probe failed: {e}"


def bounce_dev():
    """Bounce :7999 through the sanctioned script (fleet warning + all-clear come free)."""
    log( f"bouncing {DEV_CONTAINER} via bounce-dev-server.sh (fleet gets the warning)" )
    try:
        r = subprocess.run( [ BOUNCE_SCRIPT, "--quiet" ], capture_output=True, text=True, timeout=180 )
        log( f"  bounce script rc={r.returncode}: {r.stdout.strip() or r.stderr.strip()}" )
        return r.returncode == 0
    except Exception as e:                                        # noqa: BLE001 — boundary guard
        log( f"  ERROR bounce script failed: {e}" )
        return False


def report_test_container():
    """
    REPORT on :8000 — never restart it. This watcher does not touch the test server.

    WHY NOT (Krishna 🦚, pre-commit review, and he was right):
    :8000's own rule defines verified-IDLE as nothing RUNNING **and nothing
    SCHEDULED** (CLAUDE.md §TESTING VENUES). This process can see the first —
    `docker exec ps -ef` — and cannot see the second: reading the queue needs a
    JWT it does not hold. Separately, Rick's 2026-08-01 "anyone may bounce within
    reason" grant covers :7999 ONLY; it was never extended to :8000.

    An earlier version restarted :8000 on process-idle alone. That was an
    unattended actor clearing a bar the codebase sets higher, and I reached it by
    noticing the gap and then arguing my own standard down to meet the code
    instead of raising the code to meet the standard.

    So: say the container is stranded, name the one-line human remedy, stop.
    A human at the console can honour list-pending; this process cannot.
    """
    ok, _ = probe_container( TEST_CONTAINER )
    if ok:
        log( f"  {TEST_CONTAINER}: still authenticated, nothing to do" )
        return
    busy, why = container_is_busy( docker_ps( TEST_CONTAINER ) )
    log(
        f"  ⚠️  {TEST_CONTAINER} is STRANDED on the old credential ({why}). "
        f"NOT restarting it — :8000 requires nothing-running AND nothing-scheduled, "
        f"and this process cannot see the queue. Human remedy: docker restart {TEST_CONTAINER} (~50s)."
    )


def act_on_refresh():
    """Re-point :7999, prove it, and REPORT on :8000 without touching it."""
    bounce_dev()
    ok, detail = probe_container( DEV_CONTAINER )
    log( f"  probe {DEV_CONTAINER}: {'✅ PONG' if ok else '❌ ' + detail}" )
    report_test_container()


def self_test():
    """
    Prove the detector can FIRE — a detector that only ever passes by finding
    nothing is indistinguishable from a blind one (standing Lupin rule).

    Feeds the pure decision function a known inode change with a healthy expiry
    and REQUIRES a True, then feeds the no-change case and requires a False.
    """
    now_ms   = time.time() * 1000
    good_exp = now_ms + 8 * 3600 * 1000

    act, why = should_restart_containers( 111, 222, good_exp, now_ms )
    print( f"  changed inode + healthy token -> act={act}  ({why})" )
    assert act is True, "DETECTOR IS BLIND: a real refresh did not trigger it"

    act, why = should_restart_containers( 222, 222, good_exp, now_ms )
    print( f"  unchanged inode              -> act={act}  ({why})" )
    assert act is False, "DETECTOR IS TRIGGER-HAPPY: no change should not act"

    act, why = should_restart_containers( 111, 222, now_ms + 30_000, now_ms )
    print( f"  changed inode + dying token  -> act={act}  ({why})" )
    assert act is False, "would have restarted onto a token about to expire"

    act, why = should_restart_containers( None, 222, good_exp, now_ms )
    print( f"  first observation            -> act={act}  ({why})" )
    assert act is False, "must not bounce the fleet every time systemd restarts it"

    print( "SELF-TEST PASSED — the detector fires on a real change and stays quiet otherwise." )


def main():
    ap = argparse.ArgumentParser( description="Watch the host OAuth credential; re-point the containers when it changes." )
    ap.add_argument( "--once",      action="store_true", help="one observation, then exit" )
    ap.add_argument( "--self-test", action="store_true", help="prove the detector can fire, then exit" )
    ap.add_argument( "--poll",      type=int, default=DEFAULT_POLL_S, help=f"poll seconds (default {DEFAULT_POLL_S})" )
    args = ap.parse_args()

    if args.self_test:
        self_test()
        return 0

    log( f"watching {CREDENTIAL_PATH} every {args.poll}s (bridge until the c7c60896 mount fix lands)" )
    previous_inode = None

    while True:
        inode, expires = read_credential_state()
        act, why = should_restart_containers( previous_inode, inode, expires, time.time() * 1000 )

        if act:
            log( f"REFRESH DETECTED — {why}" )
            act_on_refresh()
        elif previous_inode is None or inode != previous_inode:
            # Only log non-events that represent a state CHANGE; an unchanged
            # inode every 60s would bury the real lines in noise.
            log( why )

        if inode is not None:
            previous_inode = inode
        if args.once:
            return 0
        time.sleep( args.poll )


if __name__ == "__main__":
    sys.exit( main() )
