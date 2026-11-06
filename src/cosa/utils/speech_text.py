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
_ADDRESS_START   = re.compile( r'(?:https?://|mailto:)', re.IGNORECASE )
_ADDRESS_TAIL    = re.compile( r'[^\s<>\[\]()]*' )
_TRAILING_PUNCT  = ".,;:!?'\""


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


def _balanced_close( text, start ):
    """
    Return the index just after the ")" that closes a "(" which opened just before start.

    Requires:
        - text is a str and 0 <= start <= len( text )

    Ensures:
        - returns None when parentheses never balance
    """
    depth = 1
    for index in range( start, len( text ) ):
        if text[ index ] == "(": depth += 1
        elif text[ index ] == ")":
            depth -= 1
            if depth == 0: return index + 1
    return None


def _extend_bare_address( text, end ):
    """
    Return where a bare address that stops at end really stops, taking in any "(...)" groups.

    Requires:
        - text is a str and end is the index just after a bare address match

    Ensures:
        - returns end when no "(" follows
        - each balanced "( ... )" group that follows, blanks included, is part of the address,
          and so are the non-blank characters between and after groups, less trailing punctuation
        - a "(" that never closes takes in the blank-free run it starts
    """
    while end < len( text ) and text[ end ] == "(":
        close = _balanced_close( text, end + 1 )
        if close is None: return _blank_free_run_end( text, end )
        end = _ADDRESS_TAIL.match( text, close ).end()
        while end > close and text[ end - 1 ] in _TRAILING_PUNCT: end -= 1
    return end


def _angle_target_end( text, start ):
    """
    Return the index just after the ")" that closes an "<...>" link target, or None.

    Requires:
        - text is a str and text[ start ] == "<"

    Ensures:
        - the target runs to the first ">", blanks included, and may be followed by a title
        - returns None when there is no ">" or no closing ")" after it
    """
    close = text.find( ">", start )
    if close == -1: return None
    closing = _TITLE_AND_CLOSE.match( text, close + 1 )
    return None if closing is None else closing.end()


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
        - a target that starts with http:// or https:// but holds blanks (inside a parenthesis
          group or after one) is still one link: it ends at the ")" that closes the link, or,
          when that never comes, after the last group read, so no part of it is spoken
        - an angle-bracket target "<...>" may hold blanks and ends at its ">" plus the closing ")"
        - mailto: counts as an address, like http:// and https://
        - an address target whose parentheses never balance with the link's closing ")" ends
          after the last group read inside its first blank-free run, so no part of it is spoken
        - runs in time linear in the text it reads, and never recurses
    """
    if text.startswith( "<", start ):
        angle_end = _angle_target_end( text, start )
        if angle_end is not None: return angle_end
    size  = len( text )
    index = start
    units = 0
    group = False
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
            group = True
        elif char == ")" or char.isspace(): break
        else:
            index += 1
            units += 1
    if units == 0: return None
    closing = _TITLE_AND_CLOSE.match( text, index )
    if closing is not None: return closing.end()
    address = _ADDRESS_START.match( text, start ) is not None
    if text.find( ")", index ) == -1:
        run_end = _blank_free_run_end( text, start )
        return max( run_end, index ) if address else run_end
    if not address: return None
    closed = _balanced_close( text, start )
    if closed is None and group: return index
    return closed


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
            end = _extend_bare_address( text, match.end() )
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
