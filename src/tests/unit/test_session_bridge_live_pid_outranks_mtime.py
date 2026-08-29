"""
Regression tests for bug 6afc8b3e — a LIVE session with a stale bridge mtime was
dropped from the context monitor entirely.

THE DEFECT, in one sentence: `find_active_sessions` applied its mtime TTL
unconditionally, so a seat whose PROCESS WAS PROVEN ALIVE vanished from every roster
once its bridge went 12h without a rewrite — not in `personas`, not in
`unnamed_seats`, not in any count. Rio measured two real seats invisible for 14h+
while `ps` showed them running.

WHY IT MATTERS MORE THAN IT LOOKS: the monitor exists to catch a seat before it blows
its context, so the seat that has been alive longest is precisely the one it is for.
That was the one seat it could not see, and the exclusion was silent — the roster just
got shorter. "All within budget" then means "all the ones the scanner still believed
in".

THE HEADLINE TEST is `test_a_live_pid_with_an_aged_out_bridge_is_KEPT`. Proven red
against the pre-fix code (verified by reverting the guard: the seat is absent), green
after. Raising the TTL would also turn it green, which is why
`test_raising_the_threshold_is_not_the_fix` pins that a bigger number is the
diagnostic and not the remedy.

Venue: :7999-eligible. tmp_path only, PID liveness injected — no real processes are
started and no real bridge directory is touched.
"""

import os
import json
import time

import pytest

from lupin_cli.claude_code.hooks.lib import session_bridge as sb


TWELVE_HOURS = 43200


@pytest.fixture
def bridges( tmp_path, monkeypatch ):
    """A throwaway session dir with host-PID trust on, so the TTL path is reachable."""
    monkeypatch.setattr( sb, "SESSION_DIR", tmp_path )
    monkeypatch.setattr( sb, "_can_trust_host_pids", lambda: True )
    return tmp_path


def _write_bridge( directory, pid, session_id, age_seconds, persona=None ):
    """Write cc-<pid>.json and backdate its mtime by age_seconds."""
    path = directory / f"cc-{pid}.json"
    path.write_text( json.dumps( {
        "stable_session_id" : session_id,
        "session_id"        : session_id,
        "voice_persona"     : persona,
        "tmux_session"      : f"cc-author-{session_id}",
    } ) )
    stamp = time.time() - age_seconds
    os.utime( path, ( stamp, stamp ) )
    return path


def _alive( *pids ):
    """Injectable PID liveness: exactly these pids are running."""
    live = set( pids )
    return lambda pid: pid in live


# ─────────────────────────────────────────────────────────────────────────────
# THE HEADLINE — liveness outranks mtime
# ─────────────────────────────────────────────────────────────────────────────

def test_a_live_pid_with_an_aged_out_bridge_is_KEPT( bridges, monkeypatch ):
    """
    Rio's two real seats, in miniature: process up, bridge untouched for 14h+.
    Pre-fix this returned an empty roster; the seat existed and the monitor said
    it did not.
    """
    _write_bridge( bridges, 1641511, "c6b34684", age_seconds=14.2 * 3600 )
    monkeypatch.setattr( sb, "_is_pid_alive", _alive( 1641511 ) )

    found = sb.find_active_sessions( stale_threshold_seconds=TWELVE_HOURS, require_persona=False )

    assert [ sid for _p, sid, _persona in found ] == [ "c6b34684" ], \
        "a running process whose bridge aged out must still be visible to the monitor"


def test_a_NAMED_seat_with_an_aged_out_bridge_is_kept_too( bridges, monkeypatch ):
    """
    The mtime filter ran BEFORE the persona branch, so a named seat disappeared
    identically. The null persona on Rio's two seats was a separate fact, not the cause.
    """
    _write_bridge( bridges, 1645202, "b24cab16", age_seconds=14.5 * 3600,
                   persona={ "name": "Tiberius" } )
    monkeypatch.setattr( sb, "_is_pid_alive", _alive( 1645202 ) )

    found = sb.find_active_sessions( stale_threshold_seconds=TWELVE_HOURS, require_persona=True )

    assert [ sid for _p, sid, _persona in found ] == [ "b24cab16" ]


def test_a_dead_pid_with_an_aged_out_bridge_is_still_excluded( bridges, monkeypatch ):
    """The fix must not quietly admit long-dead bridges alongside the live ones."""
    _write_bridge( bridges, 999001, "deadbeef", age_seconds=30 * 3600 )
    monkeypatch.setattr( sb, "_is_pid_alive", _alive() )          # nothing is alive

    assert sb.find_active_sessions( stale_threshold_seconds=TWELVE_HOURS, require_persona=False ) == []


def test_a_fresh_bridge_is_unaffected( bridges, monkeypatch ):
    """The common path must not change."""
    _write_bridge( bridges, 1700001, "freshsid", age_seconds=60 )
    monkeypatch.setattr( sb, "_is_pid_alive", _alive( 1700001 ) )

    found = sb.find_active_sessions( stale_threshold_seconds=TWELVE_HOURS, require_persona=False )
    assert [ sid for _p, sid, _ in found ] == [ "freshsid" ]


def test_the_live_and_the_dead_are_separated_in_one_scan( bridges, monkeypatch ):
    """Rio's delta: the fix admits the two live seats and nothing else."""
    _write_bridge( bridges, 1641511, "c6b34684", age_seconds=14.2 * 3600 )
    _write_bridge( bridges, 1645202, "b24cab16", age_seconds=14.5 * 3600 )
    _write_bridge( bridges, 999001,  "longdead", age_seconds=72 * 3600 )
    monkeypatch.setattr( sb, "_is_pid_alive", _alive( 1641511, 1645202 ) )

    found = sorted( sid for _p, sid, _ in
                    sb.find_active_sessions( stale_threshold_seconds=TWELVE_HOURS, require_persona=False ) )

    assert found == [ "b24cab16", "c6b34684" ]


def test_raising_the_threshold_only_moves_the_cliff( bridges, monkeypatch ):
    """
    Rio's warning, pinned — and sharpened by what the code actually does. A wider TTL
    would have turned the headline case green too, which is why it looked like a fix.
    It is not: it just relocates the boundary, so the SAME seat disappears again once
    it passes the new number. Liveness has no cliff to move.
    """
    _write_bridge( bridges, 1641511, "c6b34684", age_seconds=26 * 3600 )   # past a 24h TTL too
    monkeypatch.setattr( sb, "_is_pid_alive", _alive( 1641511 ) )

    widened = [ sid for _p, sid, _ in
                sb.find_active_sessions( stale_threshold_seconds=24 * 3600, require_persona=False ) ]
    fixed   = [ sid for _p, sid, _ in
                sb.find_active_sessions( stale_threshold_seconds=TWELVE_HOURS, require_persona=False ) ]

    assert widened == [ "c6b34684" ], "the widened TTL only works until the seat outlives it"
    assert fixed   == [ "c6b34684" ], "liveness keeps the seat at ANY age, which is the actual fix"


def test_widening_the_ttl_admits_dead_bridges_where_pids_cannot_be_checked( bridges, monkeypatch ):
    """
    Rio's "do not quietly admit long-dead bridges" hazard, located precisely. On the
    HOST a dead bridge is already removed by the PID filter before the TTL is reached,
    so widening is merely useless there. INSIDE A CONTAINER, where host PIDs are
    invisible, the TTL is the only signal — and widening it is what actually lets a
    long-dead bridge in.
    """
    monkeypatch.setattr( sb, "_can_trust_host_pids", lambda: False )
    _write_bridge( bridges, 999001, "longdead", age_seconds=20 * 3600 )

    at_twelve = [ sid for _p, sid, _ in
                  sb.find_active_sessions( stale_threshold_seconds=TWELVE_HOURS, require_persona=False ) ]
    at_twenty_four = [ sid for _p, sid, _ in
                       sb.find_active_sessions( stale_threshold_seconds=24 * 3600, require_persona=False ) ]

    assert at_twelve      == []
    assert at_twenty_four == [ "longdead" ], "the wider number is what lets the dead bridge through"


# ─────────────────────────────────────────────────────────────────────────────
# THE VISIBLE BUCKET — an exclusion must never again be invisible
# ─────────────────────────────────────────────────────────────────────────────

def test_a_kept_aged_out_bridge_is_reported_as_kept( bridges, monkeypatch ):
    _write_bridge( bridges, 1641511, "c6b34684", age_seconds=14.2 * 3600 )
    monkeypatch.setattr( sb, "_is_pid_alive", _alive( 1641511 ) )

    stale = []
    sb.find_active_sessions( stale_threshold_seconds=TWELVE_HOURS, require_persona=False,
                             stale_out=stale )

    assert len( stale ) == 1
    entry = stale[ 0 ]
    assert entry[ "session_id" ] == "c6b34684"
    assert entry[ "pid_alive" ]  is True
    assert entry[ "included" ]   is True
    assert entry[ "mtime_age_h" ] == pytest.approx( 14.2, abs=0.1 )
    assert "PROCESS IS ALIVE" in entry[ "why" ]


def test_an_excluded_bridge_is_reported_as_excluded( bridges, monkeypatch ):
    """
    The silent drop is the actual bug; a named drop is a fact someone can act on.

    Uses the CONTAINER context deliberately: on the host a dead-PID bridge never
    reaches the TTL — the PID filter removes it first — so the aged-out-and-excluded
    case is genuinely the one where liveness cannot be confirmed.
    """
    monkeypatch.setattr( sb, "_can_trust_host_pids", lambda: False )
    _write_bridge( bridges, 999001, "longdead", age_seconds=72 * 3600 )

    stale = []
    sb.find_active_sessions( stale_threshold_seconds=TWELVE_HOURS, require_persona=False,
                             stale_out=stale )

    assert len( stale ) == 1
    assert stale[ 0 ][ "included" ]  is False
    assert stale[ 0 ][ "pid_alive" ] is False
    assert stale[ 0 ][ "session_id" ] == "longdead"
    assert "could not be confirmed" in stale[ 0 ][ "why" ]


def test_the_bucket_stays_empty_when_nothing_aged_out( bridges, monkeypatch ):
    _write_bridge( bridges, 1700001, "freshsid", age_seconds=60 )
    monkeypatch.setattr( sb, "_is_pid_alive", _alive( 1700001 ) )

    stale = []
    sb.find_active_sessions( stale_threshold_seconds=TWELVE_HOURS, require_persona=False,
                             stale_out=stale )
    assert stale == []


def test_the_bucket_names_an_unreadable_aged_out_bridge( bridges, monkeypatch ):
    """
    A bridge that cannot be parsed still gets an entry — a silently-dropped
    unreadable bridge is the same failure the bucket exists to prevent.
    """
    monkeypatch.setattr( sb, "_can_trust_host_pids", lambda: False )
    path = bridges / "cc-999002.json"
    path.write_text( "{ not json" )
    stamp = time.time() - 30 * 3600
    os.utime( path, ( stamp, stamp ) )

    stale = []
    sb.find_active_sessions( stale_threshold_seconds=TWELVE_HOURS, require_persona=False,
                             stale_out=stale )

    assert len( stale ) == 1
    assert stale[ 0 ][ "bridge" ]     == "cc-999002.json"
    assert stale[ 0 ][ "session_id" ] is None


def test_stale_out_is_optional_and_defaults_to_no_bucket( bridges, monkeypatch ):
    """Every existing caller passes nothing and must keep working unchanged."""
    _write_bridge( bridges, 1641511, "c6b34684", age_seconds=14.2 * 3600 )
    monkeypatch.setattr( sb, "_is_pid_alive", _alive( 1641511 ) )

    found = sb.find_active_sessions( stale_threshold_seconds=TWELVE_HOURS, require_persona=False )
    assert [ sid for _p, sid, _ in found ] == [ "c6b34684" ]


# ─────────────────────────────────────────────────────────────────────────────
# THE CONTAINER CASE — where the TTL is still the only signal
# ─────────────────────────────────────────────────────────────────────────────

def test_inside_a_container_the_ttl_still_applies( bridges, monkeypatch ):
    """
    Host PIDs are invisible from a container's PID namespace, so liveness cannot
    outrank anything there and the TTL keeps its original job.
    """
    monkeypatch.setattr( sb, "_can_trust_host_pids", lambda: False )
    _write_bridge( bridges, 1641511, "c6b34684", age_seconds=14.2 * 3600 )

    found = sb.find_active_sessions( stale_threshold_seconds=TWELVE_HOURS, require_persona=False )
    assert found == [], "without trustworthy PIDs the mtime TTL is the only signal left"


def test_a_bridge_with_no_pid_in_its_name_still_ages_out( bridges, monkeypatch ):
    """No PID to trust means the TTL decides, exactly as before."""
    path = bridges / "cc-session.json"
    path.write_text( json.dumps( { "stable_session_id": "nopid123", "voice_persona": None } ) )
    stamp = time.time() - 30 * 3600
    os.utime( path, ( stamp, stamp ) )
    monkeypatch.setattr( sb, "_is_pid_alive", _alive() )

    assert sb.find_active_sessions( stale_threshold_seconds=TWELVE_HOURS, require_persona=False ) == []
