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
    5. Outstanding delegations (2026-06-09, Rick): spawned workers of yours
       that are STILL ALIVE and not yet reaped — a manager supervising a live
       crew owes review/reap duty even with zero Task* items filed, so it must
       never idle-announce while workers are out

NOTE on signal #4 interpretation: "open expect_reply DM" (§0 #3) is read here
as an *inbound* question you owe a reply to (⇒ work owed ⇒ poke). An
*outbound* expect_reply DM where YOU are awaiting a peer's reply is the
opposite — a legitimate hold/awaiting signal — and belongs to the hold
artifact's `awaiting` field, not this oracle. Flagged to María for
confirmation; cheap to adjust since the list is injected.
"""

import datetime

# TODO item status vocabulary (mirrors TodoWrite / TODO.md conventions)
TODO_IN_PROGRESS = "in_progress"
TODO_PENDING     = "pending"        # unstarted / owned-but-not-begun
TODO_COMPLETED   = "completed"

# Inbound age-out threshold (acked-inbound ledger spec part (e), Rick 2026-06-10):
# an unanswered inbound DM older than this surfaces as "stale, review" — NOT as
# owed work that pokes. 24h: a full day un-actioned ⇒ it is backlog to triage at
# leisure, not a live obligation. The gatherer (IO shell) supplies `now`; this
# threshold + the partition itself are PURE (clock injected, never read here).
INBOUND_STALE_AFTER_SECONDS = 86400

# Poke-prompt sentinel (c121037b, 2026-06-16) — the SHARED opening clause of
# every heartbeat self-poke `reason`. The poke is re-submitted as a prompt via
# tmux send-keys, which fires the UserPromptSubmit hook; that hook must NOT treat
# the heartbeat's OWN injected poke as genuine user re-engagement (doing so reset
# the poke-cap every turn → the cap never halted → infinite self-nag, empirically
# poke_count stuck at 1 across 23 pokes). `is_heartbeat_poke_prompt` keys on this
# sentinel so user_prompt_submit skips the cap reset for a self-poke but still
# resets on a real user prompt. Both POKE_REASON_TEMPLATE (oracle-owed) and
# heartbeat_decision.DECLARED_OWED_REASON (self-declared) open with it (one
# descriptive name everywhere — they derive their prefix from this constant).
POKE_PROMPT_SENTINEL = "Do not stop yet — you stopped with work owed"

# Poke reason template (rides the top-level `reason` field — NEVER systemMessage;
# see 01-…-seam-analysis.md §ERRATA). The hold-write instruction names the FULL
# hyphenated session id explicitly (c121037b facet 2): get_session_info hands an
# agent the SHORT 8-char id, and a hold written at the short id while the hook
# reads at the full stable id is silently ignored. read_hold also falls back
# across id forms (heartbeat_hold._read_hold_path) as belt-and-suspenders.
POKE_REASON_TEMPLATE = (
    POKE_PROMPT_SENTINEL + " ({specifics}) and no fresh hold. "
    "Pick one and act before you stop:\n"
    "1. Owe work? Resume and finish it now.\n"
    '2. Blocked on someone? DM them for status ("where are we on X?"), then declare a fresh hold — '
    "write .heartbeat-hold-<your-FULL-session-id>.json (use the full hyphenated session id, "
    "NOT the short 8-char form) with a reason and awaiting: peer:<name>.\n"
    "3. Truly nothing to do? Declare it — write a hold with work_owed: false."
)

NO_WORK_SPECIFICS = "no owed work detected"


def is_heartbeat_poke_prompt( prompt ):
    """
    Is `prompt` the heartbeat hook's OWN injected self-poke (not user input)?

    The self-poke rides the Stop-hook `reason` field and is re-submitted as a
    prompt via tmux send-keys; UserPromptSubmit must NOT treat that synthetic
    prompt as user re-engagement — doing so resets the per-session poke-cap on
    every poke, so the cap never halts (c121037b root cause: poke_count stuck at
    1 across 23 consecutive pokes). Both heartbeat poke reasons open with
    POKE_PROMPT_SENTINEL.

    Requires:
        - prompt is a string or None (foreign hook-payload data)

    Ensures:
        - Returns True iff prompt (left-stripped) starts with POKE_PROMPT_SENTINEL
        - Returns False for None / non-string / empty / genuine user prompts
        - Never raises
    """
    if not isinstance( prompt, str ):
        return False
    return prompt.lstrip().startswith( POKE_PROMPT_SENTINEL )


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


def _inbound_age_seconds( entry, now_epoch ):
    """
    Age in seconds of one inbound entry, or None when it cannot be dated.

    Requires:
        - entry is a dict that may carry a "ts" ISO-8601 string
        - now_epoch is a float/int POSIX timestamp ("now", injected by caller)

    Ensures:
        - Returns ( now_epoch - parsed_ts ) in seconds for a parseable ts
        - Returns None when ts is missing / non-string / unparseable
        - PURE: parses the injected string + arithmetic only; reads no clock
        - Trailing "Z" is normalized to "+00:00" so UTC stamps parse on 3.10
    """
    ts = entry.get( "ts" ) if isinstance( entry, dict ) else None
    if not isinstance( ts, str ):
        return None
    try:
        parsed = datetime.datetime.fromisoformat( ts.replace( "Z", "+00:00" ) )
    except ValueError:
        return None
    return now_epoch - parsed.timestamp()


def partition_inbound_by_age( inbound, now_epoch,
                              stale_after_seconds=INBOUND_STALE_AFTER_SECONDS ):
    """
    Split inbound entries into (fresh, stale) by age — spec part (e).

    Requires:
        - inbound is an iterable of dicts (each may carry a "ts" ISO string)
        - now_epoch is the caller's injected "now" (POSIX seconds)
        - stale_after_seconds is a positive number

    Ensures:
        - Returns ( fresh, stale ): an entry is STALE iff its age strictly
          exceeds stale_after_seconds; otherwise FRESH
        - An undateable entry (missing/unparseable ts) is FRESH — bias-to-owed,
          consistent with the gatherer's missing-tenure-floor philosophy; the
          poke cap bounds the cost
        - Input order is preserved within each bucket
        - PURE: no clock, no IO; never raises on well-formed dict input
    """
    fresh = [ ]
    stale = [ ]
    for entry in inbound:
        age = _inbound_age_seconds( entry, now_epoch )
        if age is not None and age > stale_after_seconds:
            stale.append( entry )
        else:
            fresh.append( entry )
    return fresh, stale


def evaluate_work_owed( todo_items=None, pending_decisions=None,
                        unanswered_inbound_questions=None,
                        outstanding_delegations=None ):
    """
    Pure work-owed verdict over injected state (§0 step 3).

    Requires:
        - todo_items, pending_decisions, unanswered_inbound_questions and
          outstanding_delegations are each an iterable of dicts, or None
          (treated as empty)

    Ensures:
        - Returns a verdict dict:
            { "work_owed": bool,
              "signals":   [str, ...]   # strongest-first, only those that fired
              "specifics": str }        # human-readable, for the poke reason
        - work_owed is True iff at least one signal fired
        - signals order is fixed strongest-first:
          todo_in_progress, todo_unstarted, pending_decision,
          unanswered_inbound_question, outstanding_delegation
        - outstanding_delegation fires iff ≥1 truthy entry is injected — an
          ALIVE, un-reaped spawned worker is owed work (the manager still owes
          review/reap); all-dead/reaped ⇒ empty ⇒ no signal ⇒ idle allowed.
          The live gathering (manifest ∩ live bridges) is the CALLER's IO, not
          this oracle's (pure-core discipline unchanged)
        - Never fetches live data; never raises on well-formed list input
    """
    todo_items                   = todo_items or [ ]
    pending_decisions            = pending_decisions or [ ]
    unanswered_inbound_questions = unanswered_inbound_questions or [ ]
    outstanding_delegations      = outstanding_delegations or [ ]

    in_progress, unstarted = _actionable_todos( todo_items )
    actionable_decisions   = _actionable_pending_decisions( pending_decisions )
    unanswered             = [ q for q in unanswered_inbound_questions if q ]
    outstanding            = [ d for d in outstanding_delegations if d ]

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
    if outstanding:
        signals.append( "outstanding_delegation" )
        specifics.append( f"{len( outstanding )} live worker(s) still out" )

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

    # All five signals fire → strongest-first ordering
    v = evaluate_work_owed(
        todo_items = [
            { "status": TODO_IN_PROGRESS, "owned_by_me": True },
            { "status": TODO_PENDING,     "owned_by_me": True },
            { "status": TODO_COMPLETED,   "owned_by_me": True },     # ignored
            { "status": TODO_IN_PROGRESS, "owned_by_me": False },    # ignored
        ],
        pending_decisions            = [ { "blocked_on_user": False }, { "blocked_on_user": True } ],
        unanswered_inbound_questions = [ { "question_id": "q1" } ],
        outstanding_delegations      = [ { "session_name": "cc-reviewer-x-1" } ],
    )
    assert v[ "work_owed" ] is True
    assert v[ "signals" ] == [
        "todo_in_progress", "todo_unstarted", "pending_decision",
        "unanswered_inbound_question", "outstanding_delegation"
    ], "signal ordering drift"
    assert "1 live worker(s) still out" in v[ "specifics" ]

    # Delegation-ONLY manager: no Task* items, one live worker ⇒ owed (the bug fix)
    v = evaluate_work_owed( outstanding_delegations=[ { "session_name": "cc-reviewer-x-1" } ] )
    assert v[ "work_owed" ] is True and v[ "signals" ] == [ "outstanding_delegation" ]

    # All workers reaped (falsy entries filtered) ⇒ idle allowed
    v = evaluate_work_owed( outstanding_delegations=[ None, { } ] )
    assert v[ "work_owed" ] is False

    reason = build_poke_reason( evaluate_work_owed(
        todo_items=[ { "status": TODO_IN_PROGRESS, "owned_by_me": True } ] ) )
    assert reason.startswith( "Do not stop yet" )
    assert "work_owed: false" in reason

    return True


if __name__ == "__main__":   # pragma: no cover - manual smoke entrypoint
    ok = quick_smoke_test()
    print( f"heartbeat_work_owed smoke: {'PASS' if ok else 'FAIL'}" )
