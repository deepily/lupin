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
#   target: no spaces, or holding (nested) parentheses up to _TARGET_PAREN_DEPTH levels deep
# Alternative 2: a bare http or https address. Trailing sentence punctuation is not part of it.
# Each character class stops at the closing bracket,
# so two links in one string yield two labels, never one swallowed span.
# A regular expression cannot match unbounded nesting, so the depth is a stated limit:
# a target nested deeper than this still leaks its tail into the spoken text.
_TARGET_PAREN_DEPTH = 6

_PAREN_BODY = r'[^()]*'
for _level in range( _TARGET_PAREN_DEPTH - 1 ):
    _PAREN_BODY = r'(?:[^()]|\(' + _PAREN_BODY + r'\))*'

_LINK_OR_BARE_URL = re.compile(
    r'!?\[((?:[^\[\]]|\[[^\[\]]*\])*)\]'
    r'\(\s*((?:[^()\s]|\(' + _PAREN_BODY + r'\))+)(?:\s+"[^"]*")?\s*\)'
    r'|https?://[^\s<>\[\]()]*[^\s<>\[\]().,;:!?\'"]'
)


def _spoken_form( match ):
    """
    Return what speech says for one link or bare address.

    Requires:
        - match is a match of _LINK_OR_BARE_URL

    Ensures:
        - a link with a label gives "label, URL omitted"
        - a link with an empty label gives "URL omitted"
        - a bare address gives "URL omitted"
    """
    label = match.group( 1 )
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

    return _LINK_OR_BARE_URL.sub( _spoken_form, text )
