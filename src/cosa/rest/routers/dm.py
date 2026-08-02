"""
DM API — `/api/dm/<verb>` notification-native AI↔AI direct messaging.

One coherent `/api/dm` namespace whose verb sub-routes each mirror a `dm_<verb>`
cosa-voice MCP tool 1:1. Phase 1 ships `POST /api/dm/send` (the relocated,
renamed legacy peer-DM endpoint); Phase 2 adds the siblings `/respond`, `/get`,
`/list` against the same router.

A peer DM is an ordinary notification carrying the body INLINE with
direction="ai_to_ai" — no commons board, no claim-check, no commons_read
re-fetch. Resolution reuses the commons same-user persona→session resolver;
delivery rides job_id routing to the recipient's cc-listener.

Design:
    src/rnd/v0.1.8/2026.06.16-dm-api-namespace-design.md (namespace)
    src/rnd/v0.1.8/2026.06.13-cosa-voice-token-reduction/02-notification-native-aixai-design.md (send semantics)
"""

from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from typing import Optional, Annotated, Literal
import asyncio
import re
import uuid
from datetime import datetime

# Import dependencies and services
from ..notification_fifo_queue import NotificationFifoQueue
from ..middleware.api_key_auth import require_api_key_or_jwt
from ..db.database import get_db
from ..db.repositories.notification_repository import NotificationRepository
# Central EDT-stamp formatter (2026-06-24): the ONE owner of Rick's bracketed
# outreach prefix "[YYYY.MM.DD at HH:MM:SS]", shared with the arbiter ping path so a
# reader cannot tell a DM's stamp from an arbiter ping's stamp.
from cosa.utils.edt_timestamp import format_edt_timestamp, is_already_stamped
# The notification queue dependency lives with the notifications router; reuse it
# so /api/dm/send pushes onto the same FIFO queue as /api/notify.
from .notifications import get_notification_queue

router = APIRouter( prefix="/api/dm", tags=["dm"] )


class DmSendRequest( BaseModel ):
    """
    POST /api/dm/send request body — notification-native AI↔AI DM.

    The recipient is addressed by persona name (preferred) or explicit session
    id; resolution is same-user scoped. The message body travels INLINE (no
    claim-check). Threading is carried by `reply_to` (the message being answered)
    and `thread_id` (conversation correlation; defaults to a fresh id server-side
    when omitted). `sender_persona`/`sender_icon` carry the SENDER's identity so
    the recipient can frame it as "[DM from <persona> <icon>]".
    """
    sender_session_id    : str             = Field( ..., min_length=1, max_length=128 )
    body                 : str             = Field( ..., min_length=1 )
    recipient_session_id : Optional[ str ] = Field( default=None, min_length=1, max_length=128 )
    recipient_persona    : Optional[ str ] = Field( default=None, min_length=1, max_length=64 )
    sender_persona       : Optional[ str ] = Field( default=None, max_length=64 )
    sender_icon          : Optional[ str ] = Field( default=None, max_length=16 )
    reply_to             : Optional[ str ] = Field( default=None, max_length=64 )
    thread_id            : Optional[ str ] = Field( default=None, max_length=64 )
    # The CALLER's project, for the `sender_id` stamp (row 12b5a766). The server
    # cannot derive it: the host-shaped resolver it used degrades, inside the
    # container, to "what project am I?" — the server's own cwd — which answers
    # "lupin" correctly and for the wrong question. The caller already knows
    # (the MCP resolves it host-side at module load) and now sends it.
    # OPTIONAL BY TRANSITION, NOT BY DESIGN: step 1 accepts an absent value and
    # stamps as before while COUNTING the omission; the flip to a hard reject is
    # step 2, gated on every live MCP process being respawned onto a client that
    # sends it (editing the client does not reach a running one).
    sender_project       : Optional[ str ] = Field( default=None, min_length=1, max_length=64 )


def _persist_dm_send_sync(
    sender_id, recipient_user_id, message, direction,
    sender_persona, sender_icon, reply_to, thread_id, job_id
):
    """
    Synchronous DB persist for a peer DM — run OFF the event loop via
    asyncio.to_thread. The notifications table IS the audit substrate (no commons
    board mirror), so the body + direction + provenance + threading land in
    first-class columns.

    Requires:
        - recipient_user_id is a UUID string (same-user scoping → the sender's user)

    Ensures:
        - creates the Notification row with direction='ai_to_ai' + DM fields
        - returns the new notification id (str)

    Raises:
        - propagates DB errors to the caller (handled there as non-fatal)
    """
    with get_db() as session:
        repo = NotificationRepository( session )
        db_notification = repo.create_notification(
            sender_id      = sender_id,
            recipient_id   = uuid.UUID( recipient_user_id ),
            message        = message,
            type           = "user_initiated_message",
            priority       = "medium",
            job_id         = job_id,
            direction      = direction,
            sender_persona = sender_persona,
            sender_icon    = sender_icon,
            reply_to       = reply_to,
            thread_id      = thread_id,
        )
        return str( db_notification.id )


# ─────────────────────────────────────────────────────────────────────────────
# Un-projected-DM audit (row 12b5a766, step 1 of 2)
#
# Step 2 flips an absent `sender_project` from accepted-and-stamped-as-before to
# rejected. That flip must be a MEASUREMENT, not a guess about who has respawned
# — so every DM that reaches the stamp is counted on both sides of the seam, and
# the audit line ALWAYS prints both numbers.
#
# PRINTING THE ZERO IS THE POINT. A log that says nothing when no un-projected
# DM arrives is indistinguishable from a log that was never wired, and the
# second one reads as reassuring. `un_projected=0` has to be a line somebody can
# read before the flip.
# ─────────────────────────────────────────────────────────────────────────────

_dm_project_audit = {
    "projected"            : 0,
    "un_projected"         : 0,
    "un_projected_senders" : [],
    "since"                : datetime.now().isoformat( timespec="seconds" ),
}

# Cap on distinct remembered offender sessions — the audit is a liveness signal
# for one flip decision, not an unbounded log. Overflow is reported by the count,
# which keeps rising, so a truncated sender list never reads as a smaller problem.
_DM_AUDIT_SENDER_CAP = 50


def reset_dm_project_audit():
    """
    Reset the un-projected-DM counters and re-stamp the `since` instant.

    Ensures:
        - both counters are 0, the sender list is empty, `since` is now
        - callers (tests, an operator re-baselining before a respin) get a clean
          window whose start is explicit rather than implied
    """
    _dm_project_audit[ "projected" ]            = 0
    _dm_project_audit[ "un_projected" ]         = 0
    _dm_project_audit[ "un_projected_senders" ] = []
    _dm_project_audit[ "since" ]                = datetime.now().isoformat( timespec="seconds" )


def get_dm_project_audit():
    """
    Snapshot of the un-projected-DM audit.

    Ensures:
        - returns a COPY (the sender list included), so a reader cannot mutate
          the live counters by holding the result
    """
    snapshot = dict( _dm_project_audit )
    snapshot[ "un_projected_senders" ] = list( _dm_project_audit[ "un_projected_senders" ] )
    return snapshot


def format_dm_project_audit_line():
    """
    One readable line carrying BOTH counts — including the zeros.

    Ensures:
        - contains `projected=<n>` and `un_projected=<n>` unconditionally
        - names the window start, so "0 un-projected" is scoped to a period
          rather than to all of history
    """
    return (
        f"[dm-project-audit] since {_dm_project_audit[ 'since' ]}: "
        f"projected={_dm_project_audit[ 'projected' ]} "
        f"un_projected={_dm_project_audit[ 'un_projected' ]} "
        f"offenders={len( _dm_project_audit[ 'un_projected_senders' ] )}"
    )


def _make_sender_id_builder( host_builder ):
    """
    Adapt the host-shaped `build_sender_id_for_cc` into the two-argument seam
    `execute_dm_send` calls.

    When the caller SENT its project, the stamp is built from that project
    directly — `build_sender_id_for_cc` is never consulted, because its whole
    resolution chain answers "what project is THIS PROCESS in?" and this process
    is the server. When the caller sent nothing, the host builder runs exactly as
    it does today (the step-1 transition contract).

    Requires:
        - host_builder( session_id ) -> sender_id str (the legacy 1-arg helper)

    Ensures:
        - returns a callable ( session_id, project=None ) -> sender_id str
        - a supplied project produces `claude.code@<project>.deepily.ai#<sid>`
          via the SHARED build_sender_id formatter — never a locally-formatted
          string, so the one format stays owned in one place
        - an absent project delegates to host_builder unchanged
    """
    from cosa.agents.utils.sender_id import build_sender_id as _build_sender_id

    def _build( session_id, project=None ):
        if project is None:
            return host_builder( session_id )
        return _build_sender_id( "claude.code", project=project, suffix=session_id )

    return _build


# ─────────────────────────────────────────────────────────────────────────────
# DM length audit (Phase 1 of the DM Verbosity Reduction plan, Rick 2026-07-31 —
# src/rnd/v0.1.9/2026.07.31-dm-verbosity-reduction/). Kept as a SEPARATE sibling
# counter rather than merged into `_dm_project_audit` above — different concern
# (this measures body length, not the sender_project gate), and merging would
# confuse that audit's own step-2 story.
#
# Deliberately does NOT tag rows by experiment arm (on/off toggle) — fragile if
# control and treatment sessions ever overlap in time on one server. Instead:
# snapshot `/api/dm/length-audit` before and after each arm's run; `since`
# scopes each window exactly like the project-audit already does.
# ─────────────────────────────────────────────────────────────────────────────

_dm_length_audit = {
    "count"           : 0,
    "total_chars"     : 0,
    "total_words"     : 0,
    "total_sentences" : 0,
    "since"           : datetime.now().isoformat( timespec="seconds" ),
}

# Sentence boundary: one or more .!? followed by whitespace or end-of-string.
# Deliberately simple (no NLP/abbreviation handling) — this is a verbosity
# SIGNAL for an A/B comparison, not a linguistically exact sentence splitter.
# A body with no terminal punctuation ("status?") still counts as 1 sentence
# (a bare fragment), never 0, so a short DM doesn't read as "no content."
_SENTENCE_SPLIT_RE = re.compile( r'[.!?]+(?:\s+|$)' )


def _count_sentences( body_text ):
    """
    Count sentence-like chunks in body_text via a simple .!? split.

    Requires:
        - body_text is a string

    Ensures:
        - returns 0 only for a blank/whitespace-only string
        - returns 1 for a fragment with no terminal punctuation
        - returns the count of non-empty chunks otherwise
    """
    chunks = [ c for c in _SENTENCE_SPLIT_RE.split( body_text ) if c.strip() ]
    return len( chunks )


def reset_dm_length_audit():
    """
    Reset the DM length-audit counters and re-stamp the `since` instant.

    Ensures:
        - count, total_chars, total_words, total_sentences are all 0, `since` is now
    """
    _dm_length_audit[ "count" ]           = 0
    _dm_length_audit[ "total_chars" ]     = 0
    _dm_length_audit[ "total_words" ]     = 0
    _dm_length_audit[ "total_sentences" ] = 0
    _dm_length_audit[ "since" ]           = datetime.now().isoformat( timespec="seconds" )


def get_dm_length_audit():
    """
    Snapshot of the DM length audit, with derived averages.

    Ensures:
        - returns a COPY (a reader cannot mutate the live counters by holding it)
        - includes avg_chars / avg_words / avg_sentences, all 0.0 (never
          divide-by-zero) when count is 0
    """
    snapshot = dict( _dm_length_audit )
    count = snapshot[ "count" ]
    snapshot[ "avg_chars" ]     = ( snapshot[ "total_chars" ]     / count ) if count else 0.0
    snapshot[ "avg_words" ]     = ( snapshot[ "total_words" ]     / count ) if count else 0.0
    snapshot[ "avg_sentences" ] = ( snapshot[ "total_sentences" ] / count ) if count else 0.0
    return snapshot


def format_dm_length_audit_line():
    """
    One readable line carrying the running count and averages.

    Ensures:
        - contains `count=<n>`, `avg_chars=<f>`, `avg_words=<f>`, `avg_sentences=<f>`
          unconditionally
        - names the window start, same convention as format_dm_project_audit_line
    """
    audit = get_dm_length_audit()
    return (
        f"[dm-length-audit] since {_dm_length_audit[ 'since' ]}: "
        f"count={audit[ 'count' ]} "
        f"avg_chars={audit[ 'avg_chars' ]:.1f} "
        f"avg_words={audit[ 'avg_words' ]:.1f} "
        f"avg_sentences={audit[ 'avg_sentences' ]:.1f}"
    )


def _record_dm_length( body_text ):
    """
    Count one dm_send body's length (Phase 1 DM Verbosity Reduction A/B).

    Requires:
        - body_text is the caller-supplied DM body string

    Ensures:
        - measures body_text AS SUPPLIED, before any timestamp/frame prefix is
          added elsewhere in the send path, so constant per-DM overhead never
          pollutes the arm-to-arm delta
        - increments count, total_chars, total_words, total_sentences
        - emits one audit line (same convention as _record_dm_project)
    """
    _dm_length_audit[ "count" ]           += 1
    _dm_length_audit[ "total_chars" ]     += len( body_text )
    _dm_length_audit[ "total_words" ]     += len( body_text.split() )
    _dm_length_audit[ "total_sentences" ] += _count_sentences( body_text )
    print( format_dm_length_audit_line() )


# ─────────────────────────────────────────────────────────────────────────────
# DM quality audit + judge (Phase 2 of the DM Verbosity Reduction plan, Rick
# 2026-07-31). A sibling counter to _dm_length_audit above, on a SECOND axis: it
# tallies the DM Quality Judge's grade weights (length/directness/tone/overall)
# fleet-wide, aggregate only (no persona split). It accumulates ONLY during
# TREATMENT windows — the judge runs only when `dm quality judgment enabled` is
# True — so its own `since`/`count` naturally scope it; no toggle-awareness is
# built into the counter itself.
# ─────────────────────────────────────────────────────────────────────────────

_dm_quality_audit = {
    "count"                   : 0,
    # Grades whose qualitative half carried a REAL weight. Separate from `count`
    # because LENGTH-ONLY mode (Rick, 2026-08-01) returns weight None for
    # Directness/Tone, and a None must not be averaged as if it were a 0 — that
    # is the same non-answer-in-the-answer's-value-space defect this package
    # spent the day on, just moved into the audit counter.
    "qualitative_count"       : 0,
    "total_length_weight"     : 0,
    # Sum of the Length grade's `overage` ratio (words / target). Tracked BESIDE the
    # weight, never instead of it: `total_length_weight` saturates because the grade
    # saturates — a 251-word DM and a 1000-word DM both contribute -2, so avg_length
    # has a floor it silently hits and "are DMs getting worse?" stops being answerable
    # past that point. The ratio has no ceiling, so avg_overage keeps moving (row
    # 0fc5b8f0).
    "total_overage"           : 0.0,
    "total_directness_weight" : 0,
    "total_tone_weight"       : 0,
    "total_overall_weight"    : 0,
    "since"                   : datetime.now().isoformat( timespec="seconds" ),
}

# Lazily-built judge singleton — one client per process, built on the first
# TREATMENT send only, so a control-only server never pays to construct it.
_dm_quality_judge = None


def get_dm_quality_judgment_enabled():
    """
    Resolve the `dm quality judgment enabled` toggle from lupin-app.ini at call
    time — runtime-tunable, same precedent as the cosa-voice spoken-char-cap read.

    Ensures:
        - returns True only when the ini key is explicitly True
        - returns False if the key is absent or on any config-read error (the
          safe CONTROL default) — never raises
    """
    from cosa.config.configuration_manager import ConfigurationManager
    try:
        config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
        return config_mgr.get( "dm quality judgment enabled", default=False, return_type="boolean" )
    except Exception:
        return False


def reset_dm_quality_audit():
    """Reset the DM quality-audit counters and re-stamp the `since` instant."""
    _dm_quality_audit[ "count" ]                   = 0
    _dm_quality_audit[ "qualitative_count" ]       = 0
    _dm_quality_audit[ "total_length_weight" ]     = 0
    _dm_quality_audit[ "total_overage" ]           = 0.0
    _dm_quality_audit[ "total_directness_weight" ] = 0
    _dm_quality_audit[ "total_tone_weight" ]       = 0
    _dm_quality_audit[ "total_overall_weight" ]    = 0
    _dm_quality_audit[ "since" ]                   = datetime.now().isoformat( timespec="seconds" )


def get_dm_quality_audit():
    """
    Snapshot of the DM quality audit, with derived average weights.

    Ensures:
        - returns a COPY (a reader cannot mutate the live counters by holding it)
        - includes avg_length/avg_directness/avg_tone/avg_overall, all 0.0 (the
          same `if count else 0.0` divide-by-zero guard as get_dm_length_audit)
          when count is 0
        - avg_directness/avg_tone divide by qualitative_count, NOT count. In
          LENGTH-ONLY mode qualitative_count stays 0 and both read 0.0 — a
          "nothing was graded" zero, which is why qualitative_count ships in
          the snapshot: a reader can tell it from a real average of zero
        - includes avg_overage, the mean words-to-target ratio. UNLIKE avg_length it
          has no floor, so it still moves when traffic is dominated by DMs past the
          -2 saturation point — which is precisely the population this feature aims at
    """
    snapshot = dict( _dm_quality_audit )
    count    = snapshot[ "count" ]
    qual     = snapshot[ "qualitative_count" ]
    snapshot[ "avg_length" ]     = ( snapshot[ "total_length_weight" ]     / count ) if count else 0.0
    snapshot[ "avg_overall" ]    = ( snapshot[ "total_overall_weight" ]    / count ) if count else 0.0
    snapshot[ "avg_directness" ] = ( snapshot[ "total_directness_weight" ] / qual )  if qual  else 0.0
    snapshot[ "avg_tone" ]       = ( snapshot[ "total_tone_weight" ]       / qual )  if qual  else 0.0
    snapshot[ "avg_overage" ]    = ( snapshot[ "total_overage" ]           / count ) if count else 0.0
    return snapshot


def format_dm_quality_audit_line():
    """
    One readable line carrying the running count and average weights.

    Ensures:
        - contains `count=<n>` and avg_length/avg_directness/avg_tone/avg_overall
          unconditionally, same convention as format_dm_length_audit_line
    """
    audit = get_dm_quality_audit()
    return (
        f"[dm-quality-audit] since {_dm_quality_audit[ 'since' ]}: "
        f"count={audit[ 'count' ]} "
        f"avg_length={audit[ 'avg_length' ]:.2f} "
        f"avg_directness={audit[ 'avg_directness' ]:.2f} "
        f"avg_tone={audit[ 'avg_tone' ]:.2f} "
        f"avg_overall={audit[ 'avg_overall' ]:.2f} "
        f"avg_overage={audit[ 'avg_overage' ]:.1f}x"
    )


def _record_dm_quality( quality ):
    """
    Tally one judge grade into the quality audit.

    Requires:
        - quality is the dict returned by DmQualityJudge.judge()
          ({"length","directness","tone","overall"}); Length and Overall always
          carry an int weight, Directness and Tone carry an int OR None

    Ensures:
        - increments count + the Length/Overall totals and the overage sum on
          every grade
        - a None Directness/Tone weight (LENGTH-ONLY mode) is SKIPPED, not
          coerced to 0, and does not increment qualitative_count — so the
          qualitative averages stay averages of grades that actually happened
        - emits one audit line (same convention as _record_dm_length)
    """
    _dm_quality_audit[ "count" ]                += 1
    _dm_quality_audit[ "total_length_weight" ]  += quality[ "length" ][ "weight" ]
    _dm_quality_audit[ "total_overall_weight" ] += quality[ "overall" ][ "weight" ]
    # `.get` with a 0.0 default, and this is the ONE place a defensive read is right:
    # a v2 judge on an older code path can hand back a Length dict predating `overage`,
    # and a KeyError here would 500 the SEND over a statistic. The weight above is
    # subscripted directly on purpose — that one is not optional and must fail loud.
    _dm_quality_audit[ "total_overage" ]        += quality[ "length" ].get( "overage", 0.0 )

    directness_weight = quality[ "directness" ][ "weight" ]
    tone_weight       = quality[ "tone" ][ "weight" ]
    if directness_weight is not None and tone_weight is not None:
        _dm_quality_audit[ "qualitative_count" ]       += 1
        _dm_quality_audit[ "total_directness_weight" ] += directness_weight
        _dm_quality_audit[ "total_tone_weight" ]       += tone_weight

    print( format_dm_quality_audit_line() )


def _maybe_grade_dm_quality( body_text ):
    """
    Grade a DM body IFF the DM Quality Judge toggle is ON (treatment arm).

    Requires:
        - body_text is the caller-supplied DM body string

    Ensures:
        - toggle OFF (control, default): returns None — no judge call, no audit
          tally, and execute_dm_send appends NO `quality` field (the Phase 1
          baseline result shape, unchanged)
        - toggle ON (treatment): builds the judge lazily (once per process), grades
          the body, tallies the quality audit, and returns the quality dict
        - never raises: DmQualityJudge.judge itself never raises (a judge that
          cannot even be built still returns a safe all-🤷/0 grade)
    """
    global _dm_quality_judge
    if not get_dm_quality_judgment_enabled():
        return None
    if _dm_quality_judge is None:
        # Go through the factory, not a named class: which implementation runs is
        # `dm quality judge version` (default 1), and keeping that decision in one
        # place means this call site never has to learn about a v3.
        from cosa.agents.dm_quality_judge import get_dm_quality_judge
        _dm_quality_judge = get_dm_quality_judge()
    quality = _dm_quality_judge.judge( body_text )
    _record_dm_quality( quality )
    return quality


def _record_dm_project( sender_session_id, sender_project ):
    """
    Count one DM on whichever side of the caller-supplied-project seam it lands,
    and emit the audit line.

    Requires:
        - sender_session_id is the caller's session id (named in the warning so
          an operator can identify WHICH seat still needs a respawn)
        - sender_project is the caller-supplied project, or None

    Ensures:
        - increments exactly one counter
        - an absent project ALSO prints a warning naming the session and the
          project the stamp will fall back to — accept-and-warn, never silent
        - the remembered offender list holds distinct sessions up to
          `_DM_AUDIT_SENDER_CAP`; the counter keeps rising past the cap
    """
    if sender_project is None:
        _dm_project_audit[ "un_projected" ] += 1
        senders = _dm_project_audit[ "un_projected_senders" ]
        if sender_session_id not in senders and len( senders ) < _DM_AUDIT_SENDER_CAP:
            senders.append( sender_session_id )
        print(
            f"[dm-project-audit] WARNING: DM from session '{sender_session_id}' carried no "
            f"sender_project — stamping from the SERVER's project, which is only correct when "
            f"the caller happens to be a lupin session (row 12b5a766). This caller needs a "
            f"respawn onto a client that sends it."
        )
    else:
        _dm_project_audit[ "projected" ] += 1

    print( format_dm_project_audit_line() )


def execute_dm_send(
    *,
    authenticated_user_id,
    body,
    notification_queue,
    resolve_recipient_fn,
    build_sender_id,
    persist_fn,
    new_id_fn = None,
    now_fn    = None,
    grade_quality_fn = None,
):
    """
    Pure-logic core for POST /api/dm/send — notification-native AI↔AI DM.

    Resolves the recipient (same-user scoped), persists the DM to the
    notifications table (direction='ai_to_ai' + body inline + sender provenance
    + threading), then pushes it to the recipient session's listener via job_id
    routing. No commons board, no claim-check, no watcher.

    The outbound body is prefixed with Rick's central EDT stamp
    "[YYYY.MM.DD at HH:MM:SS] " (2026-06-24) — the SAME bracketed prefix the arbiter
    pings carry, sourced from the shared cosa.utils.edt_timestamp formatter. This is
    the single server-side DM chokepoint (send AND respond reuse this core), so the
    stamp lands on EVERY peer DM in every direction. The arbiter pings ride a
    DISJOINT path (CommonsStore, not /api/dm/send) and are NOT re-stamped here.

    Requires:
        - body is a DmSendRequest
        - resolve_recipient_fn( recipient_session_id, recipient_persona,
          authenticated_user_id ) -> {"http_status":200,"session_id","persona_name"}
          OR {"http_status":422,"detail"}
        - build_sender_id( sender_session_id, sender_project ) -> sender_id str,
          where `sender_project` is the CALLER-supplied project or None. Two
          arguments, not one: the server cannot answer "what project is the
          caller?" from inside its own container, so the caller supplies it
          (row 12b5a766). None means the caller did not send one — the builder
          then falls back to today's server-side resolution and the omission is
          counted by `_record_dm_project`.
        - persist_fn( ... ) -> db notification id str
        - now_fn (if given) is a 0-arg callable returning an aware datetime — a
          TEST-ONLY seam for a deterministic stamp; production leaves it None and
          the central formatter stamps the real UTC-now instant

    Ensures:
        - 422 (recipient unresolved) is returned unchanged for AI self-correction
        - 201 persists + pushes the ai_to_ai notification (body EDT-prefixed in BOTH
          the persisted row and the pushed message) and returns
          {http_status, message_id, thread_id, recipient_session,
           recipient_session_hash8, recipient_persona, dispatched}
        - `recipient_session` is the FULL resolved session id (unchanged
          contract — reusable as `recipient_session_id` on a subsequent send);
          `recipient_session_hash8` is the 8-char form actually persisted and
          the form `/api/dm/list` filters on. Both are returned so neither name
          has to mean two shapes (row 2565956b, Rio's ruling 2026-07-21).
        - thread_id defaults to the fresh message_id when not supplied (new thread)
        - threading / reply_to / sender persona+icon metadata are UNTOUCHED — only
          the body string is prefixed

    Raises:
        - None (DB/push errors propagate to the route)
    """
    if new_id_fn is None:
        new_id_fn = lambda: str( uuid.uuid4() )
    # Phase 2 DM Quality Judge seam (default = the module-level toggle-gated
    # grader). Injected for tests; production leaves it None → _maybe_grade_dm_quality,
    # which returns None (no `quality` field) whenever the judge toggle is OFF.
    if grade_quality_fn is None:
        grade_quality_fn = _maybe_grade_dm_quality

    resolution = resolve_recipient_fn(
        recipient_session_id  = body.recipient_session_id,
        recipient_persona     = body.recipient_persona,
        authenticated_user_id = authenticated_user_id,
    )
    if resolution[ "http_status" ] != 200:
        return { "http_status": resolution[ "http_status" ], "detail": resolution[ "detail" ] }

    target_session_id = resolution[ "session_id" ]
    target_persona    = resolution.get( "persona_name" )
    # The CALLER's project drives the stamp when it sent one (row 12b5a766).
    # `build_sender_id` takes it as a second argument rather than resolving it:
    # asking the server to resolve the caller's project is the defect, not the
    # implementation of it.
    _record_dm_project( body.sender_session_id, body.sender_project )
    _record_dm_length( body.body )
    # STEP 2 (row 12b5a766, 2026-07-27): an ABSENT project is now a REJECT, not a
    # fallback. Counted FIRST — the audit records the offender even though the DM
    # is refused, so a fleet that starts offending stays visible instead of going
    # quiet at exactly the moment it matters.
    #
    # WHY THIS IS SAFE TO FLIP NOW, and it is a measurement rather than a judgement:
    #   negative arm — zero live cosa_voice_mcp.py clients predate step 1 (831e18dc)
    #   positive arm — 362 [dm-project-audit] observations over 12h, un_projected=0
    #                  on every line, with a synthetic un_projected=7 proven to
    #                  survive the same filter (so the filter discriminates)
    # The audit counts AT THE ENDPOINT, so it sees off-box callers too — which is
    # what retires Extra 1's standing "a grep cannot see a caller on another
    # machine" caveat. That was the last unmeasured unknown on this row.
    if body.sender_project is None:
        return {
            "http_status" : 422,
            "detail"      : (
                f"sender_project is REQUIRED on the DM write path. Session "
                f"'{body.sender_session_id}' sent none, and the server will not guess: "
                f"resolving the caller's project server-side is the defect (row 12b5a766), "
                f"not a fallback for it — it answers 'what project is THIS PROCESS in?', "
                f"and this process is the server. Respawn this seat onto a client that "
                f"sends sender_project."
            ),
        }
    sender_id         = build_sender_id( body.sender_session_id, body.sender_project )
    job_id            = target_session_id[ :8 ]

    message_id = new_id_fn()
    thread_id  = body.thread_id or message_id

    # Central EDT prefix on the outbound body — identical bracketed shape to the
    # arbiter pings (f"[{stamp}] {body}"). now_fn is the test-only deterministic seam.
    # IDEMPOTENT (bug f49a8b34 / bc8d9d82): skip the prepend when the body ALREADY
    # leads with a bracketed stamp (an arbiter ping pre-stamped via _route, then
    # pushed through this chokepoint) — else we'd produce a "[push-ts] [compose-ts]"
    # double. An un-stamped body (human dm_send) still gets the central stamp.
    stamped_body = body.body if is_already_stamped( body.body ) else \
        f"{format_edt_timestamp( dt=now_fn() if now_fn is not None else None )} {body.body}"

    db_id = persist_fn(
        sender_id         = sender_id,
        recipient_user_id = authenticated_user_id,
        message           = stamped_body,
        direction         = "ai_to_ai",
        sender_persona    = body.sender_persona,
        sender_icon       = body.sender_icon,
        reply_to          = body.reply_to,
        thread_id         = thread_id,
        job_id            = job_id,
    )

    notification_queue.push_notification(
        message        = stamped_body,
        type           = "user_initiated_message",
        priority       = "medium",
        id             = db_id or message_id,
        sender_id      = sender_id,
        job_id         = job_id,
        user_id        = authenticated_user_id,
        suppress_ding  = True,
        direction      = "ai_to_ai",
        sender_persona = body.sender_persona,
        sender_icon    = body.sender_icon,
        reply_to       = body.reply_to,
        thread_id      = thread_id,
    )

    result = {
        "http_status"       : 201,
        "message_id"        : db_id or message_id,
        "thread_id"         : thread_id,
        # BOTH SHAPES, EACH UNDER ITS OWN NAME (Rio's ruling, 2026-07-21).
        # `recipient_session` is the FULL id and is UNCHANGED — it is a
        # documented agent-facing contract, and `dm_send` accepts
        # `recipient_session_id` for precise addressing, so a caller
        # round-tripping this receipt into a SUBSEQUENT SEND needs the full
        # value. Truncating it to match the list side would have quietly cost
        # that. `recipient_session_hash8` is the width actually PERSISTED
        # (job_id) and the width `/api/dm/list` filters on — so a caller can
        # feed the right shape to the right place without knowing that a field
        # named "job_id" is the addressee. One name per shape, nothing
        # discarded, and no name meaning two things. See row 2565956b.
        "recipient_session"       : target_session_id,
        "recipient_session_hash8" : job_id,
        "recipient_persona" : target_persona,
        "dispatched"        : True,
    }

    # Phase 2: append the judge's grade of the composed body IFF the toggle is on.
    # OFF (control) → grade_quality_fn returns None → the result shape is the Phase 1
    # baseline, unchanged. The judge grades body.body (the raw composed text), not the
    # EDT-stamped outbound body — the stamp is per-DM overhead, not the sender's prose.
    quality = grade_quality_fn( body.body )
    if quality is not None:
        result[ "quality" ] = quality

    return result


@router.post(
    "/send",
    summary     = "Send a notification-native AI↔AI direct message (body inline)",
    description = "Notification-native peer DM: resolves the recipient persona/session (same-user scoped) and delivers the message body INLINE via a direction='ai_to_ai' notification — no commons board, no claim-check, no commons_read re-fetch. Returns 201 with {message_id, thread_id}, or 422 (RecipientResolutionError) if the recipient can't be resolved.",
)
async def post_dm_send(
    body: DmSendRequest,
    authenticated_user_id: Annotated[ str, Depends( require_api_key_or_jwt ) ],
    notification_queue: NotificationFifoQueue = Depends( get_notification_queue ),
) -> JSONResponse:
    # Lazy import to avoid a commons<->notifications import cycle and to read the
    # commons module's runtime-initialized active-session threshold.
    from cosa.rest.routers import commons as _commons
    from lupin_cli.claude_code.hooks.lib.session_bridge import (
        find_active_sessions, build_sender_id_for_cc,
    )

    def _resolve( recipient_session_id, recipient_persona, authenticated_user_id ):
        return _commons._resolve_dm_recipient(
            recipient_session_id             = recipient_session_id,
            recipient_persona                = recipient_persona,
            authenticated_user_id            = authenticated_user_id,
            # require_persona=False so a null-persona worker (pool exhausted /
            # allocation raced) is still addressable by its session_id — it has
            # no persona name to resolve by, so excluding it makes it a black
            # hole for inbound DMs (bug d57dbfea). The persona-name resolution
            # path inside _resolve_dm_recipient skips persona-less candidates.
            raw_sessions_fn                  = lambda: find_active_sessions( require_persona=False ),
            bridge_loader                    = _commons._load_bridge_fields,
            active_session_threshold_seconds = getattr( _commons, "_active_session_threshold_seconds", 600.0 ),
        )

    # FM-7 mitigation: recipient resolution + DB persist are blocking I/O — run
    # OFF the shared event loop (mirrors register-question / notify).
    result = await asyncio.to_thread(
        execute_dm_send,
        authenticated_user_id = authenticated_user_id,
        body                  = body,
        notification_queue    = notification_queue,
        resolve_recipient_fn  = _resolve,
        build_sender_id       = _make_sender_id_builder( build_sender_id_for_cc ),
        persist_fn            = _persist_dm_send_sync,
    )
    http_status = result.pop( "http_status" )
    if http_status >= 400:
        raise HTTPException( status_code=http_status, detail=result[ "detail" ] )
    return JSONResponse( status_code=http_status, content=result )


# ═════════════════════════════════════════════════════════════════════════════
# Phase 2 — DM verb family: /respond, /get, /list (Clayton 😎)
#
# Additive routes on the SAME `/api/dm` router. `respond` reuses the send
# execution core verbatim (it is send-with-mandatory-threading); `get`/`list`
# are read-path cores backed by NotificationRepository.get_by_id /
# get_dm_thread / get_dm_inbox. Design: 2026.06.16-dm-api-namespace-design.md §3.
# ═════════════════════════════════════════════════════════════════════════════


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/dm/respond — threaded reply (reply_to + thread_id REQUIRED)
#
# A "respond" is a "send" whose threading is mandatory: you cannot reply without
# naming the message you answer (reply_to) and the conversation it belongs to
# (thread_id). The send execution core (execute_dm_send) is reused verbatim —
# DmRespondRequest duck-types as the DmSendRequest `body` it consumes.
# ─────────────────────────────────────────────────────────────────────────────

class DmRespondRequest( BaseModel ):
    """
    POST /api/dm/respond request body — a threaded peer-DM reply.

    Identical to DmSendRequest except `reply_to` and `thread_id` are REQUIRED:
    a reply must name the message it answers and the conversation it continues.
    """
    sender_session_id    : str             = Field( ..., min_length=1, max_length=128 )
    body                 : str             = Field( ..., min_length=1 )
    reply_to             : str             = Field( ..., min_length=1, max_length=64 )
    thread_id            : str             = Field( ..., min_length=1, max_length=64 )
    recipient_session_id : Optional[ str ] = Field( default=None, min_length=1, max_length=128 )
    recipient_persona    : Optional[ str ] = Field( default=None, min_length=1, max_length=64 )
    sender_persona       : Optional[ str ] = Field( default=None, max_length=64 )
    sender_icon          : Optional[ str ] = Field( default=None, max_length=16 )
    # Same caller-supplied project as DmSendRequest — respond shares the execution
    # core, so it must share the stamp fix or the reply path keeps stamping the
    # server's project (row 12b5a766).
    sender_project       : Optional[ str ] = Field( default=None, min_length=1, max_length=64 )


@router.post(
    "/respond",
    summary     = "Reply to a peer DM in-thread (body inline, reply_to + thread_id required)",
    description = "Threaded peer-DM reply: a /api/dm/send whose `reply_to` (message answered) and `thread_id` (conversation) are mandatory. Resolves the recipient (same-user scoped), persists a direction='ai_to_ai' notification carrying the body inline + threading, and pushes it to the recipient session. Returns 201 with {message_id, thread_id}, or 422 if the recipient can't be resolved.",
)
async def post_dm_respond(
    body: DmRespondRequest,
    authenticated_user_id: Annotated[ str, Depends( require_api_key_or_jwt ) ],
    notification_queue: NotificationFifoQueue = Depends( get_notification_queue ),
) -> JSONResponse:
    # Mirrors post_dm_send exactly — respond shares send's resolution + execution
    # core; only the request model differs (threading mandatory).
    from cosa.rest.routers import commons as _commons
    from lupin_cli.claude_code.hooks.lib.session_bridge import (
        find_active_sessions, build_sender_id_for_cc,
    )

    def _resolve( recipient_session_id, recipient_persona, authenticated_user_id ):
        return _commons._resolve_dm_recipient(
            recipient_session_id             = recipient_session_id,
            recipient_persona                = recipient_persona,
            authenticated_user_id            = authenticated_user_id,
            # require_persona=False — null-persona workers stay reachable by
            # session_id on the reply path too (bug d57dbfea); see post_dm_send.
            raw_sessions_fn                  = lambda: find_active_sessions( require_persona=False ),
            bridge_loader                    = _commons._load_bridge_fields,
            active_session_threshold_seconds = getattr( _commons, "_active_session_threshold_seconds", 600.0 ),
        )

    result = await asyncio.to_thread(
        execute_dm_send,
        authenticated_user_id = authenticated_user_id,
        body                  = body,
        notification_queue    = notification_queue,
        resolve_recipient_fn  = _resolve,
        build_sender_id       = _make_sender_id_builder( build_sender_id_for_cc ),
        persist_fn            = _persist_dm_send_sync,
    )
    http_status = result.pop( "http_status" )
    if http_status >= 400:
        raise HTTPException( status_code=http_status, detail=result[ "detail" ] )
    return JSONResponse( status_code=http_status, content=result )


# ─────────────────────────────────────────────────────────────────────────────
# Shared serialization for the read verbs (get / list)
# ─────────────────────────────────────────────────────────────────────────────

def _serialize_dm( notification ):
    """
    Serialize a peer-DM Notification row to the wire shape returned by get/list.

    Requires:
        - notification has the ai_to_ai notification columns (id, thread_id,
          reply_to, sender_*, message, direction, state, job_id, created_at)

    Ensures:
        - returns a JSON-safe dict; created_at is ISO 8601 (or None)
        - the body is exposed as "body" (the message column) to match the
          dm_send/dm_respond request vocabulary
        - `recipient_session_hash8` names the ADDRESSEE explicitly. It is the same
          value as `job_id` (which on an ai_to_ai row IS the recipient's 8-char
          session hash), surfaced under a name that says what it is. Before this,
          a reader had to know that a field called "job_id" meant "who this was
          sent to" — and a reader who did NOT know it could conclude only that a
          DM was VISIBLE to them, never that it was ADDRESSED to them. That gap
          produced a false cross-session finding on 2026-07-16 (row 2565956b).
        - 🔴 THE NAME CARRIES ITS SHAPE ON PURPOSE. `execute_dm_send` returns a
          key called `recipient_session` holding the FULL session id, while what
          is PERSISTED is `target_session_id[ :8 ]`. Calling this field
          `recipient_session` too would have given one well-chosen name two value
          shapes — a consumer comparing them would never match, and feeding the
          send receipt back as a list filter would silently return zero rows.
          This row exists because a column named `recipient_id` does not hold a
          recipient; shipping a second name that means two things would have been
          the same defect in miniature. The `_hash8` suffix makes the shape part
          of the name. (The send response is deliberately NOT truncated to match:
          narrowing a field this fix does not own would discard information its
          consumers may rely on.)
        - `job_id` is retained unchanged for the existing consumers that already
          filter on it; this is an added name, not a rename.
    """
    return {
        "message_id"              : str( notification.id ),
        "thread_id"               : notification.thread_id,
        "reply_to"                : notification.reply_to,
        "sender_id"               : notification.sender_id,
        "sender_persona"          : notification.sender_persona,
        "sender_icon"             : notification.sender_icon,
        "body"                    : notification.message,
        "direction"               : notification.direction,
        "state"                   : notification.state,
        "job_id"                  : notification.job_id,
        "recipient_session_hash8" : notification.job_id,
        "created_at"              : notification.created_at.isoformat() if notification.created_at is not None else None,
    }


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/dm/get — fetch one DM by id (same-user scoped, DM-only)
# ─────────────────────────────────────────────────────────────────────────────

def execute_dm_get( *, message_id, authenticated_user_id, fetch_fn ):
    """
    Pure-logic core for GET /api/dm/get — fetch a single peer DM by id.

    Requires:
        - message_id: the DM's notification id (string; must parse as a UUID)
        - authenticated_user_id: the caller's user uuid (string) — scoping anchor
        - fetch_fn(uuid.UUID) -> Notification | None

    Ensures:
        - 400 if message_id is not a valid UUID
        - 404 if no row, or the row belongs to another user, or is not a peer DM
          (direction != 'ai_to_ai') — never leaks non-DM / cross-user rows
        - 200 with the serialized DM otherwise

    Raises:
        - None (DB errors propagate from fetch_fn to the route)
    """
    try:
        mid = uuid.UUID( message_id )
    except ( ValueError, AttributeError, TypeError ):
        return { "http_status": 400, "detail": f"invalid message_id: {message_id!r} (expected a UUID)" }

    notification = fetch_fn( mid )
    if notification is None:
        return { "http_status": 404, "detail": "DM not found" }

    # Same-user scope + DM-only: do not leak another user's row or a non-DM row.
    if str( notification.recipient_id ) != authenticated_user_id or notification.direction != "ai_to_ai":
        return { "http_status": 404, "detail": "DM not found" }

    return { "http_status": 200, **_serialize_dm( notification ) }


@router.get(
    "/get",
    summary     = "Fetch a single peer DM by message id",
    description = "Returns one direction='ai_to_ai' DM by its message id, scoped to the caller. 404 if it does not exist, is not a DM, or belongs to another user; 400 if message_id is not a UUID.",
)
async def get_dm(   # pragma: no cover
    message_id: str,
    authenticated_user_id: Annotated[ str, Depends( require_api_key_or_jwt ) ],
) -> JSONResponse:
    def _work():
        # Run the core INSIDE the session so _serialize_dm reads live (non-expired)
        # ORM attributes.
        with get_db() as session:
            repo = NotificationRepository( session )
            return execute_dm_get(
                message_id            = message_id,
                authenticated_user_id = authenticated_user_id,
                fetch_fn              = repo.get_by_id,
            )

    result = await asyncio.to_thread( _work )
    http_status = result.pop( "http_status" )
    if http_status >= 400:
        raise HTTPException( status_code=http_status, detail=result[ "detail" ] )
    return JSONResponse( status_code=http_status, content=result )


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/dm/list — list / poll a thread (thread_id) or the inbox (no thread_id)
# ─────────────────────────────────────────────────────────────────────────────

_DM_LIST_MAX_LIMIT = 200


DM_LIST_SCOPES = ( "session", "account" )

# The persisted addressee is `target_session_id[ :8 ]`, so every predicate built
# from a caller-supplied id must be cut to the same width before it is compared.
_SESSION_HASH_WIDTH = 8


def resolve_dm_list_scope( session_id, scope ):
    """
    Decide the effective addressee filter for a /api/dm/list read.

    The route authenticates a USER, not a session — that is the whole reason this
    resolution exists. The caller must TELL us which session it is; the server
    cannot derive it from the credential. Absence therefore means "I did not ask
    to be scoped", which must stay account-wide so the pre-existing
    client-side-filtering consumer keeps working untouched.

    🔴 NORMALIZES THE WIDTH, AND THAT IS THE POINT. The addressee is persisted as
    an 8-char prefix, but the most natural thing a caller has in hand is a FULL
    session id — `execute_dm_send` hands one back under `recipient_session`.
    Comparing a full uuid against an 8-char column matches nothing, so the
    obvious move (feed the send receipt back in) would return ZERO ROWS and look
    like "no DMs" rather than like a mistake. Truncating here makes both widths
    work. A filter that silently returns nothing for a well-formed input is worse
    than one that rejects it, and this one cannot tell the difference — so it
    accepts both instead of failing quietly on one.

    🔴 AND WHAT IT CANNOT NORMALIZE, IT REJECTS OUT LOUD. An id SHORTER than the
    persisted width can never equal an 8-char column value, so filtering on it
    would return zero rows — and a silent zero is indistinguishable from "you
    have no messages." That is the same failure shape as the row itself: a
    plausible small answer to a question the resolver never understood. So a
    too-short id is a 400, not an empty list. The caller learns it asked wrong
    instead of concluding its inbox is empty.

    Requires:
        - session_id: the caller's session id (full or 8-char), or None/""
        - scope: "session" (default), "account", or None

    Ensures:
        - Returns ( recipient_session|None, effective_scope_label, error|None )
        - a supplied session_id is stripped and TRUNCATED to 8 chars, so a full
          uuid and its own 8-char prefix resolve identically
        - a stripped session_id SHORTER than 8 chars returns an error string —
          it cannot match, and must not fail as an empty result
        - scope="account" ALWAYS yields None — an explicit, auditable wide read
        - a missing/blank session_id yields None regardless of scope, and the
          label reports "account", never a session scope the server did not apply
          (the label must never claim a narrowing that did not happen)
        - Never raises

    Args:
        session_id: caller-supplied session id, any width
        scope: requested scope label

    Returns:
        tuple: ( recipient_session|None, "session"|"account", error|None )
    """
    if scope == "account":                       return None, "account", None
    if session_id is None or not str( session_id ).strip(): return None, "account", None

    cleaned = str( session_id ).strip()
    if len( cleaned ) < _SESSION_HASH_WIDTH:
        return None, "session", (
            f"invalid 'session_id': {session_id!r} is shorter than the {_SESSION_HASH_WIDTH}-char "
            f"session hash addressees are stored under, so it can never match. Pass a full session "
            f"id or its first {_SESSION_HASH_WIDTH} characters."
        )
    return cleaned[ :_SESSION_HASH_WIDTH ], "session", None


def execute_dm_list( *, thread_id, since, limit, authenticated_user_id, thread_fn, inbox_fn,
                     session_id=None, scope="session" ):
    """
    Pure-logic core for GET /api/dm/list — list/poll a thread or the inbox.

    ⚠️ SCOPING, STATED PLAINLY BECAUSE THE OLD DOCSTRING'S "INBOX" WAS FALSE.
    `authenticated_user_id` scopes to a SERVICE ACCOUNT, not a session: peer DMs
    persist with `recipient_user_id = <the sender's own account>`, so every
    session on one account shares one pool — and since the write path currently
    stamps one and the same account for the entire fleet, that pool is the whole
    fleet's traffic. Passing `session_id` narrows to the DMs actually ADDRESSED
    to that session (see get_dm_inbox for the job_id overload + 8-char-prefix
    caveats). Omitting it keeps the legacy account-wide read, which is what the
    existing client-side-filtering hook relies on.

    Requires:
        - thread_id: a conversation id (thread view) OR None/"" (inbox view)
        - since: None, or an ISO-8601 timestamp string (poll — rows strictly newer)
        - limit: requested row cap (clamped to [1, 200])
        - authenticated_user_id: the caller's user uuid (string)
        - thread_fn(thread_id, recipient_id, since, limit, recipient_session) (asc)
        - inbox_fn(recipient_id, since, limit, recipient_session) (desc)
        - session_id: caller's 8-char session hash, or None
        - scope: "session" (default) or "account" (explicit wide read)

    Ensures:
        - 400 if `since` is a non-ISO string
        - thread view when thread_id is truthy, else inbox view
        - 400 if `session_id` is too short to ever match an addressee — a filter
          that cannot match must say so, not return an empty list that reads as
          "no messages"
        - 400 if `scope` is not one of DM_LIST_SCOPES — an unrecognized scope is
          REJECTED, never silently treated as "session". A caller who spells the
          wide read "all" must not receive a narrow one under a label saying
          "session"; that would be a quiet wrong answer to a well-formed request
        - the addressee filter is resolved by resolve_dm_list_scope; an
          account-wide read requires either scope="account" or an absent
          session_id — a wide view is never the silent outcome of a session read
        - the response ECHOES the scope actually applied, so a caller can tell
          whether it was narrowed rather than assuming it was
        - 200 with {thread_id, since, count, scope, recipient_session_hash8,
          messages}

    Raises:
        - None (DB errors propagate from the fns to the route)
    """
    if scope is not None and scope not in DM_LIST_SCOPES:
        return { "http_status": 400,
                 "detail": f"invalid 'scope': {scope!r} (expected one of {list( DM_LIST_SCOPES )})" }

    since_dt = None
    if since is not None:
        try:
            since_dt = datetime.fromisoformat( since )
        except ValueError:
            return { "http_status": 400, "detail": f"invalid 'since' timestamp: {since!r} (expected ISO 8601)" }

    effective_limit = max( 1, min( int( limit ), _DM_LIST_MAX_LIMIT ) )
    recipient_uuid  = uuid.UUID( authenticated_user_id )

    recipient_session, effective_scope, scope_error = resolve_dm_list_scope( session_id, scope )
    if scope_error is not None:
        return { "http_status": 400, "detail": scope_error }

    if thread_id:
        rows = thread_fn(
            thread_id         = thread_id,
            recipient_id      = recipient_uuid,
            since             = since_dt,
            limit             = effective_limit,
            recipient_session = recipient_session,
        )
    else:
        rows = inbox_fn(
            recipient_id      = recipient_uuid,
            since             = since_dt,
            limit             = effective_limit,
            recipient_session = recipient_session,
        )

    messages = [ _serialize_dm( row ) for row in rows ]
    return {
        "http_status"             : 200,
        "thread_id"               : thread_id,
        "since"                   : since,
        "count"                   : len( messages ),
        "scope"                   : effective_scope,
        "recipient_session_hash8" : recipient_session,
        "messages"                : messages,
    }


@router.get(
    "/list",
    summary     = "List or poll peer DMs — a thread (thread_id) or the inbox",
    description = (
        "With `thread_id`, returns that conversation oldest-first; without it, returns peer DMs newest-first. "
        "SCOPING: the credential authenticates a USER (a per-project service account), NOT a session — pass "
        "`session_id` (your 8-char session hash) to narrow to DMs actually ADDRESSED to you. WITHOUT it the read "
        "is ACCOUNT-WIDE and returns every DM sent by any session on that account, including conversations you "
        "are not party to. `scope=account` explicitly requests that wide read. The response echoes the `scope` "
        "actually applied. `session_id` may be a FULL session id OR its 8-char prefix — it is normalized "
        "server-side, so the `recipient_session` from a send receipt can be fed straight back. `since` "
        "(ISO 8601) tails only newer messages (poll); `limit` is clamped to [1, 200]. "
        "400 if `since` is malformed; 422 if `scope` is not session|account."
    ),
)
async def list_dms(   # pragma: no cover
    authenticated_user_id: Annotated[ str, Depends( require_api_key_or_jwt ) ],
    thread_id: Optional[ str ] = None,
    since: Optional[ str ] = None,
    limit: int = 50,
    session_id: Optional[ str ] = None,
    scope: Literal[ "session", "account" ] = "session",
) -> JSONResponse:
    def _work():
        with get_db() as session:
            repo = NotificationRepository( session )
            return execute_dm_list(
                thread_id             = thread_id,
                since                 = since,
                limit                 = limit,
                authenticated_user_id = authenticated_user_id,
                thread_fn             = repo.get_dm_thread,
                inbox_fn              = repo.get_dm_inbox,
                session_id            = session_id,
                scope                 = scope,
            )

    result = await asyncio.to_thread( _work )
    http_status = result.pop( "http_status" )
    if http_status >= 400:
        raise HTTPException( status_code=http_status, detail=result[ "detail" ] )
    return JSONResponse( status_code=http_status, content=result )


@router.get(
    "/project-audit",
    summary     = "Read the un-projected-DM audit — the step-2 gate evidence",
    description = (
        "Returns the live `sender_project` audit counters: `projected`, `un_projected`, the distinct "
        "offender sessions (capped), and the window start. "
        "WHY THIS EXISTS: the audit has been generated correctly since 2026-07-21 and was readable ONLY by "
        "grepping `docker logs lupin-rest-dev`, so the gate it existed to inform sat four days unread — the "
        "fifth instance of row 67fe3be1 (disclosures nobody consumes). The counters reset on every server "
        "restart, and `:7999` runs --reload, so `since` is load-bearing: a low count usually means a recent "
        "reload, not a quiet fleet. "
        "⚠️ `un_projected=0` alone proves nothing — a window with NO DM traffic reports 0/0 and reads exactly "
        "like a clean one. Always read `projected` alongside it."
    ),
)
async def get_dm_project_audit_endpoint(   # pragma: no cover
    authenticated_user_id: Annotated[ str, Depends( require_api_key_or_jwt ) ],
) -> JSONResponse:
    return JSONResponse( status_code=200, content=get_dm_project_audit() )


@router.get(
    "/length-audit",
    summary     = "Read the DM length audit — evidence for the Phase 1 verbosity A/B",
    description = (
        "Returns the live DM body length counters: `count`, `total_chars`, `total_words`, "
        "`total_sentences`, derived `avg_chars`/`avg_words`/`avg_sentences`, and the window "
        "start. Snapshot this endpoint before "
        "and after each control/treatment run of the DM Verbosity Reduction A/B "
        "(src/rnd/v0.1.9/2026.07.31-dm-verbosity-reduction/) to get a quantified delta rather "
        "than a vibes-based one. Counters reset on server restart, same as the project-audit; "
        "`since` is load-bearing for the same reason."
    ),
)
async def get_dm_length_audit_endpoint(   # pragma: no cover
    authenticated_user_id: Annotated[ str, Depends( require_api_key_or_jwt ) ],
) -> JSONResponse:
    return JSONResponse( status_code=200, content=get_dm_length_audit() )


@router.get(
    "/quality-audit",
    summary     = "Read the DM quality audit — evidence for the Phase 2 verbosity A/B",
    description = (
        "Returns the live DM Quality Judge counters: `count`, the running "
        "`total_length_weight`/`total_directness_weight`/`total_tone_weight`/"
        "`total_overall_weight`, the derived `avg_length`/`avg_directness`/`avg_tone`/"
        "`avg_overall`, and the window start. This is the SECOND A/B axis (the first "
        "is `/length-audit`): it accumulates ONLY during TREATMENT windows (the judge "
        "runs only when `dm quality judgment enabled` is True), so a control window "
        "reports count=0. Snapshot before and after a treatment run and read the "
        "avg_overall trend against the length-audit's avg_words trend "
        "(src/rnd/v0.1.9/2026.07.31-dm-verbosity-reduction/). Counters reset on server "
        "restart; `since` is load-bearing, same as the other audits."
    ),
)
async def get_dm_quality_audit_endpoint(   # pragma: no cover
    authenticated_user_id: Annotated[ str, Depends( require_api_key_or_jwt ) ],
) -> JSONResponse:
    return JSONResponse( status_code=200, content=get_dm_quality_audit() )
