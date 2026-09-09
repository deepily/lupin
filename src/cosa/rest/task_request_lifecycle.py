"""
A MANAGER'S PROMOTE/DEMOTE REQUEST: what moves it, and what deliberately does not.

Row c9fafb9d, rules 3 and 4. Rick ruled the POLICY on 2026-09-08 ~11:58 EDT by keypress:

    "it is me and me alone not managers that gets to promote and demote task items into
     the live list and out of it back into the task area me alone. Only thing managers
     can do is request And there's requests default to no"

and the SEMANTICS across 2026-09-09 ~17:40 and ~18:55, relayed by Mr. Radio 🦉:

    · a request PERSISTS until he acts on it — it does not expire and does not time out
    · a TIMEOUT leaves it PENDING. A timeout is not a denial
    · a DENIAL is a different thing: it CLOSES the row and forces a RE-FILE
    · the verdict is recorded ON THE REQUEST ROW, not carried by a notification

🔴 WHY THIS IS A MODULE AND NOT A FEW LINES INSIDE WHATEVER DOOR LANDS. The tree already
contains machinery that looks exactly right for this and is exactly wrong:
`TaskPromotionTicket` carries a `resolves_by` stamped at mint, a background resolver, and
a sweeper that marks an unanswered ticket `stalled`. Every one of those is EXPIRY, and
expiry is the thing Rick ruled against. Anyone building the request door by reaching for
the nearest similar thing gets a request that dies on a clock.

⇒ So the rule that a timeout is a NON-EVENT is written here, once, as a function that can
be called and a guard that can refuse — rather than as a sentence in a design document the
next implementer has to have read. A rule that depends on remembering is not installed.

⚠️ WHAT THIS MODULE DELIBERATELY DOES NOT DECIDE, because nobody has ruled it:
  · WHERE a request is stored — a task-store row, a new table, something else.
  · The HTTP shape of the door that files one.
Neither changes the answers below, which is why this can be built while they are open. If
one of them turns out to change an answer here, THAT is a finding — and this module would
be the cheapest possible place in the tree to discover it.

⚠️ AND IT HOLDS NO STORAGE AND NO I/O ON PURPOSE. Pulled out for the reason
`refusal_for_admission` and `promotion_precheck` were: inline, the only way to watch this
refuse is to stand up a database and drive a door, so the cheap tests would have to assert
on something adjacent and call THAT the control.
"""

# The two verbs one door serves. A re-export of the approval module's own set rather than a
# second copy: that module decides what a move IS, and two pieces of code deciding one rule
# agree until they do not.
from cosa.rest.task_approval_settings import REQUESTABLE_MOVES   # noqa: F401


# ── THE STATES ─────────────────────────────────────────────────────────────────
#
# Named rather than left as literals, for the reason `task_promotion_resolver` names its
# own five: whatever columns eventually hold this will be governed by application code
# rather than by an enum constraint, so a typo'd state would be written happily. Naming
# them makes a typo a NameError instead of a row.
REQUEST_PENDING  = "pending"
REQUEST_APPROVED = "approved"
REQUEST_DENIED   = "denied"

REQUEST_STATES = frozenset( { REQUEST_PENDING, REQUEST_APPROVED, REQUEST_DENIED } )

# 🔴 BOTH VERDICTS ARE TERMINAL, AND `denied` BEING TERMINAL IS THE HALF WORTH SAYING OUT
# LOUD. A denial does not park the request or send it back to pending: it CLOSES it, and
# the manager must file a NEW one. That is Rick's own distinction — a denial "closes the
# row and forces a re-file" — and it is exactly what separates a denial from a timeout,
# which changes nothing at all.
REQUEST_TERMINAL_STATES = frozenset( { REQUEST_APPROVED, REQUEST_DENIED } )


def is_terminal( state ):
    """
    Whether a request has been answered and is finished.

    Requires:
        - state is one of REQUEST_STATES

    Ensures:
        - True for approved and denied, False for pending
        - never raises for a valid state
    """
    return state in REQUEST_TERMINAL_STATES


def outcome_of_silence( state ):
    """
    What an unanswered request is, after any amount of time — including forever.

    🔴 THE WHOLE POINT OF THIS FUNCTION IS THAT IT TAKES NO CLOCK. There is no `now`, no
    deadline, no elapsed argument, and that absence IS the ruling made mechanical: a
    request cannot be aged out because there is nothing here to age it against. A future
    edit adding a timestamp parameter is the defect, not the fix.

    ⚠️ THIS IS NOT IN TENSION WITH "A REQUEST DEFAULTS TO NO". Silence NEVER GRANTS — a
    pending request has authorised nothing and the row has not moved, which is what
    "defaults to no" protects. What silence also does not do is DENY: a denial is a verdict
    Rick gives, and it closes the request. Reading "defaults to no" as "an old request is
    refused" would quietly delete the requests he has not got to yet, which is the opposite
    of a queue he works through.

    Requires:
        - state is one of REQUEST_STATES

    Ensures:
        - a PENDING request is still PENDING, whatever the elapsed time
        - an already-answered request keeps its verdict — silence cannot overturn a
          keypress in either direction
        - never raises for a valid state
    """
    return state


def grants_the_move( state ):
    """
    Whether this request authorises the promote or demote it asks for.

    Ensures:
        - True ONLY for an explicit approval
        - False for pending AND for denied — those two differ in whether the manager must
          re-file, not in whether anything is authorised now
        - never raises
    """
    return state == REQUEST_APPROVED


def requires_a_refile( state ):
    """
    Whether the manager must file a NEW request in order to ask again.

    ⚠️ THE ANSWER FOR `pending` IS FALSE, AND IT IS THE ONE PEOPLE WILL GET WRONG. A
    request that has sat for a day is still in front of Rick; re-filing it would put the
    same question in his queue twice and cost him the interruption his own no-batches rule
    exists to prevent. Only a DENIAL clears the way for a fresh ask.

    Ensures:
        - True only for a denied request
        - never raises
    """
    return state == REQUEST_DENIED


def refusal_for_verdict( state, verdict, actor_is_operator ):
    """
    Why this verdict may not be recorded on this request — or None if it may.

    Three separate refusals, kept apart because collapsing them would tell a caller the
    wrong thing about what to do next:

        · NOT THE OPERATOR — Rick alone answers. A manager may file and may read; the
          verdict is his. This is rules 1 and 2 one layer over: if a manager could answer
          their own request, the request door would BE a way to promote without him, which
          is the thing it exists to prevent.
        · ALREADY ANSWERED — a terminal request is finished. Overwriting a verdict would
          let a second caller silently replace his answer with another.
        · NOT A VERDICT — `pending` is where a request already is, not something anyone
          decides. Accepting it here would make "un-answer this request" a reachable
          operation, and nothing has ruled that it should be.

    Requires:
        - state is the request's CURRENT state, one of REQUEST_STATES
        - verdict is the state being recorded
        - actor_is_operator is a SERVER-RESOLVED boolean, never a caller-declared string

    Ensures:
        - returns None only when an operator records approved or denied on a PENDING
          request
        - otherwise a non-empty detail naming which of the three refusals it is, and what
          to do instead
        - never raises

    ⚠️ `actor_is_operator` IS A BOOLEAN THIS FUNCTION TRUSTS, AND THAT IS THE SEAM RATHER
    THAN A HOLE. Deciding operator-hood belongs to whatever resolved the caller's validated
    account; re-deciding it here would be a SECOND derivation of an authorization answer,
    fed weaker inputs than the first. Row b8205986 records what happens when a
    caller-declared string gets to answer this question — so callers of this function must
    pass a FACT, never a claim.
    """
    if not actor_is_operator:
        return (
            "recording a verdict on a promote/demote request is the operator's alone "
            "(Rick, 2026-09-08). A manager may FILE a request and read its state; the "
            "answer is his. Nothing about this request has changed."
        )
    if verdict not in REQUEST_TERMINAL_STATES:
        return (
            f"'{verdict}' is not a verdict. A request may only be recorded as "
            f"'{REQUEST_APPROVED}' or '{REQUEST_DENIED}'; '{REQUEST_PENDING}' is where a "
            f"request already is, and there is no ruled way to un-answer one."
        )
    if is_terminal( state ):
        return (
            f"this request is already '{state}' and a verdict is final. To ask again, FILE "
            f"A NEW REQUEST — a denial closes the row and forces a re-file (Rick, "
            f"2026-09-09). Overwriting would replace an answer he actually gave."
        )
    return None


# ── WHICH BADGE COUNTS A REQUEST (Rick via Mr. Radio, 2026-09-09 ~19:04) ───────
#
# His ruling: the TASK-AREA badge counts DEMOTE requests, the HOLDING-AREA badge counts
# PROMOTE requests, each badge counts only its own list, and the two do NOT sum into a
# single total.
#
# 🔴 THE RULE UNDERNEATH IT, WHICH IS WHY THE MAPPING LOOKS INVERTED AND IS NOT. A badge
# sits on the list the row IS IN RIGHT NOW, never the list it is asking to reach:
#
#     a DEMOTE is filed against a row that is already LIVE  -> it shows on the task list
#     a PROMOTE is filed against a row in the HOLDING area  -> it shows in the holding area
#
# So a request is always visible beside the row it is about, which is the whole point of
# putting it there rather than on a page of its own. Written down because "demote -> task
# area" reads backwards to anyone who has not seen the reason, and a reader who thinks it
# is a mistake will helpfully swap it.
#
# WARNING: TWO COUNTS, NEVER A SUM. Adding them would produce a number true of nothing —
# no list holds both kinds, so a combined total could not be rendered on either accordion
# without overstating it.
BADGE_TASK_AREA    = "task_area"
BADGE_HOLDING_AREA = "holding_area"

BADGES = frozenset( { BADGE_TASK_AREA, BADGE_HOLDING_AREA } )


def badge_for_move( move ):
    """
    Which badge counts a request for `move`.

    Requires:
        - move is one of REQUESTABLE_MOVES

    Ensures:
        - MOVE_DEMOTE -> BADGE_TASK_AREA; MOVE_ADMIT -> BADGE_HOLDING_AREA
        - RAISES rather than guessing for anything else — a move nobody has ruled a badge
          for must not be silently dropped from a count a human reads as complete
    """
    from cosa.rest.task_approval_settings import MOVE_ADMIT, MOVE_DEMOTE

    if move == MOVE_DEMOTE: return BADGE_TASK_AREA
    if move == MOVE_ADMIT:  return BADGE_HOLDING_AREA
    raise ValueError(
        f"no badge is ruled for move '{move}'. The two requestable moves are "
        f"'{MOVE_ADMIT}' and '{MOVE_DEMOTE}'; a third would need Rick to say which list "
        f"shows it, and counting it as zero would understate a badge he reads as complete."
    )


def badge_counts( requests ):
    """
    How many requests each badge shows — two independent counts, never a sum.

    🔴 ONLY PENDING REQUESTS ARE COUNTED, AND THIS IS THE ONE PLACE THE "DEFAULTS TO NO"
    CONFUSION WOULD SURFACE AS A NUMBER ON RICK'S SCREEN. A denied request is finished and
    the manager must re-file to ask again; counting it would keep an answered question
    pulsing at him forever. An approved one has already moved the row.

    Requires:
        - requests is an iterable of ( move, state ) pairs

    Ensures:
        - returns { BADGE_TASK_AREA: int, BADGE_HOLDING_AREA: int }, both keys ALWAYS
          present, so no caller has to tell "zero" from "absent"
        - counts only requests whose state is REQUEST_PENDING
        - every counted request lands in exactly ONE badge
        - never raises for a well-formed input
    """
    counts = { BADGE_TASK_AREA: 0, BADGE_HOLDING_AREA: 0 }
    for move, state in requests:
        if state != REQUEST_PENDING: continue
        counts[ badge_for_move( move ) ] += 1
    return counts
