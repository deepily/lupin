"""
Marker counting for the docstring and markdown linters (plan 1, Phase 0 step 4).

Counts the spec's six marker columns, per 1,000 words, using the frozen lists in
rule_lists. Stdlib only, so it can be vendored into lupin-mobile's tool/ directory.
"""

import re

from .rule_lists import (
    ACRONYM_ALLOWLIST, TIC_REGEX, EMPHASIS_GLYPHS, ID_REF_REGEX, RULING_REF_REGEX, AC_REF_REGEX,
    STEP_REF_REGEX, LABEL_REF_REGEX, SECTION_REGEX, PATH_REGEX, SECTION_PATH_LOOKBACK,
    SECTION_PATH_LOOKAHEAD
)

MARKER_COLUMNS = ( "em_dash", "caps_words", "section_refs", "id_refs", "tics", "emphasis_glyphs" )

WORD_REGEX       = re.compile( r"[A-Za-z0-9][\w'’\-]*" )
CAPS_REGEX       = re.compile( r"\b[A-Z][A-Z0-9]+\b" )
FRONTMATTER      = re.compile( r"\A---\n.*?\n---\n", re.DOTALL )
FENCED_BLOCK     = re.compile( r"^(```|~~~).*?^\1[^\n]*$", re.DOTALL | re.MULTILINE )
INLINE_CODE      = re.compile( r"`[^`\n]*`" )
HTML_COMMENT     = re.compile( r"<!--.*?-->", re.DOTALL )


def strip_markdown( text ):
    """
    Remove the parts of a markdown page that are not prose.

    Requires:
        - text is a str

    Ensures:
        - front matter, fenced code blocks and HTML comments are removed
        - inline code spans are kept, since a bare reference can sit inside one

    Raises:
        - nothing
    """
    text = FRONTMATTER.sub( "", text, count=1 )
    text = FENCED_BLOCK.sub( "", text )
    return HTML_COMMENT.sub( "", text )


def is_section_ref_resolved( text, match ):
    """
    Say whether a section mark has a path beside it on the same line.

    Requires:
        - match is a SECTION_REGEX match over text

    Ensures:
        - True when a path occurs within SECTION_PATH_LOOKBACK characters before the mark or
          SECTION_PATH_LOOKAHEAD characters after it, inside the same line
        - False otherwise, which makes the section mark a bare reference

    Raises:
        - nothing
    """
    line_start = text.rfind( "\n", 0, match.start() ) + 1
    line_end   = text.find( "\n", match.end() )
    if line_end == -1: line_end = len( text )
    before = text[ max( line_start, match.start() - SECTION_PATH_LOOKBACK ) : match.start() ]
    after  = text[ match.end() : min( line_end, match.end() + SECTION_PATH_LOOKAHEAD ) ]
    return PATH_REGEX.search( before ) is not None or PATH_REGEX.search( after ) is not None


def bare_section_refs( text ):
    """
    List the section marks in text that carry no path.

    Requires:
        - text is a str

    Ensures:
        - returns the matched strings, in order of appearance

    Raises:
        - nothing
    """
    return [ m.group( 0 ) for m in SECTION_REGEX.finditer( text ) if not is_section_ref_resolved( text, m ) ]


def caps_words( text ):
    """
    List the ALL-CAPS words in text that are emphasis rather than acronyms or identifiers.

    Requires:
        - text is a str, with inline code already removed if identifiers should not count

    Ensures:
        - words on the acronym allowlist are skipped
        - words containing a digit are skipped here, since label references are counted by
          the bare-reference rule
        - identifiers with an underscore never match, because CAPS_REGEX stops at one

    Raises:
        - nothing
    """
    found = []
    for m in CAPS_REGEX.finditer( text ):
        word = m.group( 0 )
        before = text[ m.start() - 1 ] if m.start() > 0 else ""
        after  = text[ m.end() ] if m.end() < len( text ) else ""
        if before == "_" or after == "_": continue
        if word in ACRONYM_ALLOWLIST or any( c.isdigit() for c in word ): continue
        found.append( word )
    return found


def count_markers( text ):
    """
    Count the six marker columns in a piece of prose.

    Requires:
        - text is a str, already stripped of front matter and fenced code where it is markdown

    Ensures:
        - returns { "words": int, <each MARKER_COLUMNS name>: int }
        - CAPS words are counted outside inline code spans; every other column is counted on
          the full text
        - id_refs counts the row, bug, task and ts references only

    Raises:
        - nothing
    """
    prose = INLINE_CODE.sub( " ", text )
    return {
        "words"           : len( WORD_REGEX.findall( text ) ),
        "em_dash"         : text.count( "—" ),
        "caps_words"      : len( caps_words( prose ) ),
        "section_refs"    : text.count( "§" ),
        "id_refs"         : len( ID_REF_REGEX.findall( text ) ),
        "tics"            : len( TIC_REGEX.findall( text ) ),
        "emphasis_glyphs" : sum( text.count( g ) for g in EMPHASIS_GLYPHS )
    }


def rates_per_thousand( counts ):
    """
    Convert raw marker counts to rates per 1,000 words.

    Requires:
        - counts is a dict from count_markers, or a sum of several

    Ensures:
        - returns a dict with the MARKER_COLUMNS keys, rounded to one decimal
        - a corpus with no words has every rate 0.0

    Raises:
        - nothing
    """
    words = counts[ "words" ]
    return { c : ( round( counts[ c ] * 1000.0 / words, 1 ) if words else 0.0 ) for c in MARKER_COLUMNS }
