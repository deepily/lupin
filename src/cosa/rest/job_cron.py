"""
Cron text and schedule entries, read against a clock that the caller passes in.

The jobs reader needs the latest time a job should have started, and the next time it should.
There are three kinds of registry schedule entry: a cron line, a delay after boot, and a fixed interval.
Nothing here reads the clock.
A cron line follows the standard rule: when both the day-of-month and the day-of-week are restricted, either one
matching is enough.
"""
import datetime

SEARCH_DAYS = 400                                                     # a yearly job still has a last and next time inside this
FIELD_RANGES = ( ( 0, 59 ), ( 0, 23 ), ( 1, 31 ), ( 1, 12 ), ( 0, 7 ) )


def parse_field( text, low, high ):
    """
    Expand one cron field.

    Requires:
        - text is a comma list of *, N, A-B, optionally followed by a slash and a step
    Ensures:
        - returns the sorted set of values inside [low, high]
    Raises:
        - ValueError on an empty list, a bad step, or a value outside the range
    """
    values = set()
    for part in text.split( "," ):
        base, _, step = part.partition( "/" )
        step = int( step ) if step else 1
        if step < 1: raise ValueError( f"cron step must be at least 1 in {text!r}" )
        if base == "*": first, last = low, high
        elif "-" in base: first, last = ( int( x ) for x in base.split( "-" ) )
        else: first = last = int( base )
        if first < low or last > high or first > last: raise ValueError( f"cron value out of range in {text!r}" )
        values.update( range( first, last + 1, step ) )
    return sorted( values )


def parse_cron( text ):
    """
    Parse a five-field cron line.

    Requires:
        - text has minute, hour, day-of-month, month, day-of-week
    Ensures:
        - returns a dict of minutes, hours, days, months, weekdays (Sunday is 0; 7 is folded to 0) and the two restriction flags
    Raises:
        - ValueError when the text does not have five valid fields
    """
    fields = text.split()
    if len( fields ) != 5: raise ValueError( f"a cron line has five fields, got {len( fields )}: {text!r}" )
    minutes, hours, days, months, weekdays = ( parse_field( f, lo, hi ) for f, ( lo, hi ) in zip( fields, FIELD_RANGES ) )
    return { "minutes": minutes, "hours": hours, "days": days, "months": months,
             "weekdays": sorted( { w % 7 for w in weekdays } ),
             "days_restricted": fields[ 2 ] != "*", "weekdays_restricted": fields[ 4 ] != "*" }


def day_matches( spec, day ):
    """
    Say whether a calendar date satisfies the date fields of a cron line.

    Ensures:
        - returns True when the month matches and the day fields match by the standard rule: either one of the two, when both are restricted
    """
    if day.month not in spec[ "months" ]: return False
    in_month = day.day in spec[ "days" ]
    in_week  = ( day.isoweekday() % 7 ) in spec[ "weekdays" ]
    if spec[ "days_restricted" ] and spec[ "weekdays_restricted" ]: return in_month or in_week
    return in_month and in_week


def moments( spec, day, tz ):
    """Ensures: returns the aware datetimes on one date at which the line fires, earliest first."""
    return [ datetime.datetime.combine( day, datetime.time( h, m ), tzinfo=tz ) for h in spec[ "hours" ] for m in spec[ "minutes" ] ]


def cron_last( text, now ):
    """
    Find the latest firing of a cron line not after now.

    Requires:
        - now is timezone-aware
    Ensures:
        - returns an aware datetime, or None when nothing fired within SEARCH_DAYS
    """
    spec = parse_cron( text )
    for back in range( SEARCH_DAYS ):
        day = now.date() - datetime.timedelta( days=back )
        if not day_matches( spec, day ): continue
        past = [ t for t in moments( spec, day, now.tzinfo ) if t <= now ]
        if past: return past[ -1 ]
    return None


def cron_next( text, now ):
    """
    Find the earliest firing of a cron line after now.

    Requires:
        - now is timezone-aware
    Ensures:
        - returns an aware datetime, or None when nothing fires within SEARCH_DAYS
    """
    spec = parse_cron( text )
    for ahead in range( SEARCH_DAYS ):
        day = now.date() + datetime.timedelta( days=ahead )
        if not day_matches( spec, day ): continue
        later = [ t for t in moments( spec, day, now.tzinfo ) if t > now ]
        if later: return later[ 0 ]
    return None


def cron_between( text, start, end ):
    """
    List the firings of a cron line in a window.

    Requires:
        - start and end are timezone-aware with the same tzinfo
    Ensures:
        - returns the aware datetimes with start < t <= end, earliest first
    """
    spec, out = parse_cron( text ), []
    for ahead in range( ( end.date() - start.date() ).days + 1 ):
        day = start.date() + datetime.timedelta( days=ahead )
        if day_matches( spec, day ): out.extend( t for t in moments( spec, day, start.tzinfo ) if start < t <= end )
    return out


def entry_label( entry ):
    """
    Name a schedule entry in one plain line.

    Ensures:
        - returns a string such as "cron 0 10 * * * (daily)"
    """
    if "cron" in entry: text = f"cron {entry[ 'cron' ]}"
    elif "after_boot_seconds" in entry: text = f"{entry[ 'after_boot_seconds' ]} s after boot"
    else: text = f"every {entry[ 'every_seconds' ]} s"
    return f"{text} ({entry[ 'mode' ]})" if entry.get( "mode" ) else text


def entry_last_due( entry, now, boot_time, last_attempt_at=None ):
    """
    Find when one schedule entry last came due.

    Requires:
        - entry holds exactly one of cron, after_boot_seconds, every_seconds
        - last_attempt_at is the start time of the job's last attempt (aware), or None; it matters for every_seconds only
    Ensures:
        - returns an aware datetime not after now, or None when the entry has not come due yet
        - an every_seconds entry came due one interval after the last attempt began
    """
    if "cron" in entry: return cron_last( entry[ "cron" ], now )
    if "after_boot_seconds" in entry:
        due = boot_time + datetime.timedelta( seconds=entry[ "after_boot_seconds" ] )
        return due if due <= now else None
    if last_attempt_at is None: return None
    due = last_attempt_at + datetime.timedelta( seconds=entry[ "every_seconds" ] )
    return due if due <= now else None


def entry_next_due( entry, now, boot_time, last_attempt_at=None ):
    """
    Find when one schedule entry next comes due.

    Requires:
        - the same as entry_last_due
    Ensures:
        - returns an aware datetime after now, or None when the entry will not fire again (a boot delay already past)
        - an every_seconds entry with no attempt yet is due now
    """
    if "cron" in entry: return cron_next( entry[ "cron" ], now )
    if "after_boot_seconds" in entry:
        due = boot_time + datetime.timedelta( seconds=entry[ "after_boot_seconds" ] )
        return due if due > now else None
    if last_attempt_at is None: return now
    due = last_attempt_at + datetime.timedelta( seconds=entry[ "every_seconds" ] )
    return due if due > now else now
