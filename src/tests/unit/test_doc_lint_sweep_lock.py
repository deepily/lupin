"""
sweep_lock: the per-package lock of the docs-rewrite sweep, held by one seat at a time.

Every test runs in a real git repo made in a temp directory; no test creates a ref in the real repository.
"""

import io
import json
import subprocess
import threading
from datetime import datetime, timedelta, timezone

import pytest

from cosa.repo.doc_lint import sweep_lock as sl

PKG  = "src/cosa/repo"
REF  = "refs/sweep-locks/src--cosa--repo"
T0   = datetime( 2026, 10, 5, 12, 0, 0, tzinfo=timezone.utc )
DAY  = timedelta( hours=24 )


def git( root, *args, stdin=None ):
    res = subprocess.run( [ "git", "-C", str( root ), "-c", "user.email=t@t", "-c", "user.name=t", *args ], input=stdin, capture_output=True, text=True )
    assert res.returncode == 0, res.stderr
    return res.stdout.strip()


@pytest.fixture
def repo( tmp_path ):
    git( tmp_path, "init", "-q" )
    return tmp_path


def ref_value( root, ref=REF ):
    res = subprocess.run( [ "git", "-C", str( root ), "rev-parse", "--verify", "--quiet", ref ], capture_output=True, text=True )
    return res.stdout.strip() if res.returncode == 0 else None


def plant( root, text, ref=REF ):
    """Point the lock ref at a blob holding exactly text, bypassing take."""
    blob = git( root, "hash-object", "-w", "--stdin", stdin=text )
    git( root, "update-ref", ref, blob )
    return blob


def test_slug_of_turns_slashes_into_double_dashes_and_drops_the_trailing_slash():
    assert sl.slug_of( "src/cosa/repo" ) == "src--cosa--repo"
    assert sl.slug_of( "src/cosa/repo/" ) == "src--cosa--repo"
    assert sl.slug_of( "docs" ) == "docs"


@pytest.mark.parametrize( "bad", [ "", "/", ".hidden", "-lead", "a b", "a..b", "x.lock", "a/b.lock", "a.", "a~b", "a:b", "a\\b" ] )
def test_slug_of_refuses_a_package_that_cannot_name_a_ref( bad ):
    with pytest.raises( ValueError, match="cannot name a lock" ):
        sl.slug_of( bad )


def test_take_creates_the_ref_with_a_record_of_who_took_it( repo ):
    ok, held = sl.take( repo, PKG, "Rio", "d882602c", now=T0 )
    assert ok is True
    assert { k: held[ k ] for k in ( "package", "persona", "session", "utc" ) } == { "package": PKG, "persona": "Rio", "session": "d882602c", "utc": T0.isoformat() }
    assert held[ "blob" ] == ref_value( repo )
    assert json.loads( git( repo, "cat-file", "blob", held[ "blob" ] ) )[ "persona" ] == "Rio"


def test_take_by_a_second_seat_is_refused_and_leaves_the_ref_alone( repo ):
    sl.take( repo, PKG, "Rio", "aaaa1111", now=T0 )
    before = ref_value( repo )
    ok, held = sl.take( repo, PKG, "Maya", "bbbb2222", now=T0 + timedelta( minutes=1 ) )
    assert ok is False
    assert ( held[ "persona" ], held[ "session" ] ) == ( "Rio", "aaaa1111" )
    assert ref_value( repo ) == before


def test_take_by_the_same_seat_twice_is_still_refused( repo ):
    sl.take( repo, PKG, "Rio", "aaaa1111", now=T0 )
    ok, _ = sl.take( repo, PKG, "Rio", "aaaa1111", now=T0 )
    assert ok is False


def test_two_seats_taking_at_the_same_moment_have_exactly_one_winner( repo ):
    results = []
    gate    = threading.Barrier( 8 )

    def worker( i ):
        gate.wait()
        results.append( sl.take( repo, PKG, f"seat{i}", f"{i:08x}", now=T0 )[ 0 ] )

    threads = [ threading.Thread( target=worker, args=( i, ) ) for i in range( 8 ) ]
    for t in threads: t.start()
    for t in threads: t.join()
    assert sorted( results ) == [ False ] * 7 + [ True ]


def test_locks_of_different_packages_do_not_collide( repo ):
    assert sl.take( repo, "src/a", "Rio", "s1", now=T0 )[ 0 ] is True
    assert sl.take( repo, "src/b", "Maya", "s2", now=T0 )[ 0 ] is True


@pytest.mark.parametrize( "persona, session", [ ( "", "s1" ), ( "Rio", "" ), ( None, "s1" ), ( "Rio", None ) ] )
def test_take_and_takeover_need_a_persona_and_a_session( repo, persona, session ):
    with pytest.raises( ValueError, match="persona and a session" ): sl.take( repo, PKG, persona, session )
    with pytest.raises( ValueError, match="persona and a session" ): sl.takeover( repo, PKG, persona, session )


def test_take_raises_when_git_cannot_write_the_object( tmp_path ):
    with pytest.raises( RuntimeError, match="hash-object failed" ):
        sl.take( tmp_path, PKG, "Rio", "s1" )


def test_take_raises_when_update_ref_fails_for_a_reason_other_than_a_held_lock( repo, monkeypatch ):
    real = sl._run

    def failing( root, *args, stdin=None ):
        if args[ 0 ] == "update-ref": return 128, "", "disk on fire"
        return real( root, *args, stdin=stdin )

    monkeypatch.setattr( sl, "_run", failing )
    with pytest.raises( RuntimeError, match="update-ref .* failed: disk on fire" ):
        sl.take( repo, PKG, "Rio", "s1" )


def test_take_without_now_stamps_the_current_time( repo ):
    before = datetime.now( timezone.utc )
    _, held = sl.take( repo, PKG, "Rio", "s1" )
    assert before <= datetime.fromisoformat( held[ "utc" ] ) <= datetime.now( timezone.utc )


def test_holder_of_a_free_lock_is_none( repo ):
    assert sl.holder_of( repo, PKG ) is None


def test_holder_of_refuses_a_ref_that_points_at_something_that_is_not_a_blob( repo ):
    git( repo, "commit", "-q", "--allow-empty", "-m", "c" )
    git( repo, "update-ref", REF, "HEAD" )
    with pytest.raises( RuntimeError, match="readable blob" ):
        sl.holder_of( repo, PKG )


@pytest.mark.parametrize( "text", [ "not json", "[]", "{}", json.dumps( { "persona": "Rio" } ), json.dumps( { "utc": "x" } ), json.dumps( { "utc": 5, "persona": "Rio" } ), json.dumps( { "utc": "x", "persona": 5 } ) ] )
def test_holder_of_refuses_a_blob_that_is_not_a_lock_record( repo, text ):
    plant( repo, text )
    with pytest.raises( RuntimeError, match="not a lock" ):
        sl.holder_of( repo, PKG )


def test_release_by_the_holder_removes_the_ref( repo ):
    sl.take( repo, PKG, "Rio", "s1", now=T0 )
    assert sl.release( repo, PKG, "Rio", "s1" ) == ( True, None )
    assert ref_value( repo ) is None
    assert sl.take( repo, PKG, "Maya", "s2", now=T0 )[ 0 ] is True


def test_release_of_a_free_lock_is_refused( repo ):
    assert sl.release( repo, PKG, "Rio", "s1" ) == ( False, "the lock is not held" )


@pytest.mark.parametrize( "persona, session", [ ( "Maya", "s1" ), ( "Rio", "s2" ), ( "Maya", "s2" ) ] )
def test_release_by_the_wrong_owner_is_refused_and_the_ref_survives( repo, persona, session ):
    sl.take( repo, PKG, "Rio", "s1", now=T0 )
    before = ref_value( repo )
    ok, why = sl.release( repo, PKG, persona, session )
    assert ok is False and "held by Rio (s1)" in why and f"not by {persona} ({session})" in why
    assert ref_value( repo ) == before


def test_release_when_the_lock_changes_hands_mid_call_is_refused_and_deletes_nothing( repo, monkeypatch ):
    sl.take( repo, PKG, "Rio", "s1", now=T0 )
    stale = sl.holder_of( repo, PKG )
    git( repo, "update-ref", "-d", REF )
    sl.take( repo, PKG, "Maya", "s2", now=T0 )
    newer = ref_value( repo )
    monkeypatch.setattr( sl, "holder_of", lambda root, package: stale )
    ok, why = sl.release( repo, PKG, "Rio", "s1" )
    assert ( ok, why ) == ( False, "the lock changed hands during the release" )
    assert ref_value( repo ) == newer


def test_release_of_a_record_with_no_session_matches_only_a_caller_with_none( repo ):
    plant( repo, json.dumps( { "package": PKG, "persona": "Rio", "utc": T0.isoformat() } ) )
    assert sl.release( repo, PKG, "Rio", "s1" )[ 0 ] is False
    assert ref_value( repo ) is not None


def test_takeover_is_refused_when_the_lock_is_younger_than_24_hours( repo ):
    sl.take( repo, PKG, "Rio", "s1", now=T0 )
    before = ref_value( repo )
    ok, why = sl.takeover( repo, PKG, "Maya", "s2", now=T0 + DAY - timedelta( seconds=1 ) )
    assert ok is False and "needs 1 day, 0:00:00" in why
    assert ref_value( repo ) == before


def test_takeover_at_exactly_24_hours_replaces_the_holder( repo ):
    sl.take( repo, PKG, "Rio", "s1", now=T0 )
    ok, held = sl.takeover( repo, PKG, "Maya", "s2", now=T0 + DAY )
    assert ok is True
    assert ( held[ "persona" ], held[ "session" ], held[ "utc" ] ) == ( "Maya", "s2", ( T0 + DAY ).isoformat() )
    assert sl.holder_of( repo, PKG )[ "persona" ] == "Maya"


def test_takeover_of_a_free_lock_is_refused( repo ):
    ok, why = sl.takeover( repo, PKG, "Maya", "s2", now=T0 )
    assert ( ok, why ) == ( False, "the lock is not held; take it instead" )
    assert ref_value( repo ) is None


def test_takeover_reads_a_time_with_no_zone_as_utc( repo ):
    plant( repo, json.dumps( { "package": PKG, "persona": "Rio", "session": "s1", "utc": "2026-10-05T12:00:00" } ) )
    assert sl.takeover( repo, PKG, "Maya", "s2", now=T0 + DAY - timedelta( seconds=1 ) )[ 0 ] is False
    assert sl.takeover( repo, PKG, "Maya", "s2", now=T0 + DAY )[ 0 ] is True


@pytest.mark.parametrize( "utc", [ "yesterday", "" ] )
def test_takeover_is_refused_when_the_holders_time_cannot_be_read( repo, utc ):
    plant( repo, json.dumps( { "package": PKG, "persona": "Rio", "session": "s1", "utc": utc } ) )
    before = ref_value( repo )
    ok, why = sl.takeover( repo, PKG, "Maya", "s2", now=T0 + 10 * DAY )
    assert ok is False and "cannot be read" in why
    assert ref_value( repo ) == before


def test_takeover_without_now_uses_the_current_time( repo ):
    sl.take( repo, PKG, "Rio", "s1", now=datetime.now( timezone.utc ) - 2 * DAY )
    assert sl.takeover( repo, PKG, "Maya", "s2" )[ 0 ] is True


def test_two_takeovers_of_one_stale_lock_have_exactly_one_winner( repo ):
    sl.take( repo, PKG, "Rio", "s0", now=T0 )
    results = []
    gate    = threading.Barrier( 8 )

    def worker( i ):
        gate.wait()
        results.append( sl.takeover( repo, PKG, f"seat{i}", f"{i:08x}", now=T0 + 2 * DAY )[ 0 ] )

    threads = [ threading.Thread( target=worker, args=( i, ) ) for i in range( 8 ) ]
    for t in threads: t.start()
    for t in threads: t.join()
    assert results.count( True ) == 1 and results.count( False ) == 7
    assert sl.holder_of( repo, PKG )[ "persona" ].startswith( "seat" )


def test_a_takeover_that_loses_the_swap_says_so_and_changes_nothing( repo, monkeypatch ):
    sl.take( repo, PKG, "Rio", "s0", now=T0 )
    stale = sl.holder_of( repo, PKG )
    git( repo, "update-ref", "-d", REF )
    sl.take( repo, PKG, "Winner", "s9", now=T0 + DAY )
    winner = ref_value( repo )
    monkeypatch.setattr( sl, "holder_of", lambda root, package: stale )
    ok, why = sl.takeover( repo, PKG, "Maya", "s2", now=T0 + 2 * DAY )
    assert ( ok, why ) == ( False, "another seat took the lock over first" )
    assert ref_value( repo ) == winner


def run_cli( repo, *args ):
    out  = io.StringIO()
    code = sl.main( [ *args, "--repo-root", str( repo ) ], out=out )
    return code, out.getvalue()


def test_cli_show_says_free_then_names_the_holder( repo ):
    assert run_cli( repo, "show", PKG ) == ( 0, "free\n" )
    sl.take( repo, PKG, "Rio", "s1", now=T0 )
    code, text = run_cli( repo, "show", PKG )
    assert code == 0 and text == f"held by Rio (s1) since {T0.isoformat()}\n"


def test_cli_take_then_a_second_take_is_refused_naming_the_holder( repo ):
    code, text = run_cli( repo, "take", PKG, "--persona", "Rio", "--session", "s1" )
    assert code == 0 and text == f"take ok: {PKG} held by Rio (s1)\n"
    code, text = run_cli( repo, "take", PKG, "--persona", "Maya", "--session", "s2" )
    assert code == 1 and text.startswith( "REFUSED: already held by Rio (s1) since " )


def test_cli_release_succeeds_for_the_holder_and_is_refused_for_anyone_else( repo ):
    run_cli( repo, "take", PKG, "--persona", "Rio", "--session", "s1" )
    code, text = run_cli( repo, "release", PKG, "--persona", "Maya", "--session", "s2" )
    assert code == 1 and text.startswith( "REFUSED: the lock is held by Rio (s1)" )
    assert run_cli( repo, "release", PKG, "--persona", "Rio", "--session", "s1" ) == ( 0, f"released {PKG}\n" )
    assert ref_value( repo ) is None


def test_cli_release_of_a_free_lock_is_refused_not_an_error( repo ):
    assert run_cli( repo, "release", PKG, "--persona", "Rio", "--session", "s1" ) == ( 1, "REFUSED: the lock is not held\n" )


def test_cli_takeover_is_refused_while_young_and_succeeds_when_old( repo ):
    sl.take( repo, PKG, "Rio", "s1" )
    code, text = run_cli( repo, "takeover", PKG, "--persona", "Maya", "--session", "s2" )
    assert code == 1 and "a takeover needs 1 day" in text
    sl.release( repo, PKG, "Rio", "s1" )
    sl.take( repo, PKG, "Rio", "s1", now=datetime.now( timezone.utc ) - 2 * DAY )
    assert run_cli( repo, "takeover", PKG, "--persona", "Maya", "--session", "s2" ) == ( 0, f"takeover ok: {PKG} held by Maya (s2)\n" )


@pytest.mark.parametrize( "verb", [ "take", "release", "takeover" ] )
def test_cli_verbs_that_change_a_lock_need_persona_and_session( repo, verb ):
    code, text = run_cli( repo, verb, PKG, "--persona", "Rio" )
    assert code == 2 and text == f"ERROR: {verb} needs --persona and --session\n"
    assert ref_value( repo ) is None


def test_cli_a_package_that_cannot_name_a_lock_is_an_error( repo ):
    code, text = run_cli( repo, "show", "a..b" )
    assert code == 2 and "cannot name a lock" in text


def test_cli_a_corrupt_lock_is_an_error_not_a_crash( repo ):
    plant( repo, "not json" )
    code, text = run_cli( repo, "show", PKG )
    assert code == 2 and "not a lock" in text


def test_cli_defaults_to_stdout_and_to_sys_argv( repo, monkeypatch, capsys ):
    monkeypatch.chdir( repo )
    monkeypatch.setattr( "sys.argv", [ "sweep_lock", "show", PKG ] )
    assert sl.main() == 0
    assert capsys.readouterr().out == "free\n"


def test_why_passes_a_reason_through_and_phrases_a_holder():
    assert sl._why( "because" ) == "because"
    assert sl._why( { "persona": "Rio", "session": "s1", "utc": "t" } ) == "already held by Rio (s1) since t"
    assert sl._why( { "persona": "Rio", "utc": "t" } ) == "already held by Rio (None) since t"


def test_the_lock_tests_create_no_ref_in_the_real_repository( repo ):
    real = subprocess.run( [ "git", "for-each-ref", "refs/sweep-locks/" ], capture_output=True, text=True )
    sl.take( repo, PKG, "Rio", "s1", now=T0 )
    after = subprocess.run( [ "git", "for-each-ref", "refs/sweep-locks/" ], capture_output=True, text=True )
    assert real.stdout == after.stdout


def test_take_records_the_time_in_utc_whatever_zone_the_caller_gave( repo ):
    eastern = T0.astimezone( timezone( timedelta( hours=-4 ) ) )
    _, held = sl.take( repo, PKG, "Rio", "s1", now=eastern )
    assert held[ "utc" ] == T0.isoformat()
