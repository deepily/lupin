"""
Health of one background job, by the rules of design section 3.

The inputs are the registry entry, the job's summary, the clock and the machine's boot time.

Nothing here reads a clock, a file or a service. The caller passes `now`, the boot time, the store's row counts,
the age of the run lock and the state of a systemd unit. That is what makes each rule testable with a fake clock. The reader decides
"silent", not the job, because a dead job cannot say so.

States, first true wins: unknown, silent, failing, behind, healthy. Every true rule is also listed as a reason, so a job
that is failing and also growing says both.
"""
import datetime

import cosa.rest.job_cron as jc
from cosa.repo.symindex.vector_status import age_hours
from lupin_mcp.reap_memento import _parse_iso_aware as parse_time

STATE_ORDER = ( "unknown", "silent", "failing", "behind", "healthy" )
FINISHED    = ( "clean", "carried" )
STRIP_MAX   = 14


def grace_of( entry ):
    """
    Read a job's grace as a timedelta.

    Ensures:
        - returns grace_seconds when the entry has it (the interval-job addition), else grace_minutes
    """
    if entry.get( "grace_seconds" ) is not None: return datetime.timedelta( seconds=entry[ "grace_seconds" ] )
    return datetime.timedelta( minutes=entry[ "grace_minutes" ] )


def covered( recent, due, mode, before=None ):
    """
    Say whether some attempt began at or after a due time.

    Requires:
        - recent is a list of { at, outcome, mode } with aware time strings
    Ensures:
        - any outcome counts, a skipped run and a hand run included: the question is "did it run"
        - with before given, only attempts earlier than it count: a later run does not cover an earlier hole
        - an attempt of another mode does not cover a due time of a named mode; an attempt with no mode covers any
    """
    for item in recent:
        at = parse_time( item[ "at" ] )
        if at is not None and at >= due and ( before is None or at < before ) and ( mode is None or item.get( "mode" ) in ( None, mode ) ): return True
    return False


def recents( summary ):
    """
    List the recent attempts of a summary.

    Ensures:
        - returns { at, outcome, mode } entries; a record with none falls back to its last attempt alone
    """
    if summary.get( "recent" ): return list( summary[ "recent" ] )
    a = summary[ "last_attempt" ]
    return [ { "at": a[ "started_at" ], "outcome": a[ "outcome" ], "mode": a.get( "mode" ) } ]


def silence( entry, summary, now, boot_time, lock_age, tune ):
    """
    Apply the "silent" rule.

    Requires:
        - entry is an effective registry entry; summary is a valid record
        - lock_age is the age in seconds of a live run lock, or None when there is none
        - tune carries lock_stale_seconds
    Ensures:
        - returns { silent, machine_off, running, last_due, next_due }
        - silent needs a schedule, a due time at least one grace ago, and no attempt since it
        - a live lock younger than lock_stale_seconds makes the job running, never silent
        - if the machine booted after the due time and the job has an after_boot entry, the job is not silent: the boot catch-up covers it
        - if it booted after the due time and the job has no after_boot entry, silent carries machine_off
    """
    schedule = entry.get( "schedule", [] )
    last     = parse_time( summary[ "last_attempt" ][ "started_at" ] )
    running  = lock_age is not None and lock_age <= tune[ "lock_stale_seconds" ]
    out      = { "silent": False, "machine_off": False, "running": running, "last_due": None, "next_due": None }
    nexts    = [ d for d in ( jc.entry_next_due( e, now, boot_time, last ) for e in schedule ) if d is not None ]
    if nexts: out[ "next_due" ] = min( nexts )
    dues = [ ( d, e ) for e in schedule for d in [ jc.entry_last_due( e, now, boot_time, last ) ] if d is not None ]
    if not dues: return out
    due, chosen = max( dues, key=lambda pair: pair[ 0 ] )
    out[ "last_due" ] = due
    if running or now <= due + grace_of( entry ): return out
    if "every_seconds" not in chosen and covered( recents( summary ), due, chosen.get( "mode" ) ): return out
    offline = boot_time > due
    if offline and any( "after_boot_seconds" in e for e in schedule ): return out
    out[ "silent" ], out[ "machine_off" ] = True, offline
    return out


def window_points( points, now, days ):
    """Ensures: returns the points no older than days, oldest first."""
    cutoff = now - datetime.timedelta( days=days )
    return [ p for p in points if parse_time( p[ "at" ] ) is not None and parse_time( p[ "at" ] ) >= cutoff ]


def scan_grew( points, tune ):
    """
    Test A: the scan debt grew over the window.

    Requires:
        - points are the window's scan points, oldest first
    Ensures:
        - returns ( earliest, latest ) counts when there are two points and the rise is at least growth_min_items and at least growth_min_percent of the earlier count; else None
    """
    if len( points ) < 2: return None
    first, last = points[ 0 ][ "count" ], points[ -1 ][ "count" ]
    if last - first >= tune[ "growth_min_items" ] and last - first >= first * tune[ "growth_min_percent" ] / 100: return first, last
    return None


def no_drain( scan, points ):
    """
    Test B: debts remain and the last two finished runs drained nothing.

    Ensures:
        - returns True only when the count is above zero and both of the last two points say drained 0 (a missing figure is not a zero)
    """
    if not scan[ "count" ] or len( points ) < 2: return False
    return all( p.get( "drained" ) == 0 for p in points[ -2: ] )


def clears_in( points ):
    """
    Say when the scan debt clears at the rate of the window.

    Requires:
        - points are the window's scan points, oldest first
    Ensures:
        - returns { kind: not_enough_runs } with fewer than two points or no time between them
        - { kind: days, days: 0 } when the latest count is 0
        - { kind: never_at_this_rate } when the debt did not fall over the window
        - otherwise { kind: days, days: count / net fall per day }
    """
    if len( points ) < 2: return { "kind": "not_enough_runs", "days": None }
    first, last = points[ 0 ], points[ -1 ]
    span = ( parse_time( last[ "at" ] ) - parse_time( first[ "at" ] ) ).total_seconds() / 86400
    if span <= 0: return { "kind": "not_enough_runs", "days": None }
    if last[ "count" ] == 0: return { "kind": "days", "days": 0.0 }
    net = ( first[ "count" ] - last[ "count" ] ) / span
    if net <= 0: return { "kind": "never_at_this_rate", "days": None }
    return { "kind": "days", "days": round( last[ "count" ] / net, 1 ) }


def freshness_of( fresh, now ):
    """
    Build the freshness block of a refresh job.

    Ensures:
        - returns age_hours computed from built_at at read time, never stored; None when the job gave no block
    """
    if fresh is None: return None
    return { "built_at": fresh.get( "built_at" ), "stale_after_hours": fresh.get( "stale_after_hours" ),
             "age_hours": age_hours( fresh.get( "built_at" ), now ) }


def fix_piling( store ):
    """
    Test C: rows pile up faster than they close.

    Requires:
        - store is { open_now, opened_in_window, closed_in_window, open_at_window_start } or None
    Ensures:
        - returns False when store is None: the test is skipped, and the page says "open rows: not reported"
        - otherwise True iff open_now > 0, rows opened exceed rows closed in the window, and open_now is not below the count at the window's start
    """
    if store is None: return False
    return store[ "open_now" ] > 0 and store[ "opened_in_window" ] > store[ "closed_in_window" ] and store[ "open_now" ] >= store[ "open_at_window_start" ]


def scan_out( scan, now, tune ):
    """
    Turn a stored scan-debt block into the page's block.

    Ensures:
        - points become { at, value }, freshness carries its age, and clears_in is worked out for the window
    """
    pts = window_points( scan[ "points" ], now, tune[ "window_days" ] )
    return { "unit": scan[ "unit" ], "count": scan[ "count" ], "never_checked": scan[ "never_checked" ], "drained_last_run": scan[ "drained_last_run" ],
             "arrived_last_interval": scan[ "arrived_last_interval" ], "as_of": scan[ "as_of" ], "freshness": freshness_of( scan[ "freshness" ], now ),
             "points": [ { "at": p[ "at" ], "value": p[ "count" ] } for p in scan[ "points" ] ], "clears_in": clears_in( pts ) if scan[ "count" ] is not None else None }


def fix_out( fix, store, entry ):
    """
    Turn a stored fix-debt block into the page's block.

    Ensures:
        - open_now and closed_in_window come from the store only, and are null when the store was not asked or failed
    """
    total = fix[ "points" ][ -1 ][ "opened_total" ] if fix[ "points" ] else None
    return { "kind": fix[ "kind" ], "own_mark": fix[ "own_mark" ] or entry.get( "fix_debt_key" ), "unfiled": fix[ "unfiled" ], "filed_total": total,
             "open_now": None if store is None else store[ "open_now" ], "closed_in_window": None if store is None else store[ "closed_in_window" ],
             "open_reported": fix[ "open_reported" ], "points": [ { "at": p[ "at" ], "value": p[ "opened_total" ] } for p in fix[ "points" ] ],
             "store_href": None }


def strip_of( entry, summary, now, tune ):
    """
    Build the strip of recent attempts, with a hole where a cron run was due and absent.

    Requires:
        - summary is a valid record
    Ensures:
        - returns at most STRIP_MAX entries, oldest first, each { at, outcome } with outcome "missed" for a hole
        - holes are only drawn after the oldest recorded attempt, so a job is not blamed for days before it reported
        - a due time inside its grace is not yet a hole
    """
    recent = recents( summary )
    out    = [ { "at": r[ "at" ], "outcome": r[ "outcome" ] } for r in recent ]
    start  = parse_time( recent[ 0 ][ "at" ] )
    for e in entry.get( "schedule", [] ):
        if "cron" not in e: continue
        dues = jc.cron_between( e[ "cron" ], start, now - grace_of( entry ) )
        for due, following in zip( dues, dues[ 1: ] + [ None ] ):
            if not covered( recent, due, e.get( "mode" ), following ): out.append( { "at": due.isoformat(), "outcome": "missed" } )
    out.sort( key=lambda item: item[ "at" ] )
    return out[ -STRIP_MAX: ]


def reasons_for( entry, summary, now, sil, store, tune ):
    """
    List every true rule as a reason.

    Requires:
        - sil is the result of silence(); store is the store's counts or None
    Ensures:
        - returns [ { state, rule, text } ] in the order silent, failing, then behind A to D
    """
    reasons, attempt = [], summary[ "last_attempt" ]
    if sil[ "silent" ]:
        why = " Missed while the machine was off." if sil[ "machine_off" ] else ""
        reasons.append( { "state": "silent", "rule": "silent", "text": f"Due {sil[ 'last_due' ].isoformat( timespec='minutes' )}, nothing since.{why}" } )
    if attempt[ "outcome" ] == "failed":
        done = summary[ "last_finished" ]
        reasons.append( { "state": "failing", "rule": "failing", "text": f"Failed {summary[ 'consecutive_failures' ]} time(s) in a row at {attempt[ 'stage' ] or 'an unnamed stage'}"
                          f"{': ' + attempt[ 'failure' ] if attempt[ 'failure' ] else ''}; last finished {done[ 'started_at' ] if done else 'never reported'}." } )
    scan = summary[ "scan_debt" ] if entry.get( "scan_debt" ) else None
    if scan is not None:
        pts = window_points( scan[ "points" ], now, tune[ "window_days" ] )
        grew = scan_grew( pts, tune )
        if grew: reasons.append( { "state": "behind", "rule": "scan_grew", "text": f"Scan debt grew {grew[ 0 ]} to {grew[ 1 ]} in the last {tune[ 'window_days' ]} days." } )
        if no_drain( scan, pts ): reasons.append( { "state": "behind", "rule": "no_drain", "text": f"{scan[ 'count' ]} left and the last two finished runs drained none." } )
        fresh = freshness_of( scan[ "freshness" ], now )
        if fresh and fresh[ "age_hours" ] is not None and fresh[ "age_hours" ] > fresh[ "stale_after_hours" ]:
            reasons.append( { "state": "behind", "rule": "stale", "text": f"Built {fresh[ 'age_hours' ]} h ago; the limit is {fresh[ 'stale_after_hours' ]} h." } )
    if entry.get( "fix_debt" ) and fix_piling( store ):
        reasons.append( { "state": "behind", "rule": "fix_piling", "text": f"{store[ 'open_now' ]} rows open; {store[ 'opened_in_window' ]} opened and {store[ 'closed_in_window' ]} closed in the window." } )
    return reasons


def assess( entry, summary, now, boot_time, tune, store=None, lock_age=None, unit_state=None, target=None ):
    """
    Compute one job's entry for GET /api/jobs/summary.

    Requires:
        - entry is an effective registry entry; tune holds window_days, growth_min_items, growth_min_percent, lock_stale_seconds
        - summary is a valid job-summary/1 record, or None when missing or unreadable
        - now and boot_time are aware datetimes; store is the store's row counts for the job's own mark, or None
        - unit_state is "active", "inactive", "not-loaded" or None; it matters only for a job with a liveness block
    Ensures:
        - returns the JobEntry dict that src/lupin_app/static/js/multiplexer/jobs/types.ts describes, with targets empty
        - state is computed here and nowhere else; a liveness-only job is healthy when up, silent when down and unknown when its unit is not loaded
    """
    base = { "job": entry[ "job" ], "target": target, "title": entry[ "title" ], "owner": entry[ "owner" ], "audience": entry.get( "audience", [] ),
             "notify_interval_seconds": int( entry[ "notify_interval_minutes" ] * 60 ), "running": False, "unscheduled": not entry.get( "schedule" ) and not entry.get( "liveness" ),
             "machine_was_off": False, "reasons": [], "applies": { "scan_debt": bool( entry.get( "scan_debt" ) ), "fix_debt": bool( entry.get( "fix_debt" ) ) },
             "last_attempt": None, "last_finished": None, "consecutive_failures": None, "work_found_last_run": None, "strip": [], "scan_debt": None, "fix_debt": None,
             "schedule": None, "liveness": None, "evidence": entry.get( "evidence", [] ), "rows": entry.get( "rows", [] ), "detail_link": entry.get( "detail_link" ),
             "unknown_reason": None, "targets": [], "schedule_unverified": bool( entry.get( "schedule_unverified" ) ), "runnable": bool( entry.get( "run" ) ), "state": "unknown" }
    if entry.get( "liveness" ):
        up = { "active": True, "inactive": False }.get( unit_state )
        base[ "liveness" ] = { "kind": entry[ "liveness" ][ "kind" ], "unit": entry[ "liveness" ][ "unit" ], "up": up }
        base[ "running" ] = bool( up )
        if up is None: base[ "unknown_reason" ] = f"unit {entry[ 'liveness' ][ 'unit' ]} is not loaded" if unit_state == "not-loaded" else "liveness unverified: no fresh answer from systemd, the host snapshot or the health endpoint"
        else: base[ "state" ] = "healthy" if up else "silent"
        if up is False: base[ "reasons" ].append( { "state": "silent", "rule": "silent", "text": f"Unit {entry[ 'liveness' ][ 'unit' ]} is not running." } )
        return base
    if summary is None:
        base[ "unknown_reason" ] = "never reported"
        return base
    sil = silence( entry, summary, now, boot_time, lock_age, tune )
    reasons = reasons_for( entry, summary, now, sil, store, tune )
    base.update( {
        "running": sil[ "running" ], "machine_was_off": sil[ "machine_off" ], "reasons": reasons, "last_attempt": summary[ "last_attempt" ],
        "last_finished": summary[ "last_finished" ], "consecutive_failures": summary[ "consecutive_failures" ], "work_found_last_run": summary[ "work_found_last_run" ],
        "strip": strip_of( entry, summary, now, tune ),
        "scan_debt": scan_out( summary[ "scan_debt" ], now, tune ) if entry.get( "scan_debt" ) and summary[ "scan_debt" ] else None,
        "fix_debt": fix_out( summary[ "fix_debt" ], store, entry ) if entry.get( "fix_debt" ) and summary[ "fix_debt" ] else None,
        "schedule": { "entries": [ jc.entry_label( e ) for e in entry.get( "schedule", [] ) ], "last_due": sil[ "last_due" ] and sil[ "last_due" ].isoformat(),
                      "next_due": sil[ "next_due" ] and sil[ "next_due" ].isoformat(), "grace_minutes": entry[ "grace_minutes" ], "grace_seconds": entry.get( "grace_seconds" ) } } )
    base[ "state" ] = next( ( s for s in STATE_ORDER[ 1:4 ] if any( r[ "state" ] == s for r in reasons ) ), "healthy" )
    return base
