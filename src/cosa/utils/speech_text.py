"""
Text clean-up that runs before a message is spoken or measured for speech.

One function lives here. The server's speech routes and the cosa-voice
spoken-length cap both use it. Both read a markdown link the same way:
speech says the label and never the address behind it.
"""

import re

# [label](target) and ![alt](src), optionally with a "title" after the target.
#   label : text, or text holding one level of [nested] brackets
#   target: no spaces, or holding one level of (nested) parentheses
# Each character class stops at the closing bracket,
# so two links in one string yield two labels, never one swallowed span.
_MARKDOWN_LINK = re.compile(
    r'!?\[((?:[^\[\]]|\[[^\[\]]*\])*)\]'
    r'\(\s*((?:[^()\s]|\([^()]*\))+)(?:\s+"[^"]*")?\s*\)'
)


def strip_markdown_links_for_speech( text ):
    """
    Replace every markdown link in text with its label alone.

    Requires:
        - text is a str

    Ensures:
        - "[label](target)" becomes "label"
        - "![alt](src)" becomes "alt"
        - a link with an empty label becomes an empty string
        - bare URLs, "[ref][id]" references and text without links are unchanged
        - the result is not stripped of surrounding whitespace; the caller decides

    Raises:
        - TypeError if text is not a str
    """
    if not isinstance( text, str ):
        raise TypeError( f"text must be a str, got {type( text ).__name__}" )

    return _MARKDOWN_LINK.sub( lambda match: match.group( 1 ), text )
