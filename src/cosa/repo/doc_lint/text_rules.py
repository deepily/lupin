"""
Text rules shared by the Python, Dart and markdown linters (plan 1, section 4.1).

One rule module, several extractors: docstring_lint feeds it Python docstrings, dartdoc_lint
feeds it Dart doc blocks and md_lint feeds it markdown prose. Two rule implementations would
drift. Stdlib only, so it can be vendored into lupin-mobile's tool/ directory with
rule_lists and marker_counts.
"""

import re
from collections import namedtuple

from .marker_counts import INLINE_CODE, blank_code, caps_words, is_section_ref_resolved
from .rule_lists import (
    TIC_REGEX, EMPHASIS_GLYPHS, ID_REF_EXTENDED_REGEX, BARE_SHA_REGEX, RULING_REF_REGEX, AC_REF_REGEX,
    STEP_REF_REGEX, LABEL_REF_REGEX, SECTION_REGEX, DATED_BANNER_REGEX, ISO_DATE_REGEX, QUOTED_SPAN_REGEX,
    AGENT_IMPERATIVE_REGEX, SUMMARY_MAX_CHARS, SENTENCE_MAX_WORDS, PREFACE_MAX_LINES
)

Finding = namedtuple( "Finding", [ "path", "line", "rule", "message" ] )

CONTRACT_HEADER = re.compile( r"^\s*(?:Requires|Ensures|Raises|Args|Arguments|Returns|Yields)\s*:\s*$" )
BULLET_LINE     = re.compile( r"^\s*(?:[-*+]|\d+[.)])\s" )
FIELD_HEADER    = re.compile( r"^\s*(?:Attributes|Parameters|Params|Examples?)\s*:\s*$" )
SENTENCE_SPLIT  = re.compile( r"(?<=[.!?])\s+(?=[A-Z0-9`\"'(])" )


def line_of_offset( text, offset ):
    """
    Return the 0-based line index that holds a character offset.

    Requires:
        - 0 <= offset <= len( text )

    Ensures:
        - returns the number of newlines before offset

    Raises:
        - nothing
    """
    return text.count( "\n", 0, offset )


def summary_findings( text, path, first_line ):
    """
    Check rule 1: the summary, the first paragraph with its wrapped lines joined, is short.

    Requires:
        - text is a str holding one docstring or doc block
        - first_line is the 1-based file line of the first line of text

    Ensures:
        - returns one Finding when the first paragraph, joined with single spaces, is longer than
          SUMMARY_MAX_CHARS, else an empty list
        - a summary wrapped over several lines is judged as one sentence, not line by line
        - the finding sits on the first line of that paragraph
        - the blank line after the summary is left to ruff's D205, not checked here

    Raises:
        - nothing
    """
    lines = text.split( "\n" )
    start = next( ( i for i, raw in enumerate( lines ) if raw.strip() ), None )
    if start is None: return []
    end = start
    while end < len( lines ) and lines[ end ].strip(): end += 1
    joined = " ".join( raw.strip() for raw in lines[ start : end ] )
    if len( joined ) > SUMMARY_MAX_CHARS:
        return [ Finding( path, first_line + start, "summary-length", f"summary is {len( joined )} characters, limit {SUMMARY_MAX_CHARS}" ) ]
    return []


def preface_findings( text, path, first_line ):
    """
    Check the preface cap: prose before the first contract header stays short.

    Requires:
        - text is a str holding one docstring

    Ensures:
        - returns one Finding when more than PREFACE_MAX_LINES lines, blanks included, come before
          the first Requires, Ensures or Raises header
        - a docstring with no contract header is not checked here; the length cap covers it

    Raises:
        - nothing
    """
    lines = text.strip( "\n" ).split( "\n" )
    for i, raw in enumerate( lines ):
        if CONTRACT_HEADER.match( raw ):
            if i > PREFACE_MAX_LINES:
                return [ Finding( path, first_line, "preface-length", f"{i} lines before the contract, limit {PREFACE_MAX_LINES}" ) ]
            return []
    return []


def prose_lines( text, markdown=False ):
    """
    Yield ( index, line, starts_paragraph ) for the prose lines of a docstring or page.

    Requires:
        - text is a str
        - markdown is True for a markdown page, False for a docstring

    Ensures:
        - docstring mode skips lines inside a contract section and bullet lines
        - a field section (Attributes, Parameters, Params, Example) covers only the lines indented
          deeper than its header, so prose after it is read again
        - markdown mode keeps bullet text, with the bullet marker removed, and skips headings
          and table rows
        - blank lines are skipped in both modes
        - indices are 0-based positions in the list of lines
        - starts_paragraph is True for a markdown bullet line, which begins a new paragraph

    Raises:
        - nothing
    """
    in_contract  = False
    field_indent = None
    for i, raw in enumerate( text.split( "\n" ) ):
        if not markdown and CONTRACT_HEADER.match( raw ):
            in_contract = True
            continue
        if not markdown and FIELD_HEADER.match( raw ):
            field_indent = len( raw ) - len( raw.lstrip() )
            continue
        if not raw.strip():
            continue
        if field_indent is not None:
            if len( raw ) - len( raw.lstrip() ) > field_indent: continue
            field_indent = None
        if markdown:
            if raw.lstrip().startswith( ( "#", "|" ) ): continue
            yield i, BULLET_LINE.sub( "", raw, count=1 ), BULLET_LINE.match( raw ) is not None
            continue
        if in_contract or BULLET_LINE.match( raw ): continue
        yield i, raw, False


def sentence_findings( text, path, first_line, markdown=False ):
    """
    Check rule 3: a sentence has fewer than SENTENCE_MAX_WORDS words.

    Requires:
        - text is a str holding one docstring or page
        - markdown selects the markdown reading of prose_lines

    Ensures:
        - consecutive prose lines are joined into one paragraph before sentences are split, so a
          sentence wrapped over several lines is judged whole
        - in markdown each bullet starts a new paragraph
        - each over-long sentence yields one Finding at the line where it starts

    Raises:
        - nothing
    """
    paragraphs = []
    for i, raw, starts in prose_lines( text, markdown ):
        if paragraphs and not starts and i == paragraphs[ -1 ][ 1 ][ -1 ][ 0 ] + 1: paragraphs[ -1 ][ 1 ].append( ( i, raw.strip() ) )
        else: paragraphs.append( ( i, [ ( i, raw.strip() ) ] ) )
    findings = []
    for _, lines in paragraphs:
        joined  = " ".join( t for _, t in lines )
        starts  = []
        offset  = 0
        for index, t in lines:
            starts.append( ( offset, index ) )
            offset += len( t ) + 1
        pos = 0
        for m in list( SENTENCE_SPLIT.finditer( joined ) ) + [ None ]:
            end      = len( joined ) if m is None else m.start()
            sentence = joined[ pos : end ]
            words    = len( sentence.split() )
            if words > SENTENCE_MAX_WORDS:
                line = max( idx for off, idx in starts if off <= pos )
                findings.append( Finding( path, first_line + line, "sentence-length", f"sentence of {words} words, limit {SENTENCE_MAX_WORDS}" ) )
            if m is not None: pos = m.end()
    return findings


def emphasis_findings( text, path, first_line, words=None ):
    """
    Check rule 4: no emphasis words in capitals, and no emphasis glyphs.

    Requires:
        - text is a str
        - words is a set of lowercase English words, or None for the vendored list

    Ensures:
        - one Finding per emphasis word in capitals and one per emphasis glyph, at its line
        - inline code spans and quoted spans are not searched for capitalised words

    Raises:
        - nothing
    """
    findings = []
    for i, raw in enumerate( text.split( "\n" ) ):
        for word in caps_words( INLINE_CODE.sub( " ", raw ), words ):
            findings.append( Finding( path, first_line + i, "caps", f"ALL-CAPS word {word}" ) )
        for glyph in EMPHASIS_GLYPHS:
            if glyph in raw:
                findings.append( Finding( path, first_line + i, "glyph", f"emphasis glyph U+{ord( glyph ):04X}" ) )
    return findings


def rhetoric_findings( text, path, first_line ):
    """
    Check rule 5: no tic phrases from the frozen list.

    Requires:
        - text is a str

    Ensures:
        - one Finding per tic phrase occurrence, at its line

    Raises:
        - nothing
    """
    findings = []
    for i, raw in enumerate( text.split( "\n" ) ):
        for m in TIC_REGEX.finditer( raw ):
            findings.append( Finding( path, first_line + i, "tic", f"tic phrase {m.group( 0 )!r}" ) )
    return findings


def defined_labels( text ):
    """
    Collect the case labels that the text itself defines.

    Requires:
        - text is a str

    Ensures:
        - returns the set of labels (a capital letter and a digit) that start a line and are followed by a dash, colon or equals sign
        - a label in this set is a local name, not a reference to a document the reader lacks

    Raises:
        - nothing
    """
    return set( re.findall( r"^[ \t]*(?:[-*][ \t]+)?\**([A-Z]\d{1,2})\**[ \t]*(?:[-:=\u2013\u2014])", text, re.MULTILINE ) )


STEP_DEFINITION = re.compile(
    r"^[ \t]*(?:#{1,6}[ \t]+|[-*][ \t]+|\d+[.)][ \t]+)?\**((?i:step|phase|stage|item|option)s?[ \t]+(?:\d+(?:\.\d+)*[a-z]?\b|[A-Z]\b|\([a-z]\)))\**[ \t]*(?:[:.\-\u2013\u2014)]|$)",
    re.MULTILINE
)


def defined_steps( text ):
    """
    Collect the step, phase or option labels that the text itself defines.

    Requires:
        - text is a str

    Ensures:
        - returns the lowercase labels, such as "step 1", that start a line or heading and are
          followed by a colon, dash, period or the end of the line
        - a reference to a label in this set is the page's own structure, not a pointer elsewhere

    Raises:
        - nothing
    """
    return { m.group( 1 ).lower() for m in STEP_DEFINITION.finditer( text ) }


def reference_findings( text, path, first_line ):
    """
    Check rule 6: no reference without a path.

    Requires:
        - text is a str

    Ensures:
        - one Finding per bare reference, at its line
        - a section mark is bare unless a path sits beside it in the same paragraph
        - a case label or step that the text defines itself is not a finding
        - a bare git sha is reported under the same rule; whether it should be is pending Rick's ruling
        - a sha that sits inside an already reported row, bug or task reference is not reported twice

    Raises:
        - nothing
    """
    findings = []
    local    = defined_labels( text )
    steps    = defined_steps( text )
    for m in SECTION_REGEX.finditer( text ):
        if not is_section_ref_resolved( text, m ):
            findings.append( Finding( path, first_line + line_of_offset( text, m.start() ), "bare-ref", f"section reference {m.group( 0 )!r} has no path" ) )
    id_spans = []
    for regex in ( ID_REF_EXTENDED_REGEX, BARE_SHA_REGEX, RULING_REF_REGEX, AC_REF_REGEX, STEP_REF_REGEX, LABEL_REF_REGEX ):
        for m in regex.finditer( text ):
            if regex is ID_REF_EXTENDED_REGEX: id_spans.append( m.span() )
            if regex is BARE_SHA_REGEX and any( a <= m.start() and m.end() <= b for a, b in id_spans ): continue
            if regex is LABEL_REF_REGEX and m.group( 0 ) in local: continue
            if regex is STEP_REF_REGEX and m.group( 0 ).lower() in steps: continue
            findings.append( Finding( path, first_line + line_of_offset( text, m.start() ), "bare-ref", f"bare reference {m.group( 0 )!r}" ) )
    return findings


def history_findings( text, path, first_line ):
    """
    Check rule 7 and the agent-imperative rule: current state only, nothing addressed to a model.

    Requires:
        - text is a str

    Ensures:
        - one Finding per dated banner, per ISO date outside quotes and code, and per imperative
          aimed at a model, at its line

    Raises:
        - nothing
    """
    findings = []
    for m in DATED_BANNER_REGEX.finditer( text ):
        findings.append( Finding( path, first_line + line_of_offset( text, m.start() ), "dated-banner", f"dated banner {m.group( 0 ).strip()!r}" ) )
    unquoted = QUOTED_SPAN_REGEX.sub( lambda q: " " * len( q.group( 0 ) ), text )
    for m in ISO_DATE_REGEX.finditer( unquoted ):
        findings.append( Finding( path, first_line + line_of_offset( text, m.start() ), "iso-date", f"date {m.group( 0 )} in prose belongs in history" ) )
    for m in AGENT_IMPERATIVE_REGEX.finditer( text ):
        findings.append( Finding( path, first_line + line_of_offset( text, m.start() ), "agent-imperative", f"text addressed to a model: {m.group( 0 )!r}" ) )
    return findings


def lint_text( text, path, first_line=1, structure=True, markdown=False, words=None ):
    """
    Run every text rule over one docstring, doc block or page.

    Requires:
        - text is a str
        - first_line is the 1-based file line of the first line of text
        - markdown is True when text is a markdown page
        - words is the English word set for rule 4, or None for the vendored list

    Ensures:
        - returns a list of Finding sorted by line, then rule
        - structure=True adds the summary and preface checks, which apply to docstrings and
          doc blocks but not to whole markdown pages

    Raises:
        - nothing
    """
    findings = []
    text = blank_code( text )
    if structure:
        findings += summary_findings( text, path, first_line )
        findings += preface_findings( text, path, first_line )
    findings += sentence_findings( text, path, first_line, markdown )
    findings += emphasis_findings( text, path, first_line, words )
    findings += rhetoric_findings( text, path, first_line )
    findings += reference_findings( text, path, first_line )
    findings += history_findings( text, path, first_line )
    return sorted( findings, key=lambda f: ( f.line, f.rule, f.message ) )
