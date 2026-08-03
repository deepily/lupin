#!/usr/bin/env python3
"""
Unit tests for the central EDT timestamp formatter (cosa.utils.edt_timestamp) —
the ONE owner of Rick's bracketed outreach prefix "[YYYY.MM.DD at HH:MM:SS]",
shared by the arbiter ping path AND the REST DM chokepoint (2026-06-24).

Covers (100% L/B/F): resolve_tz valid/default/invalid; format_outreach_ts EDT
(summer) + EST (winter, DST); format_edt_timestamp bracketed shape, explicit tz,
invalid-tz UTC fallback, dt=None→now; the drift-lock that the bracketed DM prefix
is VISUALLY IDENTICAL to the arbiter caller's f"[{inner}] " wrap; quick_smoke_test.

Venue: :7999-eligible / local — pure, no IO.
Design: src/rnd/v0.1.9/2026.06.24-central-edt-timestamp-on-all-dms.md
"""
import datetime
import os
import re
import sys

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.utils.edt_timestamp import (
    DEFAULT_TZ_NAME, OUTREACH_TS_FORMAT,
    format_edt_timestamp, format_outreach_ts, is_already_stamped, quick_smoke_test, resolve_tz,
)


JUNE = datetime.datetime( 2026, 6, 11, 21, 28, 46, tzinfo=datetime.timezone.utc )   # → 17:28:46 EDT
JAN  = datetime.datetime( 2026, 1, 11, 21, 28, 46, tzinfo=datetime.timezone.utc )   # → 16:28:46 EST

_PREFIX_RE = re.compile( r"^\[\d{4}\.\d{2}\.\d{2} at \d{2}:\d{2}:\d{2}\]$" )


# ── module constants ─────────────────────────────────────────────────────────

def test_constants_are_ricks_ratified_shape():
    assert OUTREACH_TS_FORMAT == "%Y.%m.%d at %H:%M:%S"
    assert DEFAULT_TZ_NAME    == "America/New_York"


# ── resolve_tz: valid / default / invalid ────────────────────────────────────

def test_resolve_tz_valid_name():
    tz, err = resolve_tz( "America/New_York" )
    assert err is None
    assert format_outreach_ts( JUNE, tz ) == "2026.06.11 at 17:28:46"


def test_resolve_tz_none_uses_default():
    tz, err = resolve_tz( None )
    assert err is None
    assert format_outreach_ts( JUNE, tz ) == "2026.06.11 at 17:28:46"   # EDT default


def test_resolve_tz_invalid_falls_back_to_utc_with_error():
    tz, err = resolve_tz( "Not/AZone" )
    assert err is not None and "Not/AZone" in err
    assert format_outreach_ts( JUNE, tz ) == "2026.06.11 at 21:28:46"   # UTC (no shift)


# ── format_outreach_ts: inner string, DST aware ──────────────────────────────

def test_format_outreach_ts_summer_is_edt():
    tz, _ = resolve_tz( "America/New_York" )
    assert format_outreach_ts( JUNE, tz ) == "2026.06.11 at 17:28:46"


def test_format_outreach_ts_winter_is_est():
    tz, _ = resolve_tz( "America/New_York" )
    assert format_outreach_ts( JAN, tz ) == "2026.01.11 at 16:28:46"   # EST (UTC-5)


# ── format_edt_timestamp: the bracketed prefix ───────────────────────────────

def test_format_edt_timestamp_bracketed_summer():
    assert format_edt_timestamp( JUNE ) == "[2026.06.11 at 17:28:46]"


def test_format_edt_timestamp_bracketed_winter_explicit_tz():
    assert format_edt_timestamp( JAN, "America/New_York" ) == "[2026.01.11 at 16:28:46]"


def test_format_edt_timestamp_invalid_tz_degrades_to_utc():
    # Degrade-safe: an unknown tz never raises — renders the instant in UTC.
    assert format_edt_timestamp( JUNE, "Not/AZone" ) == "[2026.06.11 at 21:28:46]"


def test_format_edt_timestamp_none_dt_renders_now_in_shape():
    # dt=None → current instant; assert the bracketed SHAPE (not a fixed value).
    prefix = format_edt_timestamp()
    assert _PREFIX_RE.match( prefix )


def test_format_edt_timestamp_drift_lock_matches_arbiter_wrap():
    # The DM-side prefix + " " is VISUALLY IDENTICAL to the arbiter caller's wrap
    # of the SAME instant — locks the two render sites together so they cannot drift.
    tz, _ = resolve_tz( "America/New_York" )
    assert format_edt_timestamp( JUNE ) + " " == f"[{format_outreach_ts( JUNE, tz )}] "


# ── is_already_stamped — DM-chokepoint idempotency guard (bug f49a8b34) ───────

def test_is_already_stamped_true_for_its_own_output():
    # The predicate recognizes EXACTLY what format_edt_timestamp emits as a leading prefix.
    assert is_already_stamped( f"{format_edt_timestamp( JUNE )} maria is blocking bob" ) is True


def test_is_already_stamped_true_with_one_leading_space():
    # Anchored at start, tolerates ONE optional leading space.
    assert is_already_stamped( " [2026.06.11 at 17:28:46] MANAGER-DOWN: bob" ) is True


def test_is_already_stamped_false_for_unstamped_body():
    assert is_already_stamped( "plain text, no stamp" ) is False
    assert is_already_stamped( "" ) is False


def test_is_already_stamped_false_when_stamp_is_mid_string():
    # A stamp must LEAD — one buried mid-body is not a leading double-stamp risk.
    assert is_already_stamped( "re: [2026.06.11 at 17:28:46] earlier" ) is False


def test_is_already_stamped_false_for_two_leading_spaces():
    # Only ONE leading space is tolerated; two means it does not lead cleanly.
    assert is_already_stamped( "  [2026.06.11 at 17:28:46] x" ) is False


def test_is_already_stamped_false_for_wrong_shape():
    # Wrong delimiters / partial stamp → not recognized (won't suppress a real stamp).
    assert is_already_stamped( "[2026-06-11 17:28:46] x" ) is False   # dashes + colon date, no " at "
    assert is_already_stamped( "[2026.06.11 at 17:28] x" )  is False   # missing seconds


def test_is_already_stamped_false_for_non_string():
    assert is_already_stamped( None ) is False
    assert is_already_stamped( 12345 ) is False
    assert is_already_stamped( [ "[2026.06.11 at 17:28:46]" ] ) is False


# ── quick_smoke_test ─────────────────────────────────────────────────────────

def test_quick_smoke_test_passes():
    assert quick_smoke_test() is True
