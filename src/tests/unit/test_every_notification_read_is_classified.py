"""
EVERY query-bearing read on NotificationRepository is CLASSIFIED, and adding a new one
without classifying it turns this file red. Row 4f320c27 follow-up.

🔴 THE DEFECT THIS EXISTS TO PREVENT, and it is the one Mr. Radio named. The fix for the
ack leak was six `Notification.type.notin_( … )` clauses, one per query. That is an
ENUMERATION, not a predicate: it is correct on the day it is written and silently wrong
the first time somebody adds a twenty-third read. Nothing would fail. The new read would
simply answer with rows that are not messages, invisibly — which is exactly how the first
six got there.

So the control is not "remember the filter". It is: **you cannot add a read without
saying which kind it is.** `CLASSIFICATION` below must name every query-bearing public
method, and the denominator is derived by INTROSPECTION rather than typed out — a method
this file has never heard of is a failure, not a silent pass.

THE PREDICATE, stated once so the classification is a judgement and not a vibe:
    a read is CONVERSATION_FACING iff its answer is shown to the user as their messages,
    their correspondents, or a count of either.
A broadcast ack is a tally element addressed to the broadcaster — no body, no reply, and
its own endpoint (`get_latest_acks_for_broadcast`) to be read from. It is therefore never
part of that answer.

WHAT EACH BUCKET ASSERTS
  CONVERSATION_FACING  — the rendered SQL must carry the exclusion. Measured, not assumed.
  ACK_SURFACE          — must NOT carry it; this is the read that exists to return acks.
  STRUCTURALLY_IMMUNE  — its own filters already exclude acks, so the clause would be
                         dead weight. The REASON is recorded per method, because
                         "immune" without a mechanism is just a hope.
  LEFT_DELIBERATELY    — returns acks and is knowingly untouched (no live caller).
  WRITE_PATH           — deletes/updates. MUST NOT exclude: a row you refuse to see is a
                         row the user can never clear.

⚠️ THE STRUCTURALLY_IMMUNE CLAIMS ARE MEASURED IN A SIBLING FILE, NOT HERE.
`src/tests/smoke/test_acks_are_not_conversations.py` runs the real queries against a real
Postgres holding exactly one ack. This file is static: it pins the classification and the
SQL. Neither is sufficient alone — static analysis cannot prove a filter excludes, and a
behavioural test cannot prove a NEW method was considered.
"""

import inspect

import pytest

from cosa.rest.db.repositories.notification_repository import NotificationRepository


CONVERSATION_FACING = "conversation_facing"
ACK_SURFACE         = "ack_surface"
STRUCTURALLY_IMMUNE = "structurally_immune"
LEFT_DELIBERATELY   = "left_deliberately"
WRITE_PATH          = "write_path"

# (bucket, why). The `why` is not decoration: for STRUCTURALLY_IMMUNE it is the mechanism,
# and a mechanism that stops being true is how this classification would rot.
CLASSIFICATION = {
    # ── shown to the user as their messages / correspondents / counts ──────────────
    "get_sender_last_activities"        : ( CONVERSATION_FACING, "the sender roster" ),
    "get_sender_last_activities_visible": ( CONVERSATION_FACING, "the operator focus bar; the multiplexer strip hydrates from it" ),
    "get_sender_conversation"           : ( CONVERSATION_FACING, "the conversation window" ),
    "get_sender_conversations_by_date"  : ( CONVERSATION_FACING, "the multiplexer's history hydration" ),
    "get_sender_date_summaries"         : ( CONVERSATION_FACING, "the per-date counts beside a conversation" ),
    "get_active_conversation"           : ( CONVERSATION_FACING, "picks whose conversation is open; an acker is not a correspondent" ),

    # ── the read that exists to return acks ───────────────────────────────────────
    "get_latest_acks_for_broadcast"     : ( ACK_SURFACE, "this IS the ack read; excluding here would hide acks from their own endpoint" ),

    # ── already cannot contain an ack, by their own filters ───────────────────────
    "get_undelivered_for_recipient"     : ( STRUCTURALLY_IMMUNE, "state in (created, queued); an ack is marked delivered on save" ),
    "count_undelivered_for_recipient"   : ( STRUCTURALLY_IMMUNE, "the same state in (created, queued) filter as the getter it counts" ),
    "dismiss_undelivered_for_recipient" : ( STRUCTURALLY_IMMUNE, "same state filter; also a write" ),
    "get_dm_thread"                     : ( STRUCTURALLY_IMMUNE, "direction == ai_to_ai; an ack is ai_to_human" ),
    "get_dm_inbox"                      : ( STRUCTURALLY_IMMUNE, "direction == ai_to_ai" ),
    "get_answers_owed_for_persona"      : ( STRUCTURALLY_IMMUNE, "response_requested AND responded_at IS NOT NULL; an ack requests no response" ),
    "get_pending_for_recipient"         : ( STRUCTURALLY_IMMUNE, "response-pending states an ack never enters" ),
    "get_expired_notifications"         : ( STRUCTURALLY_IMMUNE, "expires_at IS NOT NULL; an ack carries no expiry" ),
    "mark_expired"                      : ( STRUCTURALLY_IMMUNE, "acts on the expired set, which an ack never joins" ),
    "count_by_job_ids"                  : ( STRUCTURALLY_IMMUNE, "keyed by job_id; an ack has none. NOTE: it returns one dict KEY per INPUT id, so a len() of 1 over one input id is not a row" ),

    # ── returns acks, knowingly untouched ─────────────────────────────────────────
    "count_by_sender"                   : ( LEFT_DELIBERATELY, "returns the ack, but has no caller outside tests — excluding would be churn in code nothing reads" ),
    "get_by_recipient"                  : ( LEFT_DELIBERATELY, "returns the ack, but has no caller outside tests" ),

    # ── writes: excluding would strand rows ───────────────────────────────────────
    "bulk_delete_by_user"               : ( WRITE_PATH, "a row you refuse to see is a row the user can never clear" ),
    "delete_by_sender"                  : ( WRITE_PATH, "clearing a sender must remove its ack rows too, or they persist with no way to reach them" ),
    "soft_delete_by_date"               : ( WRITE_PATH, "the clear-this-day action must hide that day's ack rows as well" ),
}


def _query_bearing_methods():
    """
    The DENOMINATOR, derived rather than typed. Every public method DEFINED ON this class
    whose body touches `session.query`. Inherited BaseRepository methods are out of scope:
    they are generic CRUD over any model and carry no notification semantics.
    """
    found = {}
    for name, fn in vars( NotificationRepository ).items():
        if name.startswith( "_" ) or not inspect.isfunction( fn ):
            continue
        source = inspect.getsource( fn )
        if "session.query" in source:
            found[ name ] = source
    return found


def _renders_the_exclusion( source ):
    return "NON_CONVERSATION_TYPES" in source


class TestTheClassificationCoversEveryRead:

    def test_the_denominator_is_what_we_think_it_is( self ):
        """
        🔴 A GUARD THAT CANNOT STATE ITS DENOMINATOR IS TELLING YOU ABOUT ITS CORPUS.
        22 measured 2026-09-23. This is a tripwire, not a constant to keep green by
        editing: if it moves, a read was added or removed and the map below must say so.
        """
        assert len( _query_bearing_methods() ) == 22, (
            f"the number of query-bearing reads changed to {len( _query_bearing_methods() )}. "
            f"Classify the new one in CLASSIFICATION and update this count deliberately." )

    def test_every_query_bearing_read_is_classified( self ):
        """
        🔴 THE CONTROL MR. RADIO ASKED FOR. Six per-query filters are an enumeration:
        correct today, silently wrong the first time a twenty-third read is added. This
        makes that addition IMPOSSIBLE TO DO SILENTLY — the new method is unclassified,
        and this fails naming it.
        """
        unclassified = sorted( set( _query_bearing_methods() ) - set( CLASSIFICATION ) )
        assert not unclassified, (
            f"these reads are not classified: {unclassified}. Decide, for each: is its "
            f"answer shown to the user as their messages, their correspondents, or a "
            f"count of either? If yes it is CONVERSATION_FACING and needs "
            f"`Notification.type.notin_( self.NON_CONVERSATION_TYPES )`." )

    def test_the_map_does_not_name_reads_that_no_longer_exist( self ):
        """A classification for a deleted method is a stale reassurance, which is worse
        than no entry at all — it reads as coverage."""
        stale = sorted( set( CLASSIFICATION ) - set( _query_bearing_methods() ) )
        assert not stale, f"CLASSIFICATION names methods that are gone: {stale}"

    def test_every_entry_carries_a_reason( self ):
        missing = sorted( n for n, ( _, why ) in CLASSIFICATION.items() if not why or len( why ) < 10 )
        assert not missing, f"these classifications carry no usable reason: {missing}"


class TestEachBucketHoldsItsPromise:

    def test_every_conversation_facing_read_carries_the_exclusion( self ):
        """The six. Measured off the source, so a filter deleted later fails here."""
        methods = _query_bearing_methods()
        missing = sorted(
            name for name, ( bucket, _ ) in CLASSIFICATION.items()
            if bucket == CONVERSATION_FACING and not _renders_the_exclusion( methods[ name ] ) )
        assert not missing, f"conversation-facing reads missing the exclusion: {missing}"

    def test_the_ack_surface_does_NOT_carry_the_exclusion( self ):
        """
        🔴 THE INVERSE, AND IT IS NOT SYMMETRY FOR ITS OWN SAKE. A well-meaning sweep that
        added the clause everywhere would hide acks from the one endpoint built to return
        them, and every other assertion in this file would still pass.
        """
        methods = _query_bearing_methods()
        wrong = sorted(
            name for name, ( bucket, _ ) in CLASSIFICATION.items()
            if bucket == ACK_SURFACE and _renders_the_exclusion( methods[ name ] ) )
        assert not wrong, f"the ack surface must NOT exclude acks: {wrong}"

    def test_no_write_path_carries_the_exclusion( self ):
        """A row a delete refuses to see is a row the user can never clear."""
        methods = _query_bearing_methods()
        wrong = sorted(
            name for name, ( bucket, _ ) in CLASSIFICATION.items()
            if bucket == WRITE_PATH and _renders_the_exclusion( methods[ name ] ) )
        assert not wrong, f"write paths must not exclude acks or the rows become unclearable: {wrong}"

    def test_the_two_deliberate_exceptions_still_have_no_live_caller( self ):
        """
        LEFT_DELIBERATELY rests entirely on "nothing calls it". That is a fact about the
        tree, and facts about the tree change — so it is re-derived here rather than
        trusted. If somebody wires one of these to an endpoint, the reason evaporates and
        the read must be reclassified.
        """
        import pathlib, re
        src_root = pathlib.Path( __file__ ).resolve().parents[ 2 ]
        for name, ( bucket, _ ) in CLASSIFICATION.items():
            if bucket != LEFT_DELIBERATELY:
                continue
            callers = []
            for path in src_root.rglob( "*.py" ):
                parts = path.parts
                if "tests" in parts or ".venv" in parts or "node_modules" in parts:
                    continue
                if path.name == "notification_repository.py":
                    continue
                if re.search( rf"\.{re.escape( name )}\s*\(", path.read_text( errors="ignore" ) ):
                    callers.append( str( path.relative_to( src_root ) ) )
            assert not callers, (
                f"{name} is classified LEFT_DELIBERATELY because nothing calls it, but it "
                f"is now called from {callers}. Reclassify it — most likely CONVERSATION_FACING." )


class TestTheseChecksCanSeeAPositive:
    """Each predicate above is a match that passes. Each is run once against a value that must fail it."""

    def test_the_exclusion_detector_rejects_a_body_without_it( self ):
        assert not _renders_the_exclusion( "return self.session.query( Notification ).all()" )

    def test_the_exclusion_detector_accepts_a_body_with_it( self ):
        assert _renders_the_exclusion( "Notification.type.notin_( self.NON_CONVERSATION_TYPES )" )

    def test_the_denominator_finder_ignores_a_method_that_never_queries( self ):
        """`update_state` is public and does not query; it must not inflate the denominator."""
        assert "update_state" not in _query_bearing_methods()

    def test_the_denominator_finder_finds_a_method_that_does_query( self ):
        assert "get_sender_conversation" in _query_bearing_methods()
