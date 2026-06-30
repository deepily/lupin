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

# Receipts-of-progress inward twin (6929f4ac, Rick 2026-06-22): the manager
# worker-verification debounce. A MANAGER with workers OUT owes a fresh
# verification receipt (artifact-delta look-in) every `threshold` seconds; while
# its last look-in is older than this it reads as work-owed (so it keeps getting
# poked to verify, closing the "sit-back-and-wait-for-a-notification" loophole at
# the code layer — design §2/§3). v1 = the debounce alone (Rick: 10 min); the
# stall-aware escalation is v2. PURE: the clock is injected, never read here.
VERIFICATION_DEBOUNCE_SECONDS = 600

# Proactive-manager mechanism (fcb5dbc0, Lane A1 — design-of-record planning-is-
# prompting/src/rnd/2026.06.23-proactive-manager-doctrine-and-mechanism.md D1/D2/D3).
# The SAME debounce shape as the 6929f4ac inward twin, GENERALIZED to the manager's
# two proactive self-checks folded into the Stop-hook oracle (zero brute-force tick):
#   Face A (item 11, proactive DOWN): a manager sitting on a backlog with idle crew
#     capacity owes a "consider spinning up a crew" NUDGE every `threshold` seconds.
#     Self-clears when it stamps last_spinup_check_ts (it considered the nudge).
#   Face B (item 1, proactive UP): a session holding open operator gates owes a
#     RE-SURFACE of those asks every `threshold` seconds — ONE per-manager debounce
#     (last_surfaced_questions_ts) generalizing the per-gate due_gates 10-min hack
#     (D3 "retires the N per-session re-ask timers"). Self-clears on the surface stamp.
# Defaults mirror T_escalate / the verification window (Rick: ~10 min); the stop.py
# shell passes the INI-overridable runtime values in. PURE: clock injected here.
SPINUP_CHECK_DEBOUNCE_SECONDS      = 600
SURFACE_QUESTIONS_DEBOUNCE_SECONDS = 600
# Face A backlog floor: a backlog of fewer than this many owed items never warrants
# a crew-spin-up nudge (a manager judges small backlogs itself). INI-overridable.
SPINUP_BACKLOG_MIN_N = 3

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
    "1. Owe work? Resume and drive it now — but if you manage a crew: assign/delegate it to a worker "
    "(spawn one if you have more open tasks than workers); do NOT build it yourself.\n"
    '2. Blocked on someone? DM them for status ("where are we on X?"), then declare a fresh hold — '
    "write .heartbeat-hold-<your-FULL-session-id>.json (use the full hyphenated session id, "
    "NOT the short 8-char form) with a reason and awaiting: peer:<name>.\n"
    "3. Blocked on the USER (a decision only they can make)? Fire a dedicated ask_* "
    "(ask_yes_no / ask_multiple_choice / converse) to them THIS turn — do NOT bury it in a status notify "
    "or sit in a hold. A user-gate is owed work; surface it directly and re-ask until answered.\n"
    "4. Truly nothing to do? Declare it — write a hold with work_owed: false."
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


def _iso_age_seconds( ts, now_epoch ):
    """
    Age in seconds of an ISO-8601 timestamp string, or None when undateable.

    The shared, single-source age-of-a-timestamp helper (one descriptive name
    everywhere): consumed by both _inbound_age_seconds (inbound-DM age-out) and
    manager_needs_verification (the look-in debounce).

    Requires:
        - ts is anything (defensive over foreign data); only a str dates
        - now_epoch is a float/int POSIX timestamp ("now", injected by caller)

    Ensures:
        - Returns ( now_epoch - parsed_ts ) in seconds for a parseable str ts
        - Returns None when ts is missing / non-string / unparseable
        - PURE: parses the injected string + arithmetic only; reads no clock
        - Trailing "Z" is normalized to "+00:00" so UTC stamps parse on 3.10
    """
    if not isinstance( ts, str ):
        return None
    try:
        parsed = datetime.datetime.fromisoformat( ts.replace( "Z", "+00:00" ) )
    except ValueError:
        return None
    return now_epoch - parsed.timestamp()


def _inbound_age_seconds( entry, now_epoch ):
    """
    Age in seconds of one inbound entry, or None when it cannot be dated.

    Requires:
        - entry is a dict that may carry a "ts" ISO-8601 string
        - now_epoch is a float/int POSIX timestamp ("now", injected by caller)

    Ensures:
        - Returns ( now_epoch - parsed_ts ) in seconds for a parseable ts
        - Returns None when ts is missing / non-string / unparseable
        - Delegates dating to _iso_age_seconds (single-source age helper)
    """
    ts = entry.get( "ts" ) if isinstance( entry, dict ) else None
    return _iso_age_seconds( ts, now_epoch )


def manager_needs_verification( outstanding_delegations, last_verification_ts,
                                now_epoch,
                                threshold_seconds=VERIFICATION_DEBOUNCE_SECONDS ):
    """
    Inward twin (6929f4ac §3-§5): does this MANAGER owe a fresh worker-
    verification receipt right now? The pure debounce predicate.

    A manager that merely waits — no fresh look-in — must read as work-owed so
    the oracle keeps poking it to VERIFY (liveness ≠ progress; being owed ≠ doing
    the owed thing). It self-clears the instant the manager looks in (stamps
    `last_looked_in_on_workers_ts`), so a manager who is actually managing resets
    the clock for free and a manager who sits does not.

    Requires:
        - outstanding_delegations is an iterable of (truthy ⇒ alive worker)
          entries, or None — the SAME list the outstanding_delegation signal
          consumes (manifest ∩ live bridges, gathered by the IO shell)
        - last_verification_ts is the manager's most-recent verification stamp
          (ISO-8601 str) or None (never looked in)
        - now_epoch is the caller's injected "now" (POSIX seconds)
        - threshold_seconds is the debounce window (Rick: 600 = 10 min)

    Ensures:
        - Returns False when NO worker is out (all dead/reaped ⇒ nothing to
          verify ⇒ never a verification debt) — gates the whole predicate
        - With ≥1 worker out: True iff there is no datable prior look-in
          (last_verification_ts None or unparseable ⇒ bias-to-owe a first/again
          look; the poke cap bounds the cost) OR the look-in age ≥ threshold
        - Boundary: age EXACTLY == threshold owes (>=) — a 10-min-old look-in is
          due, mirroring "verify at least every 10 min"
        - PURE: no clock, no IO; never raises on well-formed input
    """
    workers = [ d for d in ( outstanding_delegations or [ ] ) if d ]
    if not workers:
        return False
    age = _iso_age_seconds( last_verification_ts, now_epoch )
    if age is None:
        return True
    return age >= threshold_seconds


def manager_needs_spinup_check( backlog_count, idle_capacity, last_spinup_check_ts,
                                now_epoch,
                                threshold_seconds=SPINUP_CHECK_DEBOUNCE_SECONDS,
                                backlog_min_n=SPINUP_BACKLOG_MIN_N ):
    """
    Face A (item 11, design D1/D2): does this MANAGER owe a crew-spin-up NUDGE
    right now? The pure debounce predicate, sibling of manager_needs_verification.

    A manager sitting on a backlog with idle crew capacity must read as work-owed
    so the oracle NAMES "consider spinning up a crew" on its next Stop — the
    manager then decides + acts of its own accord (D2: nudge, NOT auto-spin). It
    self-clears the instant the manager stamps last_spinup_check_ts (it considered
    the nudge), so a manager who just checked is not re-nudged and one who sits is.

    Requires:
        - backlog_count is the manager's owed-item count (queued + in_progress,
          gathered by the IO shell via task_query(accountable_manager=me)); any
          type accepted (foreign data) — only a non-bool int >= backlog_min_n counts
        - idle_capacity is a bool — True iff the manager has room to spawn another
          worker under the cap-8 fleet bound (live_workers < cap)
        - last_spinup_check_ts is the most-recent spin-up-check stamp (ISO-8601
          str) or None (never checked)
        - now_epoch is the caller's injected "now" (POSIX seconds)
        - threshold_seconds is the debounce window (Rick: 600 = 10 min)
        - backlog_min_n is the backlog floor below which no nudge fires

    Ensures:
        - Returns False unless ALL THREE hold — no idle capacity OR backlog < N
          short-circuits to False regardless of elapsed (a full crew or a small
          backlog never nudges; the manager's judgment is preserved)
        - bool backlog_count is rejected (True must not slip through as 1)
        - With capacity AND backlog >= N: True iff there is no datable prior check
          (None/unparseable ⇒ bias-to-nudge a first check; the poke cap bounds the
          cost) OR the check age >= threshold_seconds
        - Boundary: age EXACTLY == threshold owes (>=)
        - PURE: no clock, no IO; never raises on well-formed input
    """
    if not idle_capacity:
        return False
    if isinstance( backlog_count, bool ) or not isinstance( backlog_count, int ):
        return False
    if backlog_count < backlog_min_n:
        return False
    age = _iso_age_seconds( last_spinup_check_ts, now_epoch )
    if age is None:
        return True
    return age >= threshold_seconds


def manager_needs_question_surface( open_operator_gates, last_surfaced_questions_ts,
                                    now_epoch,
                                    threshold_seconds=SURFACE_QUESTIONS_DEBOUNCE_SECONDS ):
    """
    Face B (item 1, design D1/D3): does this session owe a RE-SURFACE of its open
    operator gates right now? The pure per-manager debounce predicate.

    A session holding ≥1 open (unanswered) operator gate must re-fire those asks
    every `threshold` seconds so a decision the human owes is never buried under a
    "ball's in your court" park. This GENERALIZES the per-gate due_gates 10-min
    hack to ONE per-manager debounce (D3 "retires the N per-session re-ask
    timers"): instead of N independent per-gate timers, the single
    last_surfaced_questions_ts gates the whole re-surface. Self-clears when the
    session stamps last_surfaced_questions_ts after re-firing.

    Requires:
        - open_operator_gates is an iterable of truthy gate entries (the OPEN,
          unanswered operator gates, gathered by the IO shell), or None
        - last_surfaced_questions_ts is the most-recent surface stamp (ISO-8601
          str) or None (never surfaced)
        - now_epoch is the caller's injected "now" (POSIX seconds)
        - threshold_seconds is the debounce window (Rick: 600 = 10 min)

    Ensures:
        - Returns False when there is NO open operator gate (nothing to surface —
          gates the whole predicate, mirroring the no-workers gate of the inward twin)
        - With ≥1 open gate: True iff there is no datable prior surface
          (None/unparseable ⇒ bias-to-surface) OR the surface age >= threshold_seconds
        - Boundary: age EXACTLY == threshold owes (>=)
        - PURE: no clock, no IO; never raises on well-formed input
    """
    gates = [ g for g in ( open_operator_gates or [ ] ) if g ]
    if not gates:
        return False
    age = _iso_age_seconds( last_surfaced_questions_ts, now_epoch )
    if age is None:
        return True
    return age >= threshold_seconds


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
                        outstanding_delegations=None,
                        needs_verification=False,
                        open_user_gates=None,
                        needs_question_surface=False,
                        needs_spinup_check=False ):
    """
    Pure work-owed verdict over injected state (§0 step 3).

    Requires:
        - todo_items, pending_decisions, unanswered_inbound_questions,
          outstanding_delegations and open_user_gates are each an iterable of
          dicts, or None (treated as empty)
        - needs_verification is a bool — the inward twin's already-computed
          debounce verdict (manager_needs_verification, the IO shell calls it)
        - needs_question_surface / needs_spinup_check are bools — the Face B / Face A
          proactive-manager debounce verdicts (manager_needs_question_surface /
          manager_needs_spinup_check, the IO shell calls them)

    Ensures:
        - Returns a verdict dict:
            { "work_owed": bool,
              "signals":   [str, ...]   # strongest-first, only those that fired
              "specifics": str }        # human-readable, for the poke reason
        - work_owed is True iff at least one signal fired
        - signals order is fixed strongest-first:
          todo_in_progress, todo_unstarted, pending_decision,
          unanswered_inbound_question, outstanding_delegation,
          needs_verification, outstanding_user_gate, surface_operator_gates,
          spinup_nudge
        - outstanding_delegation fires iff ≥1 truthy entry is injected — an
          ALIVE, un-reaped spawned worker is owed work (the manager still owes
          review/reap); all-dead/reaped ⇒ empty ⇒ no signal ⇒ idle allowed.
          The live gathering (manifest ∩ live bridges) is the CALLER's IO, not
          this oracle's (pure-core discipline unchanged)
        - needs_verification fires iff the injected bool is truthy — the inward
          twin (6929f4ac): a manager owes a fresh worker-verification receipt
          (workers out AND its look-in is stale). The IO shell computes the bool
          via manager_needs_verification; this oracle only routes it to a signal
        - outstanding_user_gate fires iff ≥1 truthy open-gate entry is injected —
          the outward twin (6929f4ac §9): an open direct user-gate is owed work
          that must be RE-SURFACED (re-asked), never parked. The IO shell filters
          to the OPEN (unanswered) gates; an answered gate clears it. Its
          specifics carries the canonical Face-B obligation VERBATIM (manager-
          autonomy.md §9.2 Face B v1.7 / role-goals.md v1.2, Rick-locked): the
          manager MUST fire a dedicated HIGH-PRIORITY action-required ask the
          moment a user-blocker is raised — never buried — AND mint the typed
          operator gate
        - surface_operator_gates fires iff the injected bool is truthy — Face B
          (proactive-manager D3): the per-manager re-surface debounce has elapsed
          while ≥1 operator gate is open. The IO shell computes the bool via
          manager_needs_question_surface; this oracle only routes it to a signal.
          Its specifics carries the same Rick-locked Face-B obligation wording
          (manager-autonomy.md §9.2 Face B v1.7 / role-goals.md v1.2)
        - spinup_nudge fires iff the injected bool is truthy — Face A (proactive-
          manager D2): a backlog ≥ N with idle crew capacity AND the spin-up-check
          debounce elapsed. The IO shell computes the bool via
          manager_needs_spinup_check; the manager then decides + acts of its own
          accord (a NUDGE, never an auto-spin)
        - Never fetches live data; never raises on well-formed list input
    """
    todo_items                   = todo_items or [ ]
    pending_decisions            = pending_decisions or [ ]
    unanswered_inbound_questions = unanswered_inbound_questions or [ ]
    outstanding_delegations      = outstanding_delegations or [ ]
    open_user_gates              = open_user_gates or [ ]

    in_progress, unstarted = _actionable_todos( todo_items )
    actionable_decisions   = _actionable_pending_decisions( pending_decisions )
    unanswered             = [ q for q in unanswered_inbound_questions if q ]
    outstanding            = [ d for d in outstanding_delegations if d ]
    open_gates             = [ g for g in open_user_gates if g ]

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
    if needs_verification:
        signals.append( "needs_verification" )
        specifics.append( "worker-verification overdue — look in on your workers (stamp last_looked_in_on_workers_ts)" )
    if open_gates:
        signals.append( "outstanding_user_gate" )
        specifics.append( f"{len( open_gates )} open user-gate(s) awaiting Rick — the manager MUST fire a dedicated HIGH-PRIORITY 'action-required' notification (a targeted ask_*) to the user the moment it's raised — NOT a line buried in a status notify — AND mint the typed operator gate (re-ask now, stamp last_asked_ts)" )
    if needs_question_surface:
        signals.append( "surface_operator_gates" )
        specifics.append( "operator-gate re-surface overdue — the manager MUST fire a dedicated HIGH-PRIORITY 'action-required' notification (a targeted ask_*) to the user the moment it's raised — NOT a line buried in a status notify — AND mint the typed operator gate (re-surface your open operator-gate asks now, stamp last_surfaced_questions_ts)" )
    if needs_spinup_check:
        signals.append( "spinup_nudge" )
        specifics.append( "more open tasks than active workers (or idle crew capacity) — you OWE a staff-up THIS tick: spawn/assign the next worker now. Waiting to be told to staff is a redline. (stamp last_spinup_check_ts)" )

    return {
        "work_owed" : bool( signals ),
        "signals"   : signals,
        "specifics" : "; ".join( specifics ) if specifics else NO_WORK_SPECIFICS,
    }


def build_poke_reason( verdict, goal_line="" ):
    """
    Compose the self-poke `reason` string from a work-owed verdict.

    The role-selected north-star goal line (role-goals Phase 2-3) is an INJECTED
    string — the IO shell (stop.py) reads it from the `heartbeat <role> goal line`
    configuration-manager key and passes it in; this pure core only APPENDS it
    (the config read is IO and stays in the shell). Canonical source of the goal
    text: planning-is-prompting -> workflow/role-goals.md §"Injection: the poke
    echo".

    Requires:
        - verdict is the dict returned by evaluate_work_owed (has "specifics")
        - goal_line is a string (the role-selected goal echo) or "" — empty ⇒
          nothing appended (output byte-identical to the pre-role-goals reason)

    Ensures:
        - Returns the POKE_REASON_TEMPLATE filled with verdict["specifics"], with
          goal_line appended as a trailing blank-line-separated block when
          goal_line is non-empty
        - Rides the top-level Stop-hook `reason` field — NEVER systemMessage
    """
    reason = POKE_REASON_TEMPLATE.format( specifics=verdict[ "specifics" ] )
    if goal_line:
        reason = reason + "\n\n" + goal_line
    return reason


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

    # Inward twin — manager owes a fresh verification (debounce predicate + signal)
    assert manager_needs_verification( [ { "session_name": "w" } ], None, 1_000_000.0 ) is True
    assert manager_needs_verification( [ ], None, 1_000_000.0 ) is False     # no workers ⇒ no debt
    v = evaluate_work_owed( needs_verification=True )
    assert v[ "work_owed" ] is True and v[ "signals" ] == [ "needs_verification" ]

    # Outward twin — an open user-gate is owed work (re-ask); answered clears it
    v = evaluate_work_owed( open_user_gates=[ { "id": "g1" } ] )
    assert v[ "work_owed" ] is True and v[ "signals" ] == [ "outstanding_user_gate" ]
    assert evaluate_work_owed( open_user_gates=[ None ] )[ "work_owed" ] is False

    # Face A (spin-up nudge) — debounce predicate + signal
    assert manager_needs_spinup_check( 5, True,  None, 1_000_000.0 ) is True      # backlog+capacity+never-checked
    assert manager_needs_spinup_check( 5, False, None, 1_000_000.0 ) is False     # no idle capacity ⇒ never
    assert manager_needs_spinup_check( 1, True,  None, 1_000_000.0 ) is False     # backlog < N ⇒ never
    assert manager_needs_spinup_check( True, True, None, 1_000_000.0 ) is False   # bool backlog rejected
    v = evaluate_work_owed( needs_spinup_check=True )
    assert v[ "work_owed" ] is True and v[ "signals" ] == [ "spinup_nudge" ]

    # Face B (operator-gate re-surface) — debounce predicate + signal
    assert manager_needs_question_surface( [ { "id": "og1" } ], None, 1_000_000.0 ) is True   # open gate, never surfaced
    assert manager_needs_question_surface( [ ], None, 1_000_000.0 ) is False                  # no open gate ⇒ never
    assert manager_needs_question_surface( [ None ], None, 1_000_000.0 ) is False             # falsy entries filtered
    v = evaluate_work_owed( needs_question_surface=True )
    assert v[ "work_owed" ] is True and v[ "signals" ] == [ "surface_operator_gates" ]

    reason = build_poke_reason( evaluate_work_owed(
        todo_items=[ { "status": TODO_IN_PROGRESS, "owned_by_me": True } ] ) )
    assert reason.startswith( "Do not stop yet" )
    assert "work_owed: false" in reason

    return True


if __name__ == "__main__":   # pragma: no cover - manual smoke entrypoint
    ok = quick_smoke_test()
    print( f"heartbeat_work_owed smoke: {'PASS' if ok else 'FAIL'}" )
