"""
The retired queue doors, and the one refusal they all share.

RICK'S RULING, 2026-08-21: *"They should be gone permanently with the new door named
in the error message. Also we should tag each of those disabled doors with an
expiration date. By the end of 2026 they should be gone. Say it loud and say it
proud — dead by the end of the year."*

TWO DOORS ARE HERE, NOT SIXTEEN — AND THE REASON IS THE WHOLE POINT OF THIS FILE.
Eighteen doors put work on the queue. Two survive (`/api/v2/ask`, `/api/v2/submit`),
one more survives alongside them (`/api/v2/resume`), and sixteen die. But
`/api/v2/submit` HAS NOT BEEN BUILT YET — at this commit `v2_ask.py` mounts `ask` and
`resume` and nothing else. Retiring the twelve submit-shaped doors now would point
twelve refusals at a route that answers 404, which teaches a caller strictly less than
the 500 it replaced. So this commit retires only the doors whose replacement actually
answers, and the rest follow the commit that builds `submit`.
(Cheech's ruling, 2026-08-21: *"a 410 that names a door that does not exist yet is a
refusal pointing at nothing."*)

WHY 410 AND NOT 404. A tombstone, deliberately. A deleted route is invisible, and
nothing would stop someone re-adding `/api/podcast-generator/submit` next year
because the product needs it. 410 Gone says the path existed, was retired on
purpose, and names its replacement — so a caller reading the failure learns the fix
instead of filing a bug.

WHY THE DATE IS IN THE MESSAGE AND NOT ONLY IN A COMMENT. A comment is read by
whoever opens this file. The callers that still hit these paths live in two
separately-managed repos (`src/lupin-mobile`, `src/lupin-plugin-firefox`) whose
owners will never open it. The refusal itself has to carry the date.

WHY NO AUTH DEPENDENCY ON A TOMBSTONE. An unauthenticated caller must learn the same
thing an authenticated one does. If the stub kept `Depends( get_current_user )` the
answer to a stale client would be 401 — which teaches nobody anything and reads like
a credentials problem.

Source of the door list: Chloé's repo-wide inventory,
`src/rnd/v0.2.0/2026.08.21-cascade-resume-artifacts/2026.08.21-queue-entry-point-inventory-corrected.md`,
each path re-resolved from its `APIRouter` prefix at build time rather than copied.
"""

from fastapi import HTTPException


# The date, stated once. It appears in every refusal body.
REMOVE_BY = "2026-12-31"

V2_ASK    = "/api/v2/ask"
V2_SUBMIT = "/api/v2/submit"


# path -> the door that replaces it.
#
# BOTH ARE QUESTION-SHAPED, which is why both can retire today. `/api/push` takes a
# bare question; `/api/job-history/{job_id}/retry` pulls `question_text` off a stored
# row and calls `push_job` with it (queues.py, comment: "the same pattern as POST
# /api/push"). A bare question is exactly what `/api/v2/ask` takes, and `ask` is live.
# Everything else hands over work whose command is already decided — that is what
# `submit` means, and it waits for `submit` to exist.
#
# (Door 5 pointed at `submit` in the first draft of this table — Rio caught it by
# reading the handler instead of the route name.)
#
# 🔴 `/api/upload-and-transcribe-mp3` WAS IN THIS TABLE AND CAME BACK OUT, 2026-08-21.
# The inventory classified it as question-shaped because its tail calls `push_job`. Read
# the handler and that is only half true: it accepts base64 MP3, transcribes it with
# Whisper, runs the result through MultiModalMunger, and queues ONLY on the
# `munger.is_agent()` branch — otherwise it returns the transcription to the caller and
# queues nothing (speech.py at HEAD). It is a speech-to-text endpoint whose agent branch
# happens to queue. `/api/v2/ask` takes text and cannot accept audio, so retiring this
# route would take browser dictation, the admin snapshot search, and the multiplexer's
# insert-at-cursor down with it and offer them nothing. Only its queueing TAIL belongs
# to `ask`; that is a separate piece of work on the route itself, not a tombstone.
#
# ✅ THAT WORK IS DONE (door 8, 2026-08-21) AND THE ROUTE STILL SURVIVES. Its
# `munger.is_agent()` branch hands the transcription to the v2 ask flow in-process and
# refuses without a signed-in user; the other branch is untouched and still needs no
# token. Rick's framing: there are two ways to ask — post your text, or speak. Both end
# up at the same flow. Keep this path OUT of the table.
#
# ── THE SUBMIT-SHAPED DOORS START ARRIVING (11b) ──
#
# `/api/v2/submit` exists now, and — this is the part worth stating, because it was very
# nearly not true — it can BUILD what these doors hand over. `resolve()` is scoped to the
# conversational class and returns None for every agentic command, so `submit` reached the
# receptionist for all of them until the agentic reader was wired in. A tombstone pointing
# at a door that answers "I do not understand" teaches a caller less than the handler it
# replaced, which is the same mistake as pointing at a 404, one layer deeper.
#
# 🔴 `/api/mock-job/submit` IS NOT HERE, AND NOT BY OVERSIGHT. Its command exists nowhere:
# there is no "mock job" entry in JOB_ARG_CONTRACTS and no branch for it in
# `create_agentic_job` — the router builds `MockAgenticJob` itself (mock_job.py:170). So
# `submit` cannot build one, and retiring that door would point its refusal at a door that
# refuses back. It waits for a mock-job command, or it stays (Cheech, 2026-08-21: a
# test-harness door with test-only callers does not justify teaching the registry a
# mock-job command tonight).
#
# Also still out, each for its own stated reason: the two resume-from doors
# (`/api/jobs/{id_hash}/resume-from-checkpoint`, `/api/test-fix-expediter/resume-from`)
# rebuild a job from server-side state, and an HTTP `SubmitRequest` can say command and
# args but never "resume job X"; `/api/test-suite/submit` is how the gate rig schedules a
# :8000 run, so it lands last, after that gate is green; and the Claude Code pair is an
# UPGRADE to the v2 door, not a tombstone (Rick).
RETIRED_DOORS = {
    "/api/push"                       : V2_ASK,
    "/api/job-history/{job_id}/retry" : V2_ASK,
    "/api/bug-fix-expediter/submit"   : V2_SUBMIT,
    # ── the research trio, retired together ──
    # One UI function submits to all three: `submitResearchJob` in notifications.js picks
    # between them off two checkboxes. Retiring them one at a time would have meant editing
    # that same function three times, each edit leaving it half cut over.
    "/api/deep-research/submit"                  : V2_SUBMIT,
    "/api/deep-research-to-podcast/submit"       : V2_SUBMIT,
    "/api/deep-research-to-presentation/submit"  : V2_SUBMIT,
    # ── the direct presentation door ──
    # It carried something no other door carried: a path-escape check, and nothing
    # downstream repeated it. Retiring the door first and moving the guard afterwards
    # would have left a window with no check at all, so the guard moved onto the job
    # (presentation_generator/job.py) in its own earlier commit and this row waited for it.
    "/api/presentation-generator/submit"          : V2_SUBMIT,
}



def refusal_detail( path: str ) -> str:
    """
    Build the refusal body for one retired door.

    Requires:
        - path is a key of RETIRED_DOORS (the full route, prefix included)

    Ensures:
        - the string names the replacement door
        - the string contains REMOVE BY <date>, so a caller who only ever sees the
          failure still learns when the tombstone itself disappears

    Raises:
        - KeyError if path is not a retired door — a typo must not produce a
          plausible-looking refusal that names the wrong replacement
    """
    replacement = RETIRED_DOORS[ path ]
    # THE SENTENCE HAS TO MATCH THE DOOR IT NAMES. This read "Every question now enters
    # through …" for every row, which was true while both retired doors were
    # question-shaped and `ask` was the only replacement. Said about `/api/v2/submit` it
    # is simply wrong — submit is the door for work whose command the caller already
    # chose, and telling someone to send a question there sends them to the wrong one of
    # two doors that both exist and both answer.
    entering = ( "Every question now enters through" if replacement == V2_ASK
                 else "Work whose command is already decided now enters through" )
    return (
        f"{path} is GONE. {entering} {replacement}. "
        f"This route is a tombstone that answers 410 and nothing else — "
        f"REMOVE BY {REMOVE_BY}, it is dead by the end of the year."
    )


def gone( path: str ) -> None:
    """
    Refuse one retired door with 410 Gone.

    Requires:
        - path is a key of RETIRED_DOORS

    Ensures:
        - never returns

    Raises:
        - HTTPException( 410 ) whose detail names the replacement door and the
          removal date
    """
    raise HTTPException( status_code=410, detail=refusal_detail( path ) )


def tombstone_description( path: str ) -> str:
    """
    Build the OpenAPI description for one retired door, so `/docs` says the same
    thing the refusal says.

    Requires:
        - path is a key of RETIRED_DOORS

    Ensures:
        - returns a one-line description naming the replacement and the date
    """
    return f"GONE (410). Use {RETIRED_DOORS[ path ]}. REMOVE BY {REMOVE_BY}."

