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

import re

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
    Whether an OPERATOR has switched the asynchronous promotion path on at all.

    Read at CALL time, not at import — the same two-layer behaviour as
    `get_ask_timeout_seconds` and for María's reason: an operator's edit lands on the
    next promotion rather than the next deploy.

    🔴 FALLBACK IS False, AND THAT IS THE OPPOSITE OF `get_enforcement_active`'S
    FAIL-OPEN. That one fails open because an absent config must not start REFUSING
    promotions. This one fails CLOSED because an absent config must not start handing
    out 202s: today's synchronous answer is the one every existing caller can read, and
    a broken config must land on the behaviour that is already understood.

    ⚠️ THE LENIENT PARSE HERE IS DELIBERATE AND IS NOT A CONTRADICTION OF THE STRICT
    PARSE ON THE WIRE FIELD — see `promotion_is_asynchronous`. An INI value was typed by
    an OPERATOR, so "yes" and "on" should mean what they obviously mean. A request field
    was sent by a CLIENT, where a coerced string is how an unintended opt-in gets in.
    Two trust contexts, two parsing rules, on purpose.

    Ensures:
        - returns a bool
        - returns False when the key is absent or unreadable
        - never raises
    """
    raw = _ini_value( INI_KEY_ASYNCHRONOUS, "string", None )
    if raw is None: return FALLBACK_ASYNCHRONOUS
    return str( raw ).strip().lower() in ( "true", "1", "yes", "on" )


def promotion_is_asynchronous( requested, enabled_fn=get_asynchronous_enabled ):
    """
    Whether THIS promotion returns a ticket instead of blocking on Rick.

    🔴 BOTH GATES MUST HOLD, AND THE CALLER'S IS THE ONE THAT MATTERS FOR SAFETY.
    Measured 2026-09-06 (Tiffany 💍, in review — the finding is hers): a 202 is a FALSE
    GREEN in every browser client. `fetch`'s `response.ok` is `status >= 200 && < 300`,
    so a 202 is `ok === true`; `ApiClient.request` only throws on `!ok`, and
    `TaskListStore.transitionTask` writes its optimistic "approved" row state BEFORE the
    call and restores only on failure. A 202 never fails, so the row would read APPROVED
    for a promotion Rick has not been asked about yet — a false FACT, not a false red,
    which is the species nobody investigates.

    ⇒ SO THE NEW STATUS CODE GOES ONLY TO A CALLER THAT ASKED FOR IT. A client that
    reads 2xx as success is CORRECT — that is the HTTP contract as nearly all code uses
    it — so changing an endpoint's status code is a breaking change to every caller
    present AND FUTURE. Repairing the three known call sites would leave the trap armed
    for the fourth one somebody writes next month. Opt-in removes it by construction.

    🔴 `requested` MUST ARRIVE AS A REAL BOOL, AND THE MODEL FIELD IS `StrictBool` FOR
    THAT REASON — this is the correction that makes the argument above actually hold.
    The first version of it reasoned that a browser could never opt in because `extras`
    is typed `Record<string, string>` and a boolean cannot go in one. TRUE ABOUT THE
    TYPE AND IRRELEVANT: the map carries the STRING "true" perfectly well. Measured on
    pydantic 2.13.3 — a plain `bool` field ACCEPTS "true", "True", "1", 1 and "yes" and
    coerces every one of them; `StrictBool` rejects all five with a 422.
    ⇒ A truthiness test here would re-open the door the type argument only appeared to
    close, which is why this compares against `True` itself rather than testing truthy.

    ⚠️ AND THE GUARANTEE HAD TO MOVE LAYERS, WHICH IS THE PART WORTH REMEMBERING. The
    first argument lived in the CLIENT'S type system — and `notifications.js` is vanilla
    JS with no type system at all, so that defence covered one of the two client layers
    and left the other bare. Validation at the SERVER covers both identically. A
    guarantee belongs where every caller must pass, never where only one kind of caller
    is checked.

    Requires:
        - requested is the caller's `asynchronous` field: True, False, or None when the
          caller said nothing (the overwhelmingly common case, and today's only one)
        - enabled_fn is the injectable operator-flag seam

    Ensures:
        - returns True IFF the operator flag is on AND the caller passed exactly True
        - a caller that said nothing gets today's synchronous behaviour
        - a non-bool that reached here anyway (the model should have refused it) is
          treated as NOT a request — the safe answer, never the new one
        - never raises
    """
    # `is not True` rather than `not requested`: None, False, "" and 0 must all mean the
    # same thing here, and so must the string "true" if the model's StrictBool were ever
    # relaxed. The one value that opts in is the boolean True.
    if requested is not True: return False
    return bool( enabled_fn() )


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

    def reason_with_suffix( self, caller_reason ):
        """
        The transition `reason` that records both the operator's words and Rick's.

        🔴 A METHOD RATHER THAN A LINE AT EACH DOOR, BECAUSE THERE ARE NOW TWO DOORS.
        The synchronous handler composed this inline; the asynchronous resolver needs
        the identical string minutes later in another call stack. Two places composing
        one value is the defect this row has spent its afternoon correcting, and a
        string that differs by a separator between the two paths would make an
        asynchronous promotion distinguishable from a synchronous one on the row —
        for no reason a reader could ever guess.

        Requires:
            - caller_reason is the operator's own `reason`, or None

        Ensures:
            - APPENDED, never assigned over. A caller-supplied reason is the operator's
              own words; dropping them to make room for ours would trade one attribution
              defect for another
            - returns the caller's reason unchanged when nothing was blessed, since
              `authority_suffix` is empty then and appending it would leave a dangling
              separator on a refusal
        """
        note = self.authority_suffix()
        if not note:              return caller_reason
        if not caller_reason:     return note
        return f"{caller_reason} · {note}"


def manager_refusal( session_id, actor, is_manager_fn=is_manager_figure,
                     classify_fn=classify_manager_figure_denial, account_persona=None,
                     move="promoting a row out of the holding area" ):
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
        - move names the manager-only act being judged, for the refusal text. The
          close door (row adaf7698) asks the same question about a different act

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
        f"'{actor}' is not a manager — {move} is "
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
    A row's title, made safe to SAY.

    Requires:
        - title is a string, or None

    Ensures:
        - returns a single-line string
        - every hex identifier is replaced by HEX_SPOKEN_AS, because a sha read aloud
          is character-by-character gibberish
        - a title longer than the budget is cut and the cut is ANNOUNCED IN WORDS, not
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


def promotion_ask_text( actor, task_id, title ):
    """
    The question Rick hears and the card he reads — pure, so the wording has
    exactly one definition and every word of it is pinnable.

    🔴 THE QUESTION NAMES THE ROW (row 218f139c, Rick raised it to P0). It used to
    read "{actor} wants to promote a row out of the holding area. Allow it?" — WHO
    and nothing about WHAT. Every promotion he approved before 2026-09-09 told him a
    persona name only, so the only thing he could weigh was the identity of the
    asker, which is the one thing this module's own gate says proves nothing. A gate
    that cannot say what it is gating is asking for a rubber stamp.

    ⚠️ THE ABSTRACT WAS ALREADY CORRECT and is unchanged — it has always carried the
    id, the title and the requester. The defect was ONLY in the spoken line, which is
    exactly the half Rick gets when he answers from across the room. Anyone reading
    the row's original wording ("no title, no id, no priority") should read it as a
    claim about the QUESTION, not about this function.

    🔴 THE ID STAYS OUT OF THE SPOKEN LINE, DELIBERATELY, AND THIS IS A DEPARTURE FROM
    THE ROW'S OWN ACCEPTANCE ("title and the short id, at minimum"). A hash verbalizes
    as character-by-character gibberish, and "I have no idea what that hash means" is
    Rick's own complaint — the thing this row exists to fix. Speaking an id would
    reproduce the defect one layer over while appearing to satisfy the acceptance.
    The id is in the abstract, where it can be read and clicked.
    """
    question = (
        f"{actor} wants to promote this row out of the holding area: "
        f"{_spoken_title( title )}. Allow it?"
    )
    abstract = (
        f"**Promotion out of the holding area**\n\n"
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

      · `response_default="no"` — INERT FOR THE OUTCOME since 675a1415:
        `approval_from_the_ask` REFUSES on `default_used` whatever this value is,
        and a defaulted "no" is refused as a timeout, never recorded as Rick's no.
        It was "yes" (Rick's earlier rule that his absence must not block) and
        reached the multiplexer's read-only card as "Default: yes"; Rick ruled it
        "no" on 2026-09-10 so the label matches the refusal (see UNANSWERED_MEANS).
      · `human_only=True` — LOAD-BEARING, the same reason self_respin carries it
        (row 804afce6). The auto-answer proxy must not answer for Rick; a gate he
        asked for, answered by a robot, is not the gate he asked for.
      · `timeout_seconds` — how long "away" takes to mean away.
    """
    question, abstract = promotion_ask_text( actor, task_id, title )
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
    )


def promotion_precheck( session_id, actor, is_manager_fn=is_manager_figure,
                        account_persona=None ):
    """
    Everything the gate can decide WITHOUT putting a question in front of Rick.

    🔴 IT EXISTS BECAUSE TWO CALLERS NEED THIS HALF AND ONLY ONE OF THEM NEEDS THE
    OTHER HALF (row `3493ae9b`, the asynchronous path). The synchronous door runs both
    halves in one breath. The asynchronous door must run THIS half inside the request —
    a non-manager still gets an immediate 403, which is Rick's own sentence order — and
    then hand the ASK to a worker, because the ask is the part that takes 120 seconds.

    ⚠️ SO THE SPLIT IS NOT A TIDY-UP, IT IS THE THING THAT KEEPS ONE DECISION FROM
    BEING MADE IN TWO PLACES. The alternative was for the asynchronous handler to
    re-implement "is this caller a manager, and is he exempt?" beside this module's
    copy. Two derivations of one value agree right up until their inputs diverge, and
    this file already carries that warning about the allowlist above it.

    Requires:
        - session_id / actor identify the caller
        - is_manager_fn is the injectable credential seam

    Ensures:
        - returns a REFUSING PromotionApproval when the caller is not a manager
        - returns an ALLOWING PromotionApproval stamped `self` when the caller is
          ask-exempt — he is looking at the row, so there is nobody to ask
        - returns None when, and only when, THE ASK MUST FIRE — no other outcome
          means that, so a caller can branch on None without re-reading the reasons
        - fires no ask of its own under any input
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


def approval_from_the_ask( session_id, actor, task_id, title, ask_fn=_default_ask ):
    """
    The ask half: put the question to Rick and read his answer, credentials ALREADY
    settled by `promotion_precheck`.

    🔴 THIS FUNCTION ASSUMES THE CALLER MAY PROMOTE AND DELIBERATELY DOES NOT CHECK.
    That is not an omission to be closed by a defensive re-check — a second credential
    check here would be a SECOND DERIVATION of the one in `promotion_precheck`, and
    worse, the asynchronous caller cannot supply the same inputs: the account identity
    that reached the precheck came off a signature-validated token inside the request
    and is deliberately NOT persisted onto the ticket. A re-check fed weaker inputs
    would refuse callers the real check passed, which is a defect wearing a belt.

    ⇒ Both doors run the precheck FIRST. The synchronous one does it one line above;
    the asynchronous one does it inside the request, before the 202 is sent.

    Requires:
        - the caller has already passed `promotion_precheck` and it returned None
        - ask_fn is the injectable ask seam (None is not accepted — a silently-absent
          ask is the one failure this gate exists to prevent)

    Ensures:
        - returns a PromotionApproval
        - a real "no" refuses; an UNRECOGNISED answer refuses; only yes allows
        - approval_source distinguishes a keypress from a timed-out default
        - never raises: an ask that BLOWS UP is caught and becomes a refusal, and
          the refusal names the exception rather than swallowing it
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
                            account_persona=None ):
    """
    The gate's whole decision: credentials, then Rick, in that order.

    ORDER IS RICK'S SENTENCE ORDER AND IT IS NOT ARBITRARY — "credentials are
    checked... and if they are, the NEXT thing that happens is that the method
    asks me". A caller who cannot promote never puts a question in front of him;
    otherwise every worker's mistaken click costs him an interruption.

    ⚠️ THIS IS NOW A COMPOSITION OF TWO NAMED HALVES AND HOLDS NO LOGIC OF ITS OWN,
    which is deliberate: the asynchronous door (row `3493ae9b`) runs the same two
    halves at two different MOMENTS, and the one thing that must not happen is each
    door growing its own copy of either half.

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
    settled = promotion_precheck( session_id, actor, is_manager_fn=is_manager_fn,
                                  account_persona=account_persona )
    if settled is not None:
        return settled

    return approval_from_the_ask( session_id, actor, task_id, title, ask_fn=ask_fn )
