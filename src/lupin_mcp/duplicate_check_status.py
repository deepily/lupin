"""
The status of the duplicate check's backlog, worked out from its run history.

Everything here is a pure function of the history lines (runs.jsonl) and the clock.
So the status page, the note after a run and the slip alert all read the same numbers.
A number the history cannot give is None, never a made-up zero.
"""
import datetime
import html
import json
import math
import os
import pathlib
import statistics

from cosa.repo import code_health_settings as chs
from cosa.rest import job_cron
from cosa.rest import job_registry
from lupin_mcp import duplicate_check_history as history

JOB             = "duplicate-check"
REPO            = "lupin"
UNIT            = "functions"
CRON_JOB_TAG    = "duplicate-check-daily"   # the marker comment the installer ends each crontab line with (duplicate_check_daily.CRON_TAG, without its "# ")
GRACE_MINUTES   = 30                    # a run is late when it has not started this long after its slot
SUMMARY_SCHEMA  = "job-summary/1"       # section 1.1 of the fleet's background job reporting format
SUMMARY_FILE    = "job-summary.json"
OWN_MARK        = "prefix:epic:dupcheck-"                  # filing.KEY_PREFIX: every row the filer mints has a correlation_key starting with it; the creator is "<persona> (duplicate-check-daily)"
POINTS          = 14
RECENT_ATTEMPTS = 7
INFLOW_DAYS     = 7                     # days of history the arrival rate averages over
DRAIN_DAYS      = 3                     # days of history the clearing rate averages over
SLIP_DAYS       = 1                     # a projected zero date this many days later than the last one is a slip
RECENT_RUNS     = 12                    # runs shown on the page
HEALTHY         = "healthy"
FALLING_BEHIND  = "falling_behind"
FAILING         = "failing"
SILENT          = "silent"
OUTCOME         = { "ok": "clean", "carried": "carried", "failed": "failed", "skipped": "skipped" }
SHAPE_TRIGGER   = { "cron": "cron", "hand": "hand", "reboot": "boot" }
TOKEN_FIELDS    = ( "input_tokens", "output_tokens", "cache_creation_tokens", "cache_read_tokens" )


def _when( line ):
    """Ensures: returns the line's start as a timezone-aware datetime."""
    return datetime.datetime.fromisoformat( line[ "started_at" ] )


def _day( line ):
    """Ensures: returns the line's start date as an ISO string, in the zone it was written in."""
    return line[ "started_at" ][ :10 ]


def measured_daily( lines ):
    """Ensures: returns the daily-mode lines whose carried count is a measurement, oldest first."""
    return [ l for l in lines if l.get( "mode" ) == history.MODE_DAILY and l.get( "status" ) in history.MEASURED and l.get( "carried" ) is not None ]


def baseline_remaining( lines ):
    """Ensures: returns the newest measured baseline carried count, or None when there is none."""
    found = [ l for l in lines if l.get( "mode" ) == history.MODE_BASELINE and l.get( "status" ) in history.MEASURED and l.get( "carried" ) is not None ]
    return found[ -1 ][ "carried" ] if found else None


def inflow_per_day( lines, now, days=INFLOW_DAYS ):
    """
    Estimate how many new definitions arrive a day.

    Requires:
        - lines are history lines in time order; now is a timezone-aware datetime
    Ensures:
        - an arrival is a measured daily run's owed count less the carried count of the measured daily run before it, never below 0
        - returns the arrivals of each calendar day within the last days days, averaged over the days that have one, rounded; None when no pair of runs gives one
        - a run without an owed count, as every run before the field existed, gives no arrival
    """
    since  = ( now - datetime.timedelta( days=days ) ).isoformat()[ :10 ]
    daily  = measured_daily( lines )
    per    = {}
    for a, b in zip( daily, daily[ 1: ] ):
        if b.get( "owed" ) is None or _day( b ) < since: continue
        per[ _day( b ) ] = per.get( _day( b ), 0 ) + max( 0, b[ "owed" ] - a[ "carried" ] )
    return round( sum( per.values() ) / len( per ) ) if per else None


def judged_per_day( lines, now, days=DRAIN_DAYS ):
    """
    Estimate how many definitions the runs clear a day.

    Ensures:
        - sums judged over every run, daily and baseline, of each calendar day within the last days days, and averages over the days that have a run, rounded
        - returns None when there is no such run
    """
    since = ( now - datetime.timedelta( days=days ) ).isoformat()[ :10 ]
    per   = {}
    for l in lines:
        if l.get( "judged" ) is None or _day( l ) < since: continue
        per[ _day( l ) ] = per.get( _day( l ), 0 ) + l[ "judged" ]
    return round( sum( per.values() ) / len( per ) ) if per else None


def projected_zero( backlog, drain, inflow, today ):
    """
    Say when the backlog reaches zero at the present rates.

    Requires:
        - backlog is the carried count plus the baseline remainder, or None; drain and inflow are definitions a day, or None; today is a date
    Ensures:
        - returns today's date as an ISO string when the backlog is 0
        - returns None when the backlog or the clearing rate is unknown, or when the net clearing rate (drain less inflow, with an unknown inflow taken as 0) is not above 0
        - otherwise returns the ISO date that many whole days ahead
    """
    if backlog == 0: return today.isoformat()
    if backlog is None or drain is None: return None
    net = drain - ( inflow or 0 )
    if net <= 0: return None
    return ( today + datetime.timedelta( days=math.ceil( backlog / net ) ) ).isoformat()


def slipped( before, after, days=SLIP_DAYS ):
    """
    Say whether the projected zero date moved later.

    Ensures:
        - returns False when before is None, as there was nothing to slip from
        - returns True when after is None (the backlog no longer reaches zero) or lies more than days later than before
    """
    if before is None: return False
    if after is None: return True
    return ( datetime.date.fromisoformat( after ) - datetime.date.fromisoformat( before ) ).days > days


def installed_crons( crontab_text ):
    """
    Read the job's five-field schedules off the installed crontab.

    Requires:
        - crontab_text is the text of crontab -l, or None when it could not be read
    Ensures:
        - returns the cron expressions of the lines that end with this job's tag, in crontab order
        - an @reboot line adds none, since its time is not on a clock
        - returns [] for None, for a crontab with no tagged line, and for one with only @reboot lines
    """
    found = [] if crontab_text is None else job_registry.crontab_schedule( crontab_text, CRON_JOB_TAG )
    return [ entry[ "cron" ] for entry in found if "cron" in entry ]


def expected_by( last, now, crons ):
    """
    Name the time by which the next run should have started.

    Requires:
        - last is the datetime of the newest run, or None; now is timezone-aware
        - crons are the installed five-field schedules, installed_crons' answer
    Ensures:
        - returns None when crons is empty or none fires within a month, because the schedule is then unknown and no lateness can be worked out
        - otherwise the earliest firing of any cron after the newest run (or after now with no run), plus GRACE_MINUTES
    """
    base  = ( last or now ).astimezone( now.tzinfo )
    slots = [ t for t in ( job_cron.cron_next( c, base ) for c in crons ) if t is not None ]
    return ( min( slots ) + datetime.timedelta( minutes=GRACE_MINUTES ) ).isoformat() if slots else None


def per_day_usage( lines ):
    """
    Total the runs' judge calls and tokens by calendar day.

    Ensures:
        - returns [ { day, runs, judge_calls, input_tokens, output_tokens, cache_creation_tokens, cache_read_tokens, cost_usd } ], oldest day first
        - a number a run did not record adds nothing; the sum is None for a day on which no run recorded it
    """
    days = {}
    for l in lines:
        row = days.setdefault( _day( l ), { "day": _day( l ), "runs": 0, "judge_calls": None, "cost_usd": None, **{ f: None for f in TOKEN_FIELDS } } )
        row[ "runs" ] += 1
        for key in ( "judge_calls", "cost_usd", *TOKEN_FIELDS ):
            if l.get( key ) is not None: row[ key ] = ( row[ key ] or 0 ) + l[ key ]
    return [ days[ d ] for d in sorted( days ) ]


def health_of( lines, backlog, drain, inflow, now, crons ):
    """
    Judge the job's health.

    Ensures:
        - silent when there is no run, or none has started by expected_by of the newest run
        - with no known schedule (crons empty) a run's lateness is not judged, so the health is never silent for a late run
        - failing when the newest run failed, falling_behind when the backlog is above 0 and the net clearing rate is not above 0, else healthy
    """
    if not lines: return SILENT
    last = lines[ -1 ]
    due  = expected_by( _when( last ), now, crons )
    if due is not None and datetime.datetime.fromisoformat( due ) < now: return SILENT
    if last[ "status" ] == "failed": return FAILING
    if backlog and drain is not None and drain - ( inflow or 0 ) <= 0: return FALLING_BEHIND
    return HEALTHY


def snapshot( folder, now, crontab_text=None ):
    """
    Work out everything the page, the note and the accordion show.

    Requires:
        - folder holds runs.jsonl; now is a timezone-aware datetime in the zone the crontab's hours are written in
        - crontab_text is the installed crontab's text, or None when it could not be read
    Ensures:
        - returns { job, as_of, backlog { carried, baseline_remaining, total, inflow_per_day }, drain { judged_per_day }, projected_zero, health, schedule { cron, verified }, runs, days, summary, unreadable_lines }
        - schedule.cron is installed_crons' answer and schedule.verified is False when it is empty, so the page says the schedule is unknown rather than showing one that is not installed
        - runs are the last RECENT_RUNS lines, newest first, each with its drained count (judged), calls, tokens, calls an hour and the branch it judged
        - summary is job_summary's record, the fleet's job-summary/1 format
    """
    read    = history.read_history( folder )
    lines   = read[ "lines" ]
    daily   = measured_daily( lines )
    carried = daily[ -1 ][ "carried" ] if daily else None
    remains = baseline_remaining( lines )
    total   = None if carried is None and remains is None else ( carried or 0 ) + ( remains or 0 )
    inflow  = inflow_per_day( lines, now )
    drain   = judged_per_day( lines, now )
    zero    = projected_zero( total, drain, inflow, now.date() )
    crons   = installed_crons( crontab_text )
    health  = health_of( lines, total, drain, inflow, now, crons )
    last    = lines[ -1 ] if lines else None
    runs    = [ { **{ k: l.get( k ) for k in ( "started_at", "mode", "trigger", "status", "branch", "owed", "judged", "carried", "judge_calls", "elapsed_seconds", "calls_per_hour",
                                              "rate_limited", "cost_usd", *TOKEN_FIELDS ) }, "failure": l.get( "failure" ) } for l in reversed( lines[ -RECENT_RUNS: ] ) ]
    return { "job": JOB, "as_of": now.isoformat(), "backlog": { "carried": carried, "baseline_remaining": remains, "total": total, "inflow_per_day": inflow },
             "drain": { "judged_per_day": drain }, "projected_zero": zero, "health": health, "schedule": { "cron": crons, "verified": bool( crons ) }, "runs": runs, "days": per_day_usage( lines )[ -INFLOW_DAYS: ], "summary": job_summary( lines, now ),
             "unreadable_lines": read[ "bad" ] }


def _evidence( lines, i ):
    """Ensures: names ledger line i (0-based) as the summary's evidence field does."""
    return f"{chs.DATA_SUBDIR}/{history.FOLDER}/{history.RUNS_FILE}:{i + 1}"


def _points( key, finished ):
    """Ensures: returns the last 14 { at, key } entries the finished lines measured."""
    return [ { "at": at, key: value } for at, value in finished if value is not None ][ -POINTS: ]


def job_summary( lines, now, rows=None ):
    """
    Build the job's summary record in the fleet's job-summary/1 format.

    Requires:
        - lines are history lines in time order; now is a timezone-aware datetime
    Ensures:
        - returns the record of section 1.1 of the reporting format, with None for what the ledger cannot give, never an omitted key and never a made-up zero
        - last_attempt is the newest line; outcome maps ok to clean; stage and failure are the two halves of the failure text before and after its first ": "; a boot trigger is named boot
        - last_finished is the newest line that finished (clean or carried); consecutive_failures counts failed lines after it
        - scan_debt.count is the last measured daily carried count, never_checked the baseline remainder (None until a baseline run measured it), arrived_last_interval the owed count of the newest measured daily run less the carried count of the one before
        - rows, when given, is { found, open } counted in the store by the created_by mark; the summary then holds found_by_mark, open_by_mark and gap, the ledger's filed total less found
        - without rows those three are None, and a gap is never reported as 0 when the store was not read
        - fix_debt.unfiled and opened_in_run are the newest finished line's queued_for_retry and filed counts, own_mark the correlation_key prefix every row the filer mints starts with; open and closed counts are the reader's, from the store
        - target is None for this job, fix_debt.kind is rows; there is no health field, the reader computes it
        - last_attempt also names the mode; recent holds the last seven attempts as { at, outcome, mode }, oldest first; scan_debt.points are { at, count, drained }
    """
    last      = lines[ -1 ] if lines else None
    finished  = [ ( i, l ) for i, l in enumerate( lines ) if l[ "status" ] in history.MEASURED ]
    fin       = finished[ -1 ] if finished else None
    after     = lines[ fin[ 0 ] + 1: ] if fin else lines
    daily     = measured_daily( lines )
    stage, _, failure = ( last[ "failure" ] or "" ).partition( ": " ) if last else ( "", "", "" )       # "branch_guard: stale_branch" is stage and failure
    ended     = lambda l: ( _when( l ) + datetime.timedelta( seconds=l[ "elapsed_seconds" ] or 0 ) ).isoformat() if l.get( "elapsed_seconds" ) is not None else None
    arrived   = max( 0, daily[ -1 ][ "owed" ] - daily[ -2 ][ "carried" ] ) if len( daily ) > 1 and daily[ -1 ].get( "owed" ) is not None else None
    opened    = 0
    fix_pts   = []
    for _, l in finished:
        opened += l.get( "filed" ) or 0
        fix_pts.append( ( l[ "started_at" ], opened ) )
    return { "schema": SUMMARY_SCHEMA, "job": JOB, "target": None, "written_at": now.isoformat(),
             "last_attempt": None if last is None else { "started_at": last[ "started_at" ], "finished_at": ended( last ), "trigger": SHAPE_TRIGGER.get( last[ "trigger" ], last[ "trigger" ] ),
                                                         "outcome": OUTCOME.get( last[ "status" ], last[ "status" ] ), "stage": stage or None, "failure": failure or None,
                                                         "evidence": _evidence( lines, len( lines ) - 1 ), "mode": last[ "mode" ] },
             "last_finished": None if fin is None else { "started_at": fin[ 1 ][ "started_at" ], "outcome": OUTCOME[ fin[ 1 ][ "status" ] ], "evidence": _evidence( lines, fin[ 0 ] ) },
             "consecutive_failures": sum( 1 for l in after if l[ "status" ] == "failed" ),
             "work_found_last_run": fin[ 1 ][ "findings" ] if fin else None,
             "scan_debt": { "unit": "definitions", "count": daily[ -1 ][ "carried" ] if daily else None, "never_checked": baseline_remaining( lines ),
                            "drained_last_run": fin[ 1 ][ "judged" ] if fin else None, "arrived_last_interval": arrived, "as_of": ended( fin[ 1 ] ) or fin[ 1 ][ "started_at" ] if fin else None,
                            "freshness": None, "points": [ { "at": l[ "started_at" ], "count": l[ "carried" ], "drained": l[ "judged" ] } for l in daily ][ -POINTS: ] },
             "fix_debt": { "unit": "rows", "kind": "rows", "own_mark": OWN_MARK, "unfiled": fin[ 1 ][ "queued_for_retry" ] if fin else None, "opened_in_run": fin[ 1 ][ "filed" ] if fin else None,
                           "filed_in_ledger": opened, "found_by_mark": rows[ "found" ] if rows else None, "open_by_mark": rows[ "open" ] if rows else None, "open_reported": rows[ "open" ] if rows else None,
                           "gap": opened - rows[ "found" ] if rows else None, "points": _points( "opened_total", fix_pts ) },
             "recent": [ { "at": l[ "started_at" ], "outcome": OUTCOME.get( l[ "status" ], l[ "status" ] ), "mode": l[ "mode" ] } for l in lines[ -RECENT_ATTEMPTS: ] ] }


def write_job_summary( folder, now, rows=None ):
    """
    Write the summary record beside the ledger, whole, by rename.

    Ensures:
        - returns the path of <folder>/job-summary.json, holding job_summary of the folder's history
        - a reader sees the old file or the new one, never half of either
    """
    path = pathlib.Path( folder ) / SUMMARY_FILE
    tmp  = path.with_name( f".{SUMMARY_FILE}.{os.getpid()}.tmp" )
    tmp.write_text( json.dumps( job_summary( history.read_lines( folder ), now, rows ), indent=2, sort_keys=True ), encoding="utf-8" )
    os.replace( tmp, path )
    return path


def note_of( line, snap ):
    """
    Say in one short sentence what a run did.

    Requires:
        - line is the run's history line; snap is snapshot's answer taken after it
    Ensures:
        - returns None for a quiet run: one that judged nothing, made no call and left no backlog
        - otherwise returns a sentence naming the calls, the definitions judged, the backlog left and the projected zero date
    """
    total = snap[ "backlog" ][ "total" ]
    if not line.get( "judge_calls" ) and not total and line[ "status" ] != "failed": return None
    left  = "unknown" if total is None else f"{total:,}"
    zero  = snap[ "projected_zero" ] or "not at the present rates"
    return f"Duplicate check {line['mode']} run: {line.get( 'judged' ) or 0} judged in {line.get( 'judge_calls' ) or 0} calls; {left} left; zero by {zero}."


def number( value, spec="," ):
    """Ensures: returns the value formatted with spec, or a dash for None."""
    return "-" if value is None else format( value, spec )


def render_html( snap ):
    """
    Lay the snapshot out as a small self-contained page.

    Ensures:
        - returns one HTML document with no script and no outside file: backlog by kind, the projected zero date, the recent runs, the tokens by day and the installed schedule or that it is unknown
        - every value from the history is escaped
    """
    b, esc = snap[ "backlog" ], html.escape
    head   = "".join( f"<th>{esc( h )}</th>" for h in ( "started", "mode", "trigger", "status", "branch", "owed", "judged", "carried", "calls", "secs", "calls/h", "limited", "in", "out", "cache write", "cache read" ) )
    runs   = "".join( "<tr>" + "".join( f"<td>{esc( str( v ) )}</td>" for v in ( ( r[ "started_at" ] or "-" )[ :16 ].replace( "T", " " ), r[ "mode" ], r[ "trigger" ], r[ "failure" ] or r[ "status" ], r[ "branch" ] or "-",
                      number( r[ "owed" ] ), number( r[ "judged" ] ), number( r[ "carried" ] ), number( r[ "judge_calls" ] ), number( r[ "elapsed_seconds" ], ".0f" ), number( r[ "calls_per_hour" ], ".0f" ),
                      number( r[ "rate_limited" ] ), number( r[ "input_tokens" ] ), number( r[ "output_tokens" ] ), number( r[ "cache_creation_tokens" ] ), number( r[ "cache_read_tokens" ] ) ) ) + "</tr>" for r in snap[ "runs" ] )
    days   = "".join( "<tr>" + "".join( f"<td>{esc( str( v ) )}</td>" for v in ( d[ "day" ], d[ "runs" ], number( d[ "judge_calls" ] ), number( d[ "input_tokens" ] ), number( d[ "output_tokens" ] ),
                      number( d[ "cache_creation_tokens" ] ), number( d[ "cache_read_tokens" ] ), number( d[ "cost_usd" ], ".2f" ) ) ) + "</tr>" for d in reversed( snap[ "days" ] ) )
    return ( "<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"utf-8\"><title>Duplicate check status</title>"
             "<style>body{font-family:sans-serif;margin:2rem}table{border-collapse:collapse;margin:1rem 0}td,th{border:1px solid #ccc;padding:.25rem .6rem;text-align:right}"
             ".big{font-size:1.4rem}</style></head><body>"
             f"<h1>Duplicate check <small>({esc( snap[ 'health' ] )})</small></h1><p class=\"big\">Projected zero: <b>{esc( snap[ 'projected_zero' ] or 'not at the present rates' )}</b></p>"
             f"<table><tr><th>carried</th><th>baseline remaining</th><th>total</th><th>inflow / day</th><th>cleared / day</th></tr><tr><td>{number( b[ 'carried' ] )}</td><td>{number( b[ 'baseline_remaining' ] )}</td>"
             f"<td>{number( b[ 'total' ] )}</td><td>{number( b[ 'inflow_per_day' ] )}</td><td>{number( snap[ 'drain' ][ 'judged_per_day' ] )}</td></tr></table>"
             f"<h2>Recent runs</h2><table><tr>{head}</tr>{runs}</table>"
             f"<h2>By day</h2><table><tr><th>day</th><th>runs</th><th>calls</th><th>in</th><th>out</th><th>cache write</th><th>cache read</th><th>notional USD</th></tr>{days}</table>"
             f"<p>Schedule read from the crontab: {esc( ', '.join( snap[ 'schedule' ][ 'cron' ] ) if snap[ 'schedule' ][ 'verified' ] else 'unknown, so lateness is not judged' )}.</p>"
             f"<p>As of {esc( snap[ 'as_of' ] )}. Tokens are what the Claude Code SDK reported; USD is its list-price figure, not a charge.</p></body></html>" )


def folder_of( root ):
    """Ensures: returns the folder the runs are recorded in, under the given project root."""
    return chs.data_dir( root ) / history.FOLDER


def median_seconds_per_call( lines, floor=20, last=5 ):
    """
    Measure how long a judge call takes on average over the latest sizeable runs.

    Ensures:
        - uses the last `last` lines that made at least `floor` calls and recorded their elapsed time, failed runs excluded
        - returns the median of elapsed_seconds / judge_calls, or None when no line qualifies
    """
    rates = [ l[ "elapsed_seconds" ] / l[ "judge_calls" ] for l in lines if l.get( "status" ) != "failed" and ( l.get( "judge_calls" ) or 0 ) >= floor and l.get( "elapsed_seconds" ) ][ -last: ]
    return statistics.median( rates ) if rates else None
