"""
The bullet line a card carries for one held row, with its one-click approve link.

A manager who asks Rick to approve rows writes each one as a markdown bullet with its own link.
Both browser clients catch a click on that link and send the approve move in place.
This module is the one writer of that line, so nobody types it by hand.

Plan: src/rnd/v0.2.2/2026.10.31-one-click-ticket-approval-plan.md
"""

import re

APPROVE_LINK_PATH  = "/app/tasks/approve?row="
APPROVE_LINK_LABEL = "approve ☐"
VIEW_LINK_PATH     = "/app/tasks/view?row="
VIEW_LINK_LABEL    = "📄"

# A full, canonical, lowercase row id. Short ids and braced or unhyphenated forms are
# refused: the click handlers send exactly this string to the server.
_ROW_ID_RE = re.compile( r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$" )


def approve_link_line( row_id, title ):
    """
    Write the card bullet for one held row: its title, its approve link, then its 📄 view link.

    Requires:
        - row_id is a full lowercase hyphenated UUID string
        - title is a string with at least one non-blank character

    Ensures:
        - returns one line, `- <title> [approve ☐](/app/tasks/approve?row=<row_id>) [📄](/app/tasks/view?row=<row_id>)`
        - whitespace runs in the title (newlines included) collapse to single spaces
        - `[` and `]` in the title are backslash-escaped so a title cannot form a link

    Raises:
        - ValueError if row_id is not a full lowercase UUID, or title is blank
        - TypeError if row_id or title is not a string
    """
    if not isinstance( row_id, str ): raise TypeError( f"row_id must be a string, got {type( row_id ).__name__}" )
    if not isinstance( title, str ):  raise TypeError( f"title must be a string, got {type( title ).__name__}" )
    if _ROW_ID_RE.match( row_id ) is None:
        raise ValueError( f"row_id must be a full lowercase UUID, got {row_id!r}" )
    flat = " ".join( title.split() )
    if flat == "": raise ValueError( "title must not be blank" )
    flat = flat.replace( "[", "\\[" ).replace( "]", "\\]" )
    return f"- {flat} [{APPROVE_LINK_LABEL}]({APPROVE_LINK_PATH}{row_id}) [{VIEW_LINK_LABEL}]({VIEW_LINK_PATH}{row_id})"
