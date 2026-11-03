"""
What a run costs, measured by the harness (plan 3, section 7.4).

The pilot pair exists to size the cap and to say how many pairs one machine can run at once. So each run records, beside its
verdicts, how long it took in working days, the CPU it used, its peak memory and its seats.

A working day is a day that is not a Saturday or a Sunday in New York. Nights count.
The harness cannot pause a run and cannot know which hours the host was off, so only the weekend is taken out.

Named limits, each stated again where the figure is logged:
- peak memory of the harness's own commands is the largest single process, not the sum of processes that overlap;
- the server container is sampled at each verdict, so its peak is the largest sample, not a continuous reading;
- peak seats is the session plus the most subagent calls seen in one assistant message, so a subagent running in the background across messages is not counted.
"""
import datetime
import re
import resource
import zoneinfo

from lupin_mcp.reuse_harness import errors as err

WORKING_ZONE       = "America/New_York"
GUARD_WORKING_DAYS = 10
SECONDS_PER_DAY    = 86400
KB_TO_BYTES        = 1024
FIRST_WEEKEND_DAY  = 5
AGENT_TOOLS        = ( "Agent", "Task" )
UNIT_BYTES         = { "B" : 1, "kB" : 1000, "KiB" : 1024, "MB" : 1000 ** 2, "MiB" : 1024 ** 2, "GB" : 1000 ** 3, "GiB" : 1024 ** 3, "TiB" : 1024 ** 4 }
STATS_PATTERN      = re.compile( r"^\s*([0-9.]+)\s*([A-Za-z]+)\s*/.*\|\s*([0-9.]+)%\s*$" )


def working_seconds( start, end ):
    """
    Count the seconds between two moments that fall on a weekday in New York.

    Requires:
        - start and end are timezone-aware datetimes with start not after end

    Ensures:
        - a Saturday or Sunday (New York dates) adds nothing, a weekday adds its real elapsed seconds, measured in UTC, so a change of clocks over a weekend cannot shift the count
        - the result is between 0 and the plain elapsed seconds

    Raises:
        - HarnessError BAD_SPEC if end is before start
    """
    if end < start: raise err.HarnessError( err.BAD_SPEC, f"the run ended ({end.isoformat()}) before it started ({start.isoformat()})" )
    zone   = zoneinfo.ZoneInfo( WORKING_ZONE )
    cursor = start.astimezone( zone )
    stop   = end.astimezone( zone )
    total  = 0.0
    while cursor < stop:
        midnight    = datetime.datetime.combine( cursor.date() + datetime.timedelta( days=1 ), datetime.time.min, tzinfo=zone )
        segment_end = min( midnight, stop )
        if cursor.weekday() < FIRST_WEEKEND_DAY: total += ( segment_end.astimezone( datetime.timezone.utc ) - cursor.astimezone( datetime.timezone.utc ) ).total_seconds()
        cursor = segment_end
    return total


def working_days( start, end ):
    """Return working_seconds as days of 24 hours."""
    return working_seconds( start, end ) / SECONDS_PER_DAY


def guard_reached( start, end ):
    """Say whether a pilot has used up its GUARD_WORKING_DAYS between start and end."""
    return working_days( start, end ) >= GUARD_WORKING_DAYS


def parse_stats( text ):
    """
    Read one line of `docker stats --no-stream --format "{{.MemUsage}}|{{.CPUPerc}}"`.

    Requires:
        - text is that line, such as "123.4MiB / 31.3GiB|2.50%"

    Ensures:
        - returns { mem_bytes, cpu_percent }, the memory in use and the CPU share since the container started its last interval
        - returns None for a line that does not have that shape or a unit that is not known, so a figure is never guessed
    """
    found = STATS_PATTERN.match( text )
    if found is None or found.group( 2 ) not in UNIT_BYTES: return None
    return { "mem_bytes" : int( float( found.group( 1 ) ) * UNIT_BYTES[ found.group( 2 ) ] ), "cpu_percent" : float( found.group( 3 ) ) }


def peak_agents( events ):
    """
    Find the most subagent calls one assistant message made at once.

    Requires:
        - events are the JSON objects of a stream-json output

    Ensures:
        - counts tool calls named in AGENT_TOOLS, per assistant message, and returns the largest count (0 when there are none)
        - the tool names are an assumption about the CLI's stream until a live pilot has shown them
    """
    peak = 0
    for event in events:
        content = event.get( "message", {} ).get( "content", [] ) if event.get( "type" ) == "assistant" else []
        if not isinstance( content, list ): continue
        peak = max( peak, sum( 1 for block in content if isinstance( block, dict ) and block.get( "type" ) == "tool_use" and block.get( "name" ) in AGENT_TOOLS ) )
    return peak


class Meter:
    """Reads what the harness's own commands have used so far."""

    def read( self ):
        """
        Read the CPU and the largest process of every command the harness has finished.

        Ensures:
            - returns { cpu_seconds, peak_rss_bytes } from the finished child processes and their finished descendants
            - cpu_seconds only grows; peak_rss_bytes is the largest one process, not a sum (Linux counts kilobytes)
        """
        used = resource.getrusage( resource.RUSAGE_CHILDREN )
        return { "cpu_seconds" : used.ru_utime + used.ru_stime, "peak_rss_bytes" : used.ru_maxrss * KB_TO_BYTES }


class Clock:
    """The wall clock of a run."""

    def now( self ):
        """Return the current moment as a timezone-aware UTC datetime."""
        return datetime.datetime.now( datetime.timezone.utc )
