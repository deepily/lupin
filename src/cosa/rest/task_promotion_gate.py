"""
Gate for promoting a row out of the holding area: managers only, then the owner is asked.

The caller's credentials are checked first. If the caller is a manager, the method itself
asks the owner, on the caller's behalf, whether the row may leave the holding area.

The ask lives inside the method, so a promotion cannot happen without the owner being asked.
A worker is refused on credentials. A manager causes the owner to be asked. No path skips the
owner quietly, so the policy never depends on anyone remembering it.

This is a module, not inline code in the router. Inline, the only way to watch a refusal is to
stand up a database, mint a row in the holding area and drive a POST. Cheap tests would then
assert on the predicate and call that the control, and a correct predicate wired to nothing
would pass them all. Here every clause is observable directly, and the router test only has
to prove the call happens.
"""
from cosa.rest.task_approval_settings import _ini_value, approver_persona_for_account
from cosa.rest import task_approval_settings as approval
from cosa.rest import task_store_rules       as rules

import re
import uuid

from dataclasses import dataclass
from typing      import Optional

from lupin_cli.claude_code.hooks.lib.manager_figure import (
    is_manager_figure,
    classify_manager_figure_denial,
    DENIAL_NO_SESSION_ID,
    DENIAL_STALE_BRIDGE,
    DENIAL_DENIED,
)


# How the approval arrived. Rick's third requirement: a keypress and a timed-out
# default MUST NOT look identical on the row, or nobody can later tell which
# promotions he actually blessed.
APPROVAL_KEYPRESS = "keypress"
APPROVAL_DEFAULT  = "default"

# The approver was Rick himself, so no ask was fired. A THIRD source, not a flavour of
# the other two: those record how an answer arrived, this records that no question was
# asked. Rick's ruling, 2026-09-04, row 998c7529.
APPROVAL_SELF     = "self"

# 🔴 WHO SKIPS THE ASK — AND THIS LIST IS DELIBERATELY NOT ANY OF THE OTHER THREE.
#
# The ask exists so a MANAGER's promotion reaches Rick. When Rick is the caller it has
# already reached him: he is looking at the row, and `human_only=True` means nothing
# else could answer it anyway. Asking him would put a question in front of him about the
# click he just made.
#
# ⚠️ IT MUST NOT BE `UNCONDITIONAL_APPROVERS`, AND IT MUST NOT BE THE APPROVER
# ALLOWLIST, though today it happens to equal the first. Those answer "who may approve";
# this answers "who IS the human the ask would be sent to", and the two are different
# questions that agree only by coincidence. Reusing either would mean that the day
# somebody is added to an approver list — a NEW manager, a second unconditional
# approver — they silently stop being asked. That is María's named failure mode for this
# change, in her words: the skip must not extend to everyone.
#
# ⇒ Adding a name here is a decision that a promotion by that person needs no human
# blessing. Adding a name to an approver list is not. Keep them separate.
ASK_EXEMPT_PERSONAS = ( "rick", )

INI_KEY_ASK_TIMEOUT = "task approval promotion ask timeout seconds"
FALLBACK_ASK_TIMEOUT_SECONDS = 120


def get_ask_timeout_seconds():
    """
    How long the owner has to answer the promotion ask before it takes its default.

    Read at call time, so an operator's edit lands on the next promotion, not the next deploy.
    Same two-layer behaviour as every other `task approval *` key.

    Ensures:
        - returns the configured int, or the fallback when absent/unreadable
        - never raises
        - decides only how long the owner has to answer, never whether the owner is asked: the ask is
          unconditional for a manager, and setting this to 1 makes the owner effectively absent without
          turning the gate off (the gate's own switch is `task approval enforcement active`)
        - a promotion holds one threadpool worker for up to this long, because `transition_task` is a
          sync handler; that is affordable for a human gate on a rare action and would not be on a
          hot path, which is why the wait is bounded and configurable
    """
    return _ini_value( INI_KEY_ASK_TIMEOUT, int, FALLBACK_ASK_TIMEOUT_SECONDS )


# ── THE ASYNCHRONOUS OPT-IN (row 3493ae9b, design §5.5.1) ────────────────────────
#
# Rick's ruling of 2026-09-06, relayed by Mr. Radio: the promotion ask GOES
# ASYNCHRONOUS — but only behind a flag that is OFF by default, and only for a caller
# that explicitly asked. TWO gates, and the second is what makes this safe rather than
# merely cautious.
INI_KEY_ASYNCHRONOUS  = "task approval promotion ask asynchronous"
FALLBACK_ASYNCHRONOUS = False


def get_asynchronous_enabled():
    """
    Whether an operator has switched the asynchronous promotion path on at all.

    Read at call time, not at import, so an operator's edit lands on the next promotion.
    The fallback is False, the opposite of `get_enforcement_active`, which fails open so that an
    absent config never starts refusing promotions.

    Ensures:
        - returns a bool
        - returns False when the key is absent or unreadable
        - never raises
        - fails closed: an absent config must not start handing out 202 answers, because the
          synchronous answer is the one every existing caller can read
        - parses leniently ("true", "1", "yes", "on") because an operator typed the value; the request
          field is parsed strictly in `promotion_is_asynchronous`, since a client could otherwise opt
          in by accident with a coerced string
    """
    raw = _ini_value( INI_KEY_ASYNCHRONOUS, "string", None )
    if raw is None: return FALLBACK_ASYNCHRONOUS
    return str( raw ).strip().lower() in ( "true", "1", "yes", "on" )


def promotion_is_asynchronous( requested, enabled_fn=get_asynchronous_enabled ):
    """
    Whether this promotion returns a ticket instead of blocking on the owner.

    Both gates must hold: the operator flag is on, and the caller passed exactly True.
    The caller's gate is the one that matters for safety, as the last bullets explain.

    Requires:
        - requested is the caller's `asynchronous` field: True, False, or None when the
          caller said nothing (the overwhelmingly common case, and today's only one)
        - enabled_fn is the injectable operator-flag seam

    Ensures:
        - returns True exactly when the operator flag is on and the caller passed exactly True
        - a caller that said nothing gets today's synchronous behaviour
        - a non-bool that reached here anyway (the model should have refused it) is
          treated as not a request, the safe answer, never the new one
        - never raises
        - a 202 is a false green in every browser client: `response.ok` is true for any 2xx,
          `ApiClient.request` throws only on a failed response, and `TaskListStore.transitionTask`
          writes its optimistic approved state before the call and restores it only on failure
        - so the new status code goes only to a caller that asked for it; changing a status code
          breaks every present and future caller that reads 2xx as success, and opt-in removes that trap
        - the comparison is against True itself, not truthiness: on pydantic 2.13.3 a plain `bool`
          field accepts and coerces "true", "True", "1", 1 and "yes", while `StrictBool` rejects all
          five with a 422, so the guarantee sits at the server and covers every client layer
    """
    # `is not True` rather than `not requested`: None, False, "" and 0 must all mean the
    # same thing here, and so must the string "true" if the model's StrictBool were ever
    # relaxed. The one value that opts in is the boolean True.
    if requested is not True: return False
    return bool( enabled_fn() )


@dataclass( frozen=True )
class AskOutcome:
    """
    One yes/no answer plus how it arrived.

    `default_used` is a real boolean, unlike the `"[default used] "` string prefix the MCP
    `ask_yes_no` verb returns. That verb returns a string, so its flag can only live in the text.
    This gate calls `notify_user_sync` directly and gets `NotificationResponse.default_used`.
    So it keeps the flag as a flag instead of parsing a marker back out of a sentence.

    `answered_by` is who the server saw post the answer: the answer door's
    { user_id, account_email, method } stamp, carried through `notify_user_sync`.
    It is None when nobody posted one (a timed-out default) or when the server predates the stamp.
    """
    answer       : str
    default_used : bool
    answered_by  : Optional[ dict ] = None


@dataclass( frozen=True )
class PromotionApproval:
    allowed         : bool
    refusal         : Optional[ str ] = None
    approval_source : Optional[ str ] = None

    def authority_suffix( self ):
        """
        The fragment stamped onto a transition's `authority` to record how the answer came.

        Ensures:
            - returns "" when the promotion was not allowed (nothing was blessed)
            - otherwise names both Rick and the source, in words a reader can
              understand without knowing this module's constants
            - a self promotion has its own wording, never "keypress": a keypress means the owner answered
              a question, while here the owner was never asked because the owner was the caller
        """
        if not self.allowed: return ""
        if self.approval_source == APPROVAL_DEFAULT:
            return "rick-approved (timed-out default, not a keypress)"
        # 🔴 ITS OWN WORDING, NOT "keypress". A keypress means Rick answered a question;
        # this means he was never asked one, because he was the caller. Collapsing the
        # two would put "Rick answered yes" on a row he never saw a prompt for — the
        # same attribution defect this module already closed for unrecognised answers.
        if self.approval_source == APPROVAL_SELF:
            return "rick-approved (his own promotion, no ask fired)"
        return "rick-approved (keypress)"

    def reason_with_suffix( self, caller_reason ):
        """
        The transition `reason` that records both the operator's words and the approval note.

        One method instead of a line at each door, because two doors need the identical string.
        Those are the synchronous handler and the asynchronous resolver, which composes it minutes
        later in another call stack. Two places composing one value can drift, for example by a separator.

        Requires:
            - caller_reason is the operator's own `reason`, or None

        Ensures:
            - appended, never assigned over: a caller-supplied reason is the operator's own words,
              and dropping them to make room for ours would trade one attribution defect for another
            - returns the caller's reason unchanged when nothing was blessed, since
              `authority_suffix` is empty then and appending it would leave a dangling
              separator on a refusal
        """
        note = self.authority_suffix()
        if not note:              return caller_reason
        if not caller_reason:     return note
        return f"{caller_reason} · {note}"


# ── WHAT `manager_refusal` MAY BE ASKED ABOUT ──────────────────────────────────
#
# 🔴 THE CLOSE IS NOT AN APPROVER-ONLY MOVE, SO IT DOES NOT BELONG IN `MOVE_SENTENCES`.
# `requested_move` never returns it, and `test_the_approver_only_move_classifier.py`
# holds that table to exactly the moves the classifier can answer. But the router's
# CLOSE door (row adaf7698) asks `manager_refusal` the same question about this act, and
# since the request door (row c9fafb9d) that function names its move by KEY — so the close
# needs a key here, or every refused manager close would be a KeyError inside a 403.
#
# ⚠️ EXTENDED FROM THE SETTINGS TABLE, NOT COPIED. The approver-only sentences stay
# defined once; this adds the one act that is manager-only without being approver-only.
# The wording is the close door's, byte for byte.
MOVE_MANAGER_CLOSE = "manager_close"

# The filing door (row c9fafb9d, rule 3) asks the same question again: only a manager may
# REQUEST a promote or demote (Mr. Radio's D1, 2026-09-10).
MOVE_REQUEST_FILING = "request_filing"

# The un-park door (row 9dde52ef) asks the same question about a manager citing a card.
MOVE_MANAGER_UNPARK = "manager_unpark"

MANAGER_ONLY_SENTENCES = {
    **approval.MOVE_SENTENCES,
    MOVE_MANAGER_CLOSE  : f"closing a row on a '{rules.MANAGER_ATTESTATION_KEY}'",
    MOVE_REQUEST_FILING : "filing a promote or demote request",
    MOVE_MANAGER_UNPARK : f"un-parking a row on an '{rules.APPROVAL_CARD_KEY}' receipt",
}


def manager_refusal( session_id, actor, is_manager_fn=is_manager_figure,
                     classify_fn=classify_manager_figure_denial, account_persona=None,
                     move=approval.MOVE_ADMIT ):
    """
    The credential half: the refusal detail, or None if the caller is a manager.

    The check is "is a manager", which is enough for moving a task between lists but not foolproof.
    It reads the session bridge. A borrowed manager identity (a detached process resolving as
    another seat) passes it, because the borrowed bridge supplies the role with everything else.

    Requires:
        - session_id is the caller's session id (full or 8-char), or None
        - actor is the caller-declared "persona + session id" string
        - move is a key of `MANAGER_ONLY_SENTENCES` naming the manager-only act being
          judged, for the refusal text. The close door asks the same question about a
          different act, `MOVE_MANAGER_CLOSE`

    Ensures:
        - returns None iff the caller resolves as a manager-figure
        - otherwise a non-empty detail naming the actor and the credential, and
          distinguishing "resolved and not a manager" from "nothing resolved"
        - never raises
        - an unreadable bridge fails closed: it is refused, not waved through to the allowlist, because
          that is the moment the caller cannot be identified and a fallback would open the gate widest
          when least is known; the message names which failure it is and how to clear it
        - the three causes (no session id, stale bridge, resolved but not a manager) read differently,
          so a locked-out manager is not sent hunting the wrong problem; the stale-bridge message names
          the recovery, a re-spin or session restart that mints a fresh bridge
        - a caller with an `account_persona` passes first: it derives from a signature-validated token,
          the stronger credential, and a browser has no session bridge at all
        - the approver allowlist in `task_approval_settings` runs before this check and agrees with it
          only by coincidence (today it lists the managers plus the owner); a new manager missing from
          that list is refused before this check, so the two predicates agree until their inputs diverge
        - the refusal names the move being judged, so a demote refusal never describes a promotion
    """
    # 🔴 THE ACCOUNT DOOR (row 998c7529, Rick's shape (b), 2026-09-04). CHECKED FIRST
    # because it is the STRONGER credential, not merely another one: `account_persona`
    # is derived from an email on a signature-validated access token, while
    # `is_manager_fn` reads a session bridge whose identity a detached process was
    # measured borrowing on 2026-09-03 (row 54a43bcf).
    #
    # ⚠️ WHY THIS EXISTS AT ALL. A BROWSER HAS NO SESSION BRIDGE. Rick clicking Approve
    # on his own board resolved no session id, so this gate refused him with
    # "no session id reached the gate" even after the approver allowlist had let him
    # through — measured 2026-09-04, and it is the second half of the P0. He is not a
    # manager-figure in the bridge sense; he is the human the bridges belong to.
    if account_persona is not None: return None

    if is_manager_fn( session_id ): return None

    why = classify_fn( session_id ) if session_id else DENIAL_NO_SESSION_ID

    # 🔴 THE THREE CAUSES MUST NOT READ ALIKE (María's ruling, 2026-09-03, guard 1).
    # A locked-out manager who cannot tell a permissions problem from a broken
    # bridge goes hunting the wrong thing — and a mislabelled failure is the single
    # most expensive shape this fleet found on 2026-09-03. Each branch names its own
    # cause, and the unreadable-bridge branch also names the RECOVERY (guard 2),
    # because the message is where a locked-out manager will actually look.
    #
    # ⚠️ THE BULK CASE IS REAL, NOT THEORETICAL. On 2026-09-03 four of seven live
    # seats were serving stale modules at once. If bridges go unreadable in bulk,
    # EVERY manager loses promotion simultaneously — and a generic "not a manager"
    # would send all of them at the permissions system instead of at their seats.
    tail = {
        DENIAL_NO_SESSION_ID : "no session id reached the gate, so nothing could be resolved",
        DENIAL_STALE_BRIDGE  : ( "your session bridge could not be read — this is NOT a permissions "
                                 "problem. The bridge predates the manager-figure stamp; a re-spin "
                                 "(or any session restart) mints a fresh one and resolves it" ),
    }.get( why, "the caller resolved, and is not a manager" )

    return (
        # ⚠️ THE MOVE IS NAMED RATHER THAN ASSUMED (row c9fafb9d). This sentence used
        # to hard-code "promoting a row out of the holding area" and the same function
        # now guards a DEMOTE request too, so a demote refusal would have named the
        # opposite move — a caller sent to look at the wrong door. `MOVE_SENTENCES` is
        # the gate's own wording, so the refusal and the gate cannot say different
        # things about one transition. The close door passes `MOVE_MANAGER_CLOSE`.
        f"'{actor}' is not a manager — {MANAGER_ONLY_SENTENCES[ move ]} is "
        f"manager-only (credential: manager-figure; {tail})."
    )


# How much of a row's title the SPOKEN question carries (row 218f139c).
#
# The server rejects a spoken payload over ~500 characters and the ENTIRE ask fails —
# perceived silence plus a burned retry. The rest of the question is a fixed ~90
# characters, and `actor` is a persona plus a session id, so 160 leaves a wide margin
# even for a title at the store's own 120-char cap. It is a budget, not a fit.
SPOKEN_TITLE_BUDGET = 160


# 🔴 A HEX RUN IN A TITLE IS GIBBERISH WHEN SPOKEN, AND ROW TITLES ARE FULL OF THEM.
# María 🌸 found this reviewing the first cut of this fix and it is the same defect the
# fix was FOR, one layer over: I kept the row id out of the spoken line and then read a
# title that contains somebody else's sha out loud.
#
# MEASURED, not assumed: ~16 of a 120-row sample carry one — "shipped at a0f04df1",
# "Review c00b4b0e for bcf15f08", "the delta 27c160b3..8bfb1eac". That is ~1 in 8, and
# María's independent count agreed before I ran mine.
#
# 7 is the floor because `git log --oneline` abbreviates to 7; 40 is a full sha. The
# word boundaries matter — without them this would eat the tail of any long hex-ish
# word. It deliberately does NOT touch 8-hex-looking words with non-hex letters in them.
_HEX_TOKEN = re.compile( r"\b[0-9a-f]{7,40}\b" )

# What a redacted identifier is SAID as. A bare deletion would leave "Review  for  —
# respond() deleted", which is broken prose; a word keeps the sentence standing and
# tells the listener an identifier was there.
HEX_SPOKEN_AS = "a hash"

# 🔴 SPOKEN, NOT TYPOGRAPHIC. This used to be "…" and María caught that too: U+2026 may
# verbalize as NOTHING, so the listener hears a sentence simply stop and has no way to
# know they were given a fragment. A test asserting the ellipsis is present asserts a
# character the listener may never hear — the assertion passes and the human is misled,
# which is this row's own defect a third time.
TRUNCATION_SPOKEN_AS = ", title truncated"


def _spoken_title( title ):
    """
    A row's title, made safe to say aloud.

    Requires:
        - title is a string, or None

    Ensures:
        - returns a single-line string
        - every hex identifier is replaced by HEX_SPOKEN_AS, because a sha read aloud
          is character-by-character gibberish
        - a title longer than the budget is cut and the cut is announced in words, not
          with a glyph that may be silent
        - a missing or blank title yields a phrase that still reads as a sentence,
          never an empty gap the listener cannot place
        - never raises
    """
    text = ( title or "" ).strip()
    if not text: return "a row with no title"
    # Newlines would be spoken as nothing at all and silently join two clauses.
    text = " ".join( text.split() )
    # Redact BEFORE truncating: otherwise a title cut mid-sha leaves a hex fragment
    # that no longer matches the pattern and is spoken as gibberish anyway.
    text = _HEX_TOKEN.sub( HEX_SPOKEN_AS, text )
    text = " ".join( text.split() )
    if len( text ) <= SPOKEN_TITLE_BUDGET: return text
    return text[ :SPOKEN_TITLE_BUDGET ].rstrip() + TRUNCATION_SPOKEN_AS


# ── WHAT SILENCE MEANS, IN THE ONE SURFACE RICK ANSWERS FROM ───────────────────
#
# 🔴 THIS REPLACES "Defaults to YES if you are away.", WHICH WAS FALSE (row 73d41df0).
# `promotion_ask_kwargs` sets `response_default="no"` (it was "yes" until 2026-09-10), the
# notification layer returns that default with `default_used=True` on a timeout, and
# `approval_from_the_ask` then REFUSES.
# 675a1415 changed the outcome on Rick's 2026-09-07 order and moved neither the sentence
# nor the default beneath it.
#
# ⚠️ THE WORDS ARE JOHN'S, BYTE FOR BYTE, from 2333a752 on the unmerged branch
# `john-202-is-not-a-success`. That commit also carries the approver-only policy work and
# does not cherry-pick onto this line, so only the sentence was ported (row d2b1b59a,
# Finding 2) — identical text keeps a later merge of his branch a no-op here.
#
# ⚠️ IT IS A CONSTANT SO THE GUARD CAN PIN THE WORDS TO THE BEHAVIOUR:
# `test_the_card_and_the_gate_agree_about_silence.py` reads THIS name against the refusal
# the gate really returns for `default_used=True`.
#
# ⚠️ `response_default = "no"` SINCE RICK'S RULING OF 2026-09-10 ~16:33 EDT (row d2b1b59a,
# "Change to no"). It was "yes", inert for the outcome, but the multiplexer's read-only
# action card printed it as "Default: yes" beside a sentence saying silence is REFUSED.
# The value still does not decide the outcome — `default_used` does — it only makes the
# card's label say what the gate does.
UNANSWERED_MEANS = (
    "⚠️ If you do not answer, this is REFUSED. Silence is not approval — your ruling "
    "of 2026-09-07. Nothing retries it: it has to be asked again."
)

# ── ONE DOOR, TWO VERBS (Rick's ruling 2026-09-08, row c9fafb9d) ───────────────
#
# "it is me and me alone not managers that gets to promote and demote task items into
# the live list and out of it back into the task area me alone."
#
# 🔴 THE ASK HAS TO SAY WHICH DIRECTION IT IS ASKING ABOUT. Both verbs travel the same
# ticket, the same resolver and the same card; if the wording did not move with them, a
# demote request would reach him reading "wants to promote this row out of the holding
# area" — the exact opposite of what he would be approving. That is a false fact in the
# one surface where a false fact is a keypress.
#
# ⚠️ KEYED ON `task_approval_settings`' MOVE CONSTANTS, NOT ON A LOCAL PAIR OF STRINGS.
# That module decides what a move IS; this one only decides how to say it. A second
# vocabulary here is two pieces of code deciding one rule, which this file already
# warns about two functions down.
ASK_WORDING = {
    approval.MOVE_ADMIT  : ( "promote this row out of the holding area",
                             "Promotion out of the holding area" ),
    approval.MOVE_DEMOTE : ( "demote this row off the active list, back into the holding area",
                             "Demotion back into the holding area" ),
}


def promotion_ask_text( actor, task_id, title, move=approval.MOVE_ADMIT ):
    """
    The spoken question and the card abstract for a promotion or demotion ask.

    Pure, so the wording has one definition and every word of it can be pinned by a test.

    Ensures:
        - returns a (question, abstract) pair
        - the question names the row by its title, not only the asker: an ask that says who and
          nothing about what invites a rubber stamp, since the asker's identity proves nothing
        - the spoken question never carries the row id, because a hash is read out character by
          character as gibberish; the id, title and requester are in the abstract, where they can
          be read and clicked
        - the abstract ends with `UNANSWERED_MEANS`, a module constant rather than a literal, so a
          test can pin the words to the refusal the gate really returns on silence
        - the wording follows `move` through `ASK_WORDING`, so a demote ask never reads as a promotion
    """
    spoken, heading = ASK_WORDING[ move ]
    question = (
        f"{actor} wants to {spoken}: "
        f"{_spoken_title( title )}. Allow it?"
    )
    abstract = (
        f"**{heading}**\n\n"
        f"- row: `{task_id}`\n"
        f"- title: {title}\n"
        f"- requested by: {actor}\n\n"
        f"{UNANSWERED_MEANS}"
    )
    return question, abstract


SENDER_AGENT_TYPE = "claude.code"

# The suffix when the requester resolves NO session -- a browser actor resolves none, which
# is the documented case behind row 9d3a975e. It NAMES THE PATH rather than hiding it.
NO_SESSION_SUFFIX = "promotion-gate"


def promotion_ask_sender_id( session_id=None ):
    """
    The sender id a promotion ask is stamped with, so the source of an ask can be traced.

    Server-side `resolve_sender_id` tries the explicit sender, then a `[PREFIX]` pattern at the
    start of the message, then the literal `claude.code@unknown.deepily.ai`. The promotion ask
    supplies neither of the first two, so this path must fill the `sender_id` column itself.

    Requires:
        - session_id is a session identifier string, or None

    Ensures:
        - returns a fully-qualified sender_id naming the requesting session when there is one
        - returns a sender suffixed `promotion-gate` when there is not, which names the path
          rather than degrading to `unknown`
        - a blank or whitespace-only session_id is treated as absent, so a falsy-but-present
          value cannot produce a sender ending in a bare `#`
        - never raises
        - a stamp identical across all suspects names no source, which is the hole this closes; the
          cause is not an unregistered `/tmp` root (the root is not an input here), so widening
          project detection would not fix it
    """
    from cosa.agents.utils.sender_id import build_sender_id

    suffix = session_id.strip() if isinstance( session_id, str ) and session_id.strip() else NO_SESSION_SUFFIX
    return build_sender_id( SENDER_AGENT_TYPE, suffix=suffix )


def promotion_ask_kwargs( actor, task_id, title, session_id=None,
                          move=approval.MOVE_ADMIT ):
    """
    Every argument the promotion ask is fired with, kept pure so all of it can be pinned.

    Separate from the boundary because the boundary is `# pragma: no cover` (a live notification
    call). Anything left inside it is the part no test can see. Three values are behaviour:

      - `response_default="no"` does not decide the outcome: `approval_from_the_ask` refuses on
        `default_used` whatever this value is, and a defaulted "no" is refused as a timeout, never
        recorded as the owner's no. It only makes the card's "Default" label match the refusal
        (see `UNANSWERED_MEANS`).
      - `human_only=True` keeps the auto-answer proxy from answering for the owner, the same reason
        `self_respin` carries it. A gate answered by a robot is not the gate that was asked for.
      - `timeout_seconds` is how long "away" takes to mean away.
    """
    question, abstract = promotion_ask_text( actor, task_id, title, move=move )
    return {
        "question"         : question,
        "abstract"         : abstract,
        "response_default" : "no",
        "timeout_seconds"  : get_ask_timeout_seconds(),
        "priority"         : "high",
        "human_only"       : True,
        "sender_id"        : promotion_ask_sender_id( session_id ),
    }


# 🔴 THE FOUR STATUSES WHERE THE NOTIFICATION SYSTEM ANSWERED FOR THE HUMAN
# (row 96d2341c).
#
# ⚠️ IT IS NOT "A HUMAN WAS REACHED", WHICH IS WHAT THIS SET WAS FIRST CALLED, AND
# MARÍA WAS RIGHT TO REFUSE THE NAME. `offline` is in here and NOBODY WAS REACHED — the
# server looked Rick up, found him not connected, and said so. What the four have in
# common is that THE ASK GOT THROUGH AND THE SYSTEM ANSWERED AUTHORITATIVELY ABOUT HIM.
# The seven excluded ones share the opposite: the ask never got that far, so nothing
# knows anything about him.
#
# ⇒ The old name would have led the next reader to DELETE `offline` as obviously
# misplaced, which would have made Rick's absence a blocker — the exact rule this gate
# exists to honour. A set whose name mis-describes its own membership invites a correct
# reading and a wrong edit.
#
# ENUMERATED FROM THE CLIENT, NOT GUESSED — `notify_user_sync` returns eleven distinct
# statuses. Seven of them mean the ask never got in front of anybody: connection_error,
# request_timeout, request_exception, unexpected_exception, stream_error, unknown_event,
# error. These four are the ones where it did.
#
# ⚠️ AN ALLOWLIST, NOT A DENYLIST, AND THAT IS THE WHOLE SAFETY OF IT. A status added to
# the client later is UNKNOWN to this list and therefore refuses. A denylist would let it
# through and stamp Rick's name on it — the failure would arrive silently and on the side
# that matters.
#
# ⚠️ AND IT IS KEYED ON STATUS RATHER THAN ON exit_code, WHICH WAS THIS FIX'S OWN FIRST
# ANSWER AND WAS WRONG. `request_timeout` is a TRANSPORT timeout carrying exit_code 2, so
# an exit-code rule let it through and the row then read "rick-approved (timed-out
# default)" — describing a wait at Rick's end that never happened, for a card he never
# saw. Maria caught the wording. The set below is what makes the wording true rather than
# adding a third label to explain a case that should simply refuse.
#
# ⚠️ `offline` AND `expired` STAY IN, deliberately. Those are an ABSENT Rick, and his
# standing rule is that his absence must not become a blocker — they allow, stamped as a
# default rather than as his keypress.
THE_NOTIFICATION_SYSTEM_ANSWERED = frozenset( {
    "responded",            # a human answered
    "expired",              # the card sat in front of him and timed out, default supplied
    "expired_no_default",   # ditto, with no default to supply
    "offline",              # he was not there to receive it; the default stands
} )


def _default_ask( **kwargs ):
    """
    Fire the ask on the human surface and return an AskOutcome.

    Calls `notify_user_sync` directly rather than the MCP `ask_yes_no` verb, for two reasons.
    Importing `lupin_mcp.cosa_voice_mcp` into the web server would pull the MCP server, with its
    stdout-watcher daemon thread, into a process that has no business hosting it. And `ask_yes_no`
    returns a string whose default flag survives only as a `"[default used] "` prefix, which this
    gate would have to parse back out. The queues already use `notify_user_sync` server-side, so
    this is the established path.
    """
    from lupin_cli.notifications.notify_user_sync import notify_user_sync
    from lupin_cli.notifications.notification_models import (
        NotificationRequest, NotificationType, NotificationPriority, ResponseType
    )

    request = NotificationRequest(
        message           = kwargs[ "question" ],
        abstract          = kwargs[ "abstract" ],
        response_type     = ResponseType.YES_NO,
        notification_type = NotificationType.CUSTOM,
        priority          = NotificationPriority( kwargs[ "priority" ] ),
        timeout_seconds   = kwargs[ "timeout_seconds" ],
        response_default  = kwargs[ "response_default" ],
        human_only        = kwargs[ "human_only" ],
        # ⚠️ `.get`, NOT `kwargs[...]`, and this is not defensive fishing — it is a
        # measured regression. `_default_ask` is an injectable seam that other code calls
        # DIRECTLY with its own kwargs; the containment probe in
        # `test_a_test_cannot_ask_a_human.py` is one such caller. A hard subscript on a
        # newly-added key turned that probe's CONTAINED outcome into OTHER_ERROR — the
        # guard from row e625e608 caught my own regression here, one row later.
        # The fallback is the NAMED path sender, never None: a direct caller that omits it
        # still gets an attributable sender instead of the server's `unknown`.
        sender_id         = kwargs.get( "sender_id" ) or promotion_ask_sender_id( None ),
    )
    response = notify_user_sync( request=request )

    # 🔴 A FAILED ASK MUST NOT BECOME RICK'S KEYPRESS (Rio ⚡, 2026-09-04, row 96d2341c).
    #
    # MEASURED, with a plain `requests.exceptions.ConnectionError` and nothing else in
    # the path: this function returned answer="yes", default_used=False, and the gate
    # stamped `approval_source='keypress'` — Rick's own answer, recorded for a question
    # that never left the process.
    #
    # `notify_user_sync` RETURNS on every transport failure rather than raising
    # (notify_user_sync.py:457-490), with `response_value=None`. The `or` below then
    # substituted `response_default` — which was "yes" at the time — and `bool( None )`
    # left `default_used` False. So the gate's `try/except` belt around `ask_fn` could
    # never fire: nothing raised.
    #
    # ⇒ TWO SEPARATE WRONGS, CLOSED SEPARATELY BELOW:
    #   (a) an ERRORED ask is not an answer at all -> raise, so the gate's existing
    #       belt refuses and names it. exit_code 1 is this module's own "error"; 2 is
    #       timeout/expiry, an ABSENT Rick, which is not raised here: it comes back
    #       with `default_used` True and the gate REFUSES it as a timeout (his ruling
    #       of 2026-09-07, which replaced "his absence is not a blocker").
    #   (b) an answer this function MANUFACTURED is never a keypress -> whenever no
    #       value came back, `default_used` is True regardless of what the response said.
    #
    # ⚠️ (b) IS THE LOAD-BEARING HALF. Refusing on an error is the visible fix; the
    # attribution is the one the gate's own comment forbids — "the one thing this gate
    # must never do is put Rick's name on a decision he did not make".
    if response.status not in THE_NOTIFICATION_SYSTEM_ANSWERED:
        raise RuntimeError(
            f"the ask never reached the notification surface, so nothing is known "
            f"about whether Rick saw it: status={response.status!r}, "
            f"exit_code={response.exit_code}"
        )

    return AskOutcome(
        answer       = ( response.response_value or kwargs[ "response_default" ] ).strip().lower(),
        default_used = bool( response.default_used ) or response.response_value is None,
        answered_by  = response.answered_by,
    )


def promotion_precheck( session_id, actor, is_manager_fn=is_manager_figure,
                        account_persona=None, move=approval.MOVE_ADMIT ):
    """
    Everything the gate can decide without putting a question in front of the owner.

    It exists because two callers need this half and only one needs the other. The synchronous door
    runs both halves together. The asynchronous door runs this half inside the request.
    So a non-manager still gets an immediate 403, and only the slow ask goes to a worker.

    Requires:
        - session_id / actor identify the caller
        - is_manager_fn is the injectable credential seam

    Ensures:
        - returns a refusing PromotionApproval when the caller is not a manager
        - returns an allowing PromotionApproval stamped `self` when the caller is
          ask-exempt, since the caller is looking at the row and there is nobody to ask
        - returns None when, and only when, the ask must fire: no other outcome
          means that, so a caller can branch on None without re-reading the reasons
        - fires no ask of its own under any input
        - the split keeps one decision from being made in two places: a second copy of "is this
          caller a manager, and are they exempt?" would agree with this one until their inputs diverge
        - the asynchronous door must not mint a ticket for an ask-exempt caller, because a ticket
          promises an answer is coming and no ask fires; the resolver never re-runs this half, so the
          caller's account identity is not stored, and a stored authorization replayed later could be forged
    """
    refusal = manager_refusal( session_id, actor, is_manager_fn=is_manager_fn,
                               account_persona=account_persona, move=move )
    if refusal is not None:
        return PromotionApproval( allowed=False, refusal=refusal )

    # 🔴 RICK DOES NOT GET ASKED ABOUT HIS OWN PROMOTION (his ruling, 2026-09-04,
    # row 998c7529 shape (b)). The ask's whole purpose is to carry a MANAGER's
    # promotion to him for a decision. When he is the caller it has already reached
    # him — he is looking at the row — and `human_only=True` means no proxy could
    # answer it in his place. Firing it would ask him to bless the click he just made.
    #
    # ⚠️ KEYED ON THE PERSONA, NOT ON "HAS AN ACCOUNT", AND THAT IS THE WHOLE
    # CORRECTNESS OF IT. `account_persona` being set means only that the caller's
    # login mapped to SOME approver — a manager mapped to an account is still a
    # manager, and must still send the question. María named the failure mode:
    # the skip must not extend to everyone. `ASK_EXEMPT_PERSONAS` is the one list
    # that decides it, and it is separate from every approver list for that reason.
    #
    # 🔴 AND IT IS WHY THE ASYNCHRONOUS DOOR MUST NOT MINT A TICKET FOR HIM. A ticket
    # is a promise that an answer is coming from somewhere; there is no ask here, so
    # nothing would ever resolve it. The asynchronous handler branches on this
    # function's None for exactly that reason — see `task_promotion_resolver`, which
    # never re-runs the credential half and therefore never needs `account_persona`
    # persisted. A resolved authorization decision that gets stored and replayed later
    # is a forgeable one; not storing it is cheaper than guarding it.
    if account_persona in ASK_EXEMPT_PERSONAS:
        return PromotionApproval( allowed=True, approval_source=APPROVAL_SELF )

    return None


def answer_posted_by_the_operator( answered_by ):
    """
    Whether an ask's answer was posted by the operator's own login.

    The answer door records who posted an answer. This is the one place the promotion gate reads it.
    A yes counts as the operator's approval only when the server saw it arrive on a login whose
    account maps to an ask-exempt persona.

    Requires:
        - answered_by is the server-stamped dict from /api/notify/response, or None

    Ensures:
        - True iff method is "jwt" and the account maps to a persona in `ASK_EXEMPT_PERSONAS`
        - False for None, a non-dict, an API-key answer, an account with no mapping, and a
          mapped account whose persona is not ask-exempt
        - never raises
        - no name is written here: the account-to-persona map is `approver_persona_for_account` and
          the persona list is `ASK_EXEMPT_PERSONAS`, so who the operator is stays configuration
    """
    if not isinstance( answered_by, dict ):  return False
    if answered_by.get( "method" ) != "jwt": return False
    return approver_persona_for_account( answered_by.get( "account_email" ) ) in ASK_EXEMPT_PERSONAS


def describe_who_answered( answered_by ):
    """
    A plain-words name for whoever posted an answer, for a refusal a human will read.

    Requires:
        - answered_by is the server-stamped dict, or None

    Ensures:
        - names the service account for an "api_key" answer
        - names the login email for a "jwt" answer that carries one
        - says so when a login's token carried no email
        - says the server recorded nobody when there is nothing to read — an answer from
          before the door stamped it, or a client that dropped the field
        - never raises
    """
    if not isinstance( answered_by, dict ): return "nobody the server recorded"
    if answered_by.get( "method" ) == "api_key":
        return f"an API-key caller (user {answered_by.get( 'user_id' )})"
    email = answered_by.get( "account_email" )
    return f"the login {email}" if email else "a login whose token carried no email"


# ── THE UN-PARK CARD (Rick, 2026-10-07, row 9dde52ef) ──────────────────────────────
#
# A manager may un-park a row when the operator answered yes on a card THE SERVER made for that
# row and that move. A card a manager wrote by hand never counts: its text is free, so nothing
# in it can say which row the yes was about. The binding therefore lives in the card's `payload`,
# a column no public door can write on a question (the notify door has no such parameter).
# The receipt covers `parked -> queued` only.
UNPARK_ASK_KIND = "unpark_ask"
UNPARK_MOVE     = "parked->queued"


def unpark_ask_payload( task_id ):
    """
    The server-written binding a minted un-park card carries in its `payload`.

    Requires:
        - task_id is a row id (UUID or its string form)

    Ensures:
        - returns { kind, task_id, move } with task_id as a string
        - the only writer is the server's mint; `unpark_card_refusal` reads it back
    """
    return { "kind": UNPARK_ASK_KIND, "task_id": str( task_id ), "move": UNPARK_MOVE }


def approval_card_id( receipt_refs ):
    """
    The card id a transition cites, as a UUID, or None when the server cannot look it up.

    Requires:
        - receipt_refs is whatever the caller sent (any type)

    Ensures:
        - returns the UUID when receipt_refs is a dict whose `approval_card` is a well-formed UUID string
        - returns None for a non-dict, a missing key, a non-string and a malformed string
        - never raises
    """
    if not isinstance( receipt_refs, dict ): return None
    value = receipt_refs.get( rules.APPROVAL_CARD_KEY )
    if not isinstance( value, str ): return None
    try:
        return uuid.UUID( value )
    except ValueError:
        return None


def unpark_card_refusal( card, task_id, parked_since, used_card_ids ):
    """
    None when the card lets a manager un-park the row, else the refusal sentence.

    Requires:
        - card is the Notification row read by the id the caller cited, or None when no row has it
        - task_id is the row being un-parked; parked_since is the instant it was parked (aware)
        - used_card_ids is the collection of card ids already written onto a transition's receipts

    Ensures:
        - returns None only when every one of these holds: the card exists and asked a question; it was answered;
          the answer is a yes that a person gave, not the timed-out default; the server saw it
          arrive on the operator's own login; the payload names this row and this move, as the
          server wrote it; the card was made after the row was parked; its id was never used
        - the card's message and abstract are never read: they are text a manager could have typed
        - never raises for a card the table can store
    """
    if card is None:
        return "No card with that id exists, so the un-park is refused."
    if parked_since is None:
        return "The row has no recorded park time, so no card can be newer than it. The un-park is refused."
    if card.response_requested is not True:
        return "That notification asked no question, so it cannot approve an un-park."
    answer = card.response_value if isinstance( card.response_value, dict ) else { }
    if card.responded_at is None or card.state != "responded":
        return "That card has no answer yet, so the un-park is refused."
    if answer.get( "source" ) == "timeout_default":
        return "That card was settled by its timed-out default, not by an answer, so the un-park is refused."
    if str( answer.get( "value", "" ) ).strip().lower() != "yes":
        return "The answer on that card was not yes, so the un-park is refused."
    answered_by = answer.get( "answered_by" )
    if not answer_posted_by_the_operator( answered_by ):
        return ( f"That card was answered by {describe_who_answered( answered_by )}, not by the operator's own "
                 f"login, so the un-park is refused." )
    if card.payload != unpark_ask_payload( task_id ):
        return "That card was not made by the server for this row and this move, so the un-park is refused."
    if card.created_at is None or card.created_at <= parked_since:
        return "That card is older than the park, so it answered something else. The un-park is refused."
    if str( card.id ) in { str( used ) for used in used_card_ids }:
        return "That card has already been used for an un-park, and a yes covers one move, so it is refused."
    return None


def approval_from_the_ask( session_id, actor, task_id, title, ask_fn=_default_ask,
                           move=approval.MOVE_ADMIT ):
    """
    The ask half: ask the owner and read the answer, with credentials already settled.

    Both doors run `promotion_precheck` first: the synchronous one a line above, the asynchronous
    one inside the request before the 202 is sent.

    Requires:
        - the caller has already passed `promotion_precheck` and it returned None
        - ask_fn is the injectable ask seam (None is not accepted: a silently-absent
          ask is the one failure this gate exists to prevent)

    Ensures:
        - returns a PromotionApproval
        - an answer the server did not see arrive on the operator's own login refuses,
          and the refusal names who posted it
        - a real "no" refuses; an unrecognised answer refuses; only yes allows
        - approval_source is keypress on an allow; a timed-out default is refused rather than allowed
        - never raises: an ask that blows up is caught and becomes a refusal, and
          the refusal names the exception rather than swallowing it
        - never re-checks credentials: a second check would be a second derivation of the one in
          `promotion_precheck`, and the asynchronous caller cannot supply the same inputs (the account
          identity came off a signature-validated token inside the request and is not persisted onto
          the ticket), so a re-check would refuse callers the real check passed
        - the poster is judged before the content, so the gate never puts the owner's name on a
          decision the owner did not make; an unrecognised or empty answer is refused for the same reason
        - a "no" is a veto only when a human said it: the default is "no", so a timed-out ask arrives
          as "no" with `default_used` True, and reading the flag, not the word, sends it to the
          timed-out refusal
        - a timed-out ask refuses because being asked and not answering is not approving; its wording
          differs from the broken-ask refusal, so a broken notifier is told apart from an absent operator
        - a broken ask refuses rather than allows: not knowing whether the owner was asked is
          different from the owner not answering, and the gate must not open widest when it knows least
    """
    # 🔴 THE ASK IS WRAPPED BECAUSE IT REACHES A LIVE SERVICE, AND THIS DOCSTRING
    # USED TO PROMISE "never raises" WHILE RAISING. Found by Maya in adversarial
    # review at `47cff912`: `_default_ask` imported `lupin_cli.notifications.models`
    # and the module is `notification_models`, so calling this with its REAL default
    # raised ModuleNotFoundError straight through the door as a 500 — and Rick was
    # never asked. Three things hid it at once: the import sits INSIDE the function
    # so startup stayed clean, `_default_ask` carried `pragma: no cover` so the
    # coverage gate could not see it, and every test injected `ask_fn` so the default
    # never ran. The import is fixed and the pragma is gone; this is the belt.
    #
    # 🔨 IT REFUSES RATHER THAN ALLOWS, which is a decision and not an obvious one.
    # Rick's standing rule is that an ABSENT Rick must not become a blocker — that is
    # what the timed-out default is for, and it still allows. A BROKEN ask is a
    # different thing: not "Rick did not answer" but "we do not know whether he was
    # even asked". Maria's fail-closed ruling on an unreadable bridge governs here
    # for the reason she gave then — the gate must not open widest exactly when it
    # knows least.
    try:
        outcome = ask_fn( **promotion_ask_kwargs( actor, task_id, title, session_id,
                                                  move=move ) )
    except Exception as e:
        return PromotionApproval(
            allowed = False,
            refusal = (
                f"Could not ask Rick about promoting '{task_id}' out of the holding "
                f"area, so the promotion is refused rather than assumed: "
                f"{type( e ).__name__}: {e}. This is NOT a permissions problem and "
                f"NOT a no from Rick — the ask itself failed to reach him."
            ),
        )

    answer = ( outcome.answer or "" ).strip().lower()

    # 🔴 WHO ANSWERED COMES BEFORE WHAT THEY SAID (row e20e249a). A yes, a no and an
    # unrecognised answer are each somebody's decision, and the one thing this gate must
    # never do is put Rick's name on a decision he did not make. So an answer the server did
    # not see arrive on the operator's own login is refused here, before any branch below
    # can read it as his. A timed-out default is left to its own branch: nobody posted it,
    # and it already refuses.
    if not outcome.default_used and not answer_posted_by_the_operator( outcome.answered_by ):
        return PromotionApproval(
            allowed = False,
            refusal = (
                f"The answer to the promotion ask for '{task_id}' was posted by "
                f"{describe_who_answered( outcome.answered_by )}, not by the operator's own "
                f"login, so it is refused rather than recorded as Rick's decision. To "
                f"proceed, Rick answers the ask signed in as himself, or promotes the row "
                f"himself, which fires no ask at all."
            ),
        )

    # A "no" only counts as a veto when a HUMAN said it. Since 2026-09-10 the default IS
    # "no", so every timed-out ask arrives here as answer "no" with `default_used` True —
    # reading the flag rather than the word is what sends it to the timed-out refusal
    # below instead of recording "Rick answered no" for a question he never answered.
    if answer.startswith( "no" ) and not outcome.default_used:
        return PromotionApproval(
            allowed = False,
            refusal = f"Rick answered no to promoting '{task_id}' out of the holding area.",
        )

    # ⚠️ HARDENING, RAISED BY MAYA AND FLAGGED BY HER AS HARDENING RATHER THAN A
    # DEFECT — she did not establish that a YES_NO response can carry anything but
    # yes or no, and neither have I. The old code allowed EVERY answer not starting
    # with "no" AND stamped it "rick-approved (keypress)", so a malformed or empty
    # response would have been recorded on the row as Rick's own keypress. That is
    # the part worth closing: not the allowing, but the ATTRIBUTION. The one thing
    # this gate must never do is put Rick's name on a decision he did not make.
    if not outcome.default_used and not answer.startswith( "yes" ):
        return PromotionApproval(
            allowed = False,
            refusal = (
                f"The answer to the promotion ask for '{task_id}' was not recognised "
                f"as yes or no ({outcome.answer!r}), so it is refused rather than "
                f"recorded as Rick's approval."
            ),
        )

    # 🔨 A TIMED-OUT ASK NOW REFUSES. RICK'S ORDER, 2026-09-07 ~21:25 EDT (broadcast
    # c43a29c5, row 1ec67228): "it must default to NO. That way you can NEVER do it
    # without my approval."
    #
    # 🔴 THIS BRANCH USED TO ALLOW, AND THAT IS THE HOLE THE ORDER NAMES. A manager
    # promoted, Rick did not answer inside the ask window (120s by default), and the
    # row went onto the board stamped "rick-approved (timed-out default, not a
    # keypress)". The stamp was honest and the outcome was still work entering the live
    # queue WITHOUT HIS APPROVAL -- decided by a clock rather than by him. Being asked
    # and not answering is not approving.
    #
    # ⚠️ AND IT IS NOT THE SAME AS THE BROKEN-ASK REFUSAL ABOVE, WHICH IS WHY IT NEEDS
    # ITS OWN WORDS. That one means "we could not reach him and do not know what he
    # would have said". This one means "he was reached, the question stood, and the
    # window closed with no answer". Both refuse now, for different reasons, and a
    # reader who cannot tell them apart cannot tell a broken notifier from an absent
    # operator.
    #
    # ⚠️ THE COST IS REAL AND IS THE INTENDED ONE: a manager promoting while Rick is
    # away or asleep is refused and must ask again when he is back. The old default
    # bought throughput at the price of the one guarantee he asked for.
    if outcome.default_used:
        return PromotionApproval(
            allowed = False,
            refusal = (
                f"Promotion of '{task_id}' out of the holding area was REFUSED because "
                f"the ask to Rick timed out with no answer. Being asked and not "
                f"answering is not approving -- his ruling of 2026-09-07 is that a row "
                f"reaches the live queue only when his approval actually lands. This is "
                f"NOT a no from Rick and NOT a permissions problem: the question stood "
                f"and the window closed. Ask again when he is available, or have him "
                f"promote it himself, which fires no ask at all."
            ),
        )

    return PromotionApproval(
        allowed         = True,
        approval_source = APPROVAL_KEYPRESS,
    )


def approval_for_promotion( session_id, actor, task_id, title,
                            is_manager_fn=is_manager_figure, ask_fn=_default_ask,
                            account_persona=None, move=approval.MOVE_ADMIT ):
    """
    The gate's whole decision: credentials first, then the owner, in that order.

    The order follows the owner's own sentence: credentials are checked, and if they pass, the next
    step is asking. A caller who cannot promote never puts a question in front of the owner,
    otherwise every worker's mistaken click would cost an interruption.

    Requires:
        - session_id / actor identify the caller; task_id + title describe the row
        - is_manager_fn and ask_fn are the injectable seams (None is not accepted:
          a silently-absent ask is the one failure this gate exists to prevent)

    Ensures:
        - returns a PromotionApproval
        - a non-manager is refused and no ask is fired
        - a manager always causes the ask to fire: there is no branch that skips it
        - a real "no" refuses; an unrecognised answer refuses; only yes allows
        - approval_source is keypress on an allow; a timed-out default is refused rather than allowed
        - never raises: an ask that blows up is caught and becomes a refusal, and
          the refusal names the exception rather than swallowing it
        - holds no logic of its own: it composes `promotion_precheck` and `approval_from_the_ask`, and
          the asynchronous door runs the same two halves at different moments, so neither half may be
          copied into a door
    """
    settled = promotion_precheck( session_id, actor, is_manager_fn=is_manager_fn,
                                  account_persona=account_persona, move=move )
    if settled is not None:
        return settled

    return approval_from_the_ask( session_id, actor, task_id, title, ask_fn=ask_fn,
                                  move=move )
