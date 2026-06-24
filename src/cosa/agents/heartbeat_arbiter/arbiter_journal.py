#!/usr/bin/env python3
"""
Arbiter journal line builder — the ONE owner of the structured-log line shape.

Item A of `src/rnd/v0.1.8/2026.06.11-arbiter-outreach-delivery-receipts-and-
local-timestamps.md`: Rick's verbatim — the ISO-UTC `ts` is "impenetrable"; every
arbiter journal line now ALSO carries a human-parsable `ts_local` field rendered
in a deploy-tunable timezone (INI key `arbiter journal local timezone`, default
America/New_York), format `2026-06-11-at-17-28-46-(EDT)`.

Before this module the line shape was copy-pasted SIX times (`_default_log_fn`
in arbiter_live_notify / health_watcher / fleet_arbiter_loop /
context_pressure_writer / arbiter_job + the app wiring default) — one-name-rule
violation that ALSO produced the §1.4 loop-label misattribution (every
fleet-arbiter event journaled as `loop: health_watcher` because assemble_app
passed the health watcher's default everywhere). Those sites now delegate here;
`make_log_fn( loop=... )` stamps the TRUE emitting loop per wiring.

Degrade-safe by the observer invariant: an invalid/unknown timezone must never
take the watcher down — it falls back to UTC rendering and the FALLBACK ITSELF
is journaled loudly once at build time (`journal_tz_invalid`).
"""
import datetime
import json
from typing import Any, Callable, Optional
from zoneinfo import ZoneInfo

# Rick's ratified human format: "2026-06-11-at-17-28-46-(EDT)"
TS_LOCAL_FORMAT     = "%Y-%m-%d-at-%H-%M-%S-(%Z)"
# Rick's ratified OUTREACH-stamp format (2026-06-24): "2026.06.24 at 11:47:57"
# — the human-facing leading prefix on every arbiter shoulder-tap/outreach message.
# Distinct from TS_LOCAL_FORMAT (dashes + tz suffix, machine-greppable journal field);
# this one is the readable inline stamp Rick reads in his DMs.
OUTREACH_TS_FORMAT  = "%Y.%m.%d at %H:%M:%S"
DEFAULT_TZ_NAME     = "America/New_York"
DEFAULT_SERVICE     = "lupin-arbiter-app"

# Item B (§3.1/§3.5): live-channel outcomes that count as DELIVERED to Rick —
# the /api/notify body `status` values meaning the notification reached a
# connected surface. ONE owner (this module owns the journal/outcome
# vocabulary); arbiter_live_notify (dedup recording) and arbiter_job (Rick-side
# receipts + re-announce resolution) both import it from here.
DELIVERED_OUTCOMES  = frozenset( { "queued", "delivered_via_listener" } )


def resolve_tz( tz_name: Optional[ str ] ):
    """
    Resolve a tz-database name to a ZoneInfo, degrade-safe.

    Requires:
        - tz_name is a string tz-database name (e.g. "America/New_York") or None

    Ensures:
        - returns ( ZoneInfo, None ) for a valid name (None → DEFAULT_TZ_NAME)
        - returns ( ZoneInfo("UTC"), <error string> ) for an invalid/unknown
          name — the caller journals the error ONCE; rendering falls back to UTC
        - never raises
    """
    name = tz_name if tz_name else DEFAULT_TZ_NAME
    try:
        return ZoneInfo( name ), None
    except Exception as e:
        return ZoneInfo( "UTC" ), f"unknown timezone {name!r}: {e}"


def format_ts_local( dt: datetime.datetime, tz: Any ) -> str:
    """
    Render an aware datetime in Rick's human format for the given tzinfo.

    Requires:
        - dt is an AWARE datetime
        - tz is a tzinfo (ZoneInfo)

    Ensures:
        - returns the same instant as `dt` rendered "%Y-%m-%d-at-%H-%M-%S-(%Z)"
          (e.g. "2026-06-11-at-17-28-46-(EDT)"; DST handled by the tz database —
          the same wall format yields "(EST)" in January)
    """
    return dt.astimezone( tz ).strftime( TS_LOCAL_FORMAT )


def format_outreach_ts( dt: datetime.datetime, tz: Any ) -> str:
    """
    Render an aware datetime as Rick's outreach stamp "YYYY.MM.DD at HH:MM:SS"
    (2026-06-24) in the given tz — the leading prefix on arbiter outreach messages.

    Requires:
        - dt is an AWARE datetime
        - tz is a tzinfo (ZoneInfo) — REUSE resolve_tz to obtain it (the INI key
          `arbiter journal local timezone`); this function builds NO tz infra

    Ensures:
        - returns the same instant as `dt` rendered "%Y.%m.%d at %H:%M:%S"
          (e.g. "2026.06.24 at 11:47:57"); DST handled by the tz database
    """
    return dt.astimezone( tz ).strftime( OUTREACH_TS_FORMAT )


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
        - loop (if given) names the TRUE emitting loop (§1.4 fix)
        - tz_name (if given) is a tz-database name; invalid → UTC fallback
        - now_fn (if given) is a 0-arg callable returning an aware UTC datetime
        - emit_fn (if given) is a 1-arg callable taking the serialized line
          (test seam; default prints flushed to stdout → systemd journal)

    Ensures:
        - returns log_fn( event, **fields ) printing ONE JSON object:
          { ts, ts_local, service, [loop,] event, **fields }
        - `ts` stays the machine-sortable ISO-8601 UTC instant (unchanged
          contract); `ts_local` is the SAME instant in the resolved tz,
          format "2026-06-11-at-17-28-46-(EDT)"
        - an invalid tz_name journals ONE `journal_tz_invalid` line at build
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
