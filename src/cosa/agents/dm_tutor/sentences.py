#!/usr/bin/env python3
"""
The sentence counter — the tutor's trigger, and the one thing it never asks a model.

Rick's instruction is the whole reason this module exists: *LLMs do not count
well.* So the decision "is this DM over three sentences" is made deterministically
here, in code, and the model is only ever asked to rewrite.

🔑 THE RULE, and every case follows FROM it rather than sitting beside it
(María, 2026-08-11):

    A sentence is a unit that CARRIES A CLAIM.
    Anything that asserts nothing is STRUCTURE — not counted, not rewritten.

That single rule settles the cases a hand-written list would have to enumerate
one at a time, and it settles the ones nobody has thought of yet:

    a table row          asserts nothing on its own          → structure
    a fenced code block  is quoted material, not a claim     → structure
    a heading            labels, it does not assert          → structure
    an attachment pointer is a reference to structure        → structure
    a bullet with prose  DOES assert                         → counts

The measured reason it matters: 42% of DMs over 250 words and 25% of the 150-250
band contain a list or a table. This is not a corner case, it is the target band.

WHAT IS NOT HANDLED, and deliberately: prose that carries two claims in one
sentence joined by a semicolon reads as one. Splitting on meaning needs a model,
and the point of this module is that no model is involved.
"""

import re


# Abbreviations that end in a period without ending a sentence. Masked before
# counting rather than pattern-matched around, because "e.g." next to a closing
# parenthesis defeats every lookahead written to date.
_ABBREVIATIONS = [
    "e.g.", "i.e.", "etc.", "vs.", "cf.", "approx.", "al.",
    "Dr.", "Mr.", "Mrs.", "Ms.", "Prof.", "St.", "Jr.", "Sr.",
    "Fig.", "No.", "p.", "pp.", "Sec.", "Ch.",
]

_MASK = " "                      # a space: same length, never a full stop

_FENCE      = re.compile( r"```.*?```", re.DOTALL )
_INLINE     = re.compile( r"`[^`\n]+`" )
_TABLE_ROW  = re.compile( r"^\s*\|.*\|\s*$" )
_TABLE_RULE = re.compile( r"^\s*\|?[\s:*-]*[-]{2,}[\s:|*-]*$" )
_HEADING    = re.compile( r"^\s*#{1,6}\s" )
_HRULE      = re.compile( r"^\s*([-*_]\s*){3,}$" )
_BULLET     = re.compile( r"^\s*(?:[-*+•]|\d+[.)])\s+" )
_QUOTE      = re.compile( r"^\s*>\s?" )

# A POINTER LINE — the line that says "it lives over there". Structure by the
# rule: it references where something is and asserts nothing about it.
#
# WIDENED 2026-08-13 to match the house style verbatim. María's wording is "the
# path is a pointer, not a fourth sentence, and does not count against the three",
# but this pattern only recognised /tmp/*.md — so a message written exactly to the
# rule counted FOUR, and the compliant house style sat on the trigger line with no
# headroom. That is the trap the canned P.S. below already sprang once: the trigger
# firing hardest on the messages that got it right.
#
# The narrowness is deliberate even after widening — a pointer line is a lead-in
# and ONE whitespace-free target, nothing else. "Fix it at src/foo.py and tell me
# what you think." keeps its slash AND its prose, so it still counts as the claim
# it is; only a line that is nothing but a pointer is discarded.
_URL_OR_PATH = (
    r"(?:[A-Za-z][A-Za-z0-9+.-]*://[^\s)]+"     # a URL — https:// , vllm:// , file://
    r"|~?/?(?:[\w.@%+-]+/)+[\w.@%+#?=&-]*"      # a path — at least one slash
    r"(?::\d+)?)"                               # optional :line suffix
)
# A short lead-in is still a pointer line: "see <path>", "→ <path>", "detail: <path>".
_POINTER_LEAD_IN = r"(?:(?:see|details?|detail|path|more|here|full\s+detail)\s*:?\s+|[→↳>]\s*)?"
# In MARKDOWN-LINK form the `[label](target)` wrapper is itself the proof that the
# line is a pointer, so the target only has to contain a slash — it does not have to
# survive the stricter path shape above. A doc-viewer link carries `?path=…&…`, which
# the bare-path pattern deliberately does not admit.
_ATTACHMENT = re.compile(
    rf"^\s*{_POINTER_LEAD_IN}"
    rf"(?:\[[^\]]*\]\(\s*[^\s)]*/[^\s)]*\s*\)|{_URL_OR_PATH})"
    rf"[.,;]?\s*$",
    re.IGNORECASE,
)

# 🔴 THE CANNED P.S. IS STRUCTURE, and this is the case that would have bitten
# hardest (María, 2026-08-11). It is a fixed invitation, not a claim about
# anything — but it punctuates as two sentences, so a clean 3-claim rewrite
# counts 6 the moment the tutor appends it.
#
# The damage is not to the tutor's own output, which can be gated before
# appending. It is that once agents MIRROR the format — which is the entire
# goal — every compliant message arrives carrying a P.S. and reads as over the
# limit. The trigger would fire hardest on exactly the messages that got it
# right, and the tutor would rewrite its own house style forever.
_CANNED_PS = re.compile( r"^\s*P\.?\s?S\.?\s+Need more detail\?.*$", re.IGNORECASE )

# 🔴 THE TUTOR'S OWN RECIPIENT NOTICE IS STRUCTURE — the same trap as the P.S. above,
# and it would have sprung the same way. The notice is appended to EVERY rewrite, so if
# it counted as a claim, a clean three-claim distillation would arrive reading as four
# and the tutor would rewrite its own output forever.
#
# It asserts nothing about the subject: it labels the message's provenance, which is
# exactly the "structure, not a claim" rule. Kept in sync with DM_TUTOR_NOTICE in
# dm.py by a test that fails if either side is edited alone.
_TUTOR_NOTICE = re.compile(
    r"^\s*[—-]\s*shortened by the DM tutor;.*$", re.IGNORECASE
)

# Decimals, versions, file:line, IP-ish runs, ellipses — periods that are not
# sentence ends. Masked wholesale rather than excluded case by case.
_NOT_A_FULL_STOP = re.compile(
    r"\b\d+(?:\.\d+)+\b"                    # 0.2.0 · 3.6 · 127.0.0.1
    r"|\bv\d+(?:\.\d+)*\b"                  # v0.1.7
    r"|\b\w+\.(?:py|md|ini|sh|json|ya?ml|txt|js|ts|html|css|sql|toml|cfg)\b(?::\d+)?"
    r"|\.\.\.|…"                            # ellipsis
)


def _mask( text ):
    """
    Replace every period that does not end a sentence with a placeholder byte.

    Requires:
        - text is a string

    Ensures:
        - returns text of the SAME LENGTH with non-terminal periods masked
        - abbreviations, decimals, versions, filenames and ellipses are masked

    Raises:
        - nothing
    """
    for abbreviation in _ABBREVIATIONS:
        text = text.replace( abbreviation, abbreviation.replace( ".", _MASK ) )

    def blank( match ): return match.group( 0 ).replace( ".", _MASK )
    return _NOT_A_FULL_STOP.sub( blank, text )


def prose_lines( text ):
    """
    Split a body into the lines that carry claims, discarding structure.

    Requires:
        - text is a string

    Ensures:
        - returns a list of prose lines, structure removed by the rule above
        - a bullet or quote marker is stripped but its prose is KEPT, because a
          bullet with prose asserts something
        - fenced and inline code are removed before any line is judged

    Raises:
        - nothing
    """
    text = _FENCE.sub( " ", text )
    text = _INLINE.sub( " ", text )

    kept = []
    for line in text.splitlines():
        if not line.strip():          continue
        if _TABLE_RULE.match( line ): continue
        if _TABLE_ROW.match( line ):  continue
        if _HEADING.match( line ):    continue
        if _HRULE.match( line ):      continue
        if _ATTACHMENT.match( line ):    continue
        if _CANNED_PS.match( line ):     continue
        if _TUTOR_NOTICE.match( line ):  continue

        line = _BULLET.sub( "", line )
        line = _QUOTE.sub( "", line )
        if line.strip(): kept.append( line.strip() )

    return kept


def count_sentences( text ):
    """
    Count the claim-carrying sentences in a DM body.

    Requires:
        - text is a string

    Ensures:
        - returns a non-negative integer
        - structure contributes nothing
        - a prose line with no terminal punctuation still counts as one, because
          it asserts something regardless of how it is punctuated
        - returns 0 for an empty body or one made entirely of structure

    Raises:
        - nothing
    """
    total = 0
    for line in prose_lines( text ):
        masked = _mask( line )
        ends   = len( re.findall( r"[.!?]+(?=\s|$)", masked ) )
        # A line of prose with no full stop is still one claim — a bullet
        # reading "Removed the emoji" asserts as much as one ending in a period.
        total += max( 1, ends )
    return total


def over_limit( text, limit=3 ):
    """
    The tutor's trigger.

    Requires:
        - text is a string
        - limit is a positive integer

    Ensures:
        - returns True only when the body carries MORE than `limit` claims

    Raises:
        - nothing
    """
    return count_sentences( text ) > limit


def quick_smoke_test():
    """Exercise the rule against the cases that motivated it. No model, no network."""
    import cosa.utils.util as du
    du.print_banner( "dm_tutor.sentences smoke test" )

    cases = [
        ( "One plain sentence.",                                            1 ),
        ( "One. Two. Three.",                                               3 ),
        ( "Headline\nSupporting one.\nSupporting two.",                     3 ),
        ( "No terminal punctuation at all",                                 1 ),
        ( "Deployed v0.2.0 to prod.",                                       1 ),
        ( "See judge.py:572 for the leak.",                                 1 ),
        ( "It took 3.6s, e.g. slower than Dr. Smith expected.",             1 ),
        # An ellipsis does NOT end a sentence here, and that is measured rather
        # than assumed: across the 2,951-body corpus it is followed by lowercase
        # 88 times and by a capital 6. It is overwhelmingly a trailing-off inside
        # a sentence in this traffic. My first expectation for this case was 2,
        # and the corpus says 1.
        ( "Wait... it passed!",                                             1 ),
        ( "Verdict here.\n\n| band | n |\n|---|---|\n| <80 | 36 |",         1 ),
        ( "Verdict here.\n\n```\ntraceback\nline two\n```",                 1 ),
        ( "## Heading\nA claim.",                                           1 ),
        ( "- Removed the emoji\n- Removed the padding",                     2 ),
        ( "The detail is attached.\n/tmp/maria-abc123.md",                  1 ),
        ( "",                                                              0 ),
        ( "| only | a | table |\n|---|---|---|",                            0 ),
        # The regression María caught: a compliant rewrite must not read as
        # over-limit once its own P.S. is attached, or the tutor rewrites the
        # house style it just taught.
        ( "Verdict.\nSupport one.\nSupport two.\n\n"
          "P.S. Need more detail? Ask me *one* question only!",              3 ),
    ]

    failures = 0
    for text, expected in cases:
        got = count_sentences( text )
        ok  = got == expected
        if not ok: failures += 1
        label = text.replace( "\n", "\\n" )[ :46 ]
        print( f"  {'✓' if ok else '✗'} {label:<48} expected {expected}, got {got}" )

    print()
    print( f"  {len(cases) - failures}/{len(cases)} passed" )
    return failures == 0


if __name__ == "__main__":
    quick_smoke_test()
