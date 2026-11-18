"""
The first count of the history recovery: how many source rows there are, by type and era.

The baseline inventory prints psql tables. This module reads that text and returns the first
stages of the yield funnel, with the reason each stage drops rows. It touches no database.
"""

import re

SEPARATOR_PATTERN = re.compile( r"^-+(?:\+-+)+$" )

DROP_REASONS = (
    ( "notification_rows",      "every notification row in the database" ),
    ( "response_required_rows", "not asks: the notification asked for no response" ),
    ( "recipient_asks",        "asks addressed to another account" ),
)


def parse_psql_tables( text ):
    """
    Read the aligned tables in psql output.

    Requires:
        - text is the captured output of psql in its default aligned format

    Ensures:
        - Returns a list of tables in the order printed
        - Each table is a list of dicts keyed by column name, with every value a string
        - A line that is not part of a table (transaction lines, row counts, headers of the run) is ignored
    """
    tables = []
    lines  = text.splitlines()
    index  = 0
    while index < len( lines ) - 1:
        if "|" in lines[ index ] and SEPARATOR_PATTERN.match( lines[ index + 1 ].replace( " ", "" ) ):
            columns = [ c.strip() for c in lines[ index ].split( "|" ) ]
            rows    = []
            index  += 2
            while index < len( lines ) and "|" in lines[ index ]:
                rows.append( dict( zip( columns, [ c.strip() for c in lines[ index ].split( "|" ) ] ) ) )
                index += 1
            tables.append( rows )
        else:
            index += 1
    return tables


def count_source_population( text ):
    """
    Count the source population from the baseline inventory output.

    Requires:
        - text is the inventory's psql output, with the totals, the type-by-state and the month tables

    Ensures:
        - Returns a dict with funnel, by_type_state and by_era
        - funnel is a list of ( stage, count, reason ) that never rises from one stage to the next
        - by_type_state maps ( response_type, state ) to its ask count
        - by_era maps ( month, response_type ) to its ask count
        - The type-by-state counts and the era counts each sum to the recipient asks

    Raises:
        - ValueError if a table is missing or a total does not add up, naming the total
    """
    tables = parse_psql_tables( text )
    totals = next( ( t for t in tables if t and "recipient_asks" in t[ 0 ] ), None )
    if totals is None: raise ValueError( "inventory output has no totals table (notification_rows, response_required_rows, recipient_asks)" )
    by_state = next( ( t for t in tables if t and "state" in t[ 0 ] and "asks" in t[ 0 ] and "logged_asks" in t[ 0 ] ), None )
    if by_state is None: raise ValueError( "inventory output has no type-by-state table" )
    by_month = next( ( t for t in tables if t and "month_utc" in t[ 0 ] ), None )
    if by_month is None: raise ValueError( "inventory output has no month table" )

    funnel = [ ( stage, int( totals[ 0 ][ stage ] ), reason ) for stage, reason in DROP_REASONS ]
    for ( stage, count, _ ), ( _, after, _ ) in zip( funnel, funnel[ 1: ] ):
        if after > count: raise ValueError( f"{stage}: the next stage ({after}) is larger than {count}" )

    asks       = funnel[ -1 ][ 1 ]
    type_state = { ( r[ "response_type" ], r[ "state" ] ) : int( r[ "asks" ] ) for r in by_state }
    era        = { ( r[ "month_utc" ], r[ "response_type" ] ) : int( r[ "asks" ] ) for r in by_month }
    if sum( type_state.values() ) != asks: raise ValueError( f"type-by-state asks sum to {sum( type_state.values() )}, not recipient_asks {asks}" )
    if sum( era.values() ) != asks: raise ValueError( f"month asks sum to {sum( era.values() )}, not recipient_asks {asks}" )
    return { "funnel": funnel, "by_type_state": type_state, "by_era": era }


def format_source_count( counts ):
    """
    Print the funnel head and the two breakdowns as plain text.

    Requires:
        - counts is the dict returned by count_source_population

    Ensures:
        - Returns one string with the funnel, the asks by type and state, and the asks by month and type
    """
    lines = [ "Yield funnel, source stages:" ]
    for stage, count, reason in counts[ "funnel" ]:
        lines.append( f"  {stage:<24}{count:>10,}   ({reason})" )
    lines.append( "Asks by type and state:" )
    for ( kind, state ), count in sorted( counts[ "by_type_state" ].items() ):
        lines.append( f"  {kind:<18}{state:<12}{count:>8,}" )
    lines.append( "Asks by month and type:" )
    for ( month, kind ), count in sorted( counts[ "by_era" ].items() ):
        lines.append( f"  {month:<12}{kind:<18}{count:>8,}" )
    return "\n".join( lines )
