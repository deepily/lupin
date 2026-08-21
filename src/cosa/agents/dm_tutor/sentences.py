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
# The narrowness is deliberate even after widening — a WHOLE-LINE pointer is a lead-in
# and ONE whitespace-free target, nothing else. "Fix it at src/foo.py and tell me
# what you think." keeps its slash AND its prose, so it still counts as the claim
# it is; only a line that is nothing but a pointer is discarded.
#
# A POINTER TOKEN — the single reference this module recognises, in FOUR shapes.
# WIDENED 2026-08-13 (row a74f2176) from URLs + slashed paths to also cover the two
# shapes the fleet writes constantly and the old pattern could not see:
#   · a BARE filename with an extension and an optional :line — "job.py:1163",
#     "running_fifo_queue.py:422" — a path the house style writes without a slash;
#   · a BARE 8-hex row id — "e0bb5a94" — the task-store handle, which carries no slash
#     and no extension at all.
# The token is used TWO ways that must never disagree: as the body of the whole-line
# structure rule (_ATTACHMENT), so a line that is nothing but a pointer counts as
# structure; and as the thing the restore lifts out of the model's reach anywhere in
# the body (pointer_tokens). The 8-hex form requires at least one hex LETTER so a plain
# 8-digit number (a year, a count) is never mistaken for a row id.
_CODE_EXT = r"py|md|ini|sh|json|ya?ml|txt|js|jsx|ts|tsx|html|css|sql|toml|cfg|xml"
_BARE_ROW_ID_SRC = r"(?=[0-9a-f]*[a-f])[0-9a-f]{8}"   # >=1 hex letter, so "20260821" is a number
_POINTER_TOKEN_SRC = (
    r"(?:[A-Za-z][A-Za-z0-9+.-]*://[^\s)]+"         # a URL — https:// , vllm:// , file://
    r"|~?/?(?:[\w.@%+-]+/)+[\w.@%+#?=&-]*(?::\d+)?" # a slashed path, optional :line
    rf"|\b[\w-]+\.(?:{_CODE_EXT})\b(?::\d+)?"       # a bare filename.ext, optional :line
    rf"|\b{_BARE_ROW_ID_SRC}\b)"                    # a bare 8-hex row id
)
_POINTER_TOKEN = re.compile( _POINTER_TOKEN_SRC, re.IGNORECASE )

# The SAME row-id shape, ANCHORED, for callers holding a raw string rather than a token
# the pointer grammar already matched. Built from the one source above so the two can
# never drift apart. See is_bare_row_id for why the distinction is load-bearing.
_BARE_ROW_ID = re.compile( rf"^{_BARE_ROW_ID_SRC}$", re.IGNORECASE )

# Punctuation stripped off BOTH ENDS before the anchored test above. The anchors are
# what make that pattern safe against a raw string, and they are also what a single
# adjacent character defeats — "#fb9faba7" is not a match, so it sailed through the
# guard and arrived as a bare line (María, row 68601b65). "#hash8" is live fleet
# vocabulary, so of all the punctuated forms it is the likeliest to land in the slot.
#
# 🔴 HYPHEN AND UNDERSCORE ARE DELIBERATELY ABSENT. They are ordinary filename
# characters; stripping them would start reshaping real names on their way to the test.
# The set is punctuation that brackets or terminates a word, nothing that belongs
# INSIDE one.
_SLOT_PUNCTUATION = "#.,;:!?()[]{}<>\"'`*"

# 🔴 THE SLASHED-PATH SHAPE ABOVE ALSO MATCHES THINGS THAT ARE NOT PATHS. The
# repeated `[\w.@%+-]+/` group happily matches a slash-separated ENUMERATION
# ("SCHEDULED/PAUSED", "pending/running/terminal") or a bare RATIO ("10/10",
# "6/10"), and a single word with a trailing slash ("training/"). None of those
# is a pointer, but `pointer_tokens` would lift each one out and
# `_restore_dropped_pointers` would append it as its own line — so a clean
# three-line rewrite arrives with a garbage final line that reads as a message
# truncated mid-word. (María, 2026-08-15, row 206dd6ea: a DM pointer line
# delivered the bare fragment "training/"; two more delivered "SCHEDULED/PAUSED"
# and "pending/running/terminal".)
#
# A slashed token is a real pointer only when it carries a POSITIVE path signal:
# a URL scheme, an absolute or home root, a filename with a code extension, or a
# trailing-slash directory of at least two segments. Everything else with a
# slash is prose that happens to contain one.
_HAS_CODE_EXT = re.compile( rf"\.(?:{_CODE_EXT})\b(?::\d+)?$", re.IGNORECASE )


def _is_real_pointer( token ):
    """
    True when a matched token is a genuine path/URL/id, not a slash-enumeration.

    Requires:
        - token is a non-empty string produced by _POINTER_TOKEN

    Ensures:
        - True for URLs, absolute/home paths, filenames carrying a code
          extension, bare filenames and hex ids (which have no slash), and
          trailing-slash directories of two or more segments
        - False for slash-separated enumerations and numeric ratios, which carry
          no path signal ("SCHEDULED/PAUSED", "pending/running/terminal", "10/10")

    Raises:
        - nothing
    """
    if "://" in token:                    return True   # a URL
    if "/" not in token:                  return True   # a bare filename or hex id
    if token.startswith( ( "/", "~/" ) ): return True   # an absolute or home path
    if _HAS_CODE_EXT.search( token ):     return True   # ends in a real filename.ext
    if token.endswith( "/" ):                            # a directory reference…
        segments = [ segment for segment in token.rstrip( "/" ).split( "/" ) if segment ]
        return len( segments ) >= 2                      # …but only a real, multi-segment one
    return False

# A short lead-in is still a pointer line: "see <path>", "→ <path>", "detail: <path>".
_POINTER_LEAD_IN = r"(?:(?:see|details?|detail|path|more|here|full\s+detail)\s*:?\s+|[→↳>]\s*)?"
# In MARKDOWN-LINK form the `[label](target)` wrapper is itself the proof that the
# line is a pointer, so the target only has to contain a slash — it does not have to
# survive the stricter path shape above. A doc-viewer link carries `?path=…&…`, which
# the bare-path pattern deliberately does not admit.
_POINTER_OR_LINK = rf"(?:\[[^\]]*\]\(\s*[^\s)]*/[^\s)]*\s*\)|{_POINTER_TOKEN_SRC})"

# A RUN of pointers on one line is structure too (row a0151611, Rick's ruling
# 2026-08-21). The restore now puts every dropped path back on a SINGLE line, so that
# line can carry two or three of them. By this module's own rule that is still
# structure — a line of nothing but pointers asserts nothing, however many it holds —
# and if the rule did not say so, a repaired message would read as one claim over and
# the tutor could re-trigger on the very line it just added. The single-pointer case is
# byte-for-byte what it always was; only the run is new.
_ATTACHMENT = re.compile(
    rf"^\s*{_POINTER_LEAD_IN}{_POINTER_OR_LINK}"
    rf"(?:[,;]?\s+{_POINTER_OR_LINK})*"
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
    r"^\s*This DM was condensed in transit\..*$", re.IGNORECASE
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


def pointer_tokens( text ):
    """
    The pointer TOKENS in a body — paths, URLs, bare filenames and row ids, wherever
    they sit, whole-line OR mid-sentence.

    WHY THIS EXISTS (Cheech, 2026-08-13): the tutor PARAPHRASED A PATH out of a live
    DM, leaving the literal words "probe script path" where the path had been. The
    house rule is "three sentences and a path", so the one element the rule names by
    name is the element that did not survive the rewrite.

    WHY IT COUNTS TOKENS, NOT LINES (row a74f2176): the first fix scanned whole lines
    with the structure rule, so it only saw a pointer that OWNED its line. A path or an
    8-hex row id written mid-sentence — "(running_fifo_queue.py:422)", "recording to
    row e0bb5a94" — was invisible to it and got paraphrased away with the sentence
    around it. Measured on the served sha: 4 of 26 rewrites dropped a file path, 9
    dropped a row id. This scans TOKENS anywhere, so a pointer buried in prose is
    lifted out of the model's reach the same as one standing alone.

    The fix is the same one this whole module rests on — Rick's "LLMs do not count
    well", generalised: do not ASK a model to preserve something exactly when you can
    take it out of the model's reach and put it back yourself. A prompt instruction to
    keep paths verbatim is a request; this is a guarantee.

    Requires:
        - text is a string

    Ensures:
        - returns the pointer tokens, first-seen order, de-duplicated
        - returns [] when the body carries none
        - a restored token is re-appended as its own line, which _ATTACHMENT now
          recognises as a whole-line pointer, so repairing a message can never push its
          claim count back over the trigger

    Raises:
        - nothing
    """
    body  = _FENCE.sub( " ", text )
    found = []
    seen  = set()
    for token in _POINTER_TOKEN.findall( body ):
        if token in seen: continue
        seen.add( token )
        # Drop a slash-enumeration or ratio the regex mistook for a path, so the
        # restore step never appends a garbage pointer line. See _is_real_pointer.
        if not _is_real_pointer( token ): continue
        found.append( token )
    return found


def is_bare_identifier( token ):
    """
    True when a pointer token is a bare identifier — an id with nowhere to look.

    WHY THE DISTINCTION EXISTS (Rick, 2026-08-21, row a0151611): "What is obviously
    pointless and nonsensical is 10 to 12 lines of hashes. A standalone nonsensical
    out-of-context hash has no place there." A path, a URL and a bare filename each
    tell a reader WHERE TO LOOK, and survive the loss of the sentence around them. An
    8-hex row id does not: once the sentence that gave it meaning is rewritten away,
    the id is eight characters of nothing.

    The test is structural, not a second pattern to keep in sync: by construction of
    _POINTER_TOKEN, a token with neither a slash nor a dot can only be the bare 8-hex
    row-id shape — a URL carries "://", a slashed path carries "/", and a bare
    filename carries its extension's dot.

    Requires:
        - token is a non-empty string produced by _POINTER_TOKEN

    Ensures:
        - True for a bare 8-hex row id ("e0bb5a94")
        - False for URLs, slashed paths and bare filenames ("job.py:1163")

    Raises:
        - nothing
    """
    return "/" not in token and "." not in token


def is_bare_row_id( value ):
    """
    True when a RAW string is exactly an 8-hex row id. Safe on untrusted input.

    🔴 WHY THIS EXISTS AND `is_bare_identifier` COULD NOT BE USED (María, row 6dbba874).
    That function's precondition is "a token produced by _POINTER_TOKEN" — given one,
    "no slash and no dot" can only be the row-id shape. Handed a RAW value it degenerates
    into exactly that test and eats every extensionless real filename: Makefile, README,
    LICENSE, Dockerfile, src, io. Three of those are tracked files in this repo. A
    precondition is not a suggestion, and borrowing a filter across the line where its
    precondition holds is how a narrow guard silently becomes a wide one.

    So callers holding a raw string — the tutor's path SLOT, whose contents are whatever
    the model typed — use this, which asks the question directly instead.

    ⚠️ SURROUNDING PUNCTUATION IS STRIPPED FIRST, and that is a second lesson from the
    same family (María, row 68601b65). The anchors that make this predicate safe on raw
    input are defeated by one adjacent character: "#fb9faba7", "fb9faba7," and
    "fb9faba7." all sailed past the guard and arrived as bare lines. Whitespace was
    already stripped, so punctuation was simply the case `strip()` does not cover.

    The trade is named rather than hidden: a hidden file literally named ".deadbeef"
    would be suppressed. That is the guard's existing bargain — a file named "deadbeef"
    was already unreachable — and it buys the shape the fleet actually writes.

    Requires:
        - value is a string ( or None )

    Ensures:
        - True for exactly 8 hex characters carrying at least one letter a-f, with or
          without surrounding whitespace and bracketing punctuation
        - False for "Makefile", "README", "src", "20260821", "src/a.py", "notes.md",
          ".gitignore", "my-notes-file", "", and None
        - hyphen and underscore are NOT stripped — they belong inside real filenames

    Raises:
        - nothing
    """
    return bool( _BARE_ROW_ID.fullmatch(
        ( value or "" ).strip().strip( _SLOT_PUNCTUATION ).strip()
    ) )


def restorable_pointers( text ):
    """
    The pointer tokens worth putting BACK when a rewrite drops them — paths only.

    🔴 THIS IS A SEPARATE SELECTOR ON PURPOSE — DO NOT NARROW `pointer_tokens` TO GET
    THE SAME EFFECT. That function is used two ways that must not disagree (its own
    docstring says so): it is the body of the whole-line structure rule _ATTACHMENT,
    so a restored line counts as structure and repairing a message can never push it
    back over the trigger. Narrowing it would ALSO change the sentence counter, and a
    bare id line would start counting as a claim.

    So the structure rule keeps seeing all four pointer shapes, and only the RESTORE
    path is narrowed — which is the only place Rick's complaint lives.

    Requires:
        - text is a string

    Ensures:
        - returns pointer_tokens( text ) minus every bare identifier, same order
        - returns [] when the body carries none, or carries only bare identifiers

    Raises:
        - nothing
    """
    return [ token for token in pointer_tokens( text ) if not is_bare_identifier( token ) ]


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
