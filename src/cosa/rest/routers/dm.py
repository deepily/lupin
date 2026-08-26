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
import json
import os
import re
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import cosa.utils.util as cu
from cosa.utils.dm_text import dm_word_count, WORD_COUNT_VERSION
from cosa.rest import dm_experiment

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
    _dm_length_audit[ "total_words" ]     += dm_word_count( body_text )
    _dm_length_audit[ "total_sentences" ] += _count_sentences( body_text )
    print( format_dm_length_audit_line() )


# ─────────────────────────────────────────────────────────────────────────────
# Per-DM JSONL traffic corpus (row 334569d6, Rick ruled by keypress 2026-08-02).
# The running counter above holds only four SUMS; totals cannot be un-summed, so
# "how many DMs ran over 250 words?" is unanswerable from it (established by the
# row 49a76406 readout). This is a SEPARATE, ADDITIVE sink that stops discarding
# the rows: one JSON object per DM, append-only, never read-modify-write.
#
# WHERE: OUTSIDE THE REPO, in the fleet data root (Rick, 2026-08-13). The corpus
# used to live at src/tmp/dm_traffic.jsonl — gitignored, but INSIDE the tree, and
# that is the defect his instruction names: a gitignored path inside the checkout
# is on `git clean -xdf`'s kill list, not shielded by it (the same reasoning that
# moved hold files and every other runtime artifact out, rows 8758d0b1 / f56fc63b).
#
# The path resolves in this order:
#   1. $LUPIN_DM_CORPUS_DIR        — what the containers set, pointing at the mount
#   2. fleet_data_root()/dm-corpus — the host-side derivation every other runtime
#                                    artifact already uses
# Both name the SAME physical directory: docker-compose bind-mounts the host's
# <projects-data>/lupin/dm-corpus at /var/lupin/dm-corpus. ⚠️ That mount and the
# env var resolve at container CREATE, so picking them up needs
# `docker compose up -d --force-recreate`, never a plain restart.
_DM_CORPUS_DIR_ENV = "LUPIN_DM_CORPUS_DIR"


def _resolve_dm_corpus_dir():
    """
    The directory the DM traffic corpus is written to — outside the repo, always.

    Ensures:
        - returns $LUPIN_DM_CORPUS_DIR when set (the container's mount point)
        - otherwise returns <fleet data root>/dm-corpus, the same convention hold
          files and the rest of the fleet's runtime state already use
        - NEVER returns a path inside the repo checkout. The last-resort fallback,
          used only if the fleet-root helper cannot be imported, derives the same
          location arithmetically rather than degrading to src/tmp/ — a silent
          degradation back into the tree would undo the whole point of the move.

    Raises:
        - nothing
    """
    override = os.environ.get( _DM_CORPUS_DIR_ENV )
    if override: return override
    try:
        from lupin_cli.claude_code.hooks.lib.heartbeat_hold import fleet_data_root
        return str( fleet_data_root() / "dm-corpus" )
    except Exception:
        # Same formula as fleet_data_root's own fallback: <projects-parent>/projects-data/<repo>.
        root = os.path.abspath( cu.get_project_root() )
        return os.path.join(
            os.path.dirname( os.path.dirname( root ) ), "projects-data",
            os.path.basename( root ), "dm-corpus"
        )


_DM_TRAFFIC_JSONL = os.path.join( _resolve_dm_corpus_dir(), "dm_traffic.jsonl" )


# ─────────────────────────────────────────────────────────────────────────────
# PROCESS PROVENANCE (Rick, 2026-08-13): "tag all DMs generated with enough
# identifying information that we can understand exactly which process created
# the serialized copies."
#
# The corpus is append-only and accumulates across restarts, code changes, config
# changes, and both servers. Without this block, a reader holding two rows that
# disagree has no way to tell whether they came from different CODE, different
# CONFIG, or the same process on two days — and every such question has previously
# been answered by inferring from timestamps, which is exactly the mistake the
# `origin` stamp was added to retire.
#
# `boot_id` is the load-bearing field: it is unique per PROCESS, so all rows from
# one server lifetime group exactly, and a restart is visible as a boundary rather
# than reconstructed from a gap in `ts`.
_PROCESS_BOOT_ID = uuid.uuid4().hex[ :12 ]


def _resolve_git_sha():
    """
    The commit this process's tree was at when it booted — resolved ONCE.

    A long-lived server imports its tree at boot and serves those bytes for its whole
    life (auto-reload is off), so the sha that matters is the one read at import, not
    the one a reader would get by running git later.

    Ensures:
        - returns a short sha string, or "unknown" on any failure
        - never raises, never blocks longer than the subprocess timeout

    Raises:
        - nothing
    """
    try:
        import subprocess
        out = subprocess.run(
            [ "git", "rev-parse", "--short", "HEAD" ], cwd=cu.get_project_root(),
            capture_output=True, text=True, timeout=5,
        )
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


_PROCESS_GIT_SHA = _resolve_git_sha()


def _process_provenance():
    """
    The identifying block stamped onto every corpus row.

    Ensures:
        - returns a fresh dict (a caller cannot mutate the shared stamp)
        - every value is JSON-serializable
        - identifies the PROCESS (boot_id, pid, host, port) and the CODE
          (git_sha, writer, schema version) separately, because they answer
          different questions and a single "version" field answers neither well

    Raises:
        - nothing
    """
    return {
        "corpus_schema_version" : DM_CORPUS_SCHEMA_VERSION,
        "writer"                : "dm.py:_persist_dm_row",
        "boot_id"               : _PROCESS_BOOT_ID,
        "pid"                   : os.getpid(),
        "host"                  : os.environ.get( "HOSTNAME" ) or "unknown",
        "server_port"           : os.environ.get( "LUPIN_SERVER_PORT" ) or "unknown",
        "git_sha"               : _PROCESS_GIT_SHA,
    }

# The ONE TRUE production corpus path, captured as its own constant that the test
# conftest's `patch.object(dm, "_DM_TRAFFIC_JSONL", tmp)` NEVER touches (row f5d6dc5e).
# The self-guard below compares the live sink against THIS. Deriving "is this
# production?" from `_DM_TRAFFIC_JSONL` itself would compare a value to itself and
# could never fire once the fixture patched it — a control blind to its own failure.
_DM_TRAFFIC_PRODUCTION_PATH = _DM_TRAFFIC_JSONL


def _running_under_pytest():
    """True iff this process is executing a pytest test (pytest sets
    PYTEST_CURRENT_TEST per test). The one signal a self-guard can read without the
    cooperation of whoever writes the next test."""
    return os.environ.get( "PYTEST_CURRENT_TEST" ) is not None


def _persist_dm_row( *, body_text, from_persona, from_session, from_project,
                     to_persona, to_session, quality, experiment=None,
                     delivered_text=None, tutor=None ):
    """
    Append ONE JSON line describing this sent DM to the traffic corpus.

    Requires:
        - identities are passed IN by the caller (dm.py send path), where they are
          already resolved — this writer resolves nothing itself
        - quality is DmQualityJudge.judge()'s dict ({"length","directness","tone",
          "overall"}) or None when the judge toggle is OFF / the DM was not delivered
        - experiment is the two-arm-pilot field dict (schedule_id, effective_arm,
          length_gate, delivery_outcome, ...) when the send fell INSIDE the experiment
          window, or None outside it
        - body_text is what the SENDER SUBMITTED; delivered_text is what the recipient
          actually received (None means "identical to submitted")
        - tutor is _apply_dm_tutor's meta dict, or None when the tutor never ran

    Ensures:
        - SELF-GUARD (row f5d6dc5e): refuses to write the PRODUCTION corpus from any
          pytest process, even if the conftest redirect fixture is not in play — the
          check lives in the code being protected, so it cannot be forgotten by
          whoever adds the next test. LIMIT, stated plainly rather than left implied:
          this catches PYTEST ONLY. A hand-run script that imports this module and
          sends a DM is caught by NEITHER this guard NOR the fixture — which is exactly
          why every row also carries `origin`, so such a contaminant can at least be
          identified after the fact instead of inferred from a timezone.
        - AUDITABLE: every row carries `origin` — "live" for a real send, "test" for a
          write made from within pytest (to a redirected sink) — so a reader filters on
          the field instead of guessing from where the process happened to run. It also
          carries `arm` (row f4bb1cdb), the config-derived feedback experiment arm in
          force ("signal_only" today), so the two-arm study is split by reading the row.
        - FAIL-SOFT: the whole body is wrapped in try/except and NEVER raises into
          the send path. dm_send is the fleet's comms bus; a corpus-write failure
          must not take a DM down (and by call-site placement the DM is already
          sent when this runs). On failure it prints a warning and returns.
        - ADDITIVE: does not touch the in-memory counter or its audit line
        - grade fields carry the judge's integer weight per dimension, or null when
          `quality` is None (judge off) — the row is still written either way
    """
    under_pytest = _running_under_pytest()
    # SELF-GUARD: a pytest process may never write the real corpus. When the sink IS
    # the production path here, the redirect fixture is not in play — refuse and write
    # nothing (a test that reached production wanted no row anyway).
    if under_pytest and _DM_TRAFFIC_JSONL == _DM_TRAFFIC_PRODUCTION_PATH:
        return
    try:
        # SUBMITTED vs DELIVERED. Before the tutor these were always the same string
        # and one `body` field was honest. They can now differ, and recording only one
        # would make the tutor's effect unmeasurable in the exact corpus built to
        # measure it: with only the delivered text you cannot recover what the sender
        # wrote, and with only the submitted text you cannot see what was sent.
        # `delivered_text=None` means "identical", recorded explicitly rather than
        # left for a reader to assume.
        delivered = body_text if delivered_text is None else delivered_text
        row = {
            "ts"           : datetime.now().isoformat( timespec="seconds" ),
            "origin"       : "test" if under_pytest else "live",
            "from"         : from_persona,
            "from_session" : from_session,
            "from_project" : from_project,
            "to"           : to_persona,
            "to_session"   : to_session,
            # UNCHANGED NAMES, UNCHANGED MEANING: `words`/`chars`/`sentences`/`body`
            # keep describing what the SENDER SUBMITTED, so every query written
            # against the existing corpus keeps returning what it returned before.
            "words"        : dm_word_count( body_text ),
            "chars"        : len( body_text ),
            "sentences"    : _count_sentences( body_text ),
            "body"         : body_text,
            # The canonical CLAIM count (ruling 4) recorded ALONGSIDE the legacy naive
            # count, never replacing it. Rows written before today carry only the naive
            # one, so overwriting the field would silently make old and new rows
            # incomparable while looking like a single clean column.
            "claims"          : _count_claims( body_text ),
            "delivered_body"  : delivered,
            "delivered_words" : dm_word_count( delivered ),
            "delivered_claims": _count_claims( delivered ),
            "body_was_rewritten" : delivered != body_text,
            "len_grade"    : quality[ "length"     ][ "weight" ] if quality else None,
            "directness"   : quality[ "directness" ][ "weight" ] if quality else None,
            "tone"         : quality[ "tone"       ][ "weight" ] if quality else None,
            "overall"      : quality[ "overall"    ][ "weight" ] if quality else None,
        }
        row.update( _process_provenance() )
        if tutor is not None:
            row.update( tutor )
        # BASELINE (outside the window): stamp the legacy feedback arm exactly as before.
        # IN-WINDOW: the disjoint two-arm vocabulary applies — `arm` is ABSENT and the
        # experiment fields (effective_arm, length_gate, ...) are merged in, so NO row
        # ever carries both `arm` and `effective_arm` (María, 2026-08-03).
        if experiment is None:
            row[ "arm" ] = get_dm_feedback_arm()
        else:
            row.update( experiment )
        # The corpus dir lives outside the repo now, so it is not created by a
        # checkout and will not exist on a fresh box or a fresh container mount.
        os.makedirs( os.path.dirname( _DM_TRAFFIC_JSONL ), exist_ok=True )
        with open( _DM_TRAFFIC_JSONL, "a", encoding="utf-8" ) as f:
            f.write( json.dumps( row, ensure_ascii=False ) + "\n" )
    except Exception as e:
        # Swallow — the DM has already been dispatched; the corpus is best-effort.
        print( f"[dm-traffic] WARNING: failed to append DM row: {e}" )


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


def get_dm_feedback_arm():
    """The DM feedback EXPERIMENT ARM in force, derived from config (row f4bb1cdb).

    Rick 2026-08-02: `dm reject on overage` False OR ABSENT → "signal_only" (arm A, the
    current feedback-only world); True → "reject_on_overage" (arm B). A MISSING key is a
    VALID arm-A state, never an error — so a config-read failure resolves to arm A too,
    NOT fail-closed. Nothing ACTS on True yet: no reject path exists. The value only
    LABELS each corpus row so arm A stays separable from a future arm B by READING the
    row, instead of inferring the condition from when the row was written (the same
    timestamp-inference mistake the `origin` stamp already retired).
    """
    from cosa.config.configuration_manager import ConfigurationManager
    try:
        reject = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" ).get(
            "dm reject on overage", default=False, return_type="boolean" )
    except Exception:
        reject = False
    return "reject_on_overage" if reject else "signal_only"


# ─────────────────────────────────────────────────────────────────────────────
# THE DM TUTOR — live on the send path (Rick, 2026-08-13: "implement it fully and
# make sure it's actually in use").
#
# The tutor was built 2026-08-11 and shipped nothing, because nothing called it.
# This is the call. Every DM over the trigger is distilled to the house shape —
# a headline, two supporting statements, and the path when one is present —
# before it is delivered.
#
# 🔴 THE TRIGGER NUMBER IS NEVER DISCLOSED, and that is a measurement decision, not
# a preference. The tutor names the target ("here it is in three"), never the
# height that fired it, and the rewritten DM carries no count of the sender's
# original. A count shown only when the tutor fires leaks the trigger by
# arithmetic — the reader subtracts and learns exactly where the line sits, then
# writes to the line instead of to the shape.
#
# FAIL-CLOSED THROUGHOUT. Every failure — config unreadable, model down, malformed
# response, gate rejection — delivers the SENDER'S ORIGINAL TEXT. A tutor that
# occasionally mangles a message is worse than no tutor, because the recipient
# cannot tell which kind of message they are holding.
# ─────────────────────────────────────────────────────────────────────────────

# Bumped when the row SHAPE changes, so a reader never has to infer the schema from
# which keys happen to be present in the rows they sampled.
# 4 — adds `tutor_rescoped` (row c1a2e859). A reader must be able to tell "no quantity
# moved" from "this row predates the check"; without the bump both look like a null.
# 5 — adds `tutor_attribution` (row cf1587cd), same reasoning one guard over: a null
# must not mean both "the reader could attribute this one" and "this row predates the
# attribution guard entirely".
# 6 — the attribution guard STOPS REFUSING (row 20026f56, Rick 2026-08-26). The outcome
# `attribution_blocked` is retired at this version and `attribution_flagged` replaces it:
# same predicate, same recorded reason, but the rewrite is DELIVERED. Old rows are NOT
# migrated, so a reader counting how often the check fires must accept both values — an
# `attribution_blocked` row is a v5 refusal and an `attribution_flagged` row is a v6 send.
DM_CORPUS_SCHEMA_VERSION = 6

# Identifies the tutor's behaviour, independent of the git sha: two processes on the
# same commit with different config are the same code and a different treatment.
DM_TUTOR_VERSION = "dm-tutor-1"

# 🔴 THE RECIPIENT IS TOLD. Added 2026-08-13 after Cheech asked what the READER is
# owed — a question the disclosure rule had never asked, because it was written
# entirely about what the SENDER must not learn.
#
# Without this the recipient holds distilled prose believing it is the sender's own
# words, and may quote it back at them. That is a real failure and it was invisible
# to every test, because every test was checking that the trigger stayed secret.
#
# It names NO number and carries NO measurement of the sender's message, so it is
# compatible with the trigger staying unpublished: it says THAT the message was
# shortened, never how long it was or what height fired.
#
# ⚠️ IT MUST COUNT AS STRUCTURE. The canned P.S. taught this the hard way: a marker
# appended to every compliant rewrite reads as an extra claim, so the tutor would
# start rewriting its own output forever. `sentences.py` treats this exact line as
# structure, and a test pins the two together.
DM_TUTOR_NOTICE = "This DM was condensed in transit. Need more detail? Ask the sender one question"

# The same notice plus four words, used ONLY where the attribution check actually fired
# (row 20026f56). Since that check stopped refusing, this is the one thing standing
# between the reader and a condensed body that lost a name the sender wrote.
#
# 🔴 CONDITIONAL, NEVER BLANKET, AND THAT IS THE WHOLE POINT. Roughly half of rewrites
# are perfectly attributable. Warning about attribution on those too makes the sentence
# wallpaper — read past everywhere, and therefore read past in the one place it matters.
# We already compute the predicate; using it to pick the wording costs nothing.
#
# "Check who did what" and not "be careful": Cheech's 2026-08-13 near-miss was precisely
# a WHO error — he was one step from calling a scope violation on the wrong person — and
# "be careful" does not say careful of what.
#
# ⚠️ SAME PREFIX AS DM_TUTOR_NOTICE, DELIBERATELY. `sentences.py` exempts this line as
# structure with `^\s*This DM was condensed in transit\..*$` — prefix-anchored — so the
# extra words land inside the `.*` and the tutor still will not rewrite its own footer.
# Change the first sentence of either constant and you re-arm that trap; a test pins both.
DM_TUTOR_ATTRIBUTION_NOTICE = "This DM was condensed in transit. Check who did what. Need more detail? Ask the sender one question"

# The SEED list of product names that end in a code extension. They are not files, nobody
# can open them, and a rewrite saying "the Node.js test" has cited nothing — so blocking
# that message is refusing real mail, which is this guard's own failure mode. Measured:
# exactly one of the 4,489 delivered rewrites in the corpus is blocked by its absence.
#
# 🔴 A LIST AND NOT A SHAPE RULE, ON MARÍA'S RULING (row f3d96537). The shape rule I
# reached for first — "a slashless token whose stem is a single capitalised word is a
# product name" — FAILS OPEN: `README.md`, `CLAUDE.md` and `TODO.md` all fit it, this
# fleet cites them constantly, and a FABRICATED `CLAUDE.md` would have walked straight
# through. An explicit list fails CLOSED: a token the list has never been told about is
# still checked.
#
# ⚠️ THIS IS THE SEED, NOT THE AUTHORITY. The live list comes from the INI key
# `dm tutor fabrication guard product names`, read per send like the attribution keys, so
# adding a name the day somebody is wrongly blocked costs an edit and a bounce rather than
# a deploy — which is the whole point of an allow-list (María, 2026-08-26).
_FAB_NOT_PATHS = frozenset(
    "node.js next.js nuxt.js vue.js ember.js backbone.js three.js d3.js react.js "
    "express.js nest.js svelte.js jquery.js chart.js socket.io".split()
)


def _parse_path_fab_mode( raw ):
    """
    Resolve the INI path-guard mode, failing toward the STRONGER check.

    ⚠️ A TYPO MUST NOT SILENTLY WEAKEN A GUARD (María, 2026-08-26). The first cut treated
    "anything that is not `pointer`" as the legacy branch, so `Pointr` in the ini would have
    rolled the fleet back to the blind pattern with nothing said. An unrecognised value now
    resolves to `pointer` AND says so on stdout: the reader gets a wrong-looking config
    reported, never a guard quietly doing less than it says.

    Requires:
        - raw is a string or None

    Ensures:
        - returns "legacy" only for the exact word, case- and whitespace-insensitive
        - returns "pointer" for None, blank, "pointer", and anything unrecognised
        - prints a warning naming the unrecognised value, and nothing for the valid ones
        - never raises

    Raises:
        - nothing
    """
    value = ( raw or "" ).strip().lower()
    if value in ( "", "pointer" ): return "pointer"
    if value == "legacy":          return "legacy"
    print( f"[dm-tutor] WARNING: unrecognised path fabrication guard mode {raw!r}, using 'pointer'" )
    return "pointer"


def _parse_product_names( raw ):
    """
    Read the INI product-name list into a lowercase frozenset.

    Requires:
        - raw is a string ( whitespace- or comma-separated ) or None

    Ensures:
        - returns the seed list `_FAB_NOT_PATHS` when raw is None or blank, so a missing
          key behaves exactly like the shipped default rather than exempting nothing
        - returns the parsed names, lowercased, otherwise
        - never raises

    Raises:
        - nothing
    """
    if not raw or not str( raw ).strip(): return _FAB_NOT_PATHS
    return frozenset( n.lower() for n in str( raw ).replace( ",", " " ).split() if n.strip() )


_DM_TUTOR_DEFAULTS = {
    "enabled"         : False,   # OFF unless config says otherwise — see below
    "trigger_claims"  : 4,       # fires on MORE THAN this many claims
    "gate_enabled"    : False,   # Rick ruled: no output gate, default off
    "gate_max_claims" : 4,
    # V3-strict ON by default — Rick's ruling 2026-08-18. The flag exists so the dial
    # moves without a code change; he has wanted to move it twice.
    "fab_guard_strict": True,
    # The attribution guard (row cf1587cd). ON, because a rewrite the reader cannot
    # attribute is the defect the row was filed for — and the failure mode of leaving it
    # off is the tutor's own history: built 2026-08-11, shipped nothing for two days
    # because nothing called it.
    "attribution_guard"      : True,
    # 3, not 1, and the number is measured rather than chosen. Across 75 hand-labelled
    # pairs: min 1 → 0.62 precision, min 3 → 0.71, min 5 → 0.75 at half the recall. A
    # message that mentions one person in passing can lose the mention without costing
    # the reader anything; one built on who-did-what cannot.
    "attribution_min_persons": 3,
    # Which PATH-fabrication check runs (row f3d96537). "pointer" — the default and what
    # ships — asks the restore side's recogniser, so a bare `filename.py` is seen. Any
    # other value rolls back to the pre-2026-08-26 pattern, which still refuses an invented
    # slashed path. THERE IS NO "OFF": a switch whose off position refuses less than the
    # state before the change is a downgrade, not a rollback (María, 2026-08-26).
    "path_fab_mode"          : "pointer",
    # Names the path-fabrication check must never call an invented pointer. Seeded from
    # `_FAB_NOT_PATHS` and overridable by INI, so the day a real product name is refused
    # the fix is a config edit rather than a deploy (row f3d96537, María's note).
    "product_names"          : _FAB_NOT_PATHS,
}


def get_dm_tutor_config():
    """
    Read the tutor's runtime knobs from lupin-app.ini.

    Runtime-configurable was Rick's explicit requirement — "so that we can dial it
    down if we find that the length of the DMs is rising to the enforced limit" —
    so nothing here is a constant in code.

    Ensures:
        - returns a dict with enabled / trigger_claims / gate_enabled / gate_max_claims
        - a config-read failure returns the defaults with enabled FALSE, so an
          unreadable config delivers original messages rather than routing every DM
          in the fleet through a model on assumptions

    Raises:
        - nothing
    """
    from cosa.config.configuration_manager import ConfigurationManager
    try:
        cm = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
        return {
            "enabled"         : cm.get( "dm tutor enabled",                default=False, return_type="boolean" ),
            "trigger_claims"  : cm.get( "dm tutor trigger claims",         default=4,     return_type="int" ),
            "gate_enabled"    : cm.get( "dm tutor output gate enabled",    default=False, return_type="boolean" ),
            "gate_max_claims" : cm.get( "dm tutor output gate max claims", default=4,     return_type="int" ),
            "fab_guard_strict": cm.get( "dm tutor fabrication guard strict", default=True,  return_type="boolean" ),
            "attribution_guard"      : cm.get( "dm tutor attribution guard enabled",     default=True, return_type="boolean" ),
            "attribution_min_persons": cm.get( "dm tutor attribution guard min persons", default=3,    return_type="int" ),
            "path_fab_mode"          : _parse_path_fab_mode(
                cm.get( "dm tutor path fabrication guard mode", default="pointer" ) ),
            "product_names"          : _parse_product_names(
                cm.get( "dm tutor fabrication guard product names", default=None ) ),
        }
    except Exception as e:
        print( f"[dm-tutor] WARNING: config read failed, tutor OFF for this send: {e}" )
        return dict( _DM_TUTOR_DEFAULTS )


def _restore_dropped_pointers( original, rewritten ):
    """
    Put back any path or URL the rewrite lost. Returns the repaired text.

    ⚠️ THE DEFECT THIS FIXES WAS LIVE (Cheech, 2026-08-13): the tutor paraphrased a
    path out of a real DM and left the literal words "probe script path" in its place.
    The house rule the tutor exists to teach is "three sentences and A PATH" — so the
    single element the rule names by name is the one the rewrite destroyed, and the
    recipient was handed a message whose pointer had become prose.

    WHY THIS IS CODE AND NOT A PROMPT LINE. Asking the model to reproduce a path
    verbatim is a request that fails silently and only in the cases that matter — long
    messages, unusual paths. Lifting the pointers out of the model's reach and putting
    them back is a guarantee. It is the same reasoning that keeps the sentence COUNT in
    code: a model is the wrong instrument for exactness.

    Requires:
        - original and rewritten are strings

    ⚠️ ONLY PATHS COME BACK, AND ONLY ONE LINE OF THEM (Rick, 2026-08-21, row
    a0151611). This guard used to append EVERY dropped pointer token as its own line,
    8-hex row ids included, so a DM carrying fifteen identifiers was delivered with a
    run of bare hashes under it: "what is obviously pointless and nonsensical is 10 to
    12 lines of hashes… a standalone nonsensical out-of-context hash has no place
    there." A path survives losing the sentence around it — it still says where to
    look. An id does not. So the restore selects on `restorable_pointers`, which drops
    the bare-identifier shape, and appends at most ONE line.

    ONE LINE, EVERY DROPPED PATH ON IT (Rick's ruling, 2026-08-21). Discarding a real
    pointer is the exact defect this guard was built for, so the rare message that
    loses two paths gets both back — joined by a space, on the one appended line, in
    first-seen order. That cost one thing and it was paid rather than absorbed: a
    multi-pointer line did NOT match the counter's whole-line structure rule, so a
    compliant three-claim rewrite plus a two-path line counted FOUR. `_ATTACHMENT` now
    recognises a RUN of pointers as structure, which is what this module's own rule
    ("a line that asserts nothing is structure") always implied.

    Requires:
        - original and rewritten are strings

    Ensures:
        - a path, URL or bare filename present in `original` and absent from the
          rewrite is restored, whether it stood on its own line in the original or was
          buried mid-sentence (row a74f2176)
        - a BARE 8-hex row id is never restored — dropped by the model, it stays gone
        - a pointer the rewrite ALREADY kept is not duplicated — membership is checked
          against the rewrite's whole text, so a path the model correctly carried
          through inline (not as its own line) still counts as kept
        - returns `rewritten` unchanged when nothing restorable was dropped
        - at most ONE line is appended, carrying every dropped path joined by a space,
          which the counter treats as structure, so repairing a message can never push
          it back over the trigger

    Raises:
        - nothing
    """
    try:
        from cosa.agents.dm_tutor.sentences import restorable_pointers
        dropped = [ p for p in restorable_pointers( original ) if p not in rewritten ]
        if not dropped: return rewritten
        return rewritten.rstrip() + "\n" + " ".join( dropped )
    except Exception:
        # A repair that raises must never cost the caller the rewrite it already has.
        return rewritten


_FAB_NUM  = re.compile( r"\b\d[\d,.]*\b" )
_FAB_HEX  = re.compile( r"\b[0-9a-f]{7,40}\b" )
# THE PRE-2026-08-26 PATH PATTERN, KEPT ONLY AS THE ROLLBACK BRANCH (row f3d96537).
# It is NOT what runs: `dm tutor path fabrication guard mode` defaults to "pointer" and
# `_fabricated_paths` is the live check. This exists so that OFF means THE OLD BEHAVIOUR
# rather than NO behaviour — a kill switch whose off position is weaker than the state
# before the change is a downgrade, not a rollback (María's ruling, 2026-08-26).
#
# ⚠️ YES, THAT IS TWO CODE PATHS, and the `fab_guard_strict` comment below is right to warn
# against them. The difference is what the dial is FOR: strict/lenient is a threshold, and
# a threshold with two implementations can drift. This is a ROLLBACK, and a rollback that
# does not restore the prior behaviour exactly is not one. The legacy branch is pinned by
# tests so it cannot rot unnoticed.
_FAB_PATH_LEGACY = re.compile( r"(?:[A-Za-z][\w+.-]*://\S+|(?:[\w.@%+-]+/)+[\w.@%+-]*)" )


# 🔴 THE LIVE CHECK NO LONGER USES THE PATTERN ABOVE, AND THAT IS THE FIX (row f3d96537).
# It was a THIRD path pattern living beside the two in `cosa.agents.dm_tutor.sentences`,
# and it required a URL scheme or at least one slash — so a bare `filename.py` was not a
# path to it. The restore side's recogniser has always known that shape; its own
# docstring says "a path, URL or bare filename". Two patterns for one idea in one
# module, and the gap between them is where an invented filename walked through:
# `seven-guards-in-dm.py` was manufactured out of the prose "seven guards in dm.py" and
# delivered into the slot Rick ruled protected (a0151611). Measured, not asserted:
#     _FAB_PATH.findall( "seven-guards-in-dm.py" )     -> []
#     restorable_pointers( "seven-guards-in-dm.py" )   -> ['seven-guards-in-dm.py']
# So the repair is REUSE, not a fourth pattern. See `_fabricated_paths`.
_FAB_CAP  = re.compile( r"\b([A-Z][A-Za-z'’-]{2,})\b" )
_FAB_WORD = re.compile( r"[A-Za-z'’-]+" )

# Capitalised words that are NEVER names, however novel. A rewrite that opens a sentence
# with "The" has not invented an entity — it has started a sentence. Without this the
# guard refused a rewrite for fabricating the word "The", which is a false positive so
# cheap to remove that leaving it in would have cost real compression for no safety.
_FAB_NOT_NAMES = frozenset(
    "the a an and but or nor so then than that this these those there here it its they "
    "them their we our us you your i my me he she his her him if when while where what "
    "which who whom whose why how all any both each every few many more most other some "
    "such only same too very not no now also for from with without into onto over under "
    "after before during since until about against between because as at by in on to of "
    "is are was were be been being do does did done have has had will would can could "
    "should may might must shall let please note yes".split()
)


# ── V3-STRICT: the capitalised-dictionary-word exemption (row ddf7581e) ──────
#
# Rick ruled "V3-strict behind a flag" on 2026-08-18, live. The problem it solves:
# the name check flagged ordinary sentence-initial verbs — Update, Implement, Verify,
# Ensure, Use — as invented entities. Measured on 400 paired bodies (run
# 2026.08.18-mrradio-host-400): flash_lite 130 blocks -> 54, phi_4 67 -> 30.
#
# WHY "STRICT" AND NOT JUST "IS IT A DICTIONARY WORD". /usr/share/dict/american-english
# holds 20,494 CAPITALISED entries, so `rachel`, `clayton`, `krishna` and `tiffany` are
# all "dictionary words". Exempting any dictionary entry would stop the guard flagging
# invented PERSON names — which is the exact incident it was built for ("there was no
# reviewer"). So a capitalised token is exempt ONLY when the word list holds it as a
# LOWERCASE entry. Proper nouns live in the list capitalised and stay flaggable.
#
# THE COST, ACCEPTED KNOWINGLY BY RICK: the guard loses its one demonstrated true
# positive — a rewrite that turned "Force-recreated" into "Deployed". "deployed" is a
# lowercase entry, so that rewrite now ships. Do not special-case it back without
# telling him.
#
# ⚠️ VENDORED, NOT READ FROM THE HOST. /usr/share/dict exists on the dev box and NOT in
# the server container, so reading it at runtime would pass every local test and fail
# in production — a host-only dependency is invisible exactly where it matters.
#
# ⚠️ LOADED ONCE AT IMPORT, never per call: 83,815 entries is ~789 KB, and re-reading it
# on every DM would put a file read on the send path. `test_dm_fabrication_guard_strict.py`
# fails if the read moves back inside the function.
_FAB_STRICT_WORDLIST_REL = "/src/conf/dm-tutor-lowercase-words.txt"


def _load_lowercase_words( path ):
    """
    Read the vendored lowercase word list into a frozenset.

    Requires:
        - path names a UTF-8 text file, one lowercase word per line

    Ensures:
        - returns a frozenset of the non-blank lines, stripped
        - returns an EMPTY frozenset if the file cannot be read, after saying so on
          stdout. An empty set exempts nothing, so an unreadable list degrades to the
          pre-V3 behaviour — MORE blocking, never less. Failing toward the permissive
          side would silently disarm the guard, which is the opposite of what a missing
          file should do
        - NEVER raises. This runs at import; one bad file must not take the whole DM
          send path down with it
    """
    try:
        with open( path, encoding="utf-8" ) as fh:
            return frozenset( line.strip() for line in fh if line.strip() )
    except OSError as e:
        print( f"[dm-tutor] WARNING: lowercase word list unreadable, strict exemption OFF: {e}" )
        return frozenset()


def _strict_wordlist_path():
    """
    Absolute path of the vendored list. Separate from the load so a test can point at
    a fixture without monkeypatching `open`.

    Ensures:
        - returns the project-root-relative path resolved through the canonical helper
        - returns "" if the project root cannot be resolved, which `_load_lowercase_words`
          then reports as unreadable rather than raising at import
    """
    try:
        import cosa.utils.util as cu
        return cu.get_project_root() + _FAB_STRICT_WORDLIST_REL
    except Exception as e:                                    # pragma: no cover - defensive; get_project_root has no failing path in-tree
        print( f"[dm-tutor] WARNING: could not resolve project root for the word list: {e}" )
        return ""


_FAB_LOWERCASE_WORDS = _load_lowercase_words( _strict_wordlist_path() )


def _strict_exempt( token, wordlist ):
    """
    True when `token` is a capitalised form of a LOWERCASE word-list entry.

    ⚠️ THE CURLY APOSTROPHE IS NOT COSMETIC. The rewriter is a language model and emits
    U+2019 constantly. The vendored list holds ASCII apostrophes, so without this
    normalisation "Update's" is exempt and "Update’s" is blocked — the same word, the
    same meaning, opposite verdicts, decided by a character nobody can see in a diff.

    Requires:
        - token is a string, wordlist is a set of lowercase strings

    Ensures:
        - returns True iff the lowercased, apostrophe-normalised token is in wordlist
        - never raises
    """
    return token.lower().replace( "\u2019", "'" ) in wordlist


# ⚠️ A SENTENCE-FINAL FULL STOP HID A FABRICATED PATH, and an existing test caught it
# before this shipped. "See src/cosa/rest/routers/dm.py." tokenises as
# `src/cosa/rest/routers/dm.py.` — trailing dot included — which carries no code
# extension at its END, so the recogniser's own path-signal test discards it and the
# invented path becomes invisible. This lifts terminal punctuation off the word before
# the recogniser reads it. Exactly the family of the trailing-lookahead lesson recorded
# on `_RESCOPE_QUANTITY` above: a guard that sees mid-sentence and not sentence-final is
# a guard with a branch nobody runs.
_FAB_TERMINAL_STOP = re.compile( r"(?<=[\w])([.,;:!?)\]}])(?=\s|$)" )


def _fabricated_paths_legacy( original, rewritten ):
    """
    The pre-2026-08-26 path check, verbatim: a set difference over `_FAB_PATH_LEGACY`.

    Reached only when `dm tutor path fabrication guard mode` is "legacy". It cannot see a
    bare filename — that blindness IS the defect of row f3d96537 — but it does refuse an
    invented SLASHED path or URL, which is what makes it a rollback rather than a downgrade.

    Requires:
        - original and rewritten are strings

    Ensures:
        - returns the sorted slash- or scheme-bearing tokens in `rewritten` absent from
          `original`, and [] when there are none
        - never raises

    Raises:
        - nothing
    """
    try:
        return sorted( set( _FAB_PATH_LEGACY.findall( rewritten ) )
                       - set( _FAB_PATH_LEGACY.findall( original ) ) )
    except Exception:
        return []


def _fabricated_paths( original, rewritten, product_names=_FAB_NOT_PATHS ):
    """
    Pointer-shaped tokens the rewrite asserts that the original never vouched for.

    ⚠️ THE DEFECT THIS FIXES WAS LIVE (María, 2026-08-26, row f3d96537). The condenser
    read the prose "seven guards in dm.py" and delivered `seven-guards-in-dm.py` — a
    filename nobody has ever written, in the slot Rick ruled protected (a0151611). The
    old check could not see it: it carried its own path pattern requiring a slash or a
    URL scheme, so a bare filename was not a path to it, while the RESTORE side's
    recogniser had known that shape all along. This asks the restore side's question.

    ⚠️ AND IT IS NOT A SET DIFFERENCE OVER TOKENS, WHICH IS THE PART THAT COSTS MAIL.
    Measured on the 4,489 delivered rewrites in the corpus, a plain token-set difference
    flags 47 of them (1.05%) — because `restorable_pointers` lifts the WHOLE path out of
    the original, so a rewrite abbreviating `src/cosa/rest/todo_fifo_queue.py` to
    `todo_fifo_queue.py` reads as an invention. That is honest mail, and refusing it is
    this guard's own failure mode. So membership is a SUBSTRING test against the whole
    original — the exact mirror of `_restore_dropped_pointers`, which asks `p not in
    rewritten`. Same idea, same direction, one shape.

    Two further ways a rewrite can be faithful and still look novel, each earned by
    reading the hits rather than assumed:
      · CASE. "Registry.py" opening a sentence is `registry.py` capitalised, not a new
        file — 11 of the 26 substring hits were exactly this.
      · AN ELIDED SUFFIX. A sender writes "executor.py:106, :108, :115"; the rewrite
        expands ":108" to "executor.py:108" and cites precisely what was meant.

    ⚠️ ALL THREE RELAXATIONS ARE FITTED, NOT VALIDATED. They were derived by reading the
    hits on this corpus, so a rate computed on that same corpus is in-sample and must not
    be quoted as the cost. The out-of-sample figure is in the writeup.

    Requires:
        - original and rewritten are strings
        - product_names is a set of lowercase names

    Ensures:
        - returns a sorted list of pointer tokens in `rewritten` that `original` does not
          vouch for, and [] when there are none
        - a token already present in `original` in any letter case is never returned
        - a token of the form `file.ext:LINE` is not returned when `original` carries
          both the file and that `:LINE` suffix
        - a name in `product_names` is never returned
        - a pointer that ENDS a sentence is seen: terminal punctuation is lifted off the
          word before the recogniser reads it
        - never raises: an unreadable comparison returns [], which leaves the tutor
          exactly as safe as it was before this check existed

    Raises:
        - nothing
    """
    try:
        from cosa.agents.dm_tutor.sentences import restorable_pointers
        low   = original.lower()
        found = set()
        for token in restorable_pointers( _FAB_TERMINAL_STOP.sub( r" \1", rewritten ) ):
            candidate = token.lower()
            if candidate in low:            continue
            if candidate in product_names:  continue
            base, _, line = candidate.rpartition( ":" )
            # An elided suffix the sender did write: "executor.py:106, :108".
            if base and line.isdigit() and base in low and ( ":" + line ) in low: continue
            found.add( token )
        return sorted( found )
    except Exception:
        # A guard that raises must not take the send path with it.
        return []


def _fabricated_facts( original, rewritten, strict=True, product_names=_FAB_NOT_PATHS,
                       path_mode="pointer" ):
    """
    Checkable facts the rewrite asserts that the original never did. Empty = clean.

    ⚠️ THE FAILURE THIS BOUNDS is a different class from losing something. On
    2026-08-13 the tutor turned a message about a task-store row into three sentences
    about "the reviewer" wanting documentation. There was no reviewer. Cheech put the
    point better than I did: a DROPPED path is visibly missing, so he asked — an
    INVENTED one READS AS SIGNAL, and his first instinct was to work out which reviewer
    and which change. Only the rest of the message being incoherent stopped him.

    And it is UNBOUNDED: a rewriter that can add one fact can add any fact. No trigger
    value limits that, which is why raising the trigger was the wrong answer — it
    changes how often the dice are rolled, not what happens when they land wrong.

    Requires:
        - original and rewritten are strings

    Ensures:
        - returns { class: [values] } for numbers, hex ids, paths and capitalised names
          present in `rewritten` but NOT in `original`
        - `path_mode="legacy"` falls back to the PRE-2026-08-26 pattern, which
          still refuses an invented slashed path or URL and cannot see a bare filename;
          EVERY other value, recognised or not, asks the restore side's recogniser. The
          rollback is to the old behaviour, never to none, and a typo cannot cause one
        - NAMES are matched POSITION-INDEPENDENTLY against every word of the original,
          case-folded. An earlier version excluded sentence-initial words to cut false
          positives and thereby missed a fabricated name in the commonest position of
          all — the start of a sentence. The control caught that before it shipped.
        - never raises

    MEASURED against the 27 real rewrite pairs in the live corpus, not assumed:
        · fires on a fabricated sha, number, path and name (controls)
        · silent on a faithful rewrite and on a faithful reordering
        · blocks 1 of 27 real pairs (4%) — and that one replaced "Force-recreated" with
          "Deployed", a meaning change worth refusing anyway

    KNOWN LIMIT, stated because glossing it would be the same defect this guards
    against: it cannot see a fabricated COMMON NOUN. "the reviewer" is lowercase and
    passes untouched. A content-word novelty rule was measured as the alternative and
    REJECTED on the same corpus — it would have blocked 23 of 27, because paraphrasing
    is the entire point of the tutor. That class needs the fail-first prompt regression,
    which is not built.
    """
    try:
        def classes( text ):
            return {
                "number" : set( _FAB_NUM.findall( text ) ),
                "hex_id" : set( _FAB_HEX.findall( text ) ),
            }
        before, after = classes( original ), classes( rewritten )
        found = { k: sorted( after[ k ] - before[ k ] ) for k in before if after[ k ] - before[ k ] }

        # PATHS are asked separately, because the honest question is not a set difference
        # over tokens. See `_fabricated_paths`.
        # `!= "legacy"`, not `== "pointer"`: an unrecognised value resolves to the STRONGER
        # check here too, so a caller that skips `_parse_path_fab_mode` cannot weaken it.
        invented_paths = ( _fabricated_paths_legacy( original, rewritten )
                           if path_mode == "legacy"
                           else _fabricated_paths( original, rewritten, product_names=product_names ) )
        if invented_paths: found[ "path" ] = invented_paths

        original_words = { w.lower() for w in _FAB_WORD.findall( original ) }
        # V3-strict (row ddf7581e). `strict=False` reproduces the pre-V3 behaviour
        # EXACTLY, because an empty exemption set excludes nothing — that is what makes
        # the INI flag a real dial rather than two divergent code paths.
        exempt         = _FAB_LOWERCASE_WORDS if strict else frozenset()
        new_names      = sorted( { c for c in _FAB_CAP.findall( rewritten )
                                   if c.lower() not in original_words
                                   and c.lower() not in _FAB_NOT_NAMES
                                   and not _strict_exempt( c, exempt ) } )
        if new_names: found[ "name" ] = new_names
        return found
    except Exception:
        # A guard that raises must not take the send path with it. An unreadable
        # comparison means "nothing proven fabricated", which leaves the tutor exactly
        # as safe as it was before this check existed.
        return {}


# A QUANTITY is a standalone number. A digit inside an identifier is not one: `0c4e8cfa`
# is a row id, `v0.2.0` a version, `:8000` a port. The first cut of the measuring harness
# tokenised on digits alone, reported 8 corpus hits, and 6 of them were id fragments — the
# count read as a finding and was an artefact of the tokeniser.
#
# The trailing lookahead deliberately does NOT exclude a following "." — an earlier cut
# did, which made every sentence-FINAL quantity invisible to this guard ("…undercount by
# 400.") while every mid-sentence one was seen. A branch that never ran is what surfaced
# it; the suite was green at the time.
_RESCOPE_QUANTITY = re.compile( r"(?<![\w:/-])(?<!\.)\d[\d,]*(?!\.?\d)(?![\w:/-])" )
_RESCOPE_ROW_ID   = re.compile( r"^\d{8}$" )
_RESCOPE_TOKEN    = re.compile( r"[A-Za-z'’-]+|\d[\d,]*" )

# The closed vocabulary in which this fleet writes which SIDE of a ledger a quantity sits
# on. Not a grammar — the words that actually carried the distinction in a day's traffic.
_RESCOPE_LEDGER = frozenset(
    "by plus minus not no never without missing undercount undercounts undercounted "
    "excludes excluding excluded dropped lost short".split()
)


def _quantity_bindings( text ):
    """
    Map each standalone quantity in `text` to the ledger markers just before it.

    Requires:
        - text is a string

    Ensures:
        - returns { quantity: set( markers ) } over a 3-token window preceding each
          quantity, restricted to `_RESCOPE_LEDGER`
        - row-id-shaped tokens (8 digits) are excluded — an identifier is never on a
          side of a ledger
    """
    quants = { m.group( 0 ) for m in _RESCOPE_QUANTITY.finditer( text )
               if not _RESCOPE_ROW_ID.match( m.group( 0 ) ) }
    toks   = _RESCOPE_TOKEN.findall( text )
    out    = {}
    for i, t in enumerate( toks ):
        if t not in quants: continue
        window = { w.lower() for w in toks[ max( 0, i - 3 ) : i ] }
        out.setdefault( t, set() ).update( window & _RESCOPE_LEDGER )
    return out


def _rescoped_quantities( original, rewritten ):
    """
    Quantities the rewrite moved to the other side of a ledger. Empty = clean.

    ⚠️ THE FAILURE THIS BOUNDS is not fabrication, and `_fabricated_facts` is blind to it
    by construction. On 2026-08-14 the tutor turned

        "tonight's 72 commits undercount by whatever is in them"   (the 72 are COUNTED)

    into

        "the roll-up undercounts by 72 commits plus whatever is in the 7 modified files"
                                                                   (the 72 are MISSING)

    Every number in the output was in the input, so nothing was invented — a quantity
    changed which clause it was bound to. María had just published a roll-up containing
    those 72 commits; as delivered, a peer appeared to be telling her the number was
    wrong. She asked whether the line was the sender's, and that is the only reason it
    was caught.

    Requires:
        - original and rewritten are strings

    Ensures:
        - returns { quantity: [ markers gained ] } for quantities present in BOTH texts
          that gained a ledger marker they did not have
        - a quantity only the rewrite carries is IGNORED — that is the fabrication
          guard's job, and double-reporting would make each guard's count unreadable
        - never raises

    MEASURED on the live corpus — 315 real rewrite pairs, 193 carrying a quantity:
        · refusing any altered sentence with a numeral   → 104/193 (54%), unusable
        · refusing on ANY scope word gained              →   5/193 (2.6%), and all four
          extra blocks were read and benign ("D IS sections 7, 9" → "D INCLUDES …")
        · refusing on a LEDGER marker gained             →   1/193 (0.5%) — the real
          inversion, and nothing else in a day's traffic

    KNOWN LIMIT, stated rather than glossed: the ledger vocabulary is a closed set, so
    this catches the shape that occurred, not every re-scoping. A rewrite that inverts a
    meaning without one of those markers passes untouched.
    """
    try:
        before, after = _quantity_bindings( original ), _quantity_bindings( rewritten )
        found = {}
        for quantity, markers in after.items():
            if quantity not in before: continue
            gained = sorted( ( markers & _RESCOPE_LEDGER ) - before[ quantity ] )
            if gained: found[ quantity ] = gained
        return found
    except Exception:
        # Same call as the fabrication guard: a check that raises must not take the send
        # path with it. An unreadable comparison means "nothing proven re-scoped", which
        # leaves the tutor exactly as safe as it was before this existed.
        return {}


# A bare hex id — a store row id and a git sha are indistinguishable by shape, which is
# the whole reason the condenser guesses wrong.
_LABEL_HEX_ID = re.compile( r"(?<![\w/-])[0-9a-f]{7,40}(?![\w/-])" )
#
# THE HEX ALTERNATIVE MUST COME FIRST. With the word pattern leading, `b8d10bd3` tokenised
# as "b", "8", "d"… because the first alternative matches the leading letter — so every id
# beginning with a letter, roughly half of them, was invisible to this guard. The suite was
# green: one test passed because the id was never seen at all, rather than for the reason it
# asserted. An unrun branch is what surfaced it.
_LABEL_TOKEN  = re.compile( r"[0-9a-f]{7,40}(?![\w-])|[A-Za-z'’#-]+|\d[\d,]*" )

# The nouns that CLASSIFY an id. Carrying one the sender wrote is fine; supplying one
# they did not is a fact they never asserted.
_LABEL_NOUNS = frozenset(
    "commit sha hash revision rev row task bug job session branch tag pr issue "
    "message thread ticket id".split()
)

_LABEL_WINDOW = 3


def _id_label_bindings( text ):
    """
    Map each bare hex id in `text` to the type nouns sitting just before it.

    Requires:
        - text is a string

    Ensures:
        - returns { hex_id: set( nouns ) } over a 3-token preceding window
    """
    ids = { m.group( 0 ) for m in _LABEL_HEX_ID.finditer( text ) }
    out = {}
    # PER LINE, and that is load-bearing: `_restore_dropped_pointers` appends recovered
    # pointers on their own lines, so a window that crossed a newline read the last word
    # of the previous sentence as this id's label and refused a perfectly good rewrite.
    # A noun on another line is not labelling this id.
    for line in ( text or "" ).splitlines():
        toks = _LABEL_TOKEN.findall( line )
        for i, t in enumerate( toks ):
            if t not in ids: continue
            window = { w.lower().strip( "#" ) for w in toks[ max( 0, i - _LABEL_WINDOW ) : i ] }
            out.setdefault( t, set() ).update( window & _LABEL_NOUNS )
    return out


def _invented_id_labels( original, rewritten ):
    """
    Type nouns the rewrite attached to an id that the sender never attached. Empty = clean.

    ⚠️ THE FAILURE THIS BOUNDS is a fabricated fact that the fabrication guard cannot see,
    because the invented word is a lowercase COMMON NOUN — the limit `_fabricated_facts`
    names in its own docstring. Observed live: a store row `0c4e8cfa` delivered as
    "commit hash 0c4e8cfa", and a session `6794a377` delivered as "bug 6794a377".

    The reader's natural recovery — go look up that commit — fails silently, because the
    id resolves to nothing in git. It is invisible to the sender, who sees only what they
    wrote, and it reads exactly like the sender being sloppy: the filer of this row
    corrected a peer twice for mislabelling ids the peer had labelled correctly.

    A CORRECT guess is still reported. When the condenser calls row `52912c4f` a "row" it
    happens to be right — and a reader cannot distinguish that from a wrong guess, which
    is the failure itself.

    Requires:
        - original and rewritten are strings

    Ensures:
        - returns { hex_id: [ nouns gained ] } for ids present in BOTH texts
        - an id only the REWRITE carries is ignored — that is the fabrication guard's job
        - never raises
    """
    try:
        before, after = _id_label_bindings( original ), _id_label_bindings( rewritten )
        found = {}
        for hex_id, nouns in after.items():
            if hex_id not in before: continue
            gained = sorted( nouns - before[ hex_id ] )
            if gained: found[ hex_id ] = gained
        return found
    except Exception:
        return {}


def _strip_invented_id_labels( original, rewritten ):
    """
    Delete type nouns the rewrite invented, keeping the compression. Repair, not refusal.

    WHY REPAIR RATHER THAN REFUSE, measured on the live corpus (134 rewrite pairs carrying
    a bare hex id): 18 invent a noun. Refusing all 18 costs 13.4% of the tutor's output on
    a defect that is usually precisely repairable — one word, deletable without touching
    anything else the sender meant. Stripping fixes 12 of them cleanly.

    THE OTHER 6 ARE WHY THE CALLER MUST RE-CHECK. A naive strip cannot reach a noun that
    sits AFTER its id ("92062fe2, the commit, ...") or one exposed only once another is
    removed. A repair that reports success while the wrong noun is still on the wire is
    worse than a refusal, so `_apply_dm_tutor` re-runs the detector on the repaired body
    and refuses if anything survives.

    Requires:
        - original and rewritten are strings

    Ensures:
        - returns `rewritten` with invented type nouns removed where they can be reached
        - the ID ITSELF is never touched — losing it would be the pointer defect again
        - returns `rewritten` unchanged if anything raises
    """
    try:
        repaired = rewritten
        for hex_id, nouns in _invented_id_labels( original, rewritten ).items():
            for noun in nouns:
                repaired = re.sub(
                    r"(?i)\b" + re.escape( noun ) + r"\b[ ]+(?=(?:[A-Za-z]+[ ]+){0,2}" + re.escape( hex_id ) + r"\b)",
                    "", repaired )
        return repaired
    except Exception:
        return rewritten


# ── THE ATTRIBUTION GUARD (row cf1587cd) ─────────────────────────────────────
#
# THE DEFECT, filed by María 🌸 on Clayton 😎's finding, 2026-08-25: a condensed DM
# loses the SUBJECT of its claims, so the reader cannot tell WHOSE measurement a
# statement is about, or a report from an instruction. Four received messages in six
# minutes; two cost a clarifying round-trip, and a third was inverted far enough that
# Clayton apologised for an ambiguity the transport had made, not him.
#
# MEASURED before anything was written (src/rnd/v0.2.0/2026.08.26-dm-condenser-drops-
# sentence-subjects.md): 75 pairs from the traffic corpus read by eye — 50 to calibrate,
# 25 held out — give 22 losses, 29.3% (95% CI 20.2-40.4%). That is a FLOOR: two of the
# fifty are attribution INVERSIONS, where the rewrite names a person and names the wrong
# one, and nothing here can see those.
#
# 🔴 IT NO LONGER REFUSES — IT ONLY MEASURES (row 20026f56, Rick 2026-08-26). It shipped
# as a refusal, and the refusal cost the sender's full uncondensed original on 53-58% of
# all rewrites. Against that: three peer reports in three weeks, every one caught by the
# human reading it, and no error that reached a commit, an artifact or a decision. Paying
# more than half of all sends to prevent friction that was already being caught is the
# wrong trade, so the gate is open and the reader gets a pointed warning instead.
#
# ⚠️ THE MEASURING HALF IS UNCHANGED AND MUST STAY THAT WAY. The predicate below is the
# only instrument watching this drift, and the day-by-day trend line reads the outcome it
# writes. Stop recording and the rate silently reads zero, which looks exactly like a
# fixed defect. Rick's own words: track it while leaving the gate open.
#
# WHY IT DOES NOT RESTORE THE NAME EITHER. `_restore_dropped_pointers` restores because a
# path is self-contained: it still says where to look with the sentence around it gone. A
# SUBJECT IS NOT. Appending "Maria" on a line under three sentences does not tell a reader
# which sentence it belongs to - it produces the bare-token line Rick banned for hashes
# (a0151611), one class over. Whether a name can be placed back in its own slot is a
# separate feasibility question and is not answered here.
#
# WARNING: REGEX, NOT A PARSER, AND DELIBERATELY. The measurement instrument uses spaCy;
# this does not, because a 50 MB model loaded at import would be a new dependency on the
# send path for a check the other four guards make with `re`. The cost is stated rather
# than hidden: on 75 hand-labelled pairs this predicate agrees 83% of the time at 0.71
# precision and 0.68 recall. A false fire now costs one sentence of extra warning on a
# message that did not need it, which is cheaper still than the uncondensed original it
# used to cost.
_ATTRIB_PRONOUN = re.compile(
    r"\b(?:i|me|my|mine|myself|we|us|our|ours|you|your|yours|yourself|yourselves)\b",
    re.IGNORECASE
)

# A role that names NOBODY. "the developer has completed a review" leaves a job title
# where a name belonged. "the sender" is in here too: it usually decodes to the sender
# and is therefore NOT counted as a loss in the measurement - but as a REFUSAL trigger it
# earns its place, because the one inversion in Maria's own thread reads "The sender's
# figure is not in question" where the sender meant the RECIPIENT's figure.
_ATTRIB_ROLE = re.compile(
    r"\bthe\s+(?:sender|author|writer|speaker|developer|engineer|reviewer|manager|"
    r"worker|user|person|individual|team|seat|agent|assistant|maintainer|owner|"
    r"caller|recipient)\b",
    re.IGNORECASE
)


def _attribution_personas():
    """
    The fleet's persona names, read from the SAME key that allocates them.

    Hardcoding the roster here would rot the moment somebody joins the pool — the check
    would stop recognising a real name as attribution and start flagging that person's
    DMs. The voice pool is the live list, so it is the one to read.

    Ensures:
        - returns a lowercase list of persona names from `cc session voice persona pool`
        - returns [] if the config cannot be read, which costs recall and never
          correctness: a rewrite that keeps a pronoun still passes, and one that keeps
          only a name is flagged unnecessarily — the cheap direction

    Raises:
        - nothing
    """
    from cosa.config.configuration_manager import ConfigurationManager
    try:
        cm   = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
        pool = cm.get( "cc session voice persona pool", default="" )
        return [ name.strip().lower() for name in ( pool or "" ).split( "," ) if name.strip() ]
    except Exception:
        return []


def _attribution_prose( text ):
    """
    The claim-carrying prose, with pointer tokens blanked — what a person check may read.

    ⚠️ THE POINTERS MUST GO, and this was measured rather than guessed. A restored line
    reading `.claude-memento-cheech-80c17315.md` contains a persona name, so a rewrite
    that had thrown every person away scored as ATTRIBUTED because of the filename under
    it. Two of the six misses in the first calibration run were that one line.

    Requires:
        - text is a string

    Ensures:
        - returns the tutor's own prose lines joined, with every pointer token replaced
          by a space
        - returns the text unchanged if the counter module cannot be imported, which
          keeps the guard working on a degraded reading rather than not at all

    Raises:
        - nothing
    """
    try:
        from cosa.agents.dm_tutor.sentences import prose_lines, pointer_tokens
        joined = " ".join( prose_lines( text ) )
        for token in pointer_tokens( joined ):
            joined = joined.replace( token, " " )
        return joined
    except Exception:
        return text


def _count_attributions( text, personas ):
    """
    How many times a text points at a person.

    Requires:
        - text is a string
        - personas is a list of lowercase names

    Ensures:
        - returns a non-negative int counting first/second-person pronouns plus
          persona-name mentions
        - returns 0 rather than raising on anything

    Raises:
        - nothing
    """
    try:
        total = len( _ATTRIB_PRONOUN.findall( text ) )
        for name in personas:
            total += len( re.findall( r"\b" + re.escape( name ) + r"\b", text, re.IGNORECASE ) )
        return total
    except Exception:
        return 0


def _dropped_attribution( original, rewritten, min_persons=3 ):
    """
    Why a reader may not be able to attribute this rewrite, or "" when they can.

    ⚠️ THIS NO LONGER DECIDES DELIVERY (row 20026f56). It used to; the caller now records
    what it says and sends the rewrite anyway, with a sharper notice attached. Read a
    non-empty return as "flag this one", never as "refuse this one".

    Two conditions, either of which fires:

      DROPPED   the original points at people at least `min_persons` times and the
                rewrite points at none. The threshold exists because a message that
                mentions one person in passing can lose that mention without costing the
                reader anything, while one built on who-did-what cannot. Measured across
                the 75 labelled pairs, the threshold trades recall for precision:
                min 1 → 0.62 precision, min 3 → 0.71, min 5 → 0.75 at half the recall.

      FRAMED    the rewrite introduces a role noun that names nobody where the original
                used no such frame — "the developer has completed a review" in place of
                a name the sender wrote.

    Requires:
        - original and rewritten are strings
        - min_persons is a positive int

    Ensures:
        - returns "" when the reader can attribute the rewrite
        - returns a short human-readable reason otherwise, which the caller records on
          the corpus row — a finding nobody can read is an unauditable one
        - NEVER raises: on any internal failure it returns "", so a broken check flags
          nothing rather than mislabelling every DM in the fleet

    Raises:
        - nothing
    """
    try:
        personas = _attribution_personas()
        orig     = _attribution_prose( original or "" )
        rewrite  = _attribution_prose( rewritten or "" )

        orig_people    = _count_attributions( orig, personas )
        rewrite_people = _count_attributions( rewrite, personas )

        if orig_people >= min_persons and rewrite_people == 0:
            return f"dropped: original points at a person {orig_people}x, rewrite 0x"

        framed = _ATTRIB_ROLE.search( rewrite )
        if framed and not _ATTRIB_ROLE.search( orig ):
            return f"role noun names nobody: \"{framed.group( 0 )}\""

        return ""
    except Exception:
        return ""


def _count_claims( body_text ):
    """
    The CANONICAL sentence count — the claim counter (ruling 4, 2026-08-12).

    A sentence is a unit that carries a claim; structure (tables, code fences,
    headings, pointer lines, the canned P.S.) asserts nothing and is not counted.
    This is the counter the tutor's trigger reads, so the audit and the trigger can
    never disagree about how long a message is.

    Ensures:
        - returns a non-negative int
        - returns 0 rather than raising if the counter module cannot be imported,
          which reads as "no claims" and therefore never fires the tutor

    Raises:
        - nothing
    """
    try:
        from cosa.agents.dm_tutor.sentences import count_sentences
        return count_sentences( body_text )
    except Exception:
        return 0


def _apply_dm_tutor( body_text, config=None, rewrite_fn=None ):
    """
    Distil one DM body if it is over the trigger. Returns ( delivered_text, meta ).

    Requires:
        - body_text is a string

    Ensures:
        - returns ( text_to_deliver, meta_dict ) and NEVER raises
        - text_to_deliver is body_text UNCHANGED on every path except a successful,
          gate-passing rewrite
        - meta_dict always states the outcome explicitly, so a corpus reader can tell
          "the tutor was off", "it did not fire", "it fired and failed" and "it fired
          and rewrote" apart. These were one silence before; a row that merely lacks a
          rewrite cannot say WHICH of those four happened
        - `tutor_claims_out` is recorded only when a rewrite came back, so a null is
          honestly "no output existed", not "output measured as zero"

    Raises:
        - nothing
    """
    config = config if config is not None else get_dm_tutor_config()
    meta   = {
        "tutor_version"        : DM_TUTOR_VERSION,
        "tutor_enabled"        : bool( config[ "enabled" ] ),
        "tutor_trigger_claims" : config[ "trigger_claims" ],
        "tutor_gate_enabled"   : bool( config[ "gate_enabled" ] ),
        "tutor_fired"          : False,
        "tutor_outcome"        : "disabled",
        "tutor_claims_in"      : None,
        "tutor_claims_out"     : None,
        "tutor_words_in"       : None,
        "tutor_words_out"      : None,
        "tutor_error"          : None,
        # What the rewrite invented, when it was refused for inventing. Recorded rather
        # than merely logged: "the tutor refused something" is not answerable from a
        # log line the next reader does not have.
        "tutor_fabricated"     : None,
        # Which quantity changed sides, when a rewrite was refused for moving one. Same
        # reasoning as `tutor_fabricated`: "it refused something" is unanswerable from a
        # log line the next reader does not have.
        "tutor_rescoped"       : None,
        # Which ids had an invented type noun stripped (delivered) or left standing
        # (refused). Recorded either way, so a corpus reader can tell a repair from a
        # clean rewrite — a silent repair is an unauditable one.
        "tutor_id_labels"      : None,
        # Why a delivered rewrite may be hard to attribute, when the check fired. Same
        # reasoning as the two fields above: "the check fired" is unanswerable from a log
        # line the next reader does not have, and this check is the widest of the five.
        # 🔴 THIS FIELD AND `tutor_outcome` ARE THE WHOLE SENSOR now that nothing is
        # refused. Both are written on every fire; neither is optional.
        "tutor_attribution"    : None,
    }

    try:
        if not config[ "enabled" ]:
            return body_text, meta

        claims_in                 = _count_claims( body_text )
        meta[ "tutor_claims_in" ] = claims_in
        meta[ "tutor_words_in" ]  = dm_word_count( body_text )

        if claims_in <= config[ "trigger_claims" ]:
            meta[ "tutor_outcome" ] = "under_trigger"
            return body_text, meta

        # OVER THE TRIGGER — this is the one path that calls a model.
        meta[ "tutor_fired" ] = True
        if rewrite_fn is None:
            from cosa.agents.dm_tutor.agent import rewrite_dm as rewrite_fn

        rewritten = rewrite_fn( body_text )
        if not rewritten or not rewritten.strip():
            # rewrite_dm is itself fail-closed and returns None on every internal
            # failure; it does not say why. "model_failed" is therefore the honest
            # label for the whole class, not a diagnosis of one cause.
            meta[ "tutor_outcome" ] = "model_failed"
            return body_text, meta

        # Put back any pointer the model paraphrased away, BEFORE measuring — the
        # restored lines are structure, so they cannot change the claim count, but
        # measuring first would record a body that is not the one delivered.
        rewritten = _restore_dropped_pointers( body_text, rewritten )

        # INVENTED-ID-LABEL REPAIR — strip a type noun the sender never wrote, then
        # re-read. Runs BEFORE the fabrication and re-scoping checks so those judge the
        # body that will actually be delivered. Removing a word cannot invent a fact or
        # move a quantity, so this ordering cannot mask either of them. Row b1f3d2df.
        invented = _invented_id_labels( body_text, rewritten )
        if invented:
            meta[ "tutor_id_labels" ] = invented
            rewritten = _strip_invented_id_labels( body_text, rewritten )
            survived  = _invented_id_labels( body_text, rewritten )
            if survived:
                # The repair did not take — a noun the strip could not reach. Deliver the
                # sender's own words rather than a body that still mislabels an id.
                meta[ "tutor_outcome" ]   = "label_blocked"
                meta[ "tutor_id_labels" ] = survived
                print( f"[dm-tutor] REFUSED a rewrite that mislabels an id: {survived}" )
                return body_text, meta

        # FABRICATION CHECK — refuse a rewrite that asserts a fact the sender never did.
        # Runs AFTER the pointer restore so a path we put back is not itself read as
        # fabricated, and BEFORE the gate so a fabricating rewrite is refused on the
        # stronger ground of the two.
        fabricated = _fabricated_facts( body_text, rewritten,
                                        strict=config[ "fab_guard_strict" ],
                                        product_names=config[ "product_names" ],
                                        path_mode=config[ "path_fab_mode" ] )
        if fabricated:
            meta[ "tutor_outcome" ]     = "fabrication_blocked"
            meta[ "tutor_fabricated" ]  = fabricated
            print( f"[dm-tutor] REFUSED a rewrite that invented facts: {fabricated}" )
            return body_text, meta

        # RE-SCOPING CHECK — refuse a rewrite that moved a quantity to the other side of a
        # ledger. Runs next to the fabrication check because it is the same class of harm
        # arriving by a different route: the fabrication guard compares WHICH facts are
        # present, this one compares WHAT THEY ARE BOUND TO. Neither can see the other's
        # failure. Row c1a2e859.
        rescoped = _rescoped_quantities( body_text, rewritten )
        if rescoped:
            meta[ "tutor_outcome" ]  = "rescope_blocked"
            meta[ "tutor_rescoped" ] = rescoped
            print( f"[dm-tutor] REFUSED a rewrite that moved a quantity across a ledger: {rescoped}" )
            return body_text, meta

        # ATTRIBUTION CHECK — MEASURED, AND NO LONGER A REFUSAL (row 20026f56, Rick
        # 2026-08-26: "just because you turn the refusal guard off doesn't mean that you
        # can't track it"). Last of the checks because it is the widest: it fires on
        # 53-58% of rewrites, so running it ahead of the others would mask their
        # narrower, sharper findings behind this one's label in the corpus.
        #
        # 🔴 THE SENSOR IS THE POINT OF THIS BLOCK NOW. Refusing was costing the full
        # original on more than half of all sends to prevent a harm that, in three weeks
        # of reports, a human caught every time. Measuring costs nothing. So the
        # predicate still runs, the reason is still written to the row, and the rewrite
        # goes out with a sharper notice attached (`DM_TUTOR_ATTRIBUTION_NOTICE`).
        # Delete the recording and the day-by-day trend line goes dark with nothing said.
        attribution = None
        if config[ "attribution_guard" ]:
            attribution = _dropped_attribution( body_text, rewritten,
                                                min_persons=config[ "attribution_min_persons" ] )
            if attribution:
                meta[ "tutor_attribution" ] = attribution
                print( f"[dm-tutor] FLAGGED a rewrite the reader may not be able to attribute: {attribution}" )

        claims_out                 = _count_claims( rewritten )
        meta[ "tutor_claims_out" ] = claims_out
        meta[ "tutor_words_out" ]  = dm_word_count( rewritten )

        # OUTPUT GATE — ruled OFF by default. When an operator turns it on, a rewrite
        # that is itself over the limit is discarded rather than delivered, and the
        # original goes out. Kept configurable because it is the only defence if a
        # future model starts returning long "distillations".
        if config[ "gate_enabled" ] and claims_out > config[ "gate_max_claims" ]:
            meta[ "tutor_outcome" ] = "gate_rejected"
            return body_text, meta

        # `attribution_flagged` is a DELIVERED rewrite that the check fired on — the v5
        # `attribution_blocked` value meant the opposite (refused) and is not reused, so
        # nobody reads a delivered row as a refused one. Both are the same predicate:
        # count how often it fires by accepting either value, not just this one.
        meta[ "tutor_outcome" ] = "attribution_flagged" if attribution else "rewritten"

        # Tell the RECIPIENT the prose is not the sender's (Cheech, 2026-08-13), and tell
        # the ones who actually lost a name to go looking for it (row 20026f56).
        notice = DM_TUTOR_ATTRIBUTION_NOTICE if attribution else DM_TUTOR_NOTICE
        return rewritten.rstrip() + "\n" + notice, meta

    except Exception as e:
        # The send path must survive anything the tutor does. An exception here means
        # the original message is delivered and the row says so.
        meta[ "tutor_outcome" ] = "error"
        meta[ "tutor_error" ]   = f"{type( e ).__name__}: {e}"
        print( f"[dm-tutor] WARNING: tutor raised, delivering original: {meta[ 'tutor_error' ]}" )
        return body_text, meta


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
        - toggle OFF (control, default): returns None — no judge call and no audit
          tally, so the deferred job writes a corpus row with null grades
        - THIS RUNS ON THE GRADING WORKER, not in the send (row ec5cf83a). Nothing
          about the function changed; where it is CALLED did. No caller may put it
          back in a request's timeline.
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


# ─────────────────────────────────────────────────────────────────────────────
# DEFERRED GRADING (row ec5cf83a — Rick's ruling 2026-08-19, mechanism picked
# here). Grading a DM used to sit INSIDE the latency of accepting it: two live
# model calls to :3001 before execute_dm_send returned, so a slow grader made
# every fleet DM slow and a dead one made it slower still.
#
# MECHANISM AND WHY THIS ONE. A single background worker thread, fed by an
# in-process queue, that grades and then writes the corpus row.
#   · Not a durable queue: the grade is a measurement, not a message. Paying for
#     durability (a table, a broker, a replay path) to protect a statistic buys a
#     new failure surface on the fleet's comms bus to protect the least valuable
#     thing on it.
#   · Not a post-hoc sweep: a sweep would have to re-read the corpus and grade
#     rows after the fact, which needs the body kept somewhere anyway — the row
#     already carries it, so the sweep is strictly more machinery for the same
#     result, and it grades late by design rather than by accident.
#   · ONE worker, not a pool: grades are order-insensitive but the corpus is an
#     append-only file, and one writer means no interleaved lines. It also caps
#     concurrent load on :3001 at exactly one conversation.
#
# BOUNDED BACKLOG, and it is the part that keeps this honest under load: the
# worker is single-threaded and each grade is two model calls, so a fleet burst
# can outrun it. Past _DM_GRADE_MAX_PENDING the deferral is REFUSED and the
# corpus row is written immediately WITHOUT a grade. A message with no grade yet
# is a normal state (Mr Radio's ruling); a message with no ROW is a lost
# measurement, which is not.
# ─────────────────────────────────────────────────────────────────────────────

_DM_GRADE_MAX_PENDING = 32
_dm_grade_executor    = None
_dm_grade_lock        = threading.Lock()
_dm_grade_audit       = {
    "accepted"             : 0,
    "refused"              : 0,   # backlog full
    "refused_under_pytest" : 0,   # the self-guard below
    "pending"              : 0,
    "failed"               : 0,
}


def get_dm_grade_audit():
    """A copy of the deferred-grade counters (accepted / refused / pending /
    failed). A copy, not the dict, so a reader cannot mutate the tally."""
    with _dm_grade_lock:
        return dict( _dm_grade_audit )


def reset_dm_grade_audit():
    """Zero the deferred-grade counters — test seam and operator reset."""
    with _dm_grade_lock:
        for key in _dm_grade_audit:
            _dm_grade_audit[ key ] = 0


def _get_dm_grade_executor():
    """The single grading worker, built on first use so a server that never
    sends a DM never starts a thread."""
    global _dm_grade_executor
    if _dm_grade_executor is None:
        _dm_grade_executor = ThreadPoolExecutor( max_workers=1, thread_name_prefix="dm-grade" )
    return _dm_grade_executor


def _submit_deferred_grade( job ):
    """
    Hand `job` to the grading worker.

    Requires:
        - job is a 0-arg callable

    Ensures:
        - SELF-GUARD (same shape as _persist_dm_row's, row f5d6dc5e): under pytest
          the deferral is ALWAYS refused and no worker is ever started. A unit test
          cannot reach the live grader through this default, and no grading thread
          can outlive the test that spawned it — which is how the toggle pins the
          send-path tests rely on stopped working the moment grading became
          asynchronous: the background call landed AFTER the patch context exited
          and dialled :3001 for real. A test that WANTS to exercise grading injects
          `defer_grade_fn` and owns the timing.
        - returns True iff the job was accepted onto the worker
        - returns False, and runs NOTHING, when _DM_GRADE_MAX_PENDING jobs are
          already outstanding — the caller then writes its row ungraded
        - a job that raises is caught, counted and printed; the worker survives

    Raises:
        - nothing
    """
    if _running_under_pytest():
        with _dm_grade_lock:
            _dm_grade_audit[ "refused_under_pytest" ] += 1
        return False
    with _dm_grade_lock:
        if _dm_grade_audit[ "pending" ] >= _DM_GRADE_MAX_PENDING:
            _dm_grade_audit[ "refused" ] += 1
            print(
                f"[dm-grade] WARNING: deferred grade REFUSED — {_dm_grade_audit[ 'pending' ]} "
                f"already pending (cap {_DM_GRADE_MAX_PENDING}); the corpus row is written "
                f"ungraded. Refused so far: {_dm_grade_audit[ 'refused' ]}."
            )
            return False
        _dm_grade_audit[ "pending" ]  += 1
        _dm_grade_audit[ "accepted" ] += 1

    def _run():
        try:
            job()
        except Exception as e:
            # The grader itself is contracted never to raise; this catches the
            # corpus write and anything a future job adds. A worker thread that
            # dies takes every LATER grade with it, which is a silent stop.
            with _dm_grade_lock:
                _dm_grade_audit[ "failed" ] += 1
            print( f"[dm-grade] WARNING: deferred grade job failed: {e}" )
        finally:
            with _dm_grade_lock:
                _dm_grade_audit[ "pending" ] -= 1

    _get_dm_grade_executor().submit( _run )
    return True


# The grade notice's identity. It comes from the JUDGE, not from the peer who was
# messaged — a grade wearing the recipient's name would read as that peer replying.
_DM_GRADE_SENDER_ID = "dm-quality-judge@lupin.deepily.ai"
_DM_GRADE_PERSONA   = "DM Quality Judge"
_DM_GRADE_ICON      = "⚖️"


def format_dm_grade_notice( message_id, quality ):
    """
    The one-line grade notice pushed back to a sender.

    Requires:
        - message_id is the id of the DM being graded
        - quality is DmQualityJudge.judge()'s dict

    Ensures:
        - NAMES THE MESSAGE IT GRADES (Mr Radio's constraint, 2026-08-19). A late
          grade with no anchor is the same confusion arriving slower: by the time it
          lands the sender may have sent three more DMs, and a bare "👎 too long"
          cannot say which one it means.
        - a dimension whose weight is None (LENGTH-ONLY mode) is shown as withheld
          rather than as a zero
    """
    def dimension( name ):
        d = quality[ name ]
        if d[ "weight" ] is None:
            return f"{name} —"
        return f"{name} {d[ 'emoji' ]} {d[ 'weight' ]:+d}"
    dimensions = " · ".join( dimension( n ) for n in ( "length", "directness", "tone", "overall" ) )
    return f"[grade for DM {message_id}] {dimensions}"


def push_dm_grade_to_sender( *, notification_queue, authenticated_user_id, sender_session_id,
                             message_id, quality ):
    """
    Deliver a finished grade back to the seat that sent the DM.

    Requires:
        - sender_session_id is the SENDER's session id (routing is by its 8-char head,
          the same job_id convention the DM itself uses)

    Ensures:
        - the sender keeps seeing its own grades. That feedback IS the live
          intervention — arm `signal_only`, "grade shown, nothing refused" — so moving
          the grade off the send path without this would have quietly ended the
          experiment rather than relocated it.
        - BEST-EFFORT AND SILENT (Mr Radio's constraint): a reaped seat is a normal
          outcome, not an error. The push is fire-and-forget onto the notification
          queue, which routes by job_id and simply reaches nobody when that seat is
          gone; anything raised is caught and printed, never propagated. A grading
          worker that dies on a departed recipient would take every LATER grade with it.
        - NOT a DM. It rides push_notification directly, so it never re-enters the send
          path — a grade delivered by dm_send would itself be graded, forever.
        - returns True iff the notice was pushed

    Raises:
        - nothing
    """
    if quality is None:
        return False
    try:
        notification_queue.push_notification(
            message        = format_dm_grade_notice( message_id, quality ),
            type           = "task",
            priority       = "low",
            id             = f"dm-grade-{message_id}",
            sender_id      = _DM_GRADE_SENDER_ID,
            job_id         = sender_session_id[ :8 ],
            user_id        = authenticated_user_id,
            suppress_ding  = True,
            direction      = "ai_to_ai",
            sender_persona = _DM_GRADE_PERSONA,
            sender_icon    = _DM_GRADE_ICON,
        )
        return True
    except Exception as e:
        print( f"[dm-grade] WARNING: could not deliver the grade for {message_id}: {e}" )
        return False


def _defer_grade_and_persist( *, defer_fn, grade_quality_fn, body_text, persist_kwargs,
                              deliver_grade_fn=None ):
    """
    Grade `body_text` and write its corpus row OFF the send path.

    Requires:
        - defer_fn( job ) -> bool accepts a 0-arg callable and reports whether it
          took it (the production default is _submit_deferred_grade)
        - persist_kwargs is every _persist_dm_row argument EXCEPT `quality`
        - deliver_grade_fn( quality ), when given, hands the finished grade back to
          the sender. It runs AFTER the row is written — the corpus is the durable
          record and must not be at the mercy of a delivery — and its failures are
          caught here as well as inside it

    Ensures:
        - the caller's timeline contains no model call: on the accepted path this
          returns as soon as the job is queued
        - EXACTLY ONE corpus row is written per call, whether the deferral was
          accepted (written by the worker, with the grade) or refused (written
          here, with quality=None)
        - a grader that RAISES still leaves a row, ungraded. DmQualityJudge.judge
          is contracted never to raise, and this catches it anyway: a broken
          contract would otherwise cost the corpus its row as well as its grade,
          and the row is the part that cannot be recomputed later
        - a REFUSED deferral delivers no grade, because there is no grade — the row
          is written ungraded and the sender simply hears nothing

    Raises:
        - nothing the caller must handle — _persist_dm_row is fail-soft
    """
    def _job():
        try:
            quality = grade_quality_fn( body_text )
        except Exception as e:
            print( f"[dm-grade] WARNING: grader raised, writing the row ungraded: {e}" )
            quality = None
        _persist_dm_row( quality=quality, **persist_kwargs )
        if deliver_grade_fn is not None:
            try:
                deliver_grade_fn( quality )
            except Exception as e:
                print( f"[dm-grade] WARNING: grade delivery raised: {e}" )

    if not defer_fn( _job ):
        _persist_dm_row( quality=None, **persist_kwargs )


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


# ─────────────────────────────────────────────────────────────────────────────
# Two-arm verbosity pilot — per-slot last-gate memory for `follows_rejection`
# (plan item 4). Keyed by ( slot_id, sender_session_id ) → the last length_gate
# outcome that sender saw IN THAT SLOT. Keying on slot_id is what resets the flag
# at every hour boundary: the first attempt a sender makes in a new block finds no
# entry and is always follows_rejection=False, so a rejecting hour never inherits a
# flag from the blind hour before it (the boundary the mirrored schedule protects).
# ─────────────────────────────────────────────────────────────────────────────
_last_gate_by_slot_sender = {}


def reset_dm_experiment_state():
    """
    Clear the per-slot last-gate memory.

    Ensures:
        - _last_gate_by_slot_sender is empty — a fresh window (and every test) starts
          with no carried `follows_rejection` state
    """
    _last_gate_by_slot_sender.clear()


def _prepare_outbound( *, body, target_session_id, build_sender_id, new_id_fn, now_fn ):
    """
    Build the sender_id, threading, and EDT-stamped body for an outbound DM.

    This is the PRE-DELIVERY step: nothing here persists or pushes anything, so a
    failure in it means the DM was never attempted (distinct from a delivery-time
    failure). Shared verbatim by the baseline and experiment send paths.

    Requires:
        - build_sender_id( sender_session_id, sender_project ) -> sender_id str
        - new_id_fn() -> a fresh message id str

    Ensures:
        - returns ( sender_id, job_id, message_id, thread_id, stamped_body )
        - job_id is the recipient's 8-char session hash (the persisted addressee)
        - stamped_body carries the central EDT prefix unless the body is already
          stamped (idempotent, bug f49a8b34 / bc8d9d82)
    """
    sender_id    = build_sender_id( body.sender_session_id, body.sender_project )
    job_id       = target_session_id[ :8 ]
    message_id   = new_id_fn()
    thread_id    = body.thread_id or message_id
    stamped_body = body.body if is_already_stamped( body.body ) else \
        f"{format_edt_timestamp( dt=now_fn() if now_fn is not None else None )} {body.body}"
    return sender_id, job_id, message_id, thread_id, stamped_body


def _dispatch_outbound( *, prep, body, authenticated_user_id, notification_queue,
                        persist_fn, target_session_id, target_persona ):
    """
    Persist + push the ai_to_ai DM and build the 201 result dict.

    This is the DELIVERY step: a failure here means delivery was ATTEMPTED (which is
    why the experiment path marks the row "failed" before calling it). Shared verbatim
    by the baseline and experiment send paths.

    Requires:
        - prep is the tuple from _prepare_outbound

    Ensures:
        - persists the DM (direction='ai_to_ai', stamped body inline) and pushes it
        - returns the 201 result dict (message_id, thread_id, recipient_session,
          recipient_session_hash8, recipient_persona, dispatched)

    Raises:
        - propagates any persist_fn / push_notification error to the caller
    """
    sender_id, job_id, message_id, thread_id, stamped_body = prep
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
    return {
        "http_status"             : 201,
        "message_id"              : db_id or message_id,
        "thread_id"               : thread_id,
        "recipient_session"       : target_session_id,
        "recipient_session_hash8" : job_id,
        "recipient_persona"       : target_persona,
        "dispatched"              : True,
    }


def _execute_experiment( *, body, assignment, arrival_utc, target_session_id, target_persona,
                         authenticated_user_id, notification_queue, build_sender_id, persist_fn,
                         new_id_fn, now_fn, grade_quality_fn, defer_grade_fn ):
    """
    Run the in-window (experiment) send path: resolve the arm, apply the length gate,
    and write ONE corpus row that survives a crash (plan items 3/4/5).

    Requires:
        - assignment is the slot dict from dm_experiment.assignment_at (non-None), so
          this send fell inside a declared experiment interval
        - arrival_utc is the SINGLE resolved arrival instant (never re-read here)

    Ensures:
        - arm resolution: an operator override (if set) beats the scheduled arm; the
          arbiter sender is exempt from the gate; otherwise the slot's arm applies
        - length gate: `rejecting` + over threshold + not exempt → HTTP 413 with a body
          that states the action WITHOUT naming the threshold (undisclosed)
        - the `quality` key is ABSENT from every in-window 201 (both arms) — a
          present-but-empty grade would itself signal measurement
        - exactly ONE corpus row is written, in a finally, so a crash before or during
          delivery still persists an honest `delivery_outcome` (never null/absent):
          not_attempted (never delivered), failed (delivery raised), delivered (ok)
        - `follows_rejection` reflects this sender's previous attempt IN THIS SLOT only

    Raises:
        - propagates a delivery-time error after the row is flushed with "failed"
    """
    policy          = dm_experiment.get_policy()
    scheduled_arm   = assignment[ "arm" ]
    slot_id         = assignment[ "slot_id" ]
    threshold       = policy.reject_threshold
    is_exempt       = ( body.sender_session_id in policy.exempt_sender_session_ids )
    override_arm    = policy.override_arm
    override_reason = policy.override_reason if override_arm is not None else None
    effective_arm   = override_arm if override_arm is not None else scheduled_arm

    word_count      = dm_word_count( body.body )
    # eligible_for_rejection: the gate is LIVE for this row (rejecting arm, not exempt).
    eligible        = ( effective_arm == "rejecting" and not is_exempt )

    # follows_rejection is stamped from the PREVIOUS attempt's gate outcome in THIS slot,
    # BEFORE this attempt updates the memory below.
    prior             = _last_gate_by_slot_sender.get( ( slot_id, body.sender_session_id ) )
    follows_rejection = ( prior == "rejected" )

    if is_exempt:
        length_gate      = "exempt"
        exemption_reason = f"arbiter sender exempt: '{body.sender_session_id}' matched the exempt list — gate skipped"
        # LOG EVERY HIT with the id that matched (María, 2026-08-03). This turns the
        # three-id hedge into an instrument: if ZERO exemptions fire on Tuesday, the
        # arbiter's real id is a fourth string and its pokes have been silently
        # rejected all along — without this line a working exemption and a completely
        # missed one look identical. Same print convention as the audit lines above.
        print(
            f"[dm-experiment] EXEMPTION HIT: sender '{body.sender_session_id}' matched the "
            f"exempt list — length gate skipped (slot {slot_id})"
        )
    elif eligible and word_count > threshold:
        length_gate      = "rejected"
        exemption_reason = None
    else:
        length_gate      = "passed"
        exemption_reason = None

    # Record THIS attempt's gate for the NEXT attempt in this slot (per-sender, per-slot).
    _last_gate_by_slot_sender[ ( slot_id, body.sender_session_id ) ] = length_gate

    row = {
        "schedule_id"            : policy.schedule_id,
        "slot_id"                : slot_id,
        "scheduled_arm"          : scheduled_arm,
        "effective_arm"          : effective_arm,
        "assigned_at_utc"        : arrival_utc.isoformat(),
        "reject_threshold"       : threshold,
        "eligible_for_rejection" : eligible,
        "exemption_reason"       : exemption_reason,
        "length_gate"            : length_gate,
        "delivery_outcome"       : "not_attempted",
        # The delivery MOMENT (UTC ISO), or None when never delivered. `ts` is the
        # row-WRITE time; the delivery-delay secondary (delivered_at − assigned_at_utc)
        # is unrecoverable after Tuesday if it is not captured now (Cheech, 2026-08-03).
        "delivered_at"           : None,
        "follows_rejection"      : follows_rejection,
        "est_tokens"             : len( body.body ) // 4,   # chars/4 ESTIMATE — no tokenizer before Tuesday
        "word_count_version"     : WORD_COUNT_VERSION,
        "override_reason"        : override_reason,
        "experiment"             : policy.experiment,
    }

    # Delivered sends get their grade DEFERRED (row ec5cf83a); every other outcome
    # (413 refusal, delivery failure) never had a grade to defer and writes its row
    # inline, so the crash-honest `delivery_outcome` contract below is untouched.
    graded_delivery = False
    try:
        if length_gate == "rejected":
            # Undisclosed refusal: state the action, never the number (413, NOT 422 —
            # the client maps 422 to recipient_unresolved, cosa_voice_mcp.py:3370).
            return {
                "http_status" : 413,
                "detail"      : "DM refused: too long. Cut it substantially and resend.",
            }
        # PRE-DELIVERY: a crash in prep leaves delivery_outcome at not_attempted.
        prep = _prepare_outbound(
            body=body, target_session_id=target_session_id,
            build_sender_id=build_sender_id, new_id_fn=new_id_fn, now_fn=now_fn,
        )
        # DELIVERY: mark "failed" first, so a persist/push raise persists an honest value.
        row[ "delivery_outcome" ] = "failed"
        result = _dispatch_outbound(
            prep=prep, body=body, authenticated_user_id=authenticated_user_id,
            notification_queue=notification_queue, persist_fn=persist_fn,
            target_session_id=target_session_id, target_persona=target_persona,
        )
        row[ "delivery_outcome" ] = "delivered"
        row[ "delivered_at" ]     = datetime.now( timezone.utc ).isoformat()
        # The judge still runs in-window for the corpus + audit tally, and its grade is
        # still NOT returned to the sender (quality key absent in both arms) — what
        # changed is WHEN: it now runs on the grading worker, after this returns.
        graded_delivery = True
        return result
    finally:
        persist_kwargs = {
            "body_text"    : body.body,
            "from_persona" : body.sender_persona,
            "from_session" : body.sender_session_id,
            "from_project" : body.sender_project,
            "to_persona"   : target_persona,
            "to_session"   : target_session_id,
            "experiment"   : row,
        }
        if graded_delivery:
            # NO deliver_grade_fn IN-WINDOW, deliberately. The baseline path pushes the
            # finished grade back to its sender; doing that here would hand a blind-arm
            # sender the very signal the arm exists to withhold, which is the same reason
            # the in-window 201 carries no `quality` key in either arm.
            _defer_grade_and_persist(
                defer_fn         = defer_grade_fn,
                grade_quality_fn = grade_quality_fn,
                body_text        = body.body,
                persist_kwargs   = persist_kwargs,
            )
        else:
            _persist_dm_row( quality=None, **persist_kwargs )


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
    arrival_utc_fn   = None,
    defer_grade_fn   = None,
    deliver_grade_fn = None,
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
        - defer_grade_fn( job ) -> bool decides WHERE the grade + corpus row run.
          Production leaves it None → the grading worker. A test injects an inline
          runner so the row exists by the time it asserts on it.
        - deliver_grade_fn( quality ) is the seam for HOW the finished grade reaches
          the sender. Production leaves it None → push_dm_grade_to_sender.

    Ensures:
        - NO MODEL CALL HAPPENS IN THIS FUNCTION'S TIMELINE (row ec5cf83a). Grading
          is queued and returns; a grader that is slow, dead or absent costs the
          sender nothing and fails no send. The 201 therefore carries NO `quality`
          key — the grade does not exist yet, and a message with no grade yet is a
          normal state
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
    # which returns None (null grades in the corpus row) whenever the toggle is OFF.
    # Since row ec5cf83a this is called by the grading WORKER, never in this timeline.
    if grade_quality_fn is None:
        grade_quality_fn = _maybe_grade_dm_quality
    # Row ec5cf83a: grading is OFF the send path. This seam decides WHERE the grade
    # runs — production hands it to the grading worker; a test injects a runner that
    # executes inline so the corpus row is written before the assertion reads it.
    if defer_grade_fn is None:
        defer_grade_fn = _submit_deferred_grade
    # Resolve the experiment arrival instant ONCE, here, before any slow resolution —
    # then thread it through the gate, logging, and response so a send that crosses an
    # hour boundary is scored against a single arm (arrival_utc_fn is the test seam).
    if arrival_utc_fn is None:
        arrival_utc_fn = lambda: datetime.now( timezone.utc )
    arrival_utc = arrival_utc_fn()

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
    # Two-arm pilot fork (plan item 3): resolve the slot for the ONE arrival instant.
    # None → outside every interval → today's exact baseline behaviour. A slot dict →
    # the experiment path (gate + suppressed grade + crash-safe corpus row).
    assignment = dm_experiment.assignment_at( arrival_utc )
    if assignment is not None:
        return _execute_experiment(
            body                  = body,
            assignment            = assignment,
            arrival_utc           = arrival_utc,
            target_session_id     = target_session_id,
            target_persona        = target_persona,
            authenticated_user_id = authenticated_user_id,
            notification_queue    = notification_queue,
            build_sender_id       = build_sender_id,
            persist_fn            = persist_fn,
            new_id_fn             = new_id_fn,
            now_fn                = now_fn,
            grade_quality_fn      = grade_quality_fn,
            defer_grade_fn        = defer_grade_fn,
        )

    # ── BASELINE (outside the experiment window) — and, since the two-arm pilot is
    # suspended, the ONLY live path. This is where the tutor runs.
    #
    # ORDER MATTERS: the tutor rewrites BEFORE _prepare_outbound, so the distilled
    # text is what gets EDT-stamped, persisted to the notification store, and pushed
    # to the recipient. Rewriting after prep would deliver the original and record a
    # rewrite that nobody received — the corpus would then describe a treatment the
    # fleet never got.
    submitted_text     = body.body
    delivered_text, tutor_meta = _apply_dm_tutor( submitted_text )
    if delivered_text != submitted_text:
        # Mutating the request model is deliberate: _prepare_outbound and
        # _dispatch_outbound both read body.body, and threading a separate text
        # through them would leave two sources of truth for "what are we sending".
        body.body = delivered_text

    prep   = _prepare_outbound(
        body=body, target_session_id=target_session_id,
        build_sender_id=build_sender_id, new_id_fn=new_id_fn, now_fn=now_fn,
    )
    result = _dispatch_outbound(
        prep=prep, body=body, authenticated_user_id=authenticated_user_id,
        notification_queue=notification_queue, persist_fn=persist_fn,
        target_session_id=target_session_id, target_persona=target_persona,
    )

    # Row ec5cf83a (Rick's ruling 2026-08-19): the grade AND the corpus row it rides
    # on now run on the grading worker, not here. The send returns on the send.
    #
    # WHAT THE SENDER SEES CHANGED, deliberately: the 201 no longer carries a
    # `quality` key at all. It cannot — the grade does not exist yet when this
    # returns, and holding the response until it did is the defect. A grade with
    # no message to attach to is the only thing worse than a message with no grade.
    #
    # WHAT THE JUDGE SEES DID NOT: it still grades what was actually DELIVERED
    # (`body.body` carries the tutor's rewrite when one happened), not the raw
    # submission and not the EDT-stamped outbound body. Grading the submitted text
    # would score a message nobody received, and the length grade in particular
    # would then describe the problem the tutor had just solved.
    #
    # Row 334569d6's corpus row (measurements + body + grades) is written by the same
    # deferred job, so a row and its grade still arrive together. Fail-soft lives
    # inside the writer. `experiment=None` → the row keeps its legacy `arm` stamp (no
    # two-arm fields), the outside-window contract.
    #
    # THE SENDER STILL GETS ITS GRADE, just not in the response. That feedback is the
    # live intervention (arm `signal_only`: grade shown, nothing refused), so the
    # worker pushes it back naming the message it graded — Mr Radio's ruling and its
    # two constraints, 2026-08-19. It is deliberately NOT sent as a DM: a grade
    # delivered by dm_send would itself be graded, forever.
    _defer_grade_and_persist(
        defer_fn         = defer_grade_fn,
        grade_quality_fn = grade_quality_fn,
        body_text        = body.body,
        deliver_grade_fn = ( deliver_grade_fn if deliver_grade_fn is not None else
                             lambda quality: push_dm_grade_to_sender(
                                 notification_queue    = notification_queue,
                                 authenticated_user_id = authenticated_user_id,
                                 sender_session_id     = body.sender_session_id,
                                 message_id            = result[ "message_id" ],
                                 quality               = quality ) ),
        persist_kwargs   = {
            "body_text"      : submitted_text,
            "delivered_text" : delivered_text,
            "tutor"          : tutor_meta,
            "from_persona"   : body.sender_persona,
            "from_session"   : body.sender_session_id,
            "from_project"   : body.sender_project,
            "to_persona"     : target_persona,
            "to_session"     : target_session_id,
        },
    )

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
