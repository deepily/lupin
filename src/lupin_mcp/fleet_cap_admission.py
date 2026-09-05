#!/usr/bin/env python3
"""
FLEET-CAP ADMISSION — the cap enforced by a process that is FRESH AT SPAWN TIME.

🔴 WHY THIS EXISTS, AND IT IS NOT A SECOND POLICY. `fleet_size_cap` already holds the
policy and `session_spawner.spawn_sessions` already calls it. That call site is correct
and stays. What it cannot do is bind a caller whose code is older than the rule, and on
2026-09-04 that is exactly what happened.

=== THE MEASUREMENT THIS MODULE ANSWERS ===

MAX CONCURRENT = 12 against a cap of 8, at 2026-09-04 11:48:03 EDT. Taken by sweep-line
over [first notification, last notification] per session in `lupin_db_dev.notifications`,
`sender_id LIKE 'claude.code@%'`, 8-hex session ids only, 31 sessions. The 12 were three
managers booted 11:07-11:09 plus nine workers spawned 11:34-11:48.

⚠️ NAME THE POPULATION: that interval is first-to-last NOTIFICATION, so a seat that ran
silently is UNDERCOUNTED. 12 is a FLOOR, not a ceiling.

TWO CAUSES, and only the second is still live:

  1. THE GATE WAS NOT IN THE TREE. `93f167e4` (09-03 19:28) shipped `fleet_size_cap.py`
     with zero callers — its own subject says "NOT YET WIRED INTO spawn_sessions".
     `9c3c7cb3` (09-03 23:00) added the call site. Its first merge onto the main line is
     `23bb0124` at 09-04 14:13:18 EDT
     (`git rev-list --ancestry-path 9c3c7cb3..HEAD --merges | tail -1`). The peak was
     11:48 — 2h25m before there was any enforcing code to run.

  2. 🔴 THE ENFORCEMENT CODE IS FROZEN AT SEAT BOOT. cosa-voice is registered **stdio**,
     so every seat runs its OWN MCP subprocess, started at boot, importing from the
     checkout, with no reload path. Measured 2026-09-05: pid 9385 started 09:43:37
     running `.../src/lupin_mcp/cosa_voice_mcp.py`, one per seat. So the three managers
     that booted at 11:07-11:09 ran PRE-GATE code for their whole twelve-hour life —
     INCLUDING every spawn they made after the 14:13 merge.

🔴 WHAT IS MEASURED ABOUT THAT SECOND CAUSE, AND WHAT IS NOT. Manifest
`spawned-21dff055` records four spawns; cross-referencing each against the occupancy
sweep at that instant:

    14:13:18  merge 23bb0124 lands                      occupancy  8
    15:06:54  spawn cc-reviewer-mr-radio-1  SUCCEEDED   occupancy  7   (a live gate ALLOWS)
    18:46:38  spawn cc-author-mr-radio-4    SUCCEEDED   occupancy 10   (a live gate REFUSES)
    19:18:00  spawn cc-author-mr-radio-1    SUCCEEDED   occupancy 11   (a live gate REFUSES)
    21:35:29  spawn cc-author-mr-radio-2    SUCCEEDED   occupancy  8   (a live gate REFUSES)

MEASURED: three spawns succeeded at or above a cap of 8, hours after the enforcing code
was in the checkout. The 15:06 row is the control that keeps the other three meaningful —
it is the one spawn a live gate would also have allowed, and it behaved identically, so
the finding is not "spawning was broken".

⚠️ THIS WAS FIRST WRITTEN AS "the gate did not fire", AND THAT IS AN OVERCLAIM. It is
left corrected here rather than quietly reworded, because the welded version is the one
that sounds explanatory. A successful spawn over cap has TWO explanations and the
artifacts on disk cannot separate them:

    (a) the gate was NOT RUNNING in that stale interpreter, or
    (b) the gate RAN and its own census UNDERCOUNTED.

(b) is live because `default_fleet_gate` counts through
`find_active_voice_persona_sessions` (`require_persona=True`), which drops mid-boot and
persona-less seats — the hole María 🌸 and Tiberius 👑 both raised independently. The
gate logs nothing about the census it took, so its denominator at 18:46 is not
recoverable.

WHAT LEANS TOWARD (a), stated as a lean rather than a proof: every session in that
occupancy sweep is identified BY ITS PERSONA — they were emitting notifications carrying
`sender_persona` at the time — so a persona-filtered census should have seen them.
Explanation (b) requires the bridge scan to have missed three or more live,
persona-bearing seats.

⇒ AND THE FIX DOES NOT DEPEND ON WHICH ONE IT WAS. (a) is closed by evaluating policy in
a fresh process; (b) is closed by counting every live bridge rather than only the seats
that won a voice. This module does both, so the ambiguity is a gap in the FORENSICS, not
in the remedy — which is the only reason it is acceptable to leave it unresolved.

🔴 THE ASYMMETRY IS THE DEFECT, AND IT IS WHY A THIRD FIX TO `default_fleet_gate` WOULD
NOT HAVE HELPED. `6883a349` already made the cap's VALUE survive a stale process by
re-reading the INI from disk. The value was fresh and the code was not. A rule that can
only reach the fleet by every seat re-booting is not installed — it is announced.

=== WHERE THIS RUNS INSTEAD ===

`start-cc-with-tmux.sh` is the launcher for EVERY session on this box — the MCP's
headless spawns and a hand-typed interactive one alike — and it is a FRESH BASH PROCESS
per launch that shells out to `python3`. So policy evaluated from here is, by
construction, the policy on disk at the moment of the spawn. No bounce, no re-boot, no
dependence on which manager's interpreter asked.

⚠️ IT DOES NOT REPLACE THE MCP-LEVEL GATE AND MUST NOT. That one refuses EARLY, before a
tmux session is created, and can say "4 requested, 2 fit" about a batch. This one sees
one child at a time and fires after the caller has committed. Two gates, two jobs: the
first is the good error message, the second is the one that actually binds.

=== THE RESERVATION, AND WHY IT IS NOT OVER-BUILDING ===

A census of live bridges cannot see a child that has been launched and has not yet
written one. That window is documented and measured in `list_spawned_sessions`: a healthy
child goes `unknown_no_bridge` -> `none` -> `allocated` in about one second. Two launches
inside that window both read the same headroom and both take it.

So an admission WRITES a reservation under a lock, and occupancy counts live bridges PLUS
reservations that have not yet materialised into one. A reservation is resolved — not
merely aged out — the moment a bridge carrying its tmux session name appears, so nothing
is ever counted twice. The TTL is garbage collection for a launch that DIED, never the
mechanism of correctness.

=== WHAT THIS DELIBERATELY DOES NOT DO ===

🔨 IT REAPS NOTHING. Rick's ruling of 2026-09-03 stands unchanged: over cap REFUSES THE
NEW SPAWN and leaves running seats alone, so the fleet drains as sessions finish. Nothing
in this module terminates a session, and that is a ruling rather than an omission.

⚠️ AND IT FAILS OPEN, matching `default_fleet_gate` deliberately. A census that cannot be
taken is not evidence the fleet is full, and a guard that refuses every launch on a
bridge-read error takes the whole fleet down over a resource limit. The failure is SAID
on stderr rather than swallowed — the thing this repo keeps re-learning is that a step
which cannot finish must decline out loud, not return a clean-looking nothing.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

# How long a reservation may sit unmaterialised before it is treated as a launch that
# died. Correctness does not rest on this number — a reservation is resolved the moment
# its bridge appears — so it only decides how long a FAILED launch keeps holding a seat.
DEFAULT_RESERVATION_TTL_SECONDS = 120

RESERVATION_SUBDIR = "fleet-admissions"
LOCK_FILENAME      = ".fleet-admission.lock"

EXIT_ADMITTED = 0
EXIT_REFUSED  = 3


def reservation_dir( sessions_dir_fn: Optional[ Callable[ [], Path ] ] = None ) -> Path:
    """
    The directory holding admission reservations.

    Requires:
        - sessions_dir_fn, when given, returns a Path

    Ensures:
        - returns <sessions dir>/fleet-admissions
        - resolves the sessions directory at CALL time, so the
          LUPIN_HOOK_SESSIONS_DIR seam is honored regardless of import order
        - does NOT create the directory

    🔴 IT LIVES BESIDE THE BRIDGES, NOT UNDER `fleet_data_root()`. The census this
    guard compares against reads `~/.claude/sessions`, and a reservation resolved from
    a different root would be a second derivation of one fact — the shape this repo has
    already been bitten by, where two sides agree only because their inputs happen to
    coincide. One directory, one derivation.
    """
    if sessions_dir_fn is None:
        from lupin_cli.claude_code.hooks.lib.sessions_dir import sessions_dir
        sessions_dir_fn = sessions_dir
    return Path( sessions_dir_fn() ) / RESERVATION_SUBDIR


def _reservation_path( directory: Path, session_name: str ) -> Path:
    """Path to one reservation file; the session name is sanitised for the filesystem."""
    safe = "".join( c if c.isalnum() or c in "-_" else "_" for c in session_name )
    return Path( directory ) / f"{safe}.json"


def read_reservations( directory: Path ) -> List[ Dict[ str, Any ] ]:
    """
    Every reservation currently on disk.

    Requires:
        - directory is a Path (need not exist)

    Ensures:
        - returns a list of reservation dicts, each carrying at least `session_name`,
          `reserved_ts` and `_path`
        - a file that cannot be read or parsed is SKIPPED, never raised on
        - returns [] when the directory is absent
        - never raises
    """
    directory = Path( directory )
    if not directory.exists():
        return []
    out = []
    for path in sorted( directory.glob( "*.json" ) ):
        try:
            with open( path ) as handle:
                data = json.load( handle )
        except ( OSError, json.JSONDecodeError, ValueError ):
            continue
        if isinstance( data, dict ) and data.get( "session_name" ):
            data[ "_path" ] = str( path )
            out.append( data )
    return out


def unmaterialised_reservations(
    reservations  : List[ Dict[ str, Any ] ],
    bridge_lookup : Callable[ [ str ], Any ],
    now           : float,
    ttl_seconds   : int = DEFAULT_RESERVATION_TTL_SECONDS
) -> List[ Dict[ str, Any ] ]:
    """
    The reservations that still occupy a seat — neither materialised nor expired.

    Requires:
        - reservations is a list of dicts carrying `session_name` and `reserved_ts`
        - bridge_lookup( tmux_session_name ) -> truthy when a live bridge names it
        - now is epoch seconds; ttl_seconds >= 0

    Ensures:
        - DROPS a reservation whose tmux session name now has a live bridge — it has
          become a counted session, and counting both would be a double count
        - DROPS a reservation older than ttl_seconds — a launch that never arrived
        - a reservation with an unreadable/absent `reserved_ts` is treated as EXPIRED,
          because a seat held by a record we cannot date is a seat held forever
        - a bridge_lookup that RAISES is treated as "not materialised": the reservation
          KEEPS its seat, the conservative direction for a resource limit
        - never raises

    🔴 MATERIALISATION IS THE MECHANISM; THE TTL IS ONLY GARBAGE COLLECTION. If this
    were TTL-only, correctness would rest on a child always booting inside the window,
    and a slow boot would silently let the fleet exceed its cap. Resolving against the
    bridge means a reservation stops occupying a seat exactly when the SESSION starts
    occupying it.
    """
    still_holding = []
    for entry in reservations:
        name = entry.get( "session_name" )
        try:
            reserved_ts = float( entry.get( "reserved_ts" ) )
        except ( TypeError, ValueError ):
            continue                                    # undateable ⇒ expired
        if now - reserved_ts > ttl_seconds:
            continue                                    # the launch never arrived
        try:
            if bridge_lookup( name ):
                continue                                # materialised into a session
        except Exception:
            pass                                        # unknown ⇒ keep the seat
        still_holding.append( entry )
    return still_holding


def prune( directory: Path, keep: List[ Dict[ str, Any ] ] ) -> int:
    """
    Delete every reservation file not in `keep`.

    Requires:
        - directory is a Path; keep is a list of reservation dicts carrying `_path`

    Ensures:
        - returns the number of files removed
        - a file that cannot be removed is skipped, never raised on
        - never raises
    """
    directory = Path( directory )
    if not directory.exists():
        return 0
    kept    = { entry.get( "_path" ) for entry in keep }
    removed = 0
    for path in directory.glob( "*.json" ):
        if str( path ) in kept:
            continue
        try:
            path.unlink()
            removed += 1
        except OSError:
            pass
    return removed


def admit(
    session_name  : str,
    *,
    headless      : bool,
    cap_fn        : Callable[ [], int ],
    census_fn     : Callable[ [], Any ],
    bridge_lookup : Callable[ [ str ], Any ],
    directory     : Path,
    now_fn        : Callable[ [], float ] = time.time,
    ttl_seconds   : int = DEFAULT_RESERVATION_TTL_SECONDS
) -> Dict[ str, Any ]:
    """
    Decide whether ONE launch may proceed, and reserve its seat when it may.

    Requires:
        - session_name is a non-empty string (the tmux session name)
        - cap_fn() -> the configured fleet cap, an int >= 1
        - census_fn() -> an iterable of live sessions (only its LENGTH is used)
        - bridge_lookup( tmux_session_name ) -> truthy when a live bridge names it
        - directory is where reservations live

    Ensures:
        - returns { session_name, cap, live, reserved, occupancy, headless, admitted,
                    reason } and, only on a failed write, `reservation_error`
        - `admitted` is True iff occupancy + 1 <= cap, where occupancy is
          live sessions + unmaterialised reservations
        - on admission, writes a reservation file for `session_name` BEFORE returning,
          so a concurrent admission holding the lock next sees this seat taken
        - on refusal, writes nothing
        - expired and materialised reservations are pruned on every call, so the store
          cannot grow without bound and a dead launch cannot hold a seat forever
        - `reason` names cap, live, reserved and headroom; it is None on admission
        - never raises

    ⚠️ THE CALLER HOLDS THE LOCK, NOT THIS FUNCTION. Serialisation belongs to the
    process boundary (`admit_under_lock`) so this half stays a pure decision a test can
    drive without a filesystem lock — and so a caller that already holds the lock cannot
    deadlock itself on a second acquire.
    """
    now          = now_fn()
    directory    = Path( directory )
    reservations = read_reservations( directory )
    holding      = unmaterialised_reservations( reservations, bridge_lookup, now, ttl_seconds )
    prune( directory, holding )

    live      = len( list( census_fn() ) )
    reserved  = len( holding )
    occupancy = live + reserved
    cap       = int( cap_fn() )

    verdict = {
        "session_name" : session_name,
        "cap"          : cap,
        "live"         : live,
        "reserved"     : reserved,
        "occupancy"    : occupancy,
        "headless"     : bool( headless ),
        "admitted"     : occupancy + 1 <= cap,
        "reason"       : None,
    }

    if not verdict[ "admitted" ]:
        headroom = max( 0, cap - occupancy )
        verdict[ "reason" ] = (
            f"FLEET CAP REFUSED THIS LAUNCH — the cap is {cap} and the fleet already "
            f"occupies {occupancy} seat(s): {live} live session(s) plus {reserved} "
            f"launch(es) in flight. {headroom} seat(s) free. "
            f"[denominator: EVERY live bridge, persona-bearing or not, plus launches "
            f"that have not yet written one. The MCP gate's refusal counts a NARROWER "
            f"population — persona-bearing bridges only — so the two can legitimately "
            f"disagree by the number of seats that lost their persona allocation.] "
            f"Nothing was terminated: the cap refuses NEW launches and leaves running "
            f"seats alone (Rick's ruling), so the fleet drains as sessions finish. "
            f"Reap a seat, or raise `cc session fleet size cap` in "
            f"src/conf/lupin-app.ini."
        )
        return verdict

    record = {
        "session_name" : session_name,
        "reserved_ts"  : now,
        "headless"     : bool( headless ),
        "pid"          : os.getpid(),
    }
    try:
        directory.mkdir( parents=True, exist_ok=True )
        with open( _reservation_path( directory, session_name ), "w" ) as handle:
            json.dump( record, handle )
    except OSError as error:
        # The decision stands; we simply could not record it. Say so rather than return
        # a clean-looking admission whose reservation silently went missing.
        verdict[ "reservation_error" ] = str( error )
    return verdict


def release( session_name: str, directory: Path ) -> bool:
    """
    Drop a reservation because its launch did not happen.

    Requires:
        - session_name is a non-empty string; directory is a Path

    Ensures:
        - returns True when a reservation file was removed, False otherwise
        - never raises

    ⚠️ NOT THE NORMAL PATH. A successful launch's reservation is retired by
    MATERIALISATION, not by a release call — the bridge appears and
    `unmaterialised_reservations` stops counting it. This exists for the launcher that
    reserved a seat and then failed to create the tmux session, where waiting out the
    TTL would hold a seat nobody is sitting in.
    """
    try:
        _reservation_path( directory, session_name ).unlink()
        return True
    except OSError:
        return False


def admit_under_lock( session_name: str, *, headless: bool, **kwargs ) -> Dict[ str, Any ]:
    """
    `admit`, serialised across every concurrent launcher on this box.

    Requires:
        - the arguments `admit` requires, including `directory`

    Ensures:
        - the census-then-reserve sequence is atomic with respect to other callers of
          this function, so two simultaneous launches cannot both claim the last seat
        - the lock is released even when `admit` raises
        - a lock that cannot be created or acquired DOES NOT block the launch: the
          decision is still taken, unserialised, and `lock_error` is set on the verdict
        - never raises on lock handling

    🔴 THE LOCK IS WHAT MAKES THE RESERVATION MEAN ANYTHING. Without it two launchers
    read the same headroom, both write a reservation, and both proceed — the reservation
    would then RECORD the overrun rather than prevent it.

    ⚠️ THE LOCK LIVES INSIDE THE RESERVATION DIRECTORY, NOT BESIDE IT, AND THAT PLACEMENT
    IS LOAD-BEARING FOR SOMEBODY ELSE'S TEST. `src/tests/bridge_dir_guard.py`
    fingerprints the sessions directory with a `*` glob to detect a merge into a live
    seat, and it hashes CONTENT. A directory is recorded as the constant `"<dir>"`, so
    everything this module writes underneath is invisible to it; a lock FILE sitting in
    the sessions directory would have been a second new name there, rewritten on every
    launch. Keeping both under one directory means this feature adds exactly ONE constant
    entry to a directory another guard is watching.

    ⚠️ `.json` IS THE RESERVATION SUFFIX AND THE LOCK DELIBERATELY DOES NOT CARRY IT —
    `read_reservations` globs `*.json`, so a lock file named with that suffix would be
    read as a malformed reservation on every call.
    """
    directory = Path( kwargs[ "directory" ] )
    lock_path = directory / LOCK_FILENAME
    handle    = None
    try:
        directory.mkdir( parents=True, exist_ok=True )
        handle = open( lock_path, "w" )
        fcntl.flock( handle.fileno(), fcntl.LOCK_EX )
    except OSError as error:
        if handle is not None:
            try:
                handle.close()
            except OSError:
                pass
        verdict = admit( session_name, headless=headless, **kwargs )
        verdict[ "lock_error" ] = str( error )
        return verdict

    try:
        return admit( session_name, headless=headless, **kwargs )
    finally:
        try:
            fcntl.flock( handle.fileno(), fcntl.LOCK_UN )
            handle.close()
        except OSError:
            pass


# ── The live wiring: real cap, real census, real bridges ─────────────────────────────

def _live_cap() -> int:
    """
    The configured fleet cap, read FRESH — config manager plus the on-disk override.

    Ensures:
        - delegates entirely to `fleet_size_cap`; this module holds no second policy
        - falls back to that module's default when configuration is unreadable
    """
    from lupin_mcp import fleet_size_cap
    try:
        from cosa.config.configuration_manager import ConfigurationManager
        config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
    except Exception:
        config_mgr = None
    return fleet_size_cap.resolve_fleet_cap(
        config_mgr, disk_fn=fleet_size_cap.default_disk_cap_reader )


def _live_census():
    """
    Every live session bridge — persona-bearing or not.

    🔴 `require_persona=False`, AND THAT IS A DELIBERATE DIFFERENCE FROM
    `default_fleet_gate`. The MCP gate counts through
    `find_active_voice_persona_sessions`, which filters to seats that HAVE a persona, so
    a live seat whose allocation failed, raced, or fell through occupies a real seat and
    is invisible to the count. The question this guard asks is "how many sessions are
    running", and the answer must not depend on whether each one won a voice.

    ⚠️ MEASURED 2026-09-05 ON THIS BOX: both projections returned 2, so the widening is
    a hole closed on principle rather than one observed firing. Said plainly instead of
    implied, because a precaution reported as though it had a receipt is worse than one
    reported as a precaution.
    """
    from lupin_cli.claude_code.hooks.lib.session_bridge import find_active_sessions
    return find_active_sessions( require_persona=False )


def _live_bridge_lookup( tmux_session_name: str ):
    """Truthy when a live bridge carries this tmux session name."""
    from lupin_cli.claude_code.hooks.lib.session_bridge import find_session_by_tmux
    return find_session_by_tmux( tmux_session_name )


def main( argv: Optional[ List[ str ] ] = None, admit_fn: Callable = admit_under_lock,
          release_fn: Callable = release, dir_fn: Callable = reservation_dir,
          stderr = None ) -> int:
    """
    The command line `start-cc-with-tmux.sh` runs before it creates a tmux session.

    Requires:
        - argv carries `--session-name <name>`; `--headless` when agent-spawned

    Ensures:
        - EXIT_ADMITTED (0) — the launch may proceed; a reservation holds its seat
        - EXIT_REFUSED (3) — over cap AND `--headless`; the refusal is on stderr
        - EXIT_ADMITTED with a warning when over cap WITHOUT `--headless`
        - EXIT_ADMITTED on ANY internal failure, with the failure printed to stderr —
          fail-open, matching `default_fleet_gate`
        - `--release` drops a reservation and exits EXIT_ADMITTED
        - never raises

    🔴 THE ASYMMETRY BETWEEN HEADLESS AND INTERACTIVE IS THE ONE POLICY CHOICE HERE, AND
    IT IS NOT A SOFTENING OF THE CAP. Agent spawns are refused. A human's own launch is
    warned about and allowed, because a cap that can lock the operator out of his own box
    is a control that removes the ability to fix it — he would need a terminal to reap
    from, and the cap would be refusing him that terminal. Both still COUNT toward
    occupancy, so an interactive session squeezes agents out, which is the correct
    direction.
    """
    stderr = stderr if stderr is not None else sys.stderr
    parser = argparse.ArgumentParser( prog="fleet_cap_admission", add_help=True )
    parser.add_argument( "--session-name", required=True )
    parser.add_argument( "--headless", action="store_true" )
    parser.add_argument( "--release",  action="store_true" )
    args = parser.parse_args( argv )

    try:
        directory = dir_fn()
        if args.release:
            release_fn( args.session_name, directory )
            return EXIT_ADMITTED

        verdict = admit_fn(
            args.session_name,
            headless      = args.headless,
            cap_fn        = _live_cap,
            census_fn     = _live_census,
            bridge_lookup = _live_bridge_lookup,
            directory     = directory,
        )
    except Exception as error:
        stderr.write( f"\n[FLEET-CAP] guard could not run, ALLOWING the launch: {error}\n\n" )
        return EXIT_ADMITTED

    if verdict.get( "admitted" ):
        return EXIT_ADMITTED

    if args.headless:
        stderr.write( f"\n[FLEET-CAP] REFUSING TO LAUNCH: {verdict[ 'reason' ]}\n\n" )
        return EXIT_REFUSED

    stderr.write(
        f"\n[FLEET-CAP] OVER CAP — allowing this INTERACTIVE launch anyway. "
        f"{verdict[ 'reason' ]}\n"
        f"Agent-spawned sessions are being refused right now; yours is not, because a "
        f"cap that locks the operator out of his own terminal cannot be undone from "
        f"inside it.\n\n"
    )
    return EXIT_ADMITTED


if __name__ == "__main__":                                # pragma: no cover - entry point
    sys.exit( main() )
