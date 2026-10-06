#!/usr/bin/env python3
"""
Heartbeat Hook: work-owed oracle (pure decision function).

Answers the work-owed decision step, "determine work-owed", consulted only when there is no fresh, honored hold.
The hold artifact short-circuits the first two steps.
If this oracle reports no owed work, the instance is done and must not be poked.
If work is owed and the per-session poke cap is not exhausted, it is poked.

Design: /mnt/DATA01/include/www.deepily.ai/projects/planning-is-prompting/src/rnd/2026.06.02-stop-hook-natural-heartbeat-poker.md (sections 0 and 4).
See: src/rnd/v0.1.8/2026.06.04-heartbeat-hook/01-spike-findings-and-stop-py-seam-analysis.md

This is a pure core: the module never fetches live commons, transcript or TODO data.
All state is injected as already-parsed lists.
The live plumbing (read TODO.md, scan Pending Decisions, query open DMs) belongs to the `stop.py` Branch-C integration layer.
That keeps the hold-artifact discipline: a collision-free pure core now, live wiring at the gated seam later.

Work-owed signals, strongest first.
The declared-hold-reason signal that heads the design list is handled by `heartbeat_hold`; this oracle is the else branch after no fresh hold.
Signal 1: TODO items you own that are in_progress.
Signal 2: TODO items you own that are unstarted (pending).
Signal 3: Pending Decisions that are not blocked on the user.
Signal 4: unanswered inbound questions, meaning expect_reply DMs addressed to you that you have not answered (work you owe a peer).
Signal 5: outstanding delegations, meaning spawned workers of yours that are still alive and not reaped.
A manager supervising a live crew owes review and reap duty even with zero Task* items filed.
So it must never idle-announce while workers are out.
Later signals arrive as injected bools or lists: needs_verification, open user gates, operator-gate re-surface and spin-up nudge (see evaluate_work_owed).

Signal 4 reads "open expect_reply DM" as an inbound question you owe a reply to, which means work owed and a poke.
An outbound expect_reply DM where you await a peer's reply is the opposite.
That is a legitimate awaiting signal and belongs to the hold artifact's `awaiting` field, not this oracle.
It is cheap to adjust, since the list is injected.
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
#
# SHORTENED 2026-07-27 (Rick, verbosity pass). "you stopped with" was dropped: the
# poke fires ONLY on a Stop, so it stated the one thing already guaranteed. The
# "Do not stop yet" PREFIX is deliberately retained — every downstream assertion
# matches on it, and it keeps the marker readable as an instruction rather than a
# machine token. Safe to change because emitter and detector both DERIVE from this
# one constant (POKE_REASON_TEMPLATE :142, DECLARED_OWED_REASON, and
# is_heartbeat_poke_prompt :188); nothing outside tests hardcodes the full string,
# and the arbiter keys on its OWN sentinel, not this one.
POKE_PROMPT_SENTINEL = "Do not stop yet"

# Arbiter-poke sentinel (b33c8e96, 2026-06-30) — the SHARED opening clause of the
# arbiter's stuck-poke and manager-staleness poke bodies. Unlike the heartbeat
# self-poke (POKE_PROMPT_SENTINEL, which rides the Stop-hook `reason` and lands at
# the START of the re-submitted prompt), an arbiter poke is delivered WRAPPED in a
# peer-DM <system-reminder> envelope (build_peer_dm_reminder) via tmux, so its body
# sits in the MIDDLE of the prompt. The matcher therefore keys on this sentinel as a
# SUBSTRING (not a prefix). CROSS-PACKAGE single source of truth: the cosa-side
# arbiter (_format_poke + _format_manager_stale_poke) DERIVES both poke prefixes from
# this constant so the emitter and this matcher cannot drift. Without the match, a
# wrapped arbiter poke was mistaken for genuine user re-engagement and RESET the
# Stop-hook poke-cap (user_prompt_submit.py:86), so each arbiter escalation reopened a
# fresh poke budget → the two detectors could reset each other → token burn while the
# user is away.
ARBITER_POKE_SENTINEL = "Heartbeat arbiter ("

# Muted-poke sentinel (2026-07-22) — the marker prefixed to the operator's
# configured substitute text when heartbeat.poke_output_enabled is false and the
# substitute is injected via tmux. Same c121037b failure mode as the two sentinels
# above, reproduced live within minutes of shipping the mute: the substitute is
# re-submitted as a prompt, UserPromptSubmit saw ordinary prose, classified it as
# genuine user re-engagement, RESET the poke-cap — so the cap could never
# accumulate and the injection re-fired every Stop with nobody typing. Matched as
# a PREFIX (it opens the injected text, like POKE_PROMPT_SENTINEL).
MUTE_PROMPT_SENTINEL = "[heartbeat: pokes muted]"

# Poke reason template (rides the top-level `reason` field — NEVER systemMessage;
# see 01-…-seam-analysis.md §ERRATA). The hold-write instruction names the FULL
# hyphenated session id explicitly (c121037b facet 2): get_session_info hands an
# agent the SHORT 8-char id, and a hold written at the short id while the hook
# reads at the full stable id is silently ignored. read_hold also falls back
# across id forms (heartbeat_hold._read_hold_path) as belt-and-suspenders.
# bug d0d7f068 (honest text): the clause between the specifics and the menu is
# VARIABLE. Default = "and no fresh hold" (unchanged byte-for-byte). But when the
# poke fires via the obligation-OVERRIDE while a hold IS honored (a DUE user-gate /
# a verification debt outranks the hold's quiescence by design), asserting "no
# fresh hold" is FALSE — the hold is fresh, just overridden. The override clause
# states the true state so the pokee isn't told to declare a hold it already has.
NO_FRESH_HOLD_CLAUSE   = "No fresh hold. "
HOLD_OVERRIDDEN_CLAUSE = (
    "Your fresh hold is HONORED but OVERRIDDEN by a due obligation (a user-gate re-ask "
    "or a worker-verification debt) — owed work a declared hold cannot suppress. "
)

# COMPRESSED 2026-07-27 (Rick): 1,099 -> 650 chars rendered, 41% shorter. Every
# MECHANICAL detail is retained verbatim, because each one is a thing that silently
# fails when omitted: the FULL hyphenated session id (a hold written at the short
# 8-char id is ignored — c121037b facet 2), `awaiting: peer:<name>`, `work_owed:
# false`, the three ask_* verb names, and `stamp last_spinup_check_ts`.
#
# What went was PROSE, not instruction: a worked example of how to phrase a DM, a
# gloss on what "blocked on the USER" means, and a restatement that a user-gate is
# owed work (already carried by "Not buried in a notify").
#
# Option labels are FRONT-LOADED (WORK IT / PEER-BLOCKED / USER-BLOCKED / NOTHING
# OWED) so a reader routes to their own case on the first two words instead of
# parsing four question-form sentences to find which one is theirs. A poke nobody
# finishes reading is a poke that does not fire.
#
# 🔴 OPTION 2 NAMES THE VERB, NOT A FILENAME (row 6698d40f (a), 2026-09-16). It used to say
# "write .heartbeat-hold-<FULL-hyphenated-session-id>.json": a filename with no directory
# and no verb, so an agent wrote it where it stood, the repo root, and the hook never
# honored it. Tiffany and María did exactly that all evening on 2026-09-14. The same shape
# was taken out of workflow/fleet-pause-resume.md in July and survived here. The verb
# picks the directory and checks the hook's own search finds the hold.
#
# THE ID IS THE STABLE ONE. The hook keys holds on `resolve_stable_session_id`, the
# PRE-clear id. After a /clear, "your full session id" reads as `claude_code.session_id`,
# which is the new one, and a hold under it is never read. `get_session_info()` hands an
# agent both, so the poke names the field.
POKE_REASON_TEMPLATE = (
    POKE_PROMPT_SENTINEL + " — {specifics}\n{hold_clause}Do ONE now:\n"
    "1. WORK IT — drive it. Manage a crew? Delegate, spawn if tasks > workers. Never build it yourself.\n"
    "2. PEER-BLOCKED — DM for status, then declare a hold with the verb (never hand-write the JSON):\n"
    "   python3 $LUPIN_ROOT/src/lupin_cli/claude_code/hooks/lib/heartbeat_hold_io.py write "
    "--session-id <stable id> --persona <you> --reason <why> --awaiting peer:<name>\n"
    "   <stable id> is claude_code.stable_session_id from get_session_info(), NOT the post-/clear id "
    "or the 8-char form. It must print \"honored yes\".\n"
    "3. USER-BLOCKED — fire ask_yes_no / ask_multiple_choice / converse THIS turn. Not buried in a "
    "notify, not a hold. Re-ask until answered.\n"
    "4. NOTHING OWED — prove it: the same verb with --no-work-owed (work_owed: false)."
)

SPECIFICS_JOINER  = "\n- "

NO_WORK_SPECIFICS = "no owed work detected"


# Store status -> the words a human reads. The poke used to say "unstarted TODO
# item(s) you own", which named a surface RETIRED at the 2026-06-17 store-only
# cutover — the native harness list stopped being the liveness source, so a
# rehydrating session was pointed at the wrong place by its own poke.
_STATUS_WORDS = { "in_progress": "in progress", "queued": "queued", "parked": "parked-expired" }

# The order buckets are read in. Explicit rather than dict-order: "2 in progress,
# 10 queued" and "10 queued, 2 in progress" are the same facts in different
# priority orders, and the first is the one that matches how the work is picked up.
_STATUS_ORDER   = ( "in_progress", "queued", "parked" )

# DERIVED, NOT RESTATED. This was a hand-written ( "P0", "P1", "P2", "P3" ) and it
# went stale the moment the enum widened to P0-P5 (b4cdf47e, row 0107c19e, Rick's
# broadcast e254ec7d). Counts never went missing — the `unknown` bucket below keeps
# the parts summing to the whole — but the ORDER did, and the "start with the N Xs"
# pointer went SILENT on any board holding only the new levels, which is every board
# minted since P5 became the default for all creation paths.
#
# Do NOT replace this with ( "P0" ... "P5" ). That is the same defect with a later
# expiry date. The server enum is the authority; this module answers to it.
#
# The import does NOT breach the PURE CORE constraint in this module's docstring:
# that rule forbids FETCHING live commons/transcript/TODO state, and this is a
# static tuple resolved at import. `hooks/lib/task_store_drain.py` imports from
# cosa.rest at module level the same way, and `user_prompt_submit.py` puts
# $LUPIN_ROOT/src on sys.path before importing any lupin_cli package, so cosa is
# reachable at this point in the boot path (measured, both directions, 2026-09-07).
from cosa.rest.task_store_rules import VALID_PRIORITIES

_PRIORITY_ORDER = tuple( VALID_PRIORITIES )


def _join_series( parts ):
    """
    Join rendered strings into an Oxford-comma series: "a", "a and b", "a, b, and c".

    Requires:
        - parts is a list of already-rendered strings

    Ensures:
        - returns "" for an empty list (the caller omits the clause entirely)
        - 1 part -> itself; 2 parts -> "x and y"; 3+ -> "x, y, and z"
    """
    if not parts:      return ""
    if len( parts ) == 1: return parts[ 0 ]
    if len( parts ) == 2: return f"{parts[0]} and {parts[1]}"
    return ", ".join( parts[ :-1 ] ) + f", and {parts[-1]}"


def format_owed_summary( status_breakdown, priority_breakdown ):
    """
    Render the poke's owed line: total, status split, priority split, and where to start.

    For example "12 owed: 2 in progress, 10 queued", followed by a priority clause and a start-with pointer.
    It replaces a two-line form that made the reader add counts and never named a priority, while the standing order is descending priority.
    Empty buckets are omitted, not zeroed: a printed 0 is noise on every poke, and an absent bucket and a zero bucket are different claims.

    Requires:
        - status_breakdown is { store_status: count } or falsy
        - priority_breakdown is { priority: count } or falsy (priorities come from `VALID_PRIORITIES`)

    Ensures:
        - returns "" when the total is 0 or the status breakdown is empty/unusable;
          the caller then falls back to its own specifics rather than printing "0 owed"
        - the total is summed from the status breakdown, not taken on faith from a
          separate count, so the parts and the whole cannot disagree in one sentence
        - the priority clause is omitted entirely when no priority data is available,
          rather than implying every row is unprioritized
        - "start with the N P1s" names the highest priority actually present, so it
          points at P0 when a P0 exists and never invents a level with no rows
        - never raises on malformed input (foreign hook-payload data)
    """
    if not isinstance( status_breakdown, dict ): return ""
    counts = { k: v for k, v in status_breakdown.items() if isinstance( v, int ) and v > 0 }
    total  = sum( counts.values() )
    if total <= 0: return ""

    known  = [ f"{counts[k]} {_STATUS_WORDS[k]}" for k in _STATUS_ORDER if counts.get( k ) ]
    # A status the map does not know still COUNTS toward the total and is named
    # verbatim — silently dropping it would make the parts stop summing to the whole.
    extra  = [ f"{v} {k}" for k, v in sorted( counts.items() )
               if k not in _STATUS_WORDS ]
    line   = f"{total} owed: " + ", ".join( known + extra )

    if isinstance( priority_breakdown, dict ):
        pri = { k: v for k, v in priority_breakdown.items() if isinstance( v, int ) and v > 0 }
        # MEMBERSHIP, not truthiness. `pri` is already >0-filtered one line up, so a
        # second truthiness test here would be a REDUNDANT guard for the same rule —
        # and two guards for one rule make the rule unfalsifiable: mutation 2026-07-27
        # showed neither could be broken alone because the other covered it. A test
        # that cannot fail is not verifying anything.
        present = [ p for p in _PRIORITY_ORDER if p in pri ]
        unknown = sorted( k for k in pri if k not in _PRIORITY_ORDER )
        if present or unknown:
            rendered = [ f"{pri[p]} at {p}" for p in present ] + [ f"{pri[u]} at {u}" for u in unknown ]
            line += " \u00b7 " + _join_series( rendered )
            if present:
                top, n = present[ 0 ], pri[ present[ 0 ] ]
                line += f" \u2014 start with the {top}" if n == 1 else f" \u2014 start with the {n} {top}s"
    return line


def is_heartbeat_poke_prompt( prompt ):
    """
    Return True if prompt is an injected liveness poke (heartbeat or arbiter), not user input.

    UserPromptSubmit must not treat either synthetic prompt as user re-engagement: that reset the per-session poke cap on every poke, so the cap never halted.
    A heartbeat self-poke is re-submitted via tmux send-keys, so `POKE_PROMPT_SENTINEL` leads the prompt: matched by prefix after left-strip.
    An arbiter poke (stuck or manager-stale) arrives wrapped in a peer-DM system-reminder envelope, so `ARBITER_POKE_SENTINEL` sits mid-prompt: matched by substring.

    Requires:
        - prompt is a string or None (foreign hook-payload data)

    Ensures:
        - Returns True iff prompt (left-stripped) starts with `POKE_PROMPT_SENTINEL`
          or `MUTE_PROMPT_SENTINEL`, or prompt contains `ARBITER_POKE_SENTINEL`
        - Returns False for None / non-string / empty / genuine user prompts
        - Never raises
    """
    if not isinstance( prompt, str ):
        return False
    stripped = prompt.lstrip()
    if stripped.startswith( POKE_PROMPT_SENTINEL ) or stripped.startswith( MUTE_PROMPT_SENTINEL ):
        return True
    return ARBITER_POKE_SENTINEL in prompt


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
    Filter Pending-Decisions to those not blocked on the user.

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

    The shared, single-source age helper (one descriptive name everywhere).
    It is consumed by both _inbound_age_seconds (inbound-DM age-out) and manager_needs_verification (the look-in debounce).

    Requires:
        - ts is anything (defensive over foreign data); only a str dates
        - now_epoch is a float/int POSIX timestamp ("now", injected by caller)

    Ensures:
        - Returns ( now_epoch - parsed_ts ) in seconds for a parseable str ts
        - Returns None when ts is missing / non-string / unparseable
        - Pure: parses the injected string and does arithmetic only; reads no clock
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
    Return whether a manager owes a fresh worker-verification receipt now (pure debounce).

    A manager that merely waits must read as work-owed, so the oracle keeps poking it to verify; liveness is not progress.
    It self-clears the instant the manager looks in (stamps `last_looked_in_on_workers_ts`); a manager who sits does not reset it.

    Requires:
        - outstanding_delegations is an iterable of (truthy means alive worker)
          entries, or None; the same list the outstanding_delegation signal
          consumes (manifest intersected with live bridges, gathered by the IO shell)
        - last_verification_ts is the manager's most-recent verification stamp
          (ISO-8601 str) or None (never looked in)
        - now_epoch is the caller's injected "now" (POSIX seconds)
        - threshold_seconds is the debounce window (600 = 10 min)

    Ensures:
        - Returns False when no worker is out (all dead or reaped means nothing to
          verify, so never a verification debt); this gates the whole predicate
        - With >= 1 worker out: True iff there is no datable prior look-in
          (last_verification_ts None or unparseable biases to owe a first or repeat
          look; the poke cap bounds the cost) or the look-in age >= threshold
        - Boundary: age exactly == threshold owes (>=), so a 10-min-old look-in is
          due, mirroring "verify at least every 10 min"
        - Pure: no clock, no IO; never raises on well-formed input
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
    Return whether a manager owes a crew spin-up nudge now (pure debounce predicate).

    A manager with a backlog and idle crew capacity must read as work-owed, so the oracle names "consider spinning up a crew" next Stop.
    The manager then decides and acts itself: this is a nudge, not an auto-spin.
    It self-clears when the manager stamps `last_spinup_check_ts`, so a manager who just checked is not re-nudged and one who sits is.

    Requires:
        - backlog_count is the manager's owed-item count (queued + in_progress,
          gathered by the IO shell via task_query(accountable_manager=me)); any
          type accepted (foreign data), but only a non-bool int >= backlog_min_n counts
        - idle_capacity is a bool, True iff the manager has room to spawn another
          worker under the cap-8 fleet bound (live_workers < cap)
        - last_spinup_check_ts is the most-recent spin-up-check stamp (ISO-8601
          str) or None (never checked)
        - now_epoch is the caller's injected "now" (POSIX seconds)
        - threshold_seconds is the debounce window (600 = 10 min)
        - backlog_min_n is the backlog floor below which no nudge fires

    Ensures:
        - Returns False unless all three hold: no idle capacity or backlog < N
          short-circuits to False regardless of elapsed time (a full crew or a small
          backlog never nudges; the manager's judgment is preserved)
        - bool backlog_count is rejected (True must not slip through as 1)
        - With capacity and backlog >= N: True iff there is no datable prior check
          (None or unparseable biases to nudge a first check; the poke cap bounds the
          cost) or the check age >= threshold_seconds
        - Boundary: age exactly == threshold owes (>=)
        - Pure: no clock, no IO; never raises on well-formed input
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
    Return whether a session owes a re-surface of its open operator gates now (pure debounce).

    A session holding an open operator gate must re-fire those asks every `threshold` seconds, so the human's decision is never buried.
    It generalizes the per-gate due_gates cadence to one per-manager debounce, replacing N independent per-session re-ask timers.
    It self-clears when the session stamps `last_surfaced_questions_ts` after re-firing.

    Requires:
        - open_operator_gates is an iterable of truthy gate entries (the open,
          unanswered operator gates, gathered by the IO shell), or None
        - last_surfaced_questions_ts is the most-recent surface stamp (ISO-8601
          str) or None (never surfaced)
        - now_epoch is the caller's injected "now" (POSIX seconds)
        - threshold_seconds is the debounce window (600 = 10 min)

    Ensures:
        - Returns False when there is no open operator gate (nothing to surface);
          this gates the whole predicate, mirroring the no-workers gate of the inward twin
        - With >= 1 open gate: True iff there is no datable prior surface
          (None or unparseable biases to surface) or the surface age >= threshold_seconds
        - Boundary: age exactly == threshold owes (>=)
        - Pure: no clock, no IO; never raises on well-formed input
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
    Split inbound entries into (fresh, stale) by age.

    Requires:
        - inbound is an iterable of dicts (each may carry a "ts" ISO string)
        - now_epoch is the caller's injected "now" (POSIX seconds)
        - stale_after_seconds is a positive number

    Ensures:
        - Returns ( fresh, stale ): an entry is stale iff its age strictly
          exceeds stale_after_seconds; otherwise fresh
        - An undateable entry (missing/unparseable ts) is fresh, a bias to owed
          consistent with the gatherer's missing-tenure-floor philosophy; the
          poke cap bounds the cost
        - Input order is preserved within each bucket
        - Pure: no clock, no IO; never raises on well-formed dict input
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
                        needs_spinup_check=False,
                        owed_summary=None ):
    """
    Return the pure work-owed verdict over injected state (the work-owed decision step).

    Requires:
        - todo_items, pending_decisions, unanswered_inbound_questions,
          outstanding_delegations and open_user_gates are each an iterable of
          dicts, or None (treated as empty)
        - needs_verification is a bool, the inward twin's debounce verdict (computed by the IO shell via manager_needs_verification)
        - needs_question_surface / needs_spinup_check are bools, the Face B / Face A debounce verdicts
          (manager_needs_question_surface / manager_needs_spinup_check, computed by the IO shell)

    Ensures:
        - Returns a verdict dict: { "work_owed": bool, "signals": [str, ...] strongest-first and only those that fired, "specifics": str for the poke reason }
        - work_owed is True iff at least one signal fired
        - signals order is fixed strongest-first: todo_in_progress, todo_unstarted, pending_decision,
          unanswered_inbound_question, outstanding_delegation, needs_verification, outstanding_user_gate,
          surface_operator_gates, spinup_nudge
        - outstanding_delegation fires iff >= 1 truthy entry is injected: an alive, un-reaped spawned worker is owed work.
          All-dead or reaped means empty, so no signal and idle is allowed. The live gathering is the caller's IO, not this oracle's.
        - needs_verification fires iff the injected bool is truthy (the inward twin: workers out and its look-in is stale).
          The IO shell computes the bool; this oracle only routes it to a signal.
        - outstanding_user_gate fires iff >= 1 truthy open-gate entry is injected (the outward twin). An open direct user gate
          must be re-surfaced (re-asked), never parked. The IO shell filters to open gates, so an answered gate clears it.
          Its specifics carries the Face B obligation verbatim (see manager-autonomy.md and role-goals.md): the manager must fire
          a dedicated high-priority action-required ask the moment a user blocker is raised, never buried, and mint the typed operator gate.
        - surface_operator_gates fires iff the injected bool is truthy: the per-manager re-surface debounce has elapsed
          while >= 1 operator gate is open. The IO shell computes the bool; this oracle only routes it.
          Its specifics carries the same Face B obligation wording.
        - spinup_nudge fires iff the injected bool is truthy: a backlog >= N with idle crew capacity and the spin-up-check
          debounce elapsed. The manager then decides and acts of its own accord (a nudge, never an auto-spin).
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

    # SIGNALS ARE UNCONDITIONAL; only the WORDING is overridable (Rick, 2026-07-27).
    # `owed_summary` replaces the two count sentences with one line carrying the
    # total, the status split and the priority split. It must NOT gate the signals:
    # `todo_in_progress` / `todo_unstarted` drive the verdict and the oracle log, and
    # letting a formatting choice decide whether a signal fires would make the poke's
    # PROSE authoritative over its LOGIC.
    if in_progress:
        signals.append( "todo_in_progress" )
    if unstarted:
        signals.append( "todo_unstarted" )

    if owed_summary:
        specifics.append( owed_summary )
    else:
        # Fallback wording for the TRANSCRIPT-REPLAY path, which has no store
        # breakdown to summarize. Deliberately UNCHANGED, "TODO item(s)" included:
        # on that path the items really ARE the harness TodoWrite list, so the word
        # is accurate there. It was only wrong on the store path, where it named a
        # surface retired at the 2026-06-17 cutover — and that path now renders
        # `owed_summary` instead.
        if in_progress:
            specifics.append( f"{len( in_progress )} in-progress TODO item(s) you own" )
        if unstarted:
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
        # Compressed 2026-07-27 (Rick): 196 -> 117 chars. The redline and the stamp
        # are the two load-bearing halves and both survive verbatim; "(or idle crew
        # capacity)" and "the next worker" were restating the trigger back at the
        # reader, who is being told about it in the same sentence.
        specifics.append( "tasks > workers — STAFF UP THIS TICK: spawn/assign now. Waiting to be told is a redline. (stamp last_spinup_check_ts)" )

    return {
        "work_owed" : bool( signals ),
        "signals"   : signals,
        # ONE OBLIGATION PER LINE (Rick, 2026-07-27). "; " joined up to four separate
        # demands — owed rows, workers still out, a verification debt, a staff-up — into
        # a single wrapping paragraph where the reader had to parse punctuation to find
        # the boundaries. The FIRST specific stays on the sentinel line because it is
        # the headline (the owed count); the rest become their own dashed lines.
        # "- " and not "· ", which the owed summary already uses INSIDE itself to
        # separate the status split from the priority split — reusing it as the
        # line bullet would make one glyph mean two different groupings.
        "specifics" : SPECIFICS_JOINER.join( specifics ) if specifics else NO_WORK_SPECIFICS,
    }


def build_poke_reason( verdict, goal_line="", hold_overridden=False, sweep_line="" ):
    """
    Compose the self-poke `reason` string from a work-owed verdict.

    The role-selected goal line is an injected string: the IO shell (stop.py) reads it from the `heartbeat <role> goal line` configuration key.
    This pure core only appends it, because the config read is IO and stays in the shell.
    Canonical goal text: planning-is-prompting workflow/role-goals.md, section "Injection: the poke echo".

    Requires:
        - verdict is the dict returned by evaluate_work_owed (has "specifics")
        - goal_line is a string (the role-selected goal echo) or "", where empty means
          nothing appended (output byte-identical to the pre-role-goals reason)
        - sweep_line is the per-persona board-sweep progress gate (board_sweep.
          sweep_progress_line) or "": a sweeping seat may not stop until every owed row
          has been iterated. Injected like goal_line: the ledger read is IO and stays in the shell
        - hold_overridden is a bool, True when the poke fires via the obligation
          override while a hold is honored (the caller passes obligation_overrides and
          is_honored). Selects the honest hold clause so the reason never asserts
          "no fresh hold" against a fresh honored hold. Default False gives the byte-identical "and no fresh hold" clause.

    Ensures:
        - Returns the `POKE_REASON_TEMPLATE` filled with verdict["specifics"] and the
          hold clause (`NO_FRESH_HOLD_CLAUSE` by default, `HOLD_OVERRIDDEN_CLAUSE` when
          hold_overridden), with goal_line appended as a trailing blank-line-separated
          block when goal_line is non-empty
        - Rides the top-level Stop-hook `reason` field, never systemMessage
    """
    hold_clause = HOLD_OVERRIDDEN_CLAUSE if hold_overridden else NO_FRESH_HOLD_CLAUSE
    reason = POKE_REASON_TEMPLATE.format( specifics=verdict[ "specifics" ], hold_clause=hold_clause )
    if goal_line:
        reason = reason + "\n\n" + goal_line
    # LAST, deliberately. The sweep gate is the most specific instruction the seat has —
    # it names a count that must reach a number — so it must not be read as a footnote to
    # the role goal above it. An empty sweep_line leaves the reason byte-identical to the
    # pre-sweep output, which is the normal state of every session that is not sweeping.
    if sweep_line:
        reason = reason + "\n\n" + sweep_line
    return reason


def quick_smoke_test():
    """
    Run a self-contained smoke test of the decision matrix.

    Ensures:
        - Returns True if owed / not-owed verdicts, ordering and reason text
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
