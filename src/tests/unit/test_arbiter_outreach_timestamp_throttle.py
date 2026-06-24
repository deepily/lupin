#!/usr/bin/env python3
"""
Arbiter outreach TIMESTAMP (Item B) + per-recipient THROTTLE (Item C) — 2026-06-24.

Item B: every human-facing outreach message carries a leading "[YYYY.MM.DD at
HH:MM:SS]" stamp rendered in the configured local tz (REUSE arbiter_journal.resolve_tz
+ the INI key `arbiter journal local timezone`), derived from the injectable poll clock.

Item C: a per-recipient trailing-window throttle (N msgs / Y min) suppresses ROUTINE
shoulder-taps (blocker ping #4 / manager tap #7) once N have been sent to a recipient
in the window — but NEVER suppresses Rick-bound escalations (the safety carve-out) nor
Rick himself.

Venue: :7999-eligible / local — pure + fully mocked (no server, no real I/O).
"""
import datetime
import os
import sys

import pytest

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.agents.heartbeat_arbiter.arbiter_job import ArbiterConsumerJob


# 16:47:57 UTC on 2026-06-24 → 12:47:57 America/New_York (EDT, summer DST UTC-4)
NOW = datetime.datetime( 2026, 6, 24, 16, 47, 57, tzinfo=datetime.timezone.utc )


class _GW:
    def __init__( self ):
        self.sent, self.posts = [ ], [ ]
    def who( self, retention_hours=24 ): return [ ]
    def send_to( self, r, b, metadata=None ): self.sent.append( ( r, b ) )
    def post( self, t, b ): self.posts.append( ( t, b ) )
    def read( self, topic, since=None, limit=50 ): return [ ]


class _Log:
    def __init__( self ): self.events = [ ]
    def __call__( self, event, **fields ): self.events.append( ( event, fields ) )
    def of( self, name ): return [ f for e, f in self.events if e == name ]


class _FixedClock:
    def __init__( self, t=NOW ): self.t = t
    def now_iso( self ): return self.t.isoformat()
    def monotonic( self ): return 0.0
    async def sleep( self, s ): return None


def _job( gw=None, log=None, notify=None, **overrides ):
    cfg = dict(
        commons           = gw or _GW(),
        poll_seconds      = 5,
        manager_recipient = "DeclaredMgr",
        clock             = _FixedClock(),
        log_fn            = log or _Log(),
        notify_fn         = notify or ( lambda *a, **k: None ),
    )
    cfg.update( overrides )
    return ArbiterConsumerJob( **cfg )


# ── Item B: the timestamp stamp ─────────────────────────────────────────────────

def test_stamp_renders_edt_format():
    """_stamp prefixes '[YYYY.MM.DD at HH:MM:SS] ' in the configured tz (default
    America/New_York → EDT), converting the UTC poll instant."""
    job = _job()                                                    # default tz America/New_York
    assert job._stamp( "hello" ) == "[2026.06.24 at 12:47:57] hello"   # 16:47:57 UTC → 12:47:57 EDT


def test_stamp_respects_configured_timezone():
    """A different tz renders the same instant in that tz (UTC here → 16:47:57)."""
    job = _job( local_timezone_name="UTC" )
    assert job._stamp( "x" ) == "[2026.06.24 at 16:47:57] x"


def test_invalid_timezone_journals_once_and_falls_back_to_utc():
    """An invalid tz name → ONE outreach_tz_invalid journal event at construction +
    UTC rendering thereafter (degrade-safe, never crashes — Item B)."""
    log = _Log()
    job = _job( log=log, local_timezone_name="Not/AZone" )
    assert len( log.of( "outreach_tz_invalid" ) ) == 1
    assert job._stamp( "x" ) == "[2026.06.24 at 16:47:57] x"          # UTC fallback


def test_route_stamps_message_and_cc():
    """_route stamps BOTH the primary message and the cc_message (the routed choke)."""
    gw = _GW()
    job = _job( gw=gw )
    job._route( 4, "ping body", blocker="Blk", owning_manager="MgrB", cc_message="cc body" )
    bodies = dict( gw.sent )
    assert bodies[ "Blk" ]  == "[2026.06.24 at 12:47:57] ping body"
    assert bodies[ "MgrB" ] == "[2026.06.24 at 12:47:57] cc body"


def test_rick_bound_message_is_stamped():
    """A Rick-bound advisory (notify) is stamped too."""
    notes = [ ]
    job = _job( notify=notes.append )
    job._route( 1, "infra alert" )
    assert notes == [ "[2026.06.24 at 12:47:57] infra alert" ]


# ── Item C: the per-recipient trailing-window throttle ───────────────────────────

def test_throttle_disabled_by_default_never_suppresses():
    """Default config (max=0/window=0) → throttle DISABLED → every routine tap sent."""
    gw = _GW()
    job = _job( gw=gw )                                             # no throttle config → disabled
    for _ in range( 5 ):
        job._route( 4, "ping", blocker="Blk" )
    assert len( gw.sent ) == 5                                      # all delivered, none suppressed


def test_throttle_suppresses_routine_tap_over_cap():
    """N=2 / Y=10min: the 1st+2nd routine taps to a recipient are sent; the 3rd is
    SUPPRESSED (no send) and journaled throttle_suppressed with the window count +
    the last-sent EDT stamp."""
    gw, log = _GW(), _Log()
    job = _job( gw=gw, log=log,
                outreach_throttle_max_messages=2, outreach_throttle_window_minutes=10 )
    for _ in range( 3 ):
        job._route( 4, "ping", blocker="Blk" )
    assert gw.sent == [ ( "Blk", "[2026.06.24 at 12:47:57] ping" ) ] * 2   # only 2 delivered
    suppressed = [ f for f in log.of( "arbiter_outreach_result" )
                   if f.get( "outcome" ) == "throttle_suppressed" ]
    assert len( suppressed ) == 1
    assert suppressed[ 0 ][ "window_count" ] == 2
    assert suppressed[ 0 ][ "last_sent_local" ] == "2026.06.24 at 12:47:57"   # EDT last-sent


def test_throttle_is_per_recipient():
    """The window is per-recipient: hitting Blk's cap does not suppress a DM to Other."""
    gw = _GW()
    job = _job( gw=gw, outreach_throttle_max_messages=1, outreach_throttle_window_minutes=10 )
    job._route( 4, "ping", blocker="Blk" )                          # Blk: 1 (at cap)
    job._route( 4, "ping", blocker="Blk" )                          # Blk: suppressed
    job._route( 4, "ping", blocker="Other" )                       # Other: fresh window → sent
    recipients = [ r for r, _b in gw.sent ]
    assert recipients == [ "Blk", "Other" ]


def test_escalation_never_suppressed_even_over_window():        # Mr Radio REQUIRED carve-out test
    """SAFETY CARVE-OUT: a Rick-bound escalation (deadlock #5 → a manager DM) is NEVER
    suppressed even when the recipient's routine-tap window is already exceeded.
    Capping a real alert to save noise is the failure this proves we avoid."""
    gw, notes = _GW(), [ ]
    job = _job( gw=gw, notify=notes.append,
                outreach_throttle_max_messages=1, outreach_throttle_window_minutes=10 )
    # exhaust M1's routine-tap window with a manager tap (#7 — throttleable)
    job._route( 7, "tap one", owning_manager="M1" )                # M1: at cap
    job._route( 7, "tap two", owning_manager="M1" )                # M1: SUPPRESSED (routine)
    # a deadlock escalation (#5) to the SAME manager — must STILL be delivered
    job._route( 5, "DEADLOCK", active_managers=[ "M1" ] )
    m1_bodies = [ b for r, b in gw.sent if r == "M1" ]
    assert "[2026.06.24 at 12:47:57] tap one" in m1_bodies          # 1st routine tap delivered
    assert "[2026.06.24 at 12:47:57] tap two" not in m1_bodies      # 2nd routine tap suppressed
    assert "[2026.06.24 at 12:47:57] DEADLOCK" in m1_bodies         # escalation NEVER suppressed
    assert notes == [ "[2026.06.24 at 12:47:57] DEADLOCK" ]         # Rick also got it


def test_rick_bound_outreach_never_throttled():
    """Rick (notify) is never subject to the per-recipient throttle even when fired
    repeatedly (the throttle gates only persona-bound DMs; _emit_to_rick has no gate)."""
    notes = [ ]
    job = _job( notify=notes.append,
                outreach_throttle_max_messages=1, outreach_throttle_window_minutes=10 )
    for _ in range( 4 ):
        job._route( 1, "infra" )                                   # RICK_ONLY, repeated
    assert len( notes ) == 4                                        # all delivered
