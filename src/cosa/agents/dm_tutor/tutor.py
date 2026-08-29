#!/usr/bin/env python3
"""
The DM formatting tutor — renders a long DM into the shape we want agents to copy.

This is NOT the compressor wearing a new name. The compressor chased a ratio and
died at 3.0% against a 38% need; §2 of the phase-2 findings closed that entire
class, because naming a target moved 51,854 tokens by 73. This asks for a FORM:

    headline (the verdict) + two supporting sentences + a canned P.S.

A form is a selection task with a checkable answer. A ratio is an estimation task
the model cannot verify against itself. That is the whole difference.

🔑 LOSS IS THE DESIGN. The old arm demanded nothing be lost, which is what put
the freeze protocol and the rewrite in direct opposition — a model asked to carry
30 opaque placeholders AND shorten is being asked for two incompatible things.
Here detail is meant to go. The P.S. is the recovery path and the sender still
holds the original.

WHAT IS PROTECTED, and how it differs from the old design (plan §3.4). Literals
are checked IN PLACE across every class, not substituted:

    Every literal that appears in the output must be byte-exact to how it was
    sent. Literals may be ABSENT — that is what dropping a sentence means.
    None may be ALTERED.

⚠️ Named limitation, inherited and worse here: this catches omission and
mutation, never RELOCATION. A sha attached to the wrong claim passes every check
below. The old design at least confined placeholders to their clause; a
three-sentence rewrite restructures freely, so relocation risk goes UP.

TRANSPORT. The compressor's envelope fails on long inputs — 22 of 186 calls, and
15 of 50 in the 250+ band. Two mechanisms were measured: a dropped
`</compressed>` tag on 19 of them, and one runaway repetition to the token
ceiling. This module answers both structurally rather than by repair:

  * `max_tokens` is sized to the TASK. Three sentences cannot legitimately need
    hundreds of tokens, so a loop dies in a fraction of a second instead of
    running to 4,096. It does not stop the loop; it stops the loop being
    expensive, and a fast failure is one you notice.
  * There is NO response envelope at all — the reply IS the rewrite. Two
    wrappers were tried and both failed on ~45% of long messages, so the
    wrapper itself was the defect. A format you cannot fail to produce beats a
    repair for one you can.
"""

import re

import cosa.utils.util as du

from cosa.agents.dm_compression.freeze import count_all_literals
from cosa.agents.dm_tutor.sentences import count_sentences, prose_lines


CANNED_PS  = "P.S. Need more detail? Ask me *one* question only!"
MAX_TOKENS = 400                  # a headline and two sentences, with room to breathe
LIMIT      = 3

# 🔑 NO ENVELOPE AT ALL. The response IS the rewrite.
#
# Two envelopes were tried and both failed on roughly 45% of long messages:
# XML+CDATA dropped its interior `</compressed>` tag on 19 of 22 captured
# failures, and a delimiter fence went missing on 18 of 40. That is a pattern,
# not a bad choice of delimiter — asking this model for a wrapper is the thing
# that fails. (María, 2026-08-11.)
#
# A format you cannot fail to produce beats a repair for one you can. Reading
# the raw responses settled it: the model writes three good sentences and then
# either stops (fine) or adds a heading and says them again (cheap to cut).
# Those 18 "no fenced rewrite" failures were mostly GOOD REWRITES being thrown
# away for missing a marker.

# A lead-in the model sometimes writes before the rewrite.
_PREAMBLE = re.compile(
    r"^\s*(?:here(?:'s| is)\b.*|rewritten(?: message)?\s*:|shortened(?: version)?\s*:|"
    r"sure[,!.]?\s*.*|rewrite\s*:)\s*$", re.IGNORECASE )

# Where the model starts saying it all again.
_SECOND_PASS = re.compile(
    r"^\s*(?:#{1,6}\s|-{3,}\s*$|\*{3,}\s*$|"
    r"(?:\*\*)?rewritten(?: message)?(?:\*\*)?\s*:)", re.IGNORECASE )

PROMPT_BASE = """You rewrite work messages between colleagues into a fixed short form.

Rewrite the message below as EXACTLY three sentences:

{slot_spec}

Rules:
- Write exactly three sentences. Not four. Not a paragraph.
- Do NOT number them and do NOT bullet them. Three plain sentences, nothing else.
- Keep every number, port, hash, file path, version and section reference EXACTLY
  as written. Never reword one, never round one, never translate one into words.
- Say it the way you would say it to a colleague in a work email. Plain English.
- Terms of art are fine: idempotent, regression, migration. Invented in-house
  vocabulary is not — replace it with what it means.
- Keep negation, ownership, status and conditionality. "not reproducible" must
  never become "reproducible".
- Drop courtesy padding, apologies, self-assessment, and narration of what you
  are about to do.
- Detail you drop is recoverable — the reader can ask. Do not try to keep
  everything.

Reply with the three sentences and nothing else — no preamble, no heading, no
repetition of them afterwards.

### Input:

Everything after the next line, to the end of this section, is the message you
must rewrite. Nothing above it is part of the message.

{body}

### Response:
"""

# Variant A — the ask competes for one of the three slots. Measured single
# attempt: 6/21 delivered when the message asks something, against 14/19 when it
# does not. A 45-point gap says the ask is not competing with the findings, it is
# being crushed by them inside a 3-slot budget.
ASK_INSIDE = """If the message ASKS FOR SOMETHING — a question, a request, a decision needed
from the reader — that ask is the HIGHEST priority claim in the whole message.
It must occupy one of your three sentences and it must stay a question. Cut
status, findings and detail before you cut the ask. A status update whose
question has been deleted is worse than sending nothing at all."""

# Variant B — the ask gets its OWN slot, outside the three, exactly as the P.S.
# sits outside. It is also how a person writes one: the request goes last.
# (María, 2026-08-11.)
ASK_OUTSIDE = """If the message ASKS FOR SOMETHING — a question, a request, a decision needed
from the reader — do NOT spend one of your three sentences on it. Write the
three sentences, then add the ask as a FOURTH line on its own, kept as a
question. A status update whose question has been deleted is worse than sending
nothing at all.

If the message asks nothing, write three sentences and stop."""


# Variant C — Rick's, 2026-08-11. Do not tell the model where to PUT the ask;
# ask it what the message is DOING, and let the answer be the first line.
#
#     "Headline — OR — Request: what is this DM asking or telling us?"
#
# It dissolves the phrasing defect the other two variants share rather than
# working around it. A and B both say the ask must "stay a question", which the
# model satisfies by prefixing four words — "The question is: Are the markers
# present" — grammatically a question and unmistakably a form being filled.
# Here the ask IS the lead, so it gets asked the way a person asks it, and
# nothing has to be bolted onto a findings sentence.
#
# It also costs no extra slot: a message that asks something leads with the ask
# instead of spending a fourth line on it.
ASK_AS_LEAD = """First decide what this message is DOING: is it ASKING for something, or
TELLING you something?

- If it ASKS — a question, a request, a decision needed from the reader — then
  your FIRST sentence is that request, written the way one colleague asks
  another. Not "The question is whether X" — just ask it. The two sentences
  after it give only the context the reader needs to answer.
- If it TELLS — then your first sentence is the verdict, as above.

Never drop the request. A status update whose question has been deleted is
worse than sending nothing at all."""


# 🔴 THE SLOT SPEC IS WRITTEN ONCE. This is the defect Rick caught by asking to
# read the assembled prompt: variants A, B and C each appended their ask rule
# AFTER a block that had already claimed sentence one for the headline, so the
# prompt gave two instructions for the same slot. The model resolved it the way
# anyone would — it followed the first, wrote a headline, and the request had
# nowhere to go. C's 7-of-12 dropped asks measured that contradiction, not the
# idea, and the verdict was withdrawn.
#
# Here slot one is decided in CODE, from the detector we already run, and only
# one spec ever reaches the model. Nothing to reconcile.

SPEC_TELL = """- Sentence one is the HEADLINE: the verdict — what is true, decided, or found.
  Not a topic label. "The gate is wrong" is a verdict; "About the gate" is not.
- Sentence two carries the most important thing behind that verdict.
- Sentence three carries the next most important thing."""

# C′ — Rick's insight with María's correction: keep "the ask leads, asked the way
# a colleague asks it", drop the classify question that let the model rule the
# request away. The branch is taken in code, so the model is never asked whether
# this message is a request; it is told that it is one.
SPEC_ASK = """This message asks the reader for something. That request is the point of it.

- Sentence one IS the request, written the way one colleague asks another. Not
  "The question is whether X" and not "A decision is needed on X" — just ask it.
- Sentence two gives the context the reader needs to answer.
- Sentence three gives the next most important thing.

Never drop the request. A status update whose question has been deleted is worse
than sending nothing at all."""


# A′ and B′ — the same two placements as A and B, but written as ONE spec so
# nothing contradicts. Without these, C′'s 12 could be entirely the contradiction
# fix with placement contributing nothing, and we could not tell which.
# (María, 2026-08-11.)

# A′ — the ask sits INSIDE the three, second, after the verdict.
SPEC_ASK_INSIDE = """This message asks the reader for something, and that request must survive.

- Sentence one is the HEADLINE: the verdict — what is true, decided, or found.
- Sentence two IS the request, written the way one colleague asks another. Not
  "The question is whether X" — just ask it.
- Sentence three carries the most important remaining thing.

Never drop the request. A status update whose question has been deleted is worse
than sending nothing at all."""

# B′ — the ask sits OUTSIDE the three, on a fourth line of its own.
SPEC_ASK_OUTSIDE = """This message asks the reader for something, and that request must survive.

- Sentence one is the HEADLINE: the verdict — what is true, decided, or found.
- Sentence two carries the most important thing behind that verdict.
- Sentence three carries the next most important thing.
- Then a FOURTH line: the request itself, written the way one colleague asks
  another. Not "The question is whether X" — just ask it.

Never drop the request. A status update whose question has been deleted is worse
than sending nothing at all."""


# The model can echo the format example instead of rewriting. It passed the gate
# once — one sentence, shorter than the input, no altered literals — which is a
# false pass, the worst kind, because the pipeline reports success while
# delivering the instructions back to the recipient. Matched on the shape of the
# example rather than on one exact string, so a reworded example does not
# silently reopen the hole.
_ECHOED_TEMPLATE = re.compile(
    r"^\s*(?:<?your\s+(?:three\s+)?(?:sentences?|headline)|your three sentences here)",
    re.IGNORECASE
)


def _asks_something( text ):
    """
    Does this text ask the reader for anything?

    Requires:
        - text is a string

    Ensures:
        - returns True when prose carries a question mark, or an imperative
          request phrasing that commonly appears without one
        - ignores the canned P.S., which asks nothing of anyone in particular
        - ignores questions inside quoted or fenced material

    Raises:
        - nothing
    """
    prose = "\n".join( prose_lines( text ) )
    prose = prose.replace( CANNED_PS, " " )
    if "?" in prose: return True

    # Requests that routinely arrive without a question mark. Kept deliberately
    # short: a wide list turns every sentence containing "let me" into an ask,
    # and a gate that fires on everything is a gate nobody can satisfy.
    if re.search( r"\b(?:please\s+\w+|let me know|your call|say the word|"
                  r"give me the word|need your (?:word|ruling|approval)|"
                  r"waiting on (?:you|your))\b", prose, re.IGNORECASE ):
        return True

    # 🔴 IMPERATIVE REQUESTS. Added after variant C scored 0 of 21 and the zero
    # turned out to be this detector, not the variant: C's natural phrasing is
    # imperative — "either point to the path where daa2baa8 exists or confirm
    # that the dirty tree is the intended target" — which is unmistakably an ask
    # and carries no question mark. Rejecting those meant rejecting rewrites that
    # had done exactly what was asked of them.
    #
    # Anchored to the START of a sentence and to a short verb list on purpose.
    # A bare search for "confirm" matches "I confirmed it", which is a report,
    # and widening a predicate widens what it lets in.
    return bool( re.search(
        # A comma counts as a boundary too: "To unblock the review, either point
        # to the path or confirm the dirty tree is intended" is an ask, and a
        # sentence-start-only anchor missed exactly that shape. Safe because the
        # verb list is base-form imperatives — `confirm\b` does not match
        # "confirmed", so a past-tense report still reads as a report.
        r"(?:^|[.!?]\s+|,\s+)(?:either\s+)?"
        r"(?:confirm|tell me|send me|point (?:me )?to|decide|choose|pick|"
        r"approve|ack|advise|weigh in|sign off|ruling needed)\b",
        prose, re.IGNORECASE ) )


def build_prompt( body, ask_outside="lead2" ):
    """
    Build the tutor prompt for one message body.

    Requires:
        - body is a non-empty string

    Ensures:
        - returns a prompt carrying the body and both fence markers
        - no brace-formatting is applied to the body itself

    Raises:
        - ValueError if body is empty
    """
    if not body or not body.strip():
        raise ValueError( "body is empty — there is nothing to rewrite" )

    # .replace(), not .format(): DM bodies carry literal braces — dict literals,
    # f-strings, code fences — and str.format reads every one as a field. The
    # judge hit exactly this (judge.py:748).
    if ask_outside in ( "lead2", "inside2", "outside2" ):
        # One spec, chosen here rather than by the model. The three differ only
        # in WHERE the request goes, which is the comparison that means anything.
        if not _asks_something( body ):
            spec = SPEC_TELL
        else:
            spec = { "lead2"    : SPEC_ASK,
                     "inside2"  : SPEC_ASK_INSIDE,
                     "outside2" : SPEC_ASK_OUTSIDE }[ ask_outside ]
    else:
        rule = { "inside": ASK_INSIDE, "outside": ASK_OUTSIDE, "lead": ASK_AS_LEAD }[ ask_outside ] \
               if isinstance( ask_outside, str ) else ( ASK_OUTSIDE if ask_outside else ASK_INSIDE )
        spec = SPEC_TELL + "\n\n" + rule

    return PROMPT_BASE.replace( "{slot_spec}", spec ).replace( "{body}", body )


def extract( raw ):
    """
    Pull the rewrite out of a fenced response.

    Requires:
        - raw is the model's response string

    Ensures:
        - returns the text between the markers, stripped
        - returns None when either marker is missing
        - tolerates the model writing prose around the fence, which is why the
          markers exist rather than trusting it to write nothing else

    Raises:
        - nothing
    """
    if raw is None: return None

    text = raw.strip()
    if not text: return None

    # Drop a preamble line — "Here is the shortened version:" — when it is
    # clearly a lead-in and not the rewrite itself.
    lines = text.splitlines()
    if lines and _PREAMBLE.match( lines[ 0 ] ):
        lines = lines[ 1: ]

    # Cut at the point the model starts a SECOND pass: a markdown heading, a
    # "Rewritten message:" label, or a horizontal rule. Observed in live output —
    # the model writes three good sentences, then adds "## Rewritten Message:"
    # and says the whole thing again. Everything after the first such marker is
    # a repeat, not content.
    kept = []
    for line in lines:
        if _SECOND_PASS.match( line ): break
        kept.append( line )

    return "\n".join( kept ).strip() or None


def literal_violations( original, rewrite ):
    """
    Literals the rewrite ALTERED. Absence is legal; mutation is not.

    Requires:
        - original and rewrite are strings

    Ensures:
        - returns a list of ( literal, sent_count, got_count ) for literals that
          appear MORE often than sent, and ( literal, 0, n ) for ones never sent
        - a literal appearing FEWER times is not a violation — dropping a
          sentence takes its literals with it, and that is the design
        - a mutation still registers, because the changed value is a literal
          that was never sent

    Raises:
        - nothing
    """
    # 🔴 Compare PROSE, not the raw strings. The model likes to number its three
    # sentences "1. / 2. / 3.", and those markers are integers the original never
    # contained — so a perfectly good rewrite was rejected for "altering" the
    # literals 1, 2 and 3. Enumeration is structure under the same claim rule the
    # sentence counter uses; stripping it here keeps the two in agreement rather
    # than leaving a second, quieter definition of what counts as content.
    want = count_all_literals( "\n".join( prose_lines( original ) ), "" )
    got  = count_all_literals( "\n".join( prose_lines( rewrite  ) ), "" )

    violations = []
    for literal, n in got.items():
        sent = want.get( literal, 0 )
        if n > sent: violations.append( ( literal, sent, n ) )
    return violations


# Speech-act verbs — the ones that bind a NAME to a POSITION. Deliberately a
# closed list: it must fire on "María proposes" and stay silent on "María ran
# the suite", because only the first invents a stance she may not hold.
_SPEECH_ACTS = (
    "propose[sd]?|suggest(?:s|ed)?|recommend(?:s|ed)?|say[s]?|said|ask(?:s|ed)?|"
    "want[s]?|wanted|claim(?:s|ed)?|argue[sd]?|think[s]?|thought|believe[sd]?|"
    "state[sd]?|note[sd]?|report(?:s|ed)?|insist(?:s|ed)?|prefer(?:s|red)?"
)

# "<Name> <speech-act>" — a capitalised name (optionally accented or two words,
# e.g. "Mr Radio") immediately governing a speech-act verb.
_ATTRIBUTION = re.compile(
    rf"\b([A-ZÁÉÍÓÚÑÜ][\wÁÉÍÓÚÑÜáéíóúñü]+(?:\s+[A-Z][\w]+)?)\s+(?:{_SPEECH_ACTS})\b"
)


# Capitalised words that are NOT names. Without these, "The proposed fix is a
# second keystroke" reads as a person called "The" holding a position — a false
# accusation that would block a perfectly clean rewrite. A guard that fires on
# good text gets switched off, so the stop-list is part of the guard working.
_NOT_A_NAME = frozenset( {
    "the", "this", "that", "these", "those", "it", "he", "she", "they", "we",
    "i", "you", "a", "an", "his", "her", "their", "our", "my", "your", "its",
    "what", "who", "which", "some", "both", "neither", "either", "one", "no",
    "if", "when", "as", "and", "but", "so", "then", "there", "here", "nobody",
    "everyone", "anyone", "someone", "nothing", "everything", "all", "most",
} )


def attribution_bindings( text ):
    """
    Every "<Name> <speech-act verb>" pair a body asserts, lowercased.

    Ensures:
        - returns a set of names bound to a speech act in `text`
        - returns an empty set when the body attributes nothing
        - a capitalised non-name ("The proposed fix…") is never a binding
        - never raises
    """
    if not text: return set()
    found = set()
    for match in _ATTRIBUTION.finditer( text ):
        name = match.group( 1 ).strip().lower()
        if name in _NOT_A_NAME:              continue
        if name.split()[ 0 ] in _NOT_A_NAME: continue
        found.add( name )
    return found


def attribution_violations( original, rewrite ):
    """
    Names the rewrite put BEHIND A POSITION that the original never put there.

    WHY THIS EXISTS (Cheech, 2026-08-15, row 897a8db1). A DM whose body read
    "My proposal, which matches Rick's instinct: follow the /clear with a
    SECOND delayed send-keys" was condensed to "María proposes sending a second
    keystroke with a prompt to address this issue" and delivered to María. She
    opened her reply with "Check your source before building on it — I did not
    propose that," correctly rejecting a proposal she had never made and the
    sender had never attributed to her.

    Note what a presence check cannot catch here: "María" WAS in the original —
    as the addressee. The condenser did not invent a token, it invented a
    RELATIONSHIP, moving a name from who-is-being-written-to into who-holds-
    the-position. So `literal_violations` passes it cleanly; only the binding
    is new.

    Why it earns a gate rather than a note. `gate` already draws the line at
    "structurally checkable" and leaves meaning-reversal to the human reader.
    This sits on the checkable side: who is bound to a speech act is a surface
    property of the text, and the rule is narrow — a binding present in the
    rewrite and absent from the original. It stays silent on "María ran the
    suite", which reports an action rather than manufacturing a stance.

    Why it matters more than an ordinary summarisation slip: it manufactures
    provenance. A position laundered into a peer's name reads to that peer as
    something they must own or disown, and to everyone downstream as their
    settled view — so a condenser free to attribute can synthesise the
    appearance of peer agreement out of one session's suggestion.

    Requires:
        - original and rewrite are strings

    Ensures:
        - returns the sorted names bound to a speech act in the rewrite but not
          in the original
        - returns [] when the rewrite attributes nothing new
        - never raises
    """
    return sorted( attribution_bindings( rewrite ) - attribution_bindings( original ) )


def gate( original, rewrite, ask_outside="lead2" ):
    """
    The tutor's pass condition — form, never ratio.

    Requires:
        - original and rewrite are strings

    Ensures:
        - returns ( ok, reason ); reason is None only when ok is True
        - checks the rewrite BEFORE the P.S. is appended
        - applies no minimum-gain rule: a message that arrives at three
          sentences has done the job whatever its byte saving

    Raises:
        - nothing
    """
    if not rewrite or not rewrite.strip():
        return False, "empty rewrite"

    # In variant B the ask occupies a fourth line OUTSIDE the three, so the
    # budget is 3 + 1 and only for messages that actually ask something. A flat
    # limit of 3 would reject every correctly-formed variant-B rewrite.
    # Only variant "outside" spends a fourth line; "lead" puts the ask in slot one.
    extra = ( ask_outside is True or ask_outside in ( "outside", "outside2" ) )
    limit = LIMIT + 1 if ( extra and _asks_something( original ) ) else LIMIT
    sentences = count_sentences( rewrite )
    if sentences > limit:
        return False, f"{sentences} sentences, limit {limit}"

    if len( rewrite ) > len( original ):
        return False, f"longer than the original ({len(rewrite)} > {len(original)} chars)"

    altered = literal_violations( original, rewrite )
    if altered:
        shown = ", ".join( f"{lit!r} sent {s}x, got {g}x" for lit, s, g in altered[ :3 ] )
        return False, f"{len(altered)} literal(s) altered: {shown}"

    # 🔴 THE REWRITE MUST NOT INVENT WHO HOLDS A POSITION.
    #
    # Row 897a8db1: a body reading "My proposal, which matches Rick's instinct"
    # arrived at its recipient as "María proposes…". She correctly rejected a
    # proposal she had never made. `literal_violations` cannot see it — her name
    # WAS in the original, as the addressee — so the invented thing is the
    # binding, not the token. See attribution_violations.
    invented = attribution_violations( original, rewrite )
    if invented:
        return False, f"attributed a position to {', '.join( repr( n ) for n in invented[ :3 ] )} — not in the original"

    # A refusal or a comment about the message rather than a rewrite of it.
    if re.match( r"^\s*(?:I (?:cannot|can't|am unable)|Sorry|As an AI)", rewrite, re.IGNORECASE ):
        return False, "model refused rather than rewrote"

    # The model handing our own example back. Caught in a live run, where it
    # PASSED every other check and would have shipped the instructions to a
    # recipient as though they were the message.
    if _ECHOED_TEMPLATE.match( rewrite ):
        return False, "model echoed the format example instead of rewriting"

    # 🔴 THE ASK MUST SURVIVE.
    #
    # Measured on the first sample run: of 9 delivered rewrites whose original
    # asked something, ZERO still asked it — the tutor deleted the request every
    # time. One was a status DM ending "want me to submit it, or are you batching
    # the branch's e2e?" that came back as three sentences of file-size trivia
    # with the ask gone. (María, 2026-08-11.)
    #
    # A three-sentence budget spends itself on findings, and the P.S. cannot
    # rescue it: the recipient never learns a question was asked, so they cannot
    # know to ask back. A status update whose ask is deleted is worse than
    # sending nothing.
    #
    # Unlike meaning-reversal, this one IS structurally checkable, so it is a
    # gate rather than a note for the human reader.
    if _asks_something( original ) and not _asks_something( rewrite ):
        return False, "the original asked something and the rewrite does not"

    return True, None


def _attempt( body, client, ask_outside="lead2" ):
    """
    One model call: prompt, raw response, extracted rewrite.

    Requires:
        - body is a non-empty string
        - client exposes .run( prompt, **kwargs ) -> str

    Ensures:
        - returns ( rewrite|None, raw|None, error|None )
        - never raises; a failed call comes back as an error string

    Raises:
        - nothing
    """
    try:
        raw = client.run( build_prompt( body, ask_outside=ask_outside ),
                          max_tokens=MAX_TOKENS,
                          stop=[ "</s>", "</stop>" ] )
    except Exception as e:
        return None, None, f"model call failed: {type( e ).__name__}: {e}"

    if not raw or not raw.strip():
        return None, raw, "model returned nothing"

    # The stop sequence means the closing fence usually never arrives — the
    # server cuts generation at it. Put it back so extract() has both markers.
    rewrite = extract( raw )
    if rewrite is None:
        return None, raw, "no rewrite in response"
    return rewrite, raw, None


def rewrite_to_form( body, client=None, append_ps=True, retries=1, ask_outside="lead2" ):
    """
    Rewrite one DM into headline + two supporting sentences + P.S.

    Requires:
        - body is a string
        - client, when given, exposes .run( prompt, **kwargs ) -> str
        - retries is the number of EXTRA attempts after a gate rejection

    Ensures:
        - returns ( delivered, error, attempted )
        - `attempted` carries the model's rewrite EVEN WHEN THE GATE REJECTS IT,
          and is None only when no text was produced at all
        - exactly one of delivered / error is None
        - a body already at or under the limit returns error "under limit: n
          sentences" — the tutor does not touch a message that got it right, and
          such a message carries no P.S., so the P.S. stays an honest signal
        - the gate runs BEFORE the P.S. is appended
        - `max_tokens` is sized to the task, so a runaway model fails fast
        - never raises

    Raises:
        - nothing

    🔴 WHY THE THIRD RETURN VALUE EXISTS. This is the third time today a
    question could not be answered because the artefact was never kept: the
    200-run did not persist WHY rewrites were rejected, the first envelope probe
    read a response the exception had already truncated, and this gate returned
    a reason with no text attached. Phase 1 is Rick judging what rewrites LOOK
    like — a rejection that shows him nothing defeats the phase. For this phase
    the gate observes; it must not suppress. (María, 2026-08-11.)
    """
    if not body or not body.strip():
        return None, "empty body", None

    sentences = count_sentences( body )
    if sentences <= LIMIT:
        return None, f"under limit: {sentences} sentences", None

    if client is None:
        from cosa.agents.llm_client_factory import LlmClientFactory
        from cosa.agents.dm_compression.compressor import DmCompressionAgent
        # Borrow the compression agent's resolved model spec rather than
        # registering a second routing command before the form is approved.
        model  = DmCompressionAgent( frozen_text="placeholder body for spec resolution only" ).model_name
        client = LlmClientFactory().get_client( model, debug=False, verbose=False )

    attempted, last_error = None, None

    for attempt_number in range( retries + 1 ):
        rewrite, _raw, error = _attempt( body, client, ask_outside=ask_outside )
        if rewrite is None:
            last_error = error
            continue

        attempted = rewrite                    # keep it whatever the gate says
        ok, reason = gate( body, rewrite, ask_outside=ask_outside )
        if ok:
            delivered = rewrite.rstrip() + "\n\n" + CANNED_PS if append_ps else rewrite
            return delivered, None, attempted
        last_error = f"gate: {reason}"

    return None, last_error, attempted


def quick_smoke_test():
    """Exercise prompt, extraction and gate with a stub. No network, no GPU."""
    du.print_banner( "dm_tutor.tutor smoke test" )

    body = (
        "I spent the morning tracing the leak and I am fairly confident it sits at "
        "judge.py:572, which is the line that shipped in d256e25a last Tuesday. The "
        "consumer thread returns before the pool callback has run, so the job stays "
        "in the running queue even though the work behind it finished cleanly. Have "
        "a look at src/cosa/rest/queue.py when you get a moment and tell me whether "
        "you read it the same way I do. It is not reproducible on port 8000."
    )

    class _Good:
        def run( self, prompt, **kwargs ):
            return ( f"The leak is at judge.py:572, shipped in d256e25a.\n"
                     f"The consumer thread returns before the pool callback runs.\n"
                     f"It is not reproducible on port 8000." )

    class _TooLong( _Good ):
        def run( self, prompt, **kwargs ):
            return ( f"One. Two. Three. Four." )

    class _AltersLiteral( _Good ):
        def run( self, prompt, **kwargs ):
            return ( f"The leak is at judge.py:572.\n"
                     f"It is not reproducible on port 8001.\nShipped in d256e25a." )

    class _Refuses( _Good ):
        def run( self, prompt, **kwargs ):
            return f"I cannot rewrite this message."

    class _NoFence( _Good ):
        def run( self, prompt, **kwargs ): return "Here is a shorter version, I think."

    cases = [
        ( "good rewrite",     _Good,          True  ),
        ( "four sentences",   _TooLong,       False ),
        ( "altered a port",   _AltersLiteral, False ),
        ( "refusal",          _Refuses,       False ),
        ( "bare preamble",    _NoFence,       False ),
    ]

    failures = 0
    for label, stub, should_pass in cases:
        rewrite, error, attempted = rewrite_to_form( body, client=stub() )
        passed = rewrite is not None
        ok     = passed == should_pass
        if not ok: failures += 1
        print( f"  {'✓' if ok else '✗'} {label:<18} "
               f"{'delivered' if passed else 'REJECTED'}"
               f"{'' if error is None else '  — ' + error[ :62 ]}" )

    under, reason, _ = rewrite_to_form( "One. Two. Three.", client=_Good() )
    ok = under is None and "under limit" in ( reason or "" )
    if not ok: failures += 1
    print( f"  {'✓' if ok else '✗'} {'already short':<18} untouched — {reason}" )

    rewrite, _, _ = rewrite_to_form( body, client=_Good() )
    has_ps = CANNED_PS in ( rewrite or "" )
    still_ok = count_sentences( rewrite or "" ) <= LIMIT
    if not ( has_ps and still_ok ): failures += 1
    print( f"  {'✓' if has_ps and still_ok else '✗'} {'P.S. appended':<18} "
           f"present={has_ps}, counts {count_sentences( rewrite or '' )} sentences with it" )

    print()
    print( f"  {7 - failures}/7 passed" )
    return failures == 0


if __name__ == "__main__":
    quick_smoke_test()
