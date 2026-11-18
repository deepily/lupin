"""
The family, retry-copy and project of each ask, in one place.

The replay report, the family back-off and the history track all read these three keys.
Each calls classify_asks, so none of them keeps a rule of its own.
"""

import re
from datetime import datetime, timedelta, timezone

from cosa.utils.iso_timestamp import parse_iso

RETRY_WINDOW    = timedelta( minutes=10 )
UNKNOWN_PROJECT = "unknown"

QUOTED_PATTERN  = re.compile( r"\"[^\"]*\"|'[^']*'|`[^`]*`|“[^”]*”" )
PATH_PATTERN    = re.compile( r"(?:~|\.{1,2})?(?:/[\w.@+-]+)+/?" )
HEX_PATTERN     = re.compile( r"\b(?=[0-9a-f]*[a-f])(?=[0-9a-f]*\d)[0-9a-f]{7,}\b|\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b", re.IGNORECASE )
DIGIT_PATTERN   = re.compile( r"\d+" )
PROJECT_PATTERN = re.compile( r"@([^.#\s@]+)" )


def normalise_text( text ):
    """
    Reduce a title or message to the words that name the kind of ask.

    Requires:
        - text is a string or None

    Ensures:
        - Returns the text lowercased, with quoted strings, paths, hex ids and digits removed
          and every run of whitespace collapsed to one space
        - Returns "" for None or for text that has nothing left
    """
    if not text: return ""
    for pattern in ( QUOTED_PATTERN, PATH_PATTERN, HEX_PATTERN, DIGIT_PATTERN ):
        text = pattern.sub( " ", text )
    return " ".join( text.lower().split() )


def classify_asks( asks ):
    """
    Give each ask its family, its retry group and its project.

    Requires:
        - asks is a list of dicts with response_type, category, title, message, sender_id and asked_at
        - asked_at is a datetime or an ISO-8601 string; a value with no offset is read as UTC

    Ensures:
        - Returns a list the same length and order as asks; each item is a dict with family,
          project, retry_group (the index in asks of the group's first ask) and is_retry_copy
        - The first ask of a group, in time order, has is_retry_copy False; later ones are True
        - An ask whose message normalises to nothing never joins a group
        - An ask outside the window of the group's first starts a new group
        - A family is ( response_type, category, normalised title ); an empty title falls back to
          the first line of the message
        - A retry group is the asks with one sender and one normalised message inside RETRY_WINDOW
          of the first of them; they count once, as the group's first ask
        - A project is the first label of the sender's domain, or "unknown" with no sender or domain

    Raises:
        - ValueError if asked_at is not a datetime or an ISO-8601 string
    """
    times = []
    for ask in asks:
        moment = parse_iso( ask[ "asked_at" ] ) if isinstance( ask[ "asked_at" ], str ) else ask[ "asked_at" ]
        if not isinstance( moment, datetime ): raise ValueError( f"asked_at must be a datetime or an ISO-8601 string, got {ask[ 'asked_at' ]!r}" )
        times.append( moment if moment.tzinfo is not None else moment.replace( tzinfo=timezone.utc ) )
    result = [ None ] * len( asks )
    firsts = {}
    for index in sorted( range( len( asks ) ), key=lambda i: ( times[ i ], i ) ):
        ask     = asks[ index ]
        message = normalise_text( ask[ "message" ] )
        key     = ( ask[ "sender_id" ], message )
        first   = firsts.get( key )
        copy    = bool( message ) and first is not None and times[ index ] - times[ first ] <= RETRY_WINDOW
        if bool( message ) and not copy: firsts[ key ] = index
        title   = normalise_text( ask[ "title" ] ) or normalise_text( ( ask[ "message" ] or "" ).strip().split( "\n" )[ 0 ] )
        match   = PROJECT_PATTERN.search( ask[ "sender_id" ] or "" )
        result[ index ] = {
            "family"        : ( ask[ "response_type" ], ask[ "category" ], title ),
            "project"       : match.group( 1 ) if match else UNKNOWN_PROJECT,
            "retry_group"   : first if copy else index,
            "is_retry_copy" : copy,
        }
    return result

