"""
The retired Podcast Generator submission door.

This module used to accept either a research file path or a plain-English description
of one. It resolved the description by fuzzy-matching the user's research documents. It
asked the user which document they meant and what languages and audience they wanted.
Only then did it queue a podcast job. It now holds a single tombstone. The route stays
registered and answers 410 Gone naming `/api/v2/ask`.

The tombstone names `ask` and not `submit`, which every other job-queueing door names.
This door was never submit-shaped. Its description path held a conversation. It could
come back and ask a question, and it could end with "cancelled" because the user declined.
That is what `/api/v2/ask` does and what `/api/v2/submit` refuses to do: submit is for work
whose command and arguments are already decided. Pointing this door at submit would name
the one door that cannot do what this one did.

The Submit Agentic Jobs accordion is retired, and Q&A on `/api/v2/ask` is the entrance.
So the accordion's podcast card is deleted rather than rewired, and asking for a podcast
is asking a question.

The request and response models, the todo-queue and websocket dependencies, the path
guard, `is_research_path`, `match_research_docs` and `get_user_document_selection` went
with the handler. None of it is orphaned work that needs re-homing. The ask flow runs the
Runtime Argument Expeditor, which owns document resolution (`fuzzy_file_match`) and
missing-argument collection. It asks its questions on the same notification-answer
surface this endpoint used.

The INI flag `podcast card uses runtime argument expeditor` went too. It gated which
resolver this handler used, its own or the expeditor's. This module was its only reader,
so with the handler gone the flag reads nothing. It is removed from `lupin-app.ini` and the
splainer. A configuration key that no longer changes any behaviour is worse than no key,
because someone will flip it and conclude the system ignored them.

What a caller sends instead:

    POST /api/v2/ask
    { "question": "make a podcast from my research on AI safety, in English and Spanish" }
"""

from fastapi import APIRouter

from cosa.rest.routers._retired_doors import gone, tombstone_description
import cosa.utils.util as cu


router = APIRouter(
    prefix="/api/podcast-generator",
    tags=[ "podcast-generator" ]
)


# ═══════════════════════════════════════════════════════════════════════════════
# Job Submission Endpoint — retired
# ═══════════════════════════════════════════════════════════════════════════════

# ── TOMBSTONE — /api/podcast-generator/submit ──
#
# THE ONE THING A READER OF THIS FILE SHOULD CARRY AWAY. This door was counted as one of
# the nine plain submit-shaped doors for most of a day, and it was not one. Reading the
# route name and the inventory row said "submit"; reading the handler said otherwise —
# Flow B ran an interactive expeditor that asked the user questions and could return
# "cancelled". Two of the nine doors turned out not to be what the inventory said they
# were, and both times the way to find out was to read the handler.
#
# The body is DELETED rather than left unreachable under a raise: unreachable code is code
# nobody can test and everybody must still read. Recover it from git if any of its handling
# turns out to be worth carrying into the flow.
@router.post(
    # The router carries a prefix, so the decorator takes the tail while the two
    # tombstone helpers take the full path the table is keyed on — a decorator given
    # the full path here would mount it TWICE-prefixed and the door would answer 404,
    # which is the one thing a tombstone must never do.
    "/submit",
    deprecated  = True,
    status_code = 410,
    summary     = "GONE — use /api/v2/ask",
    description = tombstone_description( "/api/podcast-generator/submit" )
)
async def submit_podcast_job():
    """
    Refuse this retired door with 410 Gone.

    Ensures:
        - never returns; raises HTTPException( 410 ) naming /api/v2/ask and the
          remove-by date
    """
    gone( "/api/podcast-generator/submit" )


def quick_smoke_test():
    """Quick smoke test for podcast_generator router."""
    cu.print_banner( "Podcast Generator Router Smoke Test", prepend_nl=True )

    try:
        print( "Testing module import..." )
        from cosa.rest.routers.podcast_generator import router
        print( "  PASS" )

        print( "Testing router configuration..." )
        assert router.prefix == "/api/podcast-generator"
        assert "podcast-generator" in router.tags
        print( f"  Prefix: {router.prefix}" )
        print( "  PASS" )

        # The door is a tombstone, mounted ONCE at the path the table is keyed on. The
        # router carries a prefix, so a decorator handed the full path would mount it
        # twice-prefixed and the door would answer 404 — the one answer a tombstone must
        # never give.
        print( "Testing the retired route..." )
        from cosa.rest.routers._retired_doors import RETIRED_DOORS, V2_ASK
        paths = { route.path for route in router.routes }
        assert paths == { "/api/podcast-generator/submit" }, f"mounted at {paths}"
        assert RETIRED_DOORS[ "/api/podcast-generator/submit" ] == V2_ASK
        print( "  PASS" )

        print( "\nAll Podcast Generator Router smoke tests passed" )

    except Exception as e:
        print( f"\nSmoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
