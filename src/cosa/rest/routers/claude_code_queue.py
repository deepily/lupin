"""
The two retired Claude Code submission doors.

This module used to submit Claude Code tasks to the CJ Flow queue. It now holds two
tombstones: `/api/claude-code/submit` (the canonical path) and
`/api/claude-code/queue/submit` (its alias). Each stays registered and answers 410 Gone,
naming `/api/v2/submit`, which is where that work enters now.

A Claude Code job is upgraded to use the front door `submit` under v2. It is not allowed to
die on the vine. The upgrade and the tombstone are the same decision. The job keeps running,
and the old doors say where it runs now. A door that quietly 404s teaches a stale caller
nothing. One that names its replacement teaches it the fix.

Both paths are retired, not just the alias. The canonical path is the one CLAUDE.md told
the fleet to use and the notifications UI posted to. Retiring the alias alone would leave
the door everyone uses wide open.

The caller posts to `/api/v2/submit`. The `command` is `agent router go to claude code`.
The job arguments ride in an `args` object. A `scheduled_at` value looks like
`2026-08-22T11:00:00-04:00`.

`prompt`, `project`, `task_type`, `max_turns` and `dry_run` are arguments to the job, so
they ride in `args`. `websocket_id`, `scheduled_at` and `monopolize` are directives to the
queue. They say when to run it, whether it runs alone, and where to speak. They stay
top-level, because no argument contract names a scheduling instruction.

Nothing this handler did is lost. The new door does all of it:
  - the job is built by the same `create_agentic_job` this handler called;
  - the id is scoped through the same `user_job_tracker.register_scoped_job`, in the queued
    executor (`executor.py`) rather than here;
  - `scheduled_at` and `monopolize` land on the job in the factory;
  - the 400s for a token with no uid or email are the 401s `submit` already raises;
  - the `task_type` validation moved into `ClaudeCodeJob.__init__`. `submit` checks that
    required arguments are present, not which values they may take. In `__init__` the check
    also covers the voice path and the in-process callers.

The old bodies are deleted rather than left unreachable under a raise, because unreachable
code is code nobody can test and everybody must still read. The request and response models
went with them. A Pydantic model no route reads is a shape a caller can still believe in.
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
          `REMOVE BY` date from `REMOVE_BY`
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
          `REMOVE BY` date from `REMOVE_BY`
    """
    gone( "/api/claude-code/queue/submit" )
