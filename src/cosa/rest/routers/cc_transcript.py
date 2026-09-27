#!/usr/bin/env python3
"""
CC transcript console — the REST half: the backlog door and the watchable-seat roster.

Plan: `src/rnd/v0.2.1/2026.09.27-console-tee-live-stream-plan.md` §2 item 4, §3.
Names per ruling OSQ-6. ACs A2.2 · A2.4 · A2.9 · A3.4 · A3.6 · A3.7.

Endpoints:
    - GET /api/cc-transcript/{cc_session_id} — backlog and gap repair, three directions
    - GET /api/cc-transcript-roster          — the watchable-seat roster

WHY THE ROSTER IS A SIBLING PATH AND NOT `/api/cc-transcript/roster`
--------------------------------------------------------------------
A literal segment under the same prefix collides with `{cc_session_id}`: FastAPI would match
`/api/cc-transcript/roster` against the parameterised route too, and which one wins depends on
DECLARATION ORDER. That resolves correctly today and breaks silently the first time someone
reorders the decorators — and the symptom is a roster request answered as a lookup for a seat
literally named "roster", i.e. an empty transcript rather than an error. A sibling path cannot
collide at all, so the hazard is designed out rather than guarded.

🔴 ADMIN ONLY, AND THE TWO SURFACES USE TWO DIFFERENT GATES
-----------------------------------------------------------
Ruling Q5: admin only, no redaction in v1. These REST routes use `require_admin`; the WebSocket
verbs use `websocket_manager.session_is_admin[ session_id ]`. They are different mechanisms, so
a test exercising one proves NOTHING about the other, and a criterion naming only one is
satisfiable by a gate that refuses everybody.

⚠️ The positive admin arm is proved at the OVERRIDE tier, not against the live auth stack: the
only admin accounts are `admin@lupin.deepily.ai` and Rick's own, and the fleet holds neither
password, so no test in this repo has ever watched an admin write SUCCEED — only a non-admin
fail. Rick ruled 2026-09-27 that v1 ships on the `dependency_overrides[ require_admin ]`
positive arm, with a dev-only test admin account as a separate follow-up. That proves the route
WIRING, not the live gate. Stated, never rounded down to "tested".

🔴 THE ROSTER IS A PROJECTION, AND ITS GATE IS ITS OWN
------------------------------------------------------
`/api/arbiter/fleet-state` is guarded by `require_api_key_or_jwt`, which is LOOSER than admin.
The console is admin-only, so this projection carries its own `require_admin` rather than
inheriting fleet-state's. Assert against the projection, never against `/arbiter/fleet-state`.

AND AN UNREACHABLE ARBITER IS NOT AN EMPTY FLEET. `/arbiter/fleet-state` answers HTTP 200 with
`{"status": "unreachable", ...}` when `:8001` is down — the proxy is up, the upstream is not. A
projection that mapped that to `[]` would report a healthy, empty fleet, and nobody would go
looking for the arbiter (A3.7).
"""

from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query

from cosa.rest.auth_middleware import require_admin
from cosa.rest.cc_transcript_tailer import (
    epoch_for_path,
    load_settings,
    read_backlog,
    resolve_transcript_path,
)

router = APIRouter( prefix="/api", tags=[ "cc-transcript" ] )


@router.get(
    "/cc-transcript-roster",
    summary     = "Watchable-seat roster for the CC transcript console (admin)",
    description = "A projection of /api/arbiter/fleet-state carrying `project`, `last_ts` and "
                  "`transcript_watchable` per seat. Admin-gated IN ITS OWN RIGHT — fleet-state's "
                  "own gate (require_api_key_or_jwt) is looser, and the console is admin-only "
                  "(ruling Q5). An unreachable arbiter is reported as unreachable, never as an "
                  "empty fleet."
)
async def get_cc_transcript_roster(
    admin_user: Annotated[ Dict, Depends( require_admin ) ]
):
    """
    Project the fleet roster, marking which seats can actually be watched.

    Requires:
        - the caller holds the admin role (enforced by require_admin, not by this body)

    Ensures:
        - returns { status, seats[], session_count }, each seat carrying `session_id`,
          `project`, `last_ts` and `transcript_watchable`
        - `status` is "unreachable" with an empty seat list when :8001 cannot be reached —
          DISTINGUISHABLE from a genuinely empty fleet, which returns status "ok" (A3.7)
        - `transcript_watchable` is False for a seat with no live transcript file
        - never raises: an unreadable roster degrades to the unreachable envelope
    """
    state = await _fetch_fleet_state()

    if not isinstance( state, dict ) or state.get( "status" ) == "unreachable":
        return {
            "status"        : "unreachable",
            "detail"        : ( state or { } ).get( "detail" ) if isinstance( state, dict ) else None,
            "seats"         : [ ],
            "session_count" : 0,
        }

    return {
        "status"        : "ok",
        "seats"         : _project_seats( _sessions_of( state ) ),
        "session_count" : len( _sessions_of( state ) ),
    }


@router.get(
    "/cc-transcript/{cc_session_id}",
    summary     = "CC transcript backlog and gap repair (admin)",
    description = "Serves display blocks from a seat's transcript in ONE OF THREE DIRECTIONS. "
                  "`tail_bytes` reads BACKWARD from the end of the file — the open, per ruling "
                  "Q6, which a forward-only contract cannot express. `before_offset` pages "
                  "backward from a known offset (load-earlier). `since_offset` reads forward "
                  "(gap repair). Every offset lands on a complete-line boundary. "
                  "`cc_session_id` is the seat's stable_session_id, the FULL id that survives a "
                  "/clear — never the 8-character form used elsewhere in the fleet."
)
async def get_cc_transcript(
    cc_session_id : str,
    admin_user    : Annotated[ Dict, Depends( require_admin ) ],
    tail_bytes    : Optional[ int ] = Query( default=None, ge=0,
                                             description="Read the LAST N bytes (backward). Omit N or pass 0 for the whole file." ),
    before_offset : Optional[ int ] = Query( default=None, ge=0,
                                             description="Page BACKWARD from this offset — 'load earlier'." ),
    since_offset  : Optional[ int ] = Query( default=None, ge=0,
                                             description="Read FORWARD from this offset — gap repair." ),
    max_bytes     : int             = Query( default=0, ge=0,
                                             description="Bound the window. 0 means unbounded." ),
):
    """
    Serve one window of a seat's transcript as display blocks.

    Requires:
        - the caller holds the admin role
        - cc_session_id is a seat's stable_session_id
        - at most one direction is meaningful; they are honoured in the order
          tail_bytes -> before_offset -> since_offset

    Ensures:
        - returns { cc_session_id, file_epoch, offset, next_offset, blocks }
        - with NO direction given, defaults to the ruled backlog tail
          (`cc transcript backlog tail bytes`) — the open case, which is what a client with no
          prior offset actually wants; defaulting to a forward read from 0 would hand it the
          START of a 197 KB file and silently contradict ruling Q6
        - a seat with no resolvable transcript returns empty blocks with a null epoch and
          `watchable: false` — a 200, because "this seat is not printing" is an answer
        - blocks are budgeted per `cc transcript block budget bytes`; 0 means UNBOUNDED
    """
    settings        = load_settings()
    transcript_path = resolve_transcript_path( cc_session_id )

    if not transcript_path:
        return {
            "cc_session_id" : cc_session_id,
            "file_epoch"    : None,
            "offset"        : 0,
            "next_offset"   : 0,
            "blocks"        : [ ],
            "watchable"     : False,
        }

    # No direction named means "open the pane", which ruling Q6 defines as the LAST ~64 KB.
    if tail_bytes is None and before_offset is None and since_offset is None:
        tail_bytes = settings[ "backlog_tail_bytes" ]

    body = read_backlog(
        transcript_path,
        tail_bytes    = tail_bytes,
        before_offset = before_offset,
        since_offset  = since_offset,
        max_bytes     = max_bytes,
        budget        = settings[ "block_budget_bytes" ],
    )
    body[ "cc_session_id" ] = cc_session_id
    body[ "watchable" ]     = True
    return body


# ── helpers ───────────────────────────────────────────────────────────────────

async def _fetch_fleet_state():
    """
    Read the fleet composite, reusing the arbiter router's own handler.

    Calling the handler rather than re-implementing the `:8001` pull keeps ONE place that knows
    the upstream URL, the timeout and the unreachable envelope's shape. A second implementation
    would be a second thing to keep in step, and the two would agree until they did not.

    Ensures:
        - returns the composite dict, or the arbiter's own unreachable envelope
        - returns an unreachable envelope rather than raising if the call fails outright
    """
    try:
        from cosa.rest.routers.arbiter import get_fleet_state
        return await get_fleet_state( authenticated_user_id="cc-transcript-roster" )
    except Exception as e:
        return { "status": "unreachable", "detail": f"{type( e ).__name__}: {e}" }


def _sessions_of( state ):
    """
    Pull the session list out of the fleet composite.

    The composite nests the roster under `fleet_arbiter`, and that section is None on the
    awaiting/unreachable envelopes.

    Ensures:
        - returns a list, never None — an absent or malformed section reads as no sessions
    """
    fleet = state.get( "fleet_arbiter" )
    if not isinstance( fleet, dict ): return [ ]
    sessions = fleet.get( "sessions" )
    return sessions if isinstance( sessions, list ) else [ ]


def _project_seats( sessions ):
    """
    Project each fleet session into a roster row for the console.

    Requires:
        - sessions is a list of fleet-session dicts

    Ensures:
        - returns one row per dict session, carrying session_id, project, last_ts and
          transcript_watchable
        - `session_id` is carried through at the SAME WIDTH the fleet reports, because the
          roster join depends on it matching the stream's `cc_session_id` exactly (A3.6).
          Three id widths circulate in this fleet, and a silent mismatch shows up as a roster
          row that cannot be watched
        - a non-dict entry is skipped rather than crashing the roster
    """
    rows = [ ]
    for session in sessions:
        if not isinstance( session, dict ): continue

        session_id      = session.get( "stable_session_id" ) or session.get( "session_id" ) or ""
        transcript_path = resolve_transcript_path( session_id ) if session_id else ""

        rows.append( {
            "session_id"           : session_id,
            "persona"              : session.get( "persona" ) or session.get( "persona_name" ),
            "project"              : session.get( "project" ),
            "last_ts"              : session.get( "last_ts" ) or session.get( "last_seen" ),
            "transcript_watchable" : bool( transcript_path ),
            "file_epoch"           : epoch_for_path( transcript_path ) or None,
        } )
    return rows
