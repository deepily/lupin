#!/usr/bin/env python3
"""
Arbiter manager-subject hardening, case-16 leg (D1 ratified): CASE_MANAGER_AWAITING_USER
(16) -> TIER_RICK_ONLY. An AWAITING-USER manager is ALIVE and still OWNS its crew; only
Rick unblocks, so a peer manager has zero action -> no peer fan-out (mirror case 20/17).
Case 14 (MANAGER-STALE) stays Rick+managers (orphaned crew -> peer can adopt).
Design: src/rnd/v0.1.9/2026.07.08-arbiter-manager-subject-routing-hardening.md (D1)
Venue: :7999-eligible / local -- pure + mocked, no server.
"""
import datetime
import os
import sys

import pytest

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.agents.heartbeat_arbiter.arbiter_job import ArbiterConsumerJob, CLASS_BLOCKED_ON_USER
from cosa.agents.heartbeat_arbiter.arbiter_routing import (
    tier_for, CASE_MANAGER_AWAITING_USER, TIER_RICK_ONLY )


NOW  = datetime.datetime( 2026, 7, 8, 21, 0, 0, tzinfo=datetime.timezone.utc )
LATE = NOW + datetime.timedelta( seconds=700 )


class _GW:
    def __init__( self ):
        self.sent = [ ]
    def who( self, retention_hours=24 ): return [ ]
    def send_to( self, r, b, metadata=None ): self.sent.append( ( r, b ) )
    def post( self, t, b ): pass
    def read( self, topic, since=None, limit=50 ): return [ ]


def _job( gw=None, notify=None, **overrides ):
    cfg = dict(
        commons           = gw or _GW(),
        poll_seconds      = 5,
        manager_recipient = "DeclaredMgr",
        notify_fn         = notify or ( lambda *a, **k: None ),
    )
    cfg.update( overrides )
    return ArbiterConsumerJob( **cfg )


def test_case_manager_awaiting_user_tier_is_rick_only():
    """D1: an AWAITING-USER manager-subject FYI is RICK-ONLY (mirror case 20/17)."""
    assert CASE_MANAGER_AWAITING_USER == 16
    assert tier_for( CASE_MANAGER_AWAITING_USER ) == TIER_RICK_ONLY


def test_manager_awaiting_user_acks_path_is_rick_only_no_peer_fanout():
    """RED->GREEN (acks emitter): a BLOCKED_ON_USER manager past its tap window emits
    its MANAGER-AWAITING-RICK advisory to RICK ONLY -- no active PEER manager DM."""
    gw, escal = _GW(), [ ]
    job = _job( gw, notify=lambda m, *a, **k: escal.append( m ) )
    job._last_tap_at[ "Tiberius" ] = NOW
    down = job._check_manager_acks( LATE, [ ], None, [ "Mr. Radio" ],
                                    owed_class={ "Tiberius": CLASS_BLOCKED_ON_USER } )
    assert down == 0
    awaiting = [ m for m in escal if "MANAGER-AWAITING-RICK" in m ]
    assert len( awaiting ) == 1
    assert gw.sent == [ ]                                        # RED before fix: [("Mr. Radio", <awaiting body>)]


if __name__ == "__main__":
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
