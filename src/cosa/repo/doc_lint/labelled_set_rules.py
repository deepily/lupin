"""
Selection rules of the labelled-set seeder (row 421963b6): plain-text predicates, no model, no file.

The first real dev set had about a third of its seeded pairs fail the second seat: the removed claim was still
stated elsewhere in the new text, or the cut left broken text. These predicates keep such candidates out of the plan.

Every rule here is a HEURISTIC over text. Each over-rejects (a candidate lost is a candidate not drawn; the plan
raises Shortfall when a floor cannot be met) and each has a stated blind spot:

    R2  restated_swap       a number or quantifier swap is skipped when the same value or word occurs again anywhere
                            in the docstring. Misses: a restatement in other words ("a pair" for "two").
    R3  qualifier_rejected  a qualifier deletion is skipped inside a code fence, backticks, double quotes or an
                            example block, and when another sentence sharing two content words with it carries an
                            exclusion cue or the same qualifier. Misses: an exclusion stated with no shared words.
    R4  delete_rejection    a delete is skipped when it touches the first sentence, leaves a lowercase sentence start,
                            leaves a sentence under four words, empties a heading or a field, or leaves a paragraph
                            opening on a pronoun. Misses: a pronoun inside a sentence whose antecedent was cut; a
                            list item emptied of meaning but not of words.
    R5  restated_elsewhere  a delete is skipped when another sentence holds 60% of the span's content words.
                            Misses: a restatement in synonyms; over-rejects a span built from common words.
    R7  words_of            a leading bullet or list marker is not a word.
    R8  markup_rejection    a delete or weaken span is skipped when it cuts into inline code, a code fence or a
                            [reference] link, a weaken when its changed word sits inside one, and a delete when it
                            removes the opening words of a list item (row 9d3f4562, after 5 of 16 Dart deletes came
                            out garbled). Misses: an indented code block with no fence; a fence written with tildes;
                            a backtick span or a link broken over two lines; an RST double-backtick span (``x``) is protected only
                            by the match of its inner single-backtick span, so a cut of one outer backtick is not seen.
                            Over-rejects: plain square brackets such as "[0]" are read as a link.
    R9  lead_in_rejection   a delete is skipped when it leaves a clause's lead-in hanging: HANGING_CONDITION (a sentence that opens on
                            a subordinator is left with its condition and no main clause), DROPPED_CONDITION (a clause opening on a
                            subordinator is cut out before ", and" or ", but"), JOINED_CONDITIONS (a comma and a second condition are
                            left running straight on from a first). Over-rejects and misses: see lead_in_rejection.

Rule 1 (the mechanical check after the writer) and the redraw path live in labelled_set_seeder.py.
"""

import math
import re

SENTENCE_RE = re.compile( r"(?<=[.!?])\s+" )
EDGE_PUNCT  = " \t\n.,;:!?"
PRONOUNS    = frozenset( "this it that these those they such its".split() )

BULLET_MARKERS = frozenset( "- * + • – — ·".split() )
LIST_MARKER_RE = re.compile( r"^\d+[.)]$" )

# Words that carry no claim of their own; what is left of a text once they go is its content.
FUNCTION_WORDS = frozenset( (
    "the and for with that this from are was were been being have has had not but all any can will would should could may might must shall"
    " its their there then than into onto over under about after before when where which while whose what who whom how why also only each every"
    " such these those they them you your our out off per via one two three four five six use used uses using returns return given" ).split() )

EXCLUSION_RE = re.compile( r"\b(?:never|not|no other|nothing else|except|other than|excluded?|excluding|without|nor|none)\b|n['’]t\b", re.IGNORECASE )

WORD_VALUES  = { "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6 }
NUMBER_TOKEN = re.compile( r"\b(?:\d+|" + "|".join( WORD_VALUES ) + r")\b", re.IGNORECASE )
RESTATED_SHARE = 0.6
MIN_SENTENCE_WORDS = 4

HEADING_RE = re.compile( r"^[ \t]*(?:#{1,6}[ \t]+\S.*|[A-Za-z][A-Za-z _/-]{0,40}:)[ \t]*$" )
FIELD_RE   = re.compile( r"^[ \t]*(?:[-*+][ \t]+)?([A-Za-z_][\w .-]{0,40}?)[ \t]*:[ \t]*(\S.*)?$" )

PROTECTED_RES = (
    re.compile( r"```.*?(?:```|\Z)", re.DOTALL ),
    re.compile( r"`[^`\n]+`" ),
    re.compile( r"\"[^\"\n]+\"|“[^”\n]+”" ),
    re.compile( r"(?im)^[ \t]*(?:examples?\b[^\n]*|>>>[^\n]*)(?:\n(?![ \t]*\n)[^\n]*)*" ),
)


# Rule 8: markup a cut must not land inside. A link is [text], [text](target) or [text][label]; Dart doc comments
# write a symbol reference as [Name].
CODE_RES     = ( re.compile( r"```.*?(?:```|\Z)", re.DOTALL ), re.compile( r"`[^`\n]+`" ) )
LINK_RE      = re.compile( r"\[[^\[\]\n]+\](?:\([^()\n]*\)|\[[^\[\]\n]*\])?" )
LIST_ITEM_RE = re.compile( r"(?m)^[ \t]*(?:[-*+•]|\d+[.)])[ \t]+(?=\S)" )

# Rule 9: words that open a condition, and the conjunctions that join two clauses.
SUBORDINATORS  = frozenset( "if when unless while although though because once until whenever whereas since after before where wherever whether provided".split() )
CONJUNCTION_RE = re.compile( r"\s*,\s*(?:and|or|but|nor|yet|so)\b", re.IGNORECASE )


def sentences_of( text ):
    """Split a text into sentences at terminal punctuation followed by whitespace."""
    return [ s for s in SENTENCE_RE.split( text.strip() ) if s ]


def sentence_spans( text ):
    """Return the ( start, end ) offsets of the sentences of text, skipping blank ones."""
    spans, start = [], 0
    for match in SENTENCE_RE.finditer( text ):
        spans.append( ( start, match.start() ) )
        start = match.end()
    spans.append( ( start, len( text ) ) )
    return [ ( a, b ) for a, b in spans if text[ a:b ].strip() ]


def words_of( text ):
    """
    Count words the way the spec does: split() on whitespace, with a leading bullet or list marker not counted (rule 7).

    Ensures:
        - "- keep the lock" counts 3; "1. keep the lock" counts 3; a lone "-" counts 0
    """
    tokens = text.split()
    if tokens and ( tokens[ 0 ] in BULLET_MARKERS or LIST_MARKER_RE.match( tokens[ 0 ] ) ): tokens = tokens[ 1: ]
    return len( tokens )


def content_words( text ):
    """Return the set of lowercase words of three letters or more that are not function words."""
    return { w for w in ( m.lower() for m in re.findall( r"[A-Za-z][A-Za-z'-]{2,}", text ) ) if w not in FUNCTION_WORDS }


def first_sentence_end( old ):
    """Return the offset where the first sentence of old ends (0 for a text with none): the summary line is never a delete candidate."""
    spans = sentence_spans( old )
    return spans[ 0 ][ 1 ] if spans else 0


def restated_elsewhere( old, span ):
    """
    Say whether a sentence outside the span's own sentence restates the span by content words (rule 5).

    Requires:
        - span is a ( start, end ) pair of offsets into old

    Ensures:
        - False when the span has no content words
        - True when another sentence holds at least RESTATED_SHARE of the span's content words, and at least one
    """
    own = content_words( old[ span[ 0 ]:span[ 1 ] ] )
    if not own: return False
    need = max( 1, math.ceil( RESTATED_SHARE * len( own ) ) )
    for a, b in sentence_spans( old ):
        if a <= span[ 0 ] < b or a < span[ 1 ] <= b: continue
        if len( own & content_words( old[ a:b ] ) ) >= need: return True
    return False


def protected_regions( old ):
    """Return the ( start, end ) regions of old that are code fences, backtick or double-quoted literals, or example blocks."""
    return [ ( m.start(), m.end() ) for pattern in PROTECTED_RES for m in pattern.finditer( old ) ]


def in_protected( old, start, end ):
    """Say whether [ start, end ) overlaps a protected region of old."""
    return any( a < end and start < b for a, b in protected_regions( old ) )


def number_value( token ):
    """Return the integer a number token states: digits or one of the number words one to six."""
    return int( token ) if token.isdigit() else WORD_VALUES[ token.lower() ]


def restated_swap( old, cls, token, start ):
    """
    Say whether a number or quantifier swap would leave the same claim standing elsewhere (rule 2).

    Requires:
        - token is the changed word as written at offset start in old

    Ensures:
        - number: True when another number token (digits or word) elsewhere in old states the same value
        - quantifier: True when the same word occurs again elsewhere in old
        - any other class: False
    """
    if cls == "number":
        want = number_value( token )
        return any( m.start() != start and number_value( m.group( 0 ) ) == want for m in NUMBER_TOKEN.finditer( old ) )
    if cls == "quantifier":
        return any( m.start() != start for m in re.finditer( r"\b" + re.escape( token.lower() ) + r"\b", old, flags=re.IGNORECASE ) )
    return False


def qualifier_rejected( old, start, end, token ):
    """
    Say whether a qualifier deletion is out of bounds (rule 3).

    Ensures:
        - True inside a code fence, backticks, double quotes or an example block
        - True when another sentence shares two content words with the qualifier's sentence and carries an
          exclusion cue or the same qualifier word
    """
    if in_protected( old, start, end ): return True
    holding = [ ( a, b ) for a, b in sentence_spans( old ) if a <= start < b ]
    own     = content_words( old[ holding[ 0 ][ 0 ]:holding[ 0 ][ 1 ] ] ) if holding else set()
    same    = re.compile( r"\b" + re.escape( token.lower() ) + r"\b", re.IGNORECASE )
    for a, b in sentence_spans( old ):
        if holding and ( a, b ) == holding[ 0 ]: continue
        sentence = old[ a:b ]
        if len( own & content_words( sentence ) ) >= 2 and ( EXCLUSION_RE.search( sentence ) or same.search( sentence ) ): return True
    return False


def sentence_start_before( old, index ):
    """Say whether a new sentence would begin at index: start of text, after . ! ?, or after a blank line."""
    j = index
    while j > 0 and old[ j - 1 ] in " \t\n": j -= 1
    if j == 0: return True
    return old[ j - 1 ] in ".!?" or "\n\n" in re.sub( r"[ \t]", "", old[ j:index ] )


def paragraphs_of( text ):
    """Split a text into paragraphs at blank lines."""
    return [ p for p in re.split( r"\n[ \t]*\n", text ) if p.strip() ]


def structure_emptied( old, cut ):
    """
    Return "EMPTY_FIELD" or "EMPTY_HEADING" when the cut left a field or heading that had content with none, else None.

    Ensures:
        - a field is a line "name: text" of old; it is emptied when cut holds the same "name:" with nothing after it
        - a heading is a line that is only a title with a colon, or a markdown #-title; it is emptied when old had
          non-blank lines under it (up to a blank line or the next heading) and cut has none
    """
    fields = { m.group( 1 ).strip().lower() for m in ( FIELD_RE.match( line ) for line in old.splitlines() ) if m and m.group( 2 ) }
    for line in cut.splitlines():
        m = FIELD_RE.match( line )
        if m and not m.group( 2 ) and m.group( 1 ).strip().lower() in fields: return "EMPTY_FIELD"

    def bodies( text ):
        lines, out = text.splitlines(), {}
        for i, line in enumerate( lines ):
            if not HEADING_RE.match( line ): continue
            n = 0
            for follow in lines[ i + 1: ]:
                if not follow.strip() or HEADING_RE.match( follow ): break
                n += 1
            out[ line.strip().lower() ] = n
        return out

    after = bodies( cut )
    for heading, n in bodies( old ).items():
        if n > 0 and after.get( heading ) == 0: return "EMPTY_HEADING"
    return None


def paragraph_orphan( old, cut ):
    """Say whether a paragraph of cut now opens on a pronoun, where old had no paragraph opening on that sentence."""
    firsts = { " ".join( sentences_of( p )[ 0 ].split() ) for p in paragraphs_of( old ) }
    for paragraph in paragraphs_of( cut ):
        first = " ".join( sentences_of( paragraph )[ 0 ].split() )
        if first.split()[ 0 ].strip( EDGE_PUNCT ).lower() in PRONOUNS and first not in firsts: return True
    return False


def delete_rejection( old, span, cut ):
    """
    Return the reason code a delete is refused for (rules 4 and 5), or None.

    Requires:
        - span is the ( start, end ) of the removed text in old; cut is old with it removed and the join repaired

    Ensures:
        - SUMMARY: the span starts inside the first sentence
        - RESTATED: another sentence restates the span by content words
        - PRONOUN: see paragraph_orphan
        - LOWERCASE: the text after the cut becomes a sentence start and begins lowercase
        - SHORT_SENTENCE: a sentence new to cut has fewer than MIN_SENTENCE_WORDS words
        - EMPTY_FIELD / EMPTY_HEADING: see structure_emptied
        - the checks run in that order and the first to fire is returned
    """
    if span[ 0 ] < first_sentence_end( old ): return "SUMMARY"
    if restated_elsewhere( old, span ): return "RESTATED"
    if paragraph_orphan( old, cut ): return "PRONOUN"
    after = old[ span[ 1 ]: ].lstrip( " \t\n,;:—" )
    if sentence_start_before( old, span[ 0 ] ) and after[ :1 ].isalpha() and after[ :1 ].islower(): return "LOWERCASE"
    old_sentences = { " ".join( s.split() ) for s in sentences_of( old ) }
    for sentence in sentences_of( cut ):
        if " ".join( sentence.split() ) not in old_sentences and words_of( sentence ) < MIN_SENTENCE_WORDS: return "SHORT_SENTENCE"
    return structure_emptied( old, cut )


def code_regions( old ):
    """Return the ( start, end ) regions of old that are code fences or backtick spans."""
    return [ ( m.start(), m.end() ) for pattern in CODE_RES for m in pattern.finditer( old ) ]


def link_regions( old ):
    """Return the ( start, end ) of each [reference] link in old, its target or label included."""
    return [ ( m.start(), m.end() ) for m in LINK_RE.finditer( old ) ]


def cuts_into( regions, start, end ):
    """Say whether [ start, end ) overlaps one of the regions without holding all of it."""
    return any( a < end and start < b and not ( start <= a and b <= end ) for a, b in regions )


def list_item_starts( old ):
    """Return the offsets where the text of each list item begins, just after its bullet or number."""
    return [ m.end() for m in LIST_ITEM_RE.finditer( old ) ]


def markup_rejection( old, span, token=None ):
    """
    Return the reason code a span is refused for because of markup (rule 8), or None.

    Requires:
        - span is the ( start, end ) of the span in old
        - token is None for a delete, or the ( start, end ) of the changed word for a weaken

    Ensures:
        - CODE: the span cuts into a code fence or a backtick span, or the changed word overlaps one
        - LINK: the span cuts into a [reference] link, or the changed word overlaps one
        - LIST_ITEM: a delete whose span holds the first character of a list item's text, so the item would be
          left as a bare marker or opening on a fragment; never returned for a weaken
        - a span that holds a whole code span or a whole link is not refused for it
        - the checks run in that order and the first to fire is returned
    """
    for code, regions in ( ( "CODE", code_regions( old ) ), ( "LINK", link_regions( old ) ) ):
        if cuts_into( regions, span[ 0 ], span[ 1 ] ): return code
        if token is not None and any( a < token[ 1 ] and token[ 0 ] < b for a, b in regions ): return code
    if token is None and any( span[ 0 ] <= at < span[ 1 ] for at in list_item_starts( old ) ): return "LIST_ITEM"
    return None


def lead_words( text ):
    """Return the lowercase words of text, a leading bullet or list marker not counted and edge punctuation, quotes and brackets stripped."""
    tokens = text.split()
    if tokens and ( tokens[ 0 ] in BULLET_MARKERS or LIST_MARKER_RE.match( tokens[ 0 ] ) ): tokens = tokens[ 1: ]
    return [ w.strip( EDGE_PUNCT + "()\"'`" ).lower() for w in tokens ]


def lead_in_codes( old, span ):
    """
    Return every rule 9 code that fires on a span, in the order the checks run.

    Requires:
        - span is the ( start, end ) of the removed text in old, inside one sentence, and holds at least one word

    Ensures:
        - a list of 0 or 1 codes today: no two checks can fire together (see lead_in_rejection)
    """
    a, b   = next( ( a, b ) for a, b in sentence_spans( old ) if a <= span[ 0 ] < b )
    before = old[ a:span[ 0 ] ].rstrip()
    after  = old[ span[ 1 ]:b ]
    codes  = []
    if lead_words( old[ a:b ] )[ 0 ] in SUBORDINATORS and before.endswith( "," ) and "," not in before[ :-1 ] and not after.strip( EDGE_PUNCT ): codes.append( "HANGING_CONDITION" )
    if lead_words( old[ span[ 0 ]:span[ 1 ] ] )[ 0 ] in SUBORDINATORS and CONJUNCTION_RE.match( after ): codes.append( "DROPPED_CONDITION" )
    if before.endswith( "," ) and lead_words( after )[ :1 ] and lead_words( after )[ 0 ] in SUBORDINATORS and SUBORDINATORS & set( lead_words( before ) ): codes.append( "JOINED_CONDITIONS" )
    return codes


def lead_in_rejection( old, span ):
    """
    Return the reason code a delete is refused for because it leaves a clause's lead-in hanging (rule 9), or None.

    Requires:
        - span is the ( start, end ) of the removed text in old, inside one sentence, and holds at least one word

    Ensures:
        - HANGING_CONDITION: the sentence opens on a subordinator (if, when, unless...), the text kept before the span ends on a comma
          with no other comma before it, and nothing but end punctuation follows the span, so the sentence is left as a condition
          with no main clause: "If the cache is empty, [the default is used]."
        - DROPPED_CONDITION: the span opens on a subordinator and the text after it opens on ", and", ", but", ", or", ", nor", ", yet"
          or ", so", so the kept clause is left unconditioned and the conjunction now joins it to another claim:
          "returns zero [when the list is empty], and a negative size would break the sort"
        - JOINED_CONDITIONS: the text kept before the span ends on a comma and already holds a subordinator, and the text after the
          span opens on one, so two conditions run together: "... when the form closed itself, [and with zero] when the user cancelled"
        - the checks run in that order and the first to fire is returned; no two can fire on one span, because their conditions on the
          text after the span exclude each other, so the order changes nothing today (lead_in_codes lists every code that fires, and a test
          holds it to one, so an edit that lets two fire shows up there)

    Over-rejects:
        - HANGING_CONDITION when the main clause has no comma of its own ("If empty the default is used, [and a warning is logged]")
        - DROPPED_CONDITION for every subordinate clause before a coordinator, though most leave a sentence that reads fine; measured on the
          Dart pool (4,375 entries) at ab3295c8f with 18 subordinators, 2026-10-05: it refuses 56 spans, and 502 kept delete candidates
          still open on a subordinator
        - JOINED_CONDITIONS for any comma followed by a subordinator after an earlier one, though some such sentences are well formed
        - a subordinator word used as a preposition, a participle or inside a name ("after", "before", "since", "once", "provided by")

    Misses:
        - a lead-in that is a phrase, not a subordinator: "For an empty cache, [the default is used]." or "Given a closed pool, [...]"
        - a main clause with a comma of its own before the span; a sentence whose condition opens after a semicolon or colon
        - a lead-in with a comma of its own, because any earlier comma reads as a main clause: "If a, b or c is missing, [the call fails]."
          and "If the cache is empty, and the pool is closed, [the call fails]." return None
        - a coordinator with no comma before it; a subordinator written in a quotation or in code
        - "as" and "even" (as in "even if") are left out of SUBORDINATORS on purpose: "as" is mostly a preposition, so a lead-in
          opened by either is not seen
        - a cut that leaves a lead-in two sentences back hanging, because only the span's own sentence is read
    """
    codes = lead_in_codes( old, span )
    return codes[ 0 ] if codes else None
