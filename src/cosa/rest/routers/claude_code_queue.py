"""
The two retired Claude Code submission doors.

This module used to submit Claude Code tasks to the CJ Flow queue. It now holds two
tombstones: `/api/claude-code/submit` (the canonical path) and
`/api/claude-code/queue/submit` (its alias) each stay registered and answer 410 Gone
naming `/api/v2/submit`, which is where that work enters now.

RICK'S RULING, 2026-08-21: *"A Claude code job should absolutely be upgraded and updated
to use the front door submit under V2. Under no circumstances should we allow it to die on
the vine."* The upgrade and the tombstone are the same decision, not opposite ones: the job
keeps running, and the doors that used to build it now say where it runs instead. A door
that quietly 404s teaches a stale caller nothing; one that names its replacement teaches it
the fix.

BOTH PATHS, NOT JUST THE ALIAS. The repo-wide door inventory listed only
`/api/claude-code/queue/submit`. The canonical `/api/claude-code/submit` is the one
CLAUDE.md told the fleet to use, the one the notifications UI posted to, and the one both
smoke tests and the billing probe named — retiring the alias alone would have left the door
everyone actually uses wide open.

WHAT THE CALLER DOES INSTEAD:

    POST /api/v2/submit
    { "command"      : "agent router go to claude code",
      "args"         : { "prompt": "…", "project": "lupin", "task_type": "BOUNDED",
                         "max_turns": 50, "dry_run": false },
      "websocket_id" : "<session id>",
      "scheduled_at" : "2026-08-22T11:00:00-04:00",
      "monopolize"   : false }

`prompt` / `project` / `task_type` / `max_turns` / `dry_run` are arguments to the job, so
they ride in `args`. `websocket_id` / `scheduled_at` / `monopolize` are directives to the
QUEUE — when to run it, whether it runs alone, where to speak — so they stay top-level;
`args` is checked against the command's own argument contract, and no contract names a
scheduling instruction.

NOTHING THIS HANDLER DID IS LOST, and each piece is worth naming because "the new door does
it too" is the claim a tombstone rests on:
  · the job is built by the same `create_agentic_job` this handler called;
  · the id is scoped through the same `user_job_tracker.register_scoped_job`, in the queued
    executor (executor.py) rather than here;
  · `scheduled_at` and `monopolize` land on the job in the factory;
  · the 400s for a token with no uid or email are the 401s `submit` already raises;
  · the `task_type` validation — the ONE thing `submit` does not do, because it checks that
    a command's required arguments are PRESENT, not which values they may take — moved into
    `ClaudeCodeJob.__init__`, where it also covers the voice path and the in-process
    callers rather than one endpoint.

The bodies are DELETED rather than left unreachable under a raise: unreachable code is code
nobody can test and everybody must still read. Recover them from git if any of their
handling turns out to be worth carrying into the flow.

The request and response models went with them. They described a body nothing accepts any
more, and a Pydantic model no route reads is a shape a caller can still find and reasonably
believe in.

Generated on: 2026-01-27; URL canonicalized 2026-05-11; retired 2026-08-21.
"""

from fastapi import APIRouter

from cosa.rest.routers._retired_doors import gone, tombstone_description

router = APIRouter( tags=[ "claude-code-queue" ] )


# ═══════════════════════════════════════════════════════════════════════════════
# Endpoints — retired
# ═══════════════════════════════════════════════════════════════════════════════

# TWO STUBS, NOT ONE DECORATED TWICE. The live handler carried both paths on a single
# function and told them apart by reading `request.url.path`. A tombstone must name ITS OWN
# path in its refusal, and `refusal_detail` raises KeyError on a path that is not in the
# table — so one shared stub would either have to re-read the request or risk naming the
# wrong door. Two stubs say it once each, and `/docs` gets the right description per route.

@router.post(
    "/api/claude-code/submit",
    deprecated  = True,
    status_code = 410,
    summary     = "GONE — use /api/v2/submit",
    description = tombstone_description( "/api/claude-code/submit" )
)
async def submit_claude_code_to_queue():
    """
    Refuse the canonical retired door with 410 Gone.

    Ensures:
        - never returns; raises HTTPException( 410 ) naming /api/v2/submit and the
          REMOVE BY 2026-12-31 date
    """
    gone( "/api/claude-code/submit" )


@router.post(
    "/api/claude-code/queue/submit",
    deprecated  = True,
    status_code = 410,
    summary     = "GONE — use /api/v2/submit",
    description = tombstone_description( "/api/claude-code/queue/submit" )
)
async def submit_claude_code_to_queue_alias():
    """
    Refuse the alias retired door with 410 Gone.

    Ensures:
        - never returns; raises HTTPException( 410 ) naming /api/v2/submit and the
          REMOVE BY 2026-12-31 date
    """
    gone( "/api/claude-code/queue/submit" )
