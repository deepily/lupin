"""
Promotion out of the holding area: manager-only, and Rick is asked from inside
the method.

Rick, by voice 2026-09-04 (spec: src/rnd/2026.09.04-gated-promotion-out-of-the-
holding-area.md):

    "the caller's credentials are checked to make sure they're actually a
     manager. And if they are, the next thing that happens is that the method
     you call asks, on your behalf, me, if you can take a task out of the
     holding area and promote it into the queue."

🔴 THE ASK LIVES INSIDE THE METHOD, AND THAT IS THE WHOLE DESIGN. Not "the
manager should ask Rick" but "the promotion cannot happen without Rick being
asked". A worker is refused on credentials; a manager causes Rick to be asked on
their behalf. There is no path that quietly skips him, so the policy stops
depending on anyone remembering it.

WHY A MODULE AND NOT INLINE IN THE ROUTER — the same reason `refusal_for_admission`
was pulled out of `tasks.py`. Inline, the only way to watch this refuse is to
stand up a database, mint a row in the holding area and drive a POST, so the
cheap tests would assert on the predicate instead and call THAT the control.
That is the fixture-that-cannot-discriminate shape: a correct predicate wired to
nothing passes every such test. Out here, every clause is observable directly and
the router test only has to prove the call happens.
"""
from cosa.rest.task_approval_settings import _ini_value

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
    How long Rick has to answer before the ask times out and takes its default.

    WHY A FUNCTION AND NOT A CONSTANT — María's ruling 2026-09-03. Read at CALL
    time, so an operator's edit lands on the next promotion rather than the next
    deploy. The same two-layer behaviour as every other `task approval *` key.

    ⚠️ THIS DIAL DOES NOT DECIDE WHETHER RICK IS ASKED, ONLY HOW LONG HE HAS.
    The ask is unconditional for a manager and there is no value here that skips
    it — turning it to 1 makes him effectively absent, it does not make the gate
    dark. The dial for the gate itself is `task approval enforcement active`.

    ⚠️ AND IT IS A THREADPOOL WORKER, NOT A FREE WAIT. `transition_task` is a sync
    handler, so FastAPI runs it in a threadpool and a promotion holds one worker
    for up to this long. That is affordable for a human gate on a rare action and
    would not be for a hot path — which is why it is bounded and configurable
    rather than left to the caller.

    Ensures:
        - returns the configured int, or the fallback when absent/unreadable
        - never raises
    """
    return _ini_value( INI_KEY_ASK_TIMEOUT, int, FALLBACK_ASK_TIMEOUT_SECONDS )


@dataclass( frozen=True )
class AskOutcome:
    """
    One yes/no answer plus HOW it arrived.

    `default_used` is a real boolean here rather than the `"[default used] "`
    string prefix the MCP `ask_yes_no` verb returns. That verb returns a STRING,
    so its flag has nowhere to live except inside the text; this gate talks to
    `notify_user_sync` directly and gets `NotificationResponse.default_used`, so
    it keeps the flag as a flag. Parsing a marker back out of a sentence would be
    re-deriving something we were handed.
    """
    answer       : str
    default_used : bool


@dataclass( frozen=True )
class PromotionApproval:
    allowed         : bool
    refusal         : Optional[ str ] = None
    approval_source : Optional[ str ] = None

    def authority_suffix( self ):
        """
        The fragment stamped onto the transition's `authority` so the row itself
        records which way the answer came.

        Ensures:
            - returns "" when the promotion was not allowed (nothing was blessed)
            - otherwise names BOTH Rick and the source, in words a reader can
              understand without knowing this module's constants
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


def manager_refusal( session_id, actor, is_manager_fn=is_manager_figure,
                     classify_fn=classify_manager_figure_denial, account_persona=None ):
    """
    The credential half: the refusal detail, or None if the caller is a manager.

    🔴 NOT FOOLPROOF, AND RICK CHOSE THAT DELIBERATELY. His words:

        "Just 'is a manager' is sufficient for right now. This is not like we're
         dealing with finances or editing genomes — we're simply promoting a task
         from one list to another. So document that just 'is a manager' is not
         quite foolproof. And then let's keep moving."

    ⚠️ WHY IT IS NOT FOOLPROOF, AT THE CHECK ITSELF SO THE NEXT READER MEETS A
    DELIBERATE DEFERRAL RATHER THAN ASSUMING NOBODY THOUGHT OF IT. A credential
    check is only as strong as the identity underneath it, and `is_manager_figure`
    reads the SESSION BRIDGE. On 2026-09-03 a detached process was measured
    silently resolving as another seat's identity — no error, no alert (row
    `54a43bcf`, made visible and refused at write time by `13014bd1`). A gate
    asking "are you a manager?" answers YES for a BORROWED manager identity,
    because the borrowed bridge supplies the role along with everything else.

    🔨 FAIL CLOSED ON AN UNREADABLE BRIDGE — María's ruling 2026-09-03, in her
    words: "this gate exists to stop an unauthorised promotion. An unreadable
    bridge is precisely the condition under which we cannot tell who is asking.
    Falling back to the allowlist there means the gate opens widest exactly when
    it knows least — which is the shape of every defect we found tonight."

    So an unreadable bridge is REFUSED, not waved through to the allowlist. The
    cost is paid in the message rather than the policy: the refusal says which
    failure it is and how to clear it.

    `13014bd1` already refuses a GUESSED identity at every identity-bearing write,
    so the hardening exists and wiring it here would be wiring, not new work.
    Rick has deferred it on a proportionality judgement.

    ⚠️ AND THE ALLOWLIST IN FRONT OF THIS CHECK AGREES WITH IT BY COINCIDENCE,
    NOT BY CONSTRUCTION. The approver allowlist (`task_approval_settings`) runs
    first and today reads ['cheech', 'maria', 'mr radio', 'rick'] — which happens
    to be the managers plus Rick. Nothing keeps the two in step: a NEW manager
    who is not added to that list is refused by the allowlist before this check
    is ever reached. Two predicates answering one question by different routes
    agree until the day their inputs diverge.

    Requires:
        - session_id is the caller's session id (full or 8-char), or None
        - actor is the caller-declared "persona + session id" string

    Ensures:
        - returns None iff the caller resolves as a manager-figure
        - otherwise a non-empty detail naming the ACTOR and the CREDENTIAL, and
          distinguishing "resolved and not a manager" from "nothing resolved"
        - never raises
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
        f"'{actor}' is not a manager — promoting a row out of the holding area is "
        f"manager-only (credential: manager-figure; {tail})."
    )


def promotion_ask_text( actor, task_id, title ):
    """
    The question Rick hears and the card he reads — pure, so the wording has
    exactly one definition and every word of it is pinnable.
    """
    question = f"{actor} wants to promote a row out of the holding area. Allow it?"
    abstract = (
        f"**Promotion out of the holding area**\n\n"
        f"- row: `{task_id}`\n"
        f"- title: {title}\n"
        f"- requested by: {actor}\n\n"
        f"Defaults to YES if you are away."
    )
    return question, abstract


SENDER_AGENT_TYPE = "claude.code"

# The suffix when the requester resolves NO session -- a browser actor resolves none, which
# is the documented case behind row 9d3a975e. It NAMES THE PATH rather than hiding it.
NO_SESSION_SUFFIX = "promotion-gate"


def promotion_ask_sender_id( session_id=None ):
    """
    Who the promotion ask says it is (row b48e231f).

    🔴 WHY THIS EXISTS. `NotificationRequest` carries a `sender_id` field and this ask never
    set it. Server-side `resolve_sender_id` then falls through -- explicit sender, then a
    `[PREFIX]` regex on the message, then the literal `claude.code@unknown.deepily.ai` -- and
    the promotion ask supplies neither of the first two. Measured 2026-09-04: EVERY promotion
    ask ever recorded, 29 of them across two days and several worktrees, carries `unknown`,
    while ordinary seats in the same table in the same minute stamp real senders. So the
    column discriminates; this path simply never filled it.

    ⚠️ THAT IS AN ATTRIBUTION HOLE, NOT A COSMETIC ONE. During the 2026-09-04 incident five
    tiers were live and the one field that would have named the source read `unknown` for
    every candidate at once. A stamp identical across all suspects is not a weak clue, it is
    no clue.

    ⚠️ AND IT WAS ORIGINALLY MIS-DIAGNOSED AS AN UNREGISTERED-`/tmp`-root defect. It is not:
    the root is not an input here, and an ask at 19:48:56 carried `unknown` an hour after the
    `/tmp` process died. Do not "fix" this by widening project detection.

    Requires:
        - session_id is a session identifier string, or None

    Ensures:
        - returns a fully-qualified sender_id naming the requesting SESSION when there is one
        - returns a sender suffixed `promotion-gate` when there is not, which names the path
          rather than degrading to `unknown`
        - a blank or whitespace-only session_id is treated as absent, so a falsy-but-present
          value cannot produce a sender ending in a bare `#`
        - never raises
    """
    from cosa.agents.utils.sender_id import build_sender_id

    suffix = session_id.strip() if isinstance( session_id, str ) and session_id.strip() else NO_SESSION_SUFFIX
    return build_sender_id( SENDER_AGENT_TYPE, suffix=suffix )


def promotion_ask_kwargs( actor, task_id, title, session_id=None ):
    """
    EVERY argument the ask is fired with — pure, so all of it is pinnable.

    ⚠️ WHY THIS IS SEPARATE FROM THE BOUNDARY BELOW. The boundary is
    `# pragma: no cover` because it is a live notification call; anything left
    inside it is BY CONSTRUCTION the part of this feature no test can see. Three
    of these values are behaviour, not decoration:

      · `response_default="yes"` — Rick's standing rule that an absent Rick must
        not become a blocker. He keeps the veto when present and loses nothing
        when away. Flipping this to "no" turns every promotion into a stall the
        moment he steps out.
      · `human_only=True` — LOAD-BEARING, the same reason self_respin carries it
        (row 804afce6). The auto-answer proxy must not answer for Rick; a gate he
        asked for, answered by a robot, is not the gate he asked for.
      · `timeout_seconds` — how long "away" takes to mean away.
    """
    question, abstract = promotion_ask_text( actor, task_id, title )
    return {
        "question"         : question,
        "abstract"         : abstract,
        "response_default" : "yes",
        "timeout_seconds"  : get_ask_timeout_seconds(),
        "priority"         : "high",
        "human_only"       : True,
        "sender_id"        : promotion_ask_sender_id( session_id ),
    }


def _default_ask( **kwargs ):
    """
    Fire the ask on the human surface and return an AskOutcome.

    Goes at `notify_user_sync` DIRECTLY rather than at the MCP `ask_yes_no` verb.
    Two reasons, both measured: importing `lupin_mcp.cosa_voice_mcp` into the web
    server pulls the MCP server — including its stdout-watcher daemon thread —
    into a process that has no business hosting it; and `ask_yes_no` returns a
    STRING whose default-flag survives only as a `"[default used] "` prefix,
    which this gate would then have to parse back out. The queues already use
    `notify_user_sync` server-side (todo_fifo_queue, running_fifo_queue), so this
    is the established path, not a new one.
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
    return AskOutcome(
        answer       = ( response.response_value or kwargs[ "response_default" ] ).strip().lower(),
        default_used = bool( response.default_used ),
    )


def approval_for_promotion( session_id, actor, task_id, title,
                            is_manager_fn=is_manager_figure, ask_fn=_default_ask,
                            account_persona=None ):
    """
    The gate's whole decision: credentials, then Rick, in that order.

    ORDER IS RICK'S SENTENCE ORDER AND IT IS NOT ARBITRARY — "credentials are
    checked... and if they are, the NEXT thing that happens is that the method
    asks me". A caller who cannot promote never puts a question in front of him;
    otherwise every worker's mistaken click costs him an interruption.

    Requires:
        - session_id / actor identify the caller; task_id + title describe the row
        - is_manager_fn and ask_fn are the injectable seams (None is not accepted —
          a silently-absent ask is the one failure this gate exists to prevent)

    Ensures:
        - returns a PromotionApproval
        - a non-manager is refused and NO ask is fired
        - a manager ALWAYS causes the ask to fire — there is no branch that skips it
        - a real "no" refuses; an UNRECOGNISED answer refuses; only yes allows
        - approval_source distinguishes a keypress from a timed-out default
        - never raises: an ask that BLOWS UP is caught and becomes a refusal, and
          the refusal names the exception rather than swallowing it
    """
    refusal = manager_refusal( session_id, actor, is_manager_fn=is_manager_fn,
                               account_persona=account_persona )
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
    if account_persona in ASK_EXEMPT_PERSONAS:
        return PromotionApproval( allowed=True, approval_source=APPROVAL_SELF )

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
        outcome = ask_fn( **promotion_ask_kwargs( actor, task_id, title, session_id ) )
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

    # A "no" only counts as a veto when a HUMAN said it. A default-"no" cannot
    # occur (the default is "yes"), but reading the flag rather than the word
    # keeps that true if the default is ever changed.
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

    return PromotionApproval(
        allowed         = True,
        approval_source = APPROVAL_DEFAULT if outcome.default_used else APPROVAL_KEYPRESS,
    )
