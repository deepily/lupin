"""
The wake watch must look where the boot receipt was WRITTEN.

Rick ruled 2026-09-03 (row db56ac6d): a seat's data keys on the seat's OWN repo,
everywhere. The receipt writer already did. The wake reader did not — it fell
through to the firing MANAGER's ambient LUPIN_ROOT, so a cross-repo spawn wrote
its receipt to one directory and had it looked for in another.

⚠️ WHY THIS NEEDED A TEST AND NOT JUST A FIX: manager and worker share a repo on
nearly every spawn, so writer and reader AGREE BY ACCIDENT almost always. A test
that only exercises the common case passes identically before and after the fix.
Every arm below therefore names which case it is, and the same-repo arm is a
NEGATIVE CONTROL — without it, "the base_dir changed" would be satisfied by code
that simply always changed it.
"""
import pytest

from cosa.agents.heartbeat_arbiter.respin_wake_check import arm_watches_for_spawn


def _spawned( project, name="cc-seat-1" ):
    return { "spawned": [ { "session_name": name, "status": "spawned", "project": project } ] }


def _recorder():
    calls = []
    def starter( **kw ):
        calls.append( kw )
        return object()
    return calls, starter


def test_a_cross_repo_seat_is_watched_in_its_own_data_root():
    calls, starter = _recorder()
    arm_watches_for_spawn(
        _spawned( "lupin-mobile" ), alert_fn=lambda m: None, fired_at="T0",
        start_fn=starter, base_dir_for=lambda r: f"/data/{r['project']}" )
    assert len( calls ) == 1
    assert calls[ 0 ][ "base_dir" ] == "/data/lupin-mobile", \
        "the watch did not read the spawned seat's own data root"


def test_a_same_repo_seat_still_lands_on_the_very_same_root():
    """NEGATIVE CONTROL. The common case must be unchanged, or the arm above
    is satisfied by code that merely always differs."""
    calls, starter = _recorder()
    arm_watches_for_spawn(
        _spawned( "lupin" ), alert_fn=lambda m: None, fired_at="T0",
        start_fn=starter, base_dir_for=lambda r: f"/data/{r['project']}" )
    assert calls[ 0 ][ "base_dir" ] == "/data/lupin"


def test_with_no_resolver_the_call_is_byte_identical_to_before():
    """REGRESSION CONTROL: omitting base_dir_for must pass no base_dir at all,
    so every existing caller keeps today's ambient behaviour."""
    calls, starter = _recorder()
    arm_watches_for_spawn(
        _spawned( "lupin-mobile" ), alert_fn=lambda m: None, fired_at="T0",
        start_fn=starter )
    assert "base_dir" not in calls[ 0 ]


def test_a_resolver_that_cannot_answer_leaves_the_watch_on_the_default():
    calls, starter = _recorder()
    arm_watches_for_spawn(
        _spawned( "no-such-repo" ), alert_fn=lambda m: None, fired_at="T0",
        start_fn=starter, base_dir_for=lambda r: None )
    assert len( calls ) == 1, "an unresolvable project cost the watch entirely"
    assert "base_dir" not in calls[ 0 ]


def test_a_resolver_that_RAISES_still_arms_the_watch():
    """A resolver failure must never be worse than no resolver."""
    def boom( record ):
        raise RuntimeError( "resolver exploded" )
    calls, starter = _recorder()
    arm_watches_for_spawn(
        _spawned( "lupin-mobile" ), alert_fn=lambda m: None, fired_at="T0",
        start_fn=starter, base_dir_for=boom )
    assert len( calls ) == 1, "a raising resolver silently dropped the watch"
    assert "base_dir" not in calls[ 0 ]


def test_an_explicit_base_dir_outranks_the_per_record_resolver():
    calls, starter = _recorder()
    arm_watches_for_spawn(
        _spawned( "lupin-mobile" ), alert_fn=lambda m: None, fired_at="T0",
        start_fn=starter, base_dir_for=lambda r: "/data/guessed",
        base_dir="/data/named-outright" )
    assert calls[ 0 ][ "base_dir" ] == "/data/named-outright"


def test_two_seats_in_two_repos_get_two_different_roots():
    """The loop resolves PER RECORD, not once for the batch."""
    calls, starter = _recorder()
    result = { "spawned": [
        { "session_name": "a", "status": "spawned", "project": "lupin" },
        { "session_name": "b", "status": "spawned", "project": "lupin-mobile" },
    ] }
    arm_watches_for_spawn( result, alert_fn=lambda m: None, fired_at="T0",
                           start_fn=starter, base_dir_for=lambda r: f"/data/{r['project']}" )
    assert [ c[ "base_dir" ] for c in calls ] == [ "/data/lupin", "/data/lupin-mobile" ]


def test_a_failed_record_is_still_not_watched():
    """Unchanged behaviour: only `spawned` records arm."""
    calls, starter = _recorder()
    result = { "spawned": [ { "session_name": "a", "status": "failed", "project": "lupin" } ] }
    arm_watches_for_spawn( result, alert_fn=lambda m: None, fired_at="T0",
                           start_fn=starter, base_dir_for=lambda r: "/data/x" )
    assert calls == []
