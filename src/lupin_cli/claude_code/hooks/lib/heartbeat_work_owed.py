#!/usr/bin/env python3
"""
Heartbeat Hook — work-owed oracle (pure decision function).

Answers §0 decision-logic STEP 3: "determine work-owed." Consulted only when
there is NO fresh, honored hold (the hold artifact short-circuits steps 1-2).
If this oracle reports no owed work, the instance is genuinely done → do NOT
poke. If work is owed and the per-session poke-cap is not exhausted → poke.

Design authority (LOCKED): planning-is-prompting →
    src/rnd/2026.06.02-stop-hook-natural-heartbeat-poker.md  §0 #3 + §4.
Lupin-side seam analysis: lupin →
    src/rnd/v0.1.8/2026.06.04-heartbeat-hook/01-spike-findings-and-stop-py-seam-analysis.md

**PURE CORE — by design (María constraint, 2026-06-04):** this module NEVER
fetches live commons / transcript / TODO data. All state is *injected* as
already-parsed lists. The live-data plumbing (read TODO.md, scan Pending
Decisions, query open DMs) belongs to the `stop.py` Branch-C integration
layer, which is gated on the 3-way Rachel seam review. Same discipline that
kept the hold-artifact module collision-free: pure core now, live wiring at
the gated seam later.

Work-owed signals, strongest-first (§0 #3; the declared-hold-reason signal
that heads that list is handled by the `heartbeat_hold` module, not here —
this oracle is the "else" branch after no fresh hold):
    1. TODO items you own that are in_progress
    2. TODO items you own that are unstarted (pending)
    3. Pending-Decisions that are NOT blocked on the user
    4. Unanswered INBOUND questions (expect_reply DMs addressed to you that
       you have not yet answered — work you owe a peer)

NOTE on signal #4 interpretation: "open expect_reply DM" (§0 #3) is read here
as an *inbound* question you owe a reply to (⇒ work owed ⇒ poke). An
*outbound* expect_reply DM where YOU are awaiting a peer's reply is the
opposite — a legitimate hold/awaiting signal — and belongs to the hold
artifact's `awaiting` field, not this oracle. Flagged to María for
confirmation; cheap to adjust since the list is injected.
"""

# TODO item status vocabulary (mirrors TodoWrite / TODO.md conventions)
TODO_IN_PROGRESS = "in_progress"
TODO_PENDING     = "pending"        # unstarted / owned-but-not-begun
TODO_COMPLETED   = "completed"

# Poke reason template (rides the top-level `reason` field — NEVER systemMessage;
# see 01-…-seam-analysis.md §ERRATA).
POKE_REASON_TEMPLATE = (
    "Do not stop yet — you stopped with work owed ({specifics}) and no fresh hold. "
    "Pick one and act before you stop:\n"
    "1. Owe work? Resume and finish it now.\n"
    '2. Blocked on someone? DM them for status ("where are we on X?"), then declare a fresh hold — '
    "write .heartbeat-hold-<session_id>.json with a reason and awaiting: peer:<name>.\n"
    "3. Truly nothing to do? Declare it — write a hold with work_owed: false."
)

NO_WORK_SPECIFICS = "no owed work detected"


def _actionable_todos( todo_items ):
    """
    Partition owned TODO items into (in_progress, unstarted).

    Requires:
        - todo_items is an iterable of dicts (foreign/parsed data)

    Ensures:
        - Returns ( in_progress_list, unstarted_list )
        - Only items with owned_by_me truthy are considered
        - Non-dict entries are skipped (defensive over foreign data)
        - completed / unknown statuses contribute to neither list
    """
    in_progress = [ ]
    unstarted   = [ ]
    for item in todo_items:
        if not isinstance( item, dict ):
            continue
        if not item.get( "owned_by_me", False ):
            continue
        status = item.get( "status" )
        if status == TODO_IN_PROGRESS:
            in_progress.append( item )
        elif status == TODO_PENDING:
            unstarted.append( item )
    return in_progress, unstarted


def _actionable_pending_decisions( pending_decisions ):
    """
    Filter Pending-Decisions to those NOT blocked on the user.

    Requires:
        - pending_decisions is an iterable of dicts

    Ensures:
        - Returns the list of dict entries whose blocked_on_user is falsy
        - Non-dict entries are skipped
    """
    return [
        d for d in pending_decisions
        if isinstance( d, dict ) and not d.get( "blocked_on_user", False )
    ]


def evaluate_work_owed( todo_items=None, pending_decisions=None,
                        unanswered_inbound_questions=None ):
    """
    Pure work-owed verdict over injected state (§0 step 3).

    Requires:
        - todo_items, pending_decisions, unanswered_inbound_questions are each
          an iterable of dicts, or None (treated as empty)

    Ensures:
        - Returns a verdict dict:
            { "work_owed": bool,
              "signals":   [str, ...]   # strongest-first, only those that fired
              "specifics": str }        # human-readable, for the poke reason
        - work_owed is True iff at least one signal fired
        - signals order is fixed strongest-first:
          todo_in_progress, todo_unstarted, pending_decision,
          unanswered_inbound_question
        - Never fetches live data; never raises on well-formed list input
    """
    todo_items                   = todo_items or [ ]
    pending_decisions            = pending_decisions or [ ]
    unanswered_inbound_questions = unanswered_inbound_questions or [ ]

    in_progress, unstarted = _actionable_todos( todo_items )
    actionable_decisions   = _actionable_pending_decisions( pending_decisions )
    unanswered             = [ q for q in unanswered_inbound_questions if q ]

    signals   = [ ]
    specifics = [ ]

    if in_progress:
        signals.append( "todo_in_progress" )
        specifics.append( f"{len( in_progress )} in-progress TODO item(s) you own" )
    if unstarted:
        signals.append( "todo_unstarted" )
        specifics.append( f"{len( unstarted )} unstarted TODO item(s) you own" )
    if actionable_decisions:
        signals.append( "pending_decision" )
        specifics.append( f"{len( actionable_decisions )} pending decision(s) not blocked on the user" )
    if unanswered:
        signals.append( "unanswered_inbound_question" )
        specifics.append( f"{len( unanswered )} unanswered inbound question(s) awaiting your reply" )

    return {
        "work_owed" : bool( signals ),
        "signals"   : signals,
        "specifics" : "; ".join( specifics ) if specifics else NO_WORK_SPECIFICS,
    }


def build_poke_reason( verdict ):
    """
    Compose the self-poke `reason` string from a work-owed verdict.

    Requires:
        - verdict is the dict returned by evaluate_work_owed (has "specifics")

    Ensures:
        - Returns the POKE_REASON_TEMPLATE filled with verdict["specifics"]
        - Rides the top-level Stop-hook `reason` field — NEVER systemMessage
    """
    return POKE_REASON_TEMPLATE.format( specifics=verdict[ "specifics" ] )


def quick_smoke_test():
    """
    Self-contained smoke test of the decision matrix.

    Ensures:
        - Returns True if owed / not-owed verdicts + ordering + reason text
          behave as designed; raises AssertionError otherwise.
    """
    # Nothing owed → genuinely done
    v = evaluate_work_owed()
    assert v[ "work_owed" ] is False,            "empty state should not owe work"
    assert v[ "signals" ] == [ ],                "empty state should fire no signals"
    assert v[ "specifics" ] == NO_WORK_SPECIFICS

    # All four signals fire → strongest-first ordering
    v = evaluate_work_owed(
        todo_items = [
            { "status": TODO_IN_PROGRESS, "owned_by_me": True },
            { "status": TODO_PENDING,     "owned_by_me": True },
            { "status": TODO_COMPLETED,   "owned_by_me": True },     # ignored
            { "status": TODO_IN_PROGRESS, "owned_by_me": False },    # ignored
        ],
        pending_decisions            = [ { "blocked_on_user": False }, { "blocked_on_user": True } ],
        unanswered_inbound_questions = [ { "question_id": "q1" } ],
    )
    assert v[ "work_owed" ] is True
    assert v[ "signals" ] == [
        "todo_in_progress", "todo_unstarted", "pending_decision", "unanswered_inbound_question"
    ], "signal ordering drift"

    reason = build_poke_reason( v )
    assert reason.startswith( "Do not stop yet" )
    assert "work_owed: false" in reason

    return True


if __name__ == "__main__":   # pragma: no cover - manual smoke entrypoint
    ok = quick_smoke_test()
    print( f"heartbeat_work_owed smoke: {'PASS' if ok else 'FAIL'}" )
