#!/usr/bin/env python3
"""
Launch or observe the Heartbeat Arbiter consumer (`ArbiterConsumerJob`).

The arbiter tails the fleet heartbeat-event stream (`~/.claude/heartbeat-events/`).
It asks commons who is active and builds a fleet view, a dependency graph and an
idle roster. It auto-pings blockers, escalates deadlocks, and surfaces a roster
to the manager.

Each poll prints a one-line summary so the run can be watched:

    poll #1  sessions=5  edges=1  cycles=0  pings_fired=0  roster=3

Safe by default: it runs in dry-run mode. It reads real fleet state but only logs
the DMs and posts it would send, so no real pings reach the fleet. Add `--live`
to send them. Use `--once` for a single observe-poll, or omit it to loop.

Example:
    python src/scripts/run-heartbeat-arbiter.py --once            # one dry observe-poll, then exit
    python src/scripts/run-heartbeat-arbiter.py                   # dry-run loop (logs intended pings)
    python src/scripts/run-heartbeat-arbiter.py --live            # real: pings the fleet
    python src/scripts/run-heartbeat-arbiter.py --poll-seconds 15 --manager Tiberius
    python src/scripts/run-heartbeat-arbiter.py --quiet 300 --alive 600   # quiet must be below alive

Defaults are quiet=300s and alive=600s.
"""
import argparse
import os
import sys
from pathlib import Path

# ── Bootstrap (runs before `cosa` is importable) ─────────────────────────────
_lupin_root = os.environ.get( "LUPIN_ROOT" ) or str( Path( __file__ ).resolve().parents[ 2 ] )
_src_path   = os.path.join( _lupin_root, "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.agents.heartbeat_arbiter.arbiter_job import ArbiterConsumerJob
from cosa.agents.heartbeat_arbiter.arbiter_gateway import LupinArbiterGateway
from lupin_cli.claude_code.hooks.lib.heartbeat_hold import read_hold_via_bridge   # 6929f4ac + row 011f1f90: resilient reader (repo-root holds visible)
import cosa.utils.util as cu   # EST timestamps (project canonical US/Eastern)


class _DryGateway:
    """
    Wrap a real ArbiterGateway so that only reads are real.

    `who()` reads for real, so the roster and graph are accurate. `send_to()` and
    `post()` only log, so no real DM or surface post reaches the fleet.
    """
    def __init__( self, inner ):
        self._inner = inner

    def who( self, retention_hours: int = 24 ):
        return self._inner.who( retention_hours=retention_hours )

    def send_to( self, recipient: str, body: str ) -> None:
        print( f"    [DRY] would PING → {recipient}: {body[ :140 ]}", flush=True )

    def post( self, topic: str, body: str ) -> None:
        indented = body.replace( "\n", "\n          " )
        print( f"    [DRY] would POST → {topic}:\n          {indented}", flush=True )


def _log( msg ):
    print( f"    [arbiter] {msg}", flush=True )


def main():
    p = argparse.ArgumentParser( description="Launch/observe the Heartbeat Arbiter consumer." )
    p.add_argument( "--live",         action="store_true", help="REALLY send pings/posts to the fleet (default: dry-run, log only)" )
    p.add_argument( "--once",         action="store_true", help="run a single poll then exit (vs continuous loop)" )
    p.add_argument( "--poll-seconds", type=int, default=60, help="seconds between polls (loop mode); per-minute default for debugging" )
    p.add_argument( "--quiet",        type=int, default=300, help="quiet_threshold_seconds (idle-window lower bound)" )
    p.add_argument( "--alive",        type=int, default=600, help="alive_threshold_seconds (idle-window upper bound); must be > --quiet" )
    p.add_argument( "--manager",      default="Tiberius", help="manager_recipient persona for the roster surface" )
    args = p.parse_args()

    real    = LupinArbiterGateway.from_environment( "arbiter-runner", persona_name="heartbeat-arbiter" )
    gateway = real if args.live else _DryGateway( real )
    mode    = "🔴 LIVE — pinging the fleet" if args.live else "🟢 DRY-RUN — logging only, no real pings"

    print( f"▶ Heartbeat Arbiter — {mode}" )
    print( f"  quiet={args.quiet}s  alive={args.alive}s  poll={args.poll_seconds}s  manager={args.manager}" )
    print( f"  events: ~/.claude/heartbeat-events/    (Ctrl-C to stop)\n" )

    arbiter = ArbiterConsumerJob(
        commons                 = gateway,
        poll_seconds            = args.poll_seconds,
        manager_recipient       = args.manager,
        alive_threshold_seconds = args.alive,
        quiet_threshold_seconds = args.quiet,
        hold_reader_fn          = read_hold_via_bridge, # 6929f4ac + row 011f1f90: resilient reader; log_fn omitted (manual dev runner, no structured journal)
        notify_fn               = _log,
    )

    try:
        if args.once:
            summary = arbiter._poll_once()
            print( f"\n  poll summary: {summary}" )
        else:
            n = [ 0 ]
            _orig = arbiter._poll_once
            def _wrapped():                     # per-poll summary line for the loop
                r  = _orig()
                n[ 0 ] += 1
                ts = cu.get_current_datetime( tz_name="US/Eastern", format_str="%H:%M:%S %Z" )
                print( f"  {ts}  poll #{n[ 0 ]}  sessions={r['sessions']}  edges={r['edges']}  "
                       f"cycles={r['cycles']}  pings_fired={r['pings_fired']}  roster={r['roster']}", flush=True )
                return r
            arbiter._poll_once = _wrapped
            arbiter.do_all()
    except KeyboardInterrupt:
        print( "\n■ stopped." )


if __name__ == "__main__":
    main()
