"""
Marker counting for the docstring and markdown linters (documentation-standard plan).

Counts the spec's six marker columns, per 1,000 words, using the frozen lists in
rule_lists. Stdlib only, so it can be vendored into lupin-mobile's tool/ directory.
"""

import re

from .rule_lists import (
    CAPS_WORD_EXCEPTIONS, QUOTED_SPAN_REGEX, TIC_REGEX, EMPHASIS_GLYPHS, ID_REF_REGEX, SECTION_REGEX,
    PATH_REGEX, SECTION_PATH_LOOKBACK, SECTION_PATH_LOOKAHEAD
)
from .word_list import default_words

MARKER_COLUMNS = ( "em_dash", "caps_words", "section_refs", "id_refs", "tics", "emphasis_glyphs" )

WORD_REGEX       = re.compile( r"[A-Za-z0-9][\w'’\-]*" )
CAPS_REGEX       = re.compile( r"\b[A-Z][A-Z0-9]+\b" )
FRONTMATTER      = re.compile( r"\A---\n.*?\n---\n", re.DOTALL )
FENCED_BLOCK     = re.compile( r"^(```|~~~).*?^\1[^\n]*$", re.DOTALL | re.MULTILINE )
INLINE_CODE      = re.compile( r"`[^`\n]*`" )
HTML_COMMENT     = re.compile( r"<!--.*?-->", re.DOTALL )
DOCTEST_BLOCK    = re.compile( r"^[ \t]*>>>.*?(?=\n[ \t]*\n|\Z)", re.DOTALL | re.MULTILINE )


def _blank( match ):
    """
    Replace a matched block with as many newlines as it spans.

    Requires:
        - match is a re match object

    Ensures:
        - returns a string of newlines only, so line numbers after the block do not move

    Raises:
        - nothing
    """
    return "\n" * match.group( 0 ).count( "\n" )


def blank_code( text ):
    """
    Blank the fenced code blocks and doctest blocks in a docstring or page.

    Requires:
        - text is a str

    Ensures:
        - returns text with each such block reduced to its newlines, so line numbers hold
        - prose outside the blocks is untouched

    Raises:
        - nothing
    """
    return DOCTEST_BLOCK.sub( _blank, FENCED_BLOCK.sub( _blank, text ) )


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
    Say whether a section mark has a path beside it in the same paragraph.

    Requires:
        - match is a SECTION_REGEX match over text

    Ensures:
        - True when a path occurs within SECTION_PATH_LOOKBACK characters before the mark or
          SECTION_PATH_LOOKAHEAD characters after it, without crossing a blank line
        - a hard-wrapped line break does not separate the mark from its path
        - False otherwise, which makes the section mark a bare reference

    Raises:
        - nothing
    """
    para_start = text.rfind( "\n\n", 0, match.start() ) + 1
    para_end   = text.find( "\n\n", match.end() )
    if para_end == -1: para_end = len( text )
    before = text[ max( para_start, match.start() - SECTION_PATH_LOOKBACK ) : match.start() ]
    after  = text[ match.end() : min( para_end, match.end() + SECTION_PATH_LOOKAHEAD ) ]
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


def caps_words( text, words=None ):
    """
    List the ALL-CAPS words in text that are emphasis.

    Requires:
        - text is a str
        - words is a set of lowercase English words; None means the vendored list

    Ensures:
        - a word counts only when its lowercase form is in words and it is not in
          CAPS_WORD_EXCEPTIONS
        - words inside quotes or backticks, with a digit, next to an underscore or hyphen, are skipped

    Raises:
        - OSError when words is None and the vendored list is missing
    """
    words = default_words() if words is None else words
    text  = QUOTED_SPAN_REGEX.sub( lambda m: " " * len( m.group( 0 ) ), text )
    found = []
    for m in CAPS_REGEX.finditer( text ):
        word   = m.group( 0 )
        before = text[ m.start() - 1 ] if m.start() > 0 else ""
        after  = text[ m.end() ] if m.end() < len( text ) else ""
        if before in ( "_", "-" ) or after in ( "_", "-" ): continue
        if any( c.isdigit() for c in word ) or word in CAPS_WORD_EXCEPTIONS: continue
        if word.lower() in words: found.append( word )
    return found


def count_markers( text, words=None ):
    """
    Count the six marker columns in a piece of prose.

    Requires:
        - text is a str, already stripped of front matter and fenced code where it is markdown
        - words is a set of lowercase English words, or None for the vendored list

    Ensures:
        - returns { "words": int, <each MARKER_COLUMNS name>: int }
        - fenced and doctest blocks are blanked first; capitalised words are counted outside inline
          code spans; every other column is counted on the rest of the text
        - id_refs counts the row, bug, task and ts references only

    Raises:
        - nothing
    """
    text  = blank_code( text )
    prose = INLINE_CODE.sub( " ", text )
    return {
        "words"           : len( WORD_REGEX.findall( text ) ),
        "em_dash"         : text.count( "—" ),
        "caps_words"      : len( caps_words( prose, words ) ),
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
