"""
The bullet line a card carries for one held row, with its one-click approve link.

A manager who asks Rick to approve rows writes each one as a markdown bullet with its own link.
Both browser clients catch a click on that link and send the approve move in place.
This module is the one writer of that line, so nobody types it by hand.

Plan: src/rnd/v0.2.2/2026.10.31-one-click-ticket-approval-plan.md
"""

import re
from urllib.parse import quote

APPROVE_LINK_PATH  = "/app/tasks/approve?row="
APPROVE_LINK_LABEL = "approve ☐"
VIEW_LINK_PATH     = "/app/tasks/view?row="
VIEW_LINK_LABEL    = "📋"
PRIORITY_LINK_PARAM = "&priority="
PRIORITY_LINK_ICON  = "⏫"
PRIORITIES          = ( "P0", "P1", "P2", "P3", "P4", "P5" )

# A full, canonical, lowercase row id. Short ids and braced or unhyphenated forms are
# refused: the click handlers send exactly this string to the server.
_ROW_ID_RE = re.compile( r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$" )


def approve_link_line( row_id, title, priority=None ):
    """
    Write the card bullet for one held row: its title, its approve link, then its 📋 view link.

    Requires:
        - row_id is a full lowercase hyphenated UUID string
        - title is a string with at least one non-blank character
        - priority is None, or one of P0..P5

    Ensures:
        - returns one line, `- <title> [approve ☐](/app/tasks/approve?row=<row_id>) [📋](/app/tasks/view?row=<row_id>)`
        - with no priority the line is the two-link line, unchanged
        - with a priority a third link sits between them, `[⏫ P0](/app/tasks/approve?row=<row_id>&priority=P0)`,
          which admits the row at that level; the server honours it for Rick's login only, and only when it raises the row
        - whitespace runs in the title (newlines included) collapse to single spaces
        - `[` and `]` in the title are backslash-escaped so a title cannot form a link

    Raises:
        - ValueError if row_id is not a full lowercase UUID, title is blank, or priority is not None or one of P0..P5
        - TypeError if row_id or title is not a string
    """
    if not isinstance( row_id, str ): raise TypeError( f"row_id must be a string, got {type( row_id ).__name__}" )
    if not isinstance( title, str ):  raise TypeError( f"title must be a string, got {type( title ).__name__}" )
    if _ROW_ID_RE.match( row_id ) is None:
        raise ValueError( f"row_id must be a full lowercase UUID, got {row_id!r}" )
    flat = " ".join( title.split() )
    if flat == "": raise ValueError( "title must not be blank" )
    flat = flat.replace( "[", "\\[" ).replace( "]", "\\]" )
    if priority is not None and priority not in PRIORITIES: raise ValueError( f"priority must be None or one of {PRIORITIES}, got {priority!r}" )
    raised = "" if priority is None else f" [{PRIORITY_LINK_ICON} {priority}]({APPROVE_LINK_PATH}{row_id}{PRIORITY_LINK_PARAM}{priority})"
    return f"- {flat} [{APPROVE_LINK_LABEL}]({APPROVE_LINK_PATH}{row_id}){raised} [{VIEW_LINK_LABEL}]({VIEW_LINK_PATH}{row_id})"


BATCH_APPROVE_PATH = "/app/tasks/approve?rows="
BATCH_VIEW_PATH    = "/app/tasks/view?rows="
BATCH_MOVES        = ( "queued", "dropped" )


def parse_batch_row_ids( row_ids ):
    """
    Check a list of row ids for a batch link and return it as a list.

    Requires:
        - row_ids is a list or tuple of strings

    Ensures:
        - returns the ids in the order given
        - the same full-lowercase-UUID rule as `approve_link_line` applies to every id

    Raises:
        - TypeError if row_ids is not a list or tuple, or an id is not a string
        - ValueError if the list is empty, an id is not a full lowercase UUID, or an id appears twice
    """
    if not isinstance( row_ids, ( list, tuple ) ): raise TypeError( f"row_ids must be a list, got {type( row_ids ).__name__}" )
    if len( row_ids ) == 0: raise ValueError( "row_ids must not be empty" )
    seen = set()
    for row_id in row_ids:
        if not isinstance( row_id, str ): raise TypeError( f"row_id must be a string, got {type( row_id ).__name__}" )
        if _ROW_ID_RE.match( row_id ) is None: raise ValueError( f"row_id must be a full lowercase UUID, got {row_id!r}" )
        if row_id in seen: raise ValueError( f"row_id appears twice: {row_id}" )
        seen.add( row_id )
    return list( row_ids )


def approve_batch_line( row_ids, move="queued", reason=None ):
    """
    Write the card bullet for a list of held rows, with one link that moves them all.

    The bullet also carries one 📋 link that lists every row.

    Requires:
        - row_ids is a non-empty list of distinct full lowercase UUIDs
        - move is "queued" (approve) or "dropped"
        - a drop carries a non-blank reason; an approve carries none

    Ensures:
        - returns one line, `- <N> held rows [approve all N ☐](/app/tasks/approve?rows=<a>,<b>&move=queued) [📋](/app/tasks/view?rows=<a>,<b>)`
        - a drop reads `[drop all N ☐]` and ends its link with `&move=dropped&reason=<percent-encoded reason>`
        - ids keep the order given

    Raises:
        - TypeError or ValueError as `parse_batch_row_ids` does
        - ValueError if move is not one of BATCH_MOVES, a drop has a blank reason, or an approve has a reason
    """
    ids = parse_batch_row_ids( row_ids )
    if move not in BATCH_MOVES: raise ValueError( f"move must be one of {BATCH_MOVES}, got {move!r}" )
    if move == "queued" and reason is not None: raise ValueError( "an approve takes no reason" )
    count = len( ids )
    joined = ",".join( ids )
    tail = "&move=queued"
    verb = "approve"
    if move == "dropped":
        if not isinstance( reason, str ) or reason.strip() == "": raise ValueError( "a drop needs a non-blank reason" )
        tail = f"&move=dropped&reason={quote( ' '.join( reason.split() ), safe='' )}"
        verb = "drop"
    return f"- {count} held rows [{verb} all {count} ☐]({BATCH_APPROVE_PATH}{joined}{tail}) [{VIEW_LINK_LABEL}]({BATCH_VIEW_PATH}{joined})"
