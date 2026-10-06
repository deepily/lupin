#!/usr/bin/env python3
"""
Arbiter journal line builder: the single owner of the structured-log line shape.

The ISO-UTC `ts` is hard to read, so every journal line also carries a
human-parsable `ts_local` field. It is rendered in a deploy-tunable timezone
(INI key `arbiter journal local timezone`, default America/New_York), in the
format `2026-06-11-at-17-28-46-(EDT)`.

Every emitter delegates here instead of keeping its own copy of the line shape.
Separate copies had drifted: assemble_app passed the health watcher's default
everywhere, so every fleet-arbiter event was journaled as `loop: health_watcher`.
`make_log_fn( loop=... )` stamps the true emitting loop per wiring.

The builder is degrade-safe: an invalid or unknown timezone must never take the
watcher down. It falls back to UTC rendering and journals the fallback loudly
once at build time (`journal_tz_invalid`).
"""
import datetime
import json
from typing import Any, Callable, Optional

# OUTREACH_TS_FORMAT + DEFAULT_TZ_NAME + resolve_tz + format_outreach_ts moved to the
# neutral central module cosa.utils.edt_timestamp (2026-06-24) so the REST DM path can
# reuse Rick's outreach stamp WITHOUT importing from this arbiter package (which would
# be a bad dependency direction). Re-imported here and re-exported UNCHANGED → the
# arbiter ping output stays BYTE-IDENTICAL and existing importers (arbiter_job,
# test_arbiter_journal) keep importing these names from arbiter_journal with no change.
from cosa.utils.edt_timestamp import (
    DEFAULT_TZ_NAME, OUTREACH_TS_FORMAT, format_outreach_ts, resolve_tz,
)

# Rick's ratified human format: "2026-06-11-at-17-28-46-(EDT)"
TS_LOCAL_FORMAT     = "%Y-%m-%d-at-%H-%M-%S-(%Z)"
DEFAULT_SERVICE     = "lupin-arbiter-app"

# Item B (§3.1/§3.5): live-channel outcomes that count as DELIVERED to Rick —
# the /api/notify body `status` values meaning the notification reached a
# connected surface. ONE owner (this module owns the journal/outcome
# vocabulary); arbiter_live_notify (dedup recording) and arbiter_job (Rick-side
# receipts + re-announce resolution) both import it from here.
DELIVERED_OUTCOMES  = frozenset( { "queued", "delivered_via_listener" } )


def format_ts_local( dt: datetime.datetime, tz: Any ) -> str:
    """
    Render an aware datetime in the human `ts_local` format for the given tzinfo.

    Requires:
        - dt is an aware datetime
        - tz is a tzinfo (ZoneInfo)

    Ensures:
        - returns the same instant as `dt` rendered "%Y-%m-%d-at-%H-%M-%S-(%Z)"
          (e.g. "2026-06-11-at-17-28-46-(EDT)"; DST is handled by the tz database,
          so the same format yields "(EST)" in January)
    """
    return dt.astimezone( tz ).strftime( TS_LOCAL_FORMAT )


def make_log_fn(
    *,
    service : str                  = DEFAULT_SERVICE,
    loop    : Optional[ str ]      = None,
    tz_name : Optional[ str ]      = None,
    now_fn  : Optional[ Callable ] = None,
    emit_fn : Optional[ Callable ] = None,
) -> Callable:
    """
    Build the canonical structured-log seam: log_fn( event, **fields ).

    Requires:
        - service is a non-empty string
        - loop (if given) names the true emitting loop
        - tz_name (if given) is a tz-database name; invalid → UTC fallback
        - now_fn (if given) is a 0-arg callable returning an aware UTC datetime
        - emit_fn (if given) is a 1-arg callable taking the serialized line
          (test seam; default prints flushed to stdout → systemd journal)

    Ensures:
        - returns log_fn( event, **fields ) printing one JSON object:
          { ts, ts_local, service, [loop,] event, **fields }
        - `ts` stays the machine-sortable ISO-8601 UTC instant (unchanged
          contract); `ts_local` is the same instant in the resolved tz,
          format "2026-06-11-at-17-28-46-(EDT)"
        - an invalid tz_name journals one `journal_tz_invalid` line at build
          time and renders ts_local in UTC thereafter (never raises)
        - non-serializable field values are stringified ( default=str )
    """
    now_fn  = now_fn  if now_fn  is not None else _utcnow
    emit_fn = emit_fn if emit_fn is not None else _print_line
    tz, tz_error = resolve_tz( tz_name )

    def log_fn( event: str, **fields: Any ) -> None:
        now  = now_fn()
        line : dict = {
            "ts"       : now.isoformat(),
            "ts_local" : format_ts_local( now, tz ),
            "service"  : service,
        }
        if loop is not None: line[ "loop" ] = loop
        line[ "event" ] = event
        line.update( fields )
        emit_fn( json.dumps( line, default=str ) )

    if tz_error is not None:
        log_fn( "journal_tz_invalid", error=tz_error, fallback="UTC" )

    return log_fn


def _utcnow() -> datetime.datetime:
    """Ensures: returns the current aware UTC datetime (the wall-clock boundary)."""
    return datetime.datetime.now( datetime.timezone.utc )


def _print_line( serialized: str ) -> None:   # pragma: no cover - literal stdout IO boundary
    """Ensures: prints one flushed line to stdout → the systemd journal."""
    print( serialized, flush=True )


def quick_smoke_test():
    """Self-contained smoke test (no IO). Returns True or raises AssertionError."""
    lines = [ ]
    clock = lambda: datetime.datetime( 2026, 6, 11, 21, 28, 46, tzinfo=datetime.timezone.utc )

    # canonical shape: ts + ts_local + service + loop + event, EDT in June
    log = make_log_fn( loop="fleet_arbiter", tz_name="America/New_York",
                       now_fn=clock, emit_fn=lines.append )
    log( "arbiter_outreach", kind="stall", case=11 )
    line = json.loads( lines[ -1 ] )
    assert line[ "ts" ]       == "2026-06-11T21:28:46+00:00"
    assert line[ "ts_local" ] == "2026-06-11-at-17-28-46-(EDT)"
    assert line[ "service" ]  == "lupin-arbiter-app" and line[ "loop" ] == "fleet_arbiter"
    assert line[ "event" ]    == "arbiter_outreach" and line[ "case" ] == 11

    # DST flip: the same builder renders EST in January
    jan = lambda: datetime.datetime( 2026, 1, 11, 21, 28, 46, tzinfo=datetime.timezone.utc )
    log = make_log_fn( tz_name="America/New_York", now_fn=jan, emit_fn=lines.append )
    log( "tick" )
    assert json.loads( lines[ -1 ] )[ "ts_local" ] == "2026-01-11-at-16-28-46-(EST)"
    assert "loop" not in json.loads( lines[ -1 ] )                      # loop omitted when None

    # invalid tz → UTC fallback + ONE loud journal_tz_invalid at build time
    lines.clear()
    log = make_log_fn( tz_name="Not/AZone", now_fn=clock, emit_fn=lines.append )
    assert json.loads( lines[ 0 ] )[ "event" ] == "journal_tz_invalid"
    log( "tick" )
    assert json.loads( lines[ -1 ] )[ "ts_local" ].endswith( "-(UTC)" )
    return True


if __name__ == "__main__":   # pragma: no cover - manual smoke entrypoint
    ok = quick_smoke_test()
    print( f"arbiter_journal smoke: {'PASS' if ok else 'FAIL'}" )
