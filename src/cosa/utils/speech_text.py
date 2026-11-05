"""
Text clean-up that runs before a message is spoken or measured for speech.

One function lives here. The server's speech routes and the cosa-voice
spoken-length cap both use it. Both read a link the same way. Speech never
says an address. It says the label, then a marker, so a link is never dropped
silently.
"""

import re

URL_OMITTED = "URL omitted"

# Alternative 1: [label](target) and ![alt](src), optionally with a "title" after the target.
#   label : text, or text holding one level of [nested] brackets
#   target: found by _scan_target, which counts parentheses, so any nesting depth works
# Alternative 2: a bare http or https address. Trailing sentence punctuation is not part of it.
# Each character class stops at the closing bracket,
# so two links in one string yield two labels, never one swallowed span.
_LINK_OR_BARE_URL = re.compile(
    r'(!?\[((?:[^\[\]]|\[[^\[\]]*\])*)\]\(\s*)'
    r'|https?://[^\s<>\[\]()]*[^\s<>\[\]().,;:!?\'"]'
)
_TITLE_AND_CLOSE = re.compile( r'(?:\s+"[^"]*")?\s*\)' )


def _blank_free_run_end( text, start ):
    """
    Return the index where the run of non-blank characters that begins at start ends.

    Requires:
        - text is a str and 0 <= start <= len( text )

    Ensures:
        - returns len( text ) when no blank follows start
    """
    end = start
    while end < len( text ) and not text[ end ].isspace(): end += 1
    return end


def _scan_target( text, start ):
    """
    Find where the link target that begins at start ends.

    Requires:
        - text is a str and start is the index just after "](" and any blank space

    Ensures:
        - returns the index just after the closing ")" of the link when the target is balanced
        - a target is a run of characters that are not blank and not a parenthesis,
          or a balanced "( ... )" group at any depth
        - returns None when this is not a link (empty target, or the closing ")" is missing
          here but a ")" appears later in the text)
        - when a "(" is never closed, or no ")" follows the target at all, returns the index
          where the target's blank-free run ends, so the whole target is dropped and no part
          of the address is spoken
        - runs in time linear in the text it reads, and never recurses
    """
    size  = len( text )
    index = start
    units = 0
    while index < size:
        char = text[ index ]
        if char == "(":
            depth = 0
            probe = index
            while probe < size:
                if text[ probe ] == "(": depth += 1
                elif text[ probe ] == ")":
                    depth -= 1
                    if depth == 0: break
                probe += 1
            if depth != 0: return _blank_free_run_end( text, start )
            index = probe + 1
            units += 1
        elif char == ")" or char.isspace(): break
        else:
            index += 1
            units += 1
    if units == 0: return None
    closing = _TITLE_AND_CLOSE.match( text, index )
    if closing is not None: return closing.end()
    if text.find( ")", index ) == -1: return _blank_free_run_end( text, start )
    return None


def _spoken_form( match ):
    """
    Return what speech says for one link or bare address.

    Requires:
        - match is a match of _LINK_OR_BARE_URL; group 2 is the label of a link

    Ensures:
        - a link with a label gives "label, URL omitted"
        - a link with an empty label gives "URL omitted"
        - a bare address gives "URL omitted"
    """
    label = match.group( 2 )
    if label: return f"{label}, {URL_OMITTED}"
    return URL_OMITTED


def strip_markdown_links_for_speech( text ):
    """
    Replace every link and bare http or https address in text with its spoken form.

    Requires:
        - text is a str

    Ensures:
        - "[label](target)" becomes "label, URL omitted"
        - "![alt](src)" becomes "alt, URL omitted"
        - a link with an empty label becomes "URL omitted"
        - a bare http or https address becomes "URL omitted"
        - "[ref][id]" references and text without links are unchanged
        - the result is not stripped of surrounding whitespace; the caller decides

    Raises:
        - TypeError if text is not a str
    """
    if not isinstance( text, str ):
        raise TypeError( f"text must be a str, got {type( text ).__name__}" )

    pieces = []
    cursor = 0   # text before this index is already in pieces
    search = 0   # where the next match may begin
    while True:
        match = _LINK_OR_BARE_URL.search( text, search )
        if match is None: break
        if match.group( 1 ) is None:
            end = match.end()
        else:
            end = _scan_target( text, match.end() )
            if end is None:
                search = match.start() + 1
                continue
        pieces.append( text[ cursor : match.start() ] )
        pieces.append( _spoken_form( match ) )
        cursor = search = end
    pieces.append( text[ cursor : ] )
    return "".join( pieces )
