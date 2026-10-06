"""
train_builder: which approved packages go in one train, read from sweep claim rows.

The claim rows are plain dicts shaped like the store's rows, with bodies written in the format
TaskRepository.apply_amendment stamps (the test asserts the repository's own stamp pattern sees them).
Everything else is real: a small git repo in a temp directory, real commits, real checks directories.
"""

import contextlib
import io
import json
import subprocess
import sys
import types

import pytest

from cosa.repo.doc_lint import train_builder as tb, word_list
from cosa.rest.task_store_prose_refs import strip_amendment_stamps

OWNER  = "Cheech"
TS     = "2026-10-05T22:02:28.169063+00:00"
WRITER = "Mr. Radio"


def _git( root, *args ):
    res = subprocess.run( [ "git", "-C", str( root ), "-c", "user.email=t@t", "-c", "user.name=t", *args ], capture_output=True, text=True )
    assert res.returncode == 0, res.stderr
    return res.stdout.strip()


def stamped( *blocks ):
    """Join ( actor, note ) blocks the way apply_amendment does: a divider line, the note, a blank line between blocks."""
    return "\n\n".join( f"[amendment · {actor} · {TS}]\n{note}" for actor, note in blocks )


def approval( checks, commits, verdict="pass" ):
    return tb.APPROVAL_PREFIX + " " + json.dumps( { "checks": str( checks ), "commits": commits, "verdict": verdict } )


@pytest.fixture
def world( tmp_path, monkeypatch ):
    monkeypatch.setattr( tb, "TEMP_ROOTS", ( str( tmp_path / "hot" ), ) )
    _git( tmp_path, "init", "-q" )
    ( tmp_path / "src" / "conf" ).mkdir( parents=True )
    ( tmp_path / "src" / "conf" / "dm-tutor-lowercase-words.txt" ).write_text( "the\n", encoding="utf-8" )
    for pkg in ( "a", "b", "c", "d" ):
        ( tmp_path / pkg ).mkdir()
        ( tmp_path / pkg / "__init__.py" ).write_text( f'"""Package {pkg}."""\n', encoding="utf-8" )
    _git( tmp_path, "add", "." )
    _git( tmp_path, "commit", "-qm", "base" )
    shas = {}
    for name in ( "one", "two", "three" ):
        ( tmp_path / "a" / f"{name}.py" ).write_text( f'"""{name}."""\n', encoding="utf-8" )
        _git( tmp_path, "add", "." )
        _git( tmp_path, "commit", "-qm", name )
        shas[ name ] = _git( tmp_path, "rev-parse", "HEAD" )
    ( tmp_path / "data" ).mkdir()
    yield types.SimpleNamespace( root=tmp_path, data=tmp_path / "data", shas=shas )
    word_list._state[ "root" ]  = None
    word_list._state[ "words" ] = None


def checks_dir( world, name, result_pass=True, history_pass=True ):
    path = world.data / name
    path.mkdir()
    ( path / "result.json" ).write_text( json.dumps( { "pass": result_pass } ), encoding="utf-8" )
    ( path / "history-destination.json" ).write_text( json.dumps( { "pass": history_pass } ), encoding="utf-8" )
    return path


def claim( package, body, owner=OWNER, row_id=None ):
    return { "id": row_id or f"id-{package}", "title": f"docs sweep: {package}", "owner_persona": owner, "status": "queued", "body": body }


def train( world, rows, size=11 ):
    return tb.build_train( world.root, rows, [ "a", "b", "c", "d" ], size, str( world.data ) )


def refusal_for( world, body, owner=OWNER ):
    result = train( world, [ claim( "a", body, owner ) ] )
    return result[ "refused" ][ 0 ][ "reason" ] if result[ "refused" ] else result[ "packages" ]


def test_the_fixture_bodies_are_recognised_by_the_repositorys_own_stamp_pattern():
    body = stamped( ( WRITER + " 43ff094e", "note one" ), ( "Tiberius 9f3a1b2c", "note two" ) )
    assert strip_amendment_stamps( body )[ 1 ] == 2


def test_amendments_split_a_body_and_read_post_terminal_addenda():
    body = "the original body\n\n" + stamped( ( "Tiberius 9f3a1b2c", "first\nsecond line" ) ) + "\n\n[post-terminal addendum · Cheech 78067fb5 · " + TS + " · row was 'done' at write — added after close, not a reopening]\nlate verdict"
    blocks = tb.amendments_of( body )
    assert [ ( b[ "kind" ], b[ "actor" ], b[ "ts" ], b[ "note" ] ) for b in blocks ] == [
        ( "amendment", "Tiberius 9f3a1b2c", TS, "first\nsecond line" ),
        ( "post-terminal addendum", "Cheech 78067fb5", TS, "late verdict" ) ]
    assert tb.amendments_of( None ) == [] and tb.amendments_of( "" ) == [] and tb.amendments_of( "no blocks here" ) == []


def test_persona_of_drops_the_session_id_accents_case_and_punctuation():
    assert tb.persona_of( "María 9f3a1b2c" ) == "maria" and tb.persona_of( "mr radio 43ff094e" ) == "mrradio" == tb.persona_of( "Mr. Radio" )
    assert tb.persona_of( "Cheech" ) == "cheech" and tb.persona_of( "Agent7 9f3a1b2c" ) == "agent7"


def test_a_train_holds_the_approved_packages_in_sweep_order_with_commits_and_bisect_order( world ):
    ca, cc = checks_dir( world, "ca" ), checks_dir( world, "cc" )
    s = world.shas
    rows = [
        claim( "c", stamped( ( "Tiberius 9f3a1b2c", approval( cc, [ s[ "three" ], s[ "two" ] ] ) ) ) ),
        claim( "a", stamped( ( "Tiberius 9f3a1b2c", approval( ca, [ s[ "one" ], s[ "two" ] ] ) ) ) ),
        claim( "b", "no amendment yet" ),
        { "id": "stray", "title": "other thing:a", "owner_persona": OWNER, "status": "queued", "body": "not a sweep row" } ]
    result = train( world, rows )
    assert [ p[ "package" ] for p in result[ "packages" ] ] == [ "a", "c" ] and result[ "bisect_order" ] == [ "a", "c" ]
    assert result[ "commits" ] == [ s[ "one" ], s[ "two" ], s[ "three" ] ]
    assert result[ "refused" ] == [ { "package": "b", "reason": "no approval amendment" } ] and result[ "not_claimed" ] == 1 and result[ "deferred" ] == []
    assert result[ "head" ] == _git( world.root, "rev-parse", "HEAD" ) and result[ "size" ] == 11
    assert result[ "packages" ][ 0 ] == { "package": "a", "row_id": "id-a", "approver": "Tiberius 9f3a1b2c", "checks": str( ca ), "commits": [ s[ "one" ], s[ "two" ] ] }


def test_the_size_cut_defers_the_rest_and_takes_only_the_cut_packages_commits( world ):
    s = world.shas
    rows = [ claim( p, stamped( ( "Tiberius 9f3a1b2c", approval( checks_dir( world, "c" + p ), [ s[ "one" ] if p == "a" else s[ "three" ] ] ) ) ) ) for p in ( "a", "b", "c" ) ]
    result = train( world, rows, size=1 )
    assert [ p[ "package" ] for p in result[ "packages" ] ] == [ "a" ] and result[ "bisect_order" ] == [ "a" ] and result[ "deferred" ] == [ "b", "c" ] and result[ "commits" ] == [ s[ "one" ] ]


def test_the_latest_approval_wins_and_a_later_failing_verdict_refuses( world ):
    checks, s = checks_dir( world, "c1" ), world.shas
    good_then_bad = stamped( ( "Tiberius 9f3a1b2c", "reviewed the six checks\n" + approval( checks, [ s[ "one" ] ] ) ), ( "Maria 1a2b3c4d", approval( checks, [ s[ "one" ] ], "fail" ) ) )
    assert refusal_for( world, good_then_bad ) == "verdict is 'fail', not pass"
    bad_then_good = stamped( ( "Maria 1a2b3c4d", approval( checks, [ s[ "one" ] ], "fail" ) ), ( "Tiberius 9f3a1b2c", approval( checks, [ s[ "one" ] ] ) ) )
    assert refusal_for( world, bad_then_good )[ 0 ][ "approver" ] == "Tiberius 9f3a1b2c"


def test_the_refusals_each_name_their_reason( world, tmp_path ):
    checks, s = checks_dir( world, "ok" ), world.shas
    good = approval( checks, [ s[ "one" ] ] )
    assert refusal_for( world, stamped( ( "Cheech 78067fb5", good ) ) ) == "approved by its author (Cheech 78067fb5)"
    assert refusal_for( world, stamped( ( "María 78067fb5", good ) ), owner="maria" ) == "approved by its author (María 78067fb5)"
    assert refusal_for( world, stamped( ( "Tiberius 9f3a1b2c", approval( checks, [ s[ "one" ] ], " PASS " ) ) ) )[ 0 ][ "package" ] == "a"
    assert refusal_for( world, stamped( ( "Tiberius 9f3a1b2c", approval( checks, [ s[ "one" ] ], "pass with findings" ) ) ) ) == "verdict is 'pass with findings', not pass"
    assert refusal_for( world, stamped( ( "Tiberius 9f3a1b2c", approval( checks, [ "0" * 40 ] ) ) ) ) == f"commit {'0' * 40} does not exist"
    assert refusal_for( world, stamped( ( "Tiberius 9f3a1b2c", good ) ), owner=None )[ 0 ][ "package" ] == "a"
    for line in ( tb.APPROVAL_PREFIX + " {nope", tb.APPROVAL_PREFIX + " [1]" ):
        assert "approval line is not" in refusal_for( world, stamped( ( "Tiberius 9f3a1b2c", line ) ) )
    for payload in ( { "commits": [ s[ "one" ] ], "verdict": "pass" }, { "checks": str( checks ), "commits": [], "verdict": "pass" }, { "checks": str( checks ), "commits": s[ "one" ], "verdict": "pass" },
                     { "checks": str( checks ), "commits": [ 1 ], "verdict": "pass" }, { "checks": str( checks ), "commits": [ s[ "one" ] ], "verdict": True } ):
        body = stamped( ( "Tiberius 9f3a1b2c", tb.APPROVAL_PREFIX + " " + json.dumps( payload ) ) )
        assert refusal_for( world, body ) == "the approval line needs checks (a path), commits (a non-empty list) and verdict"
    two = [ claim( "a", stamped( ( "Tiberius 9f3a1b2c", good ) ), row_id="r1" ), claim( "a", stamped( ( "Tiberius 9f3a1b2c", good ) ), row_id="r2" ) ]
    assert train( world, two )[ "refused" ] == [ { "package": "a", "reason": "2 claim rows for this package" } ]


def test_the_checks_directory_must_be_durable_present_and_passing( world, tmp_path ):
    s     = world.shas
    other = tmp_path / "other"
    other.mkdir()
    hot   = tmp_path / "hot" / "real"
    hot.mkdir( parents=True )
    ( hot / "result.json" ).write_text( '{"pass": true}', encoding="utf-8" )
    ( world.data / "link" ).symlink_to( hot )
    broken = world.data / "broken"
    broken.mkdir()
    ( broken / "result.json" ).write_text( "not json", encoding="utf-8" )
    ( broken / "history-destination.json" ).write_text( '{"pass": true}', encoding="utf-8" )
    nolist = world.data / "nolist"
    nolist.mkdir()
    ( nolist / "result.json" ).write_text( "[1]", encoding="utf-8" )
    missing = world.data / "partial"
    missing.mkdir()
    ( missing / "result.json" ).write_text( '{"pass": true}', encoding="utf-8" )
    truthy = world.data / "truthy"
    truthy.mkdir()
    ( truthy / "result.json" ).write_text( '{"pass": "yes"}', encoding="utf-8" )
    ( truthy / "history-destination.json" ).write_text( '{"pass": true}', encoding="utf-8" )
    cases = [
        ( truthy, "does not say pass" ),
        ( hot, "is under a temp directory" ), ( world.data / "link", "is under a temp directory" ), ( other, "is not under" ),
        ( world.data / "gone", "does not exist" ), ( broken, "result.json in" ), ( nolist, "does not say pass" ), ( missing, "history-destination.json in" ),
        ( checks_dir( world, "r_fail", result_pass=False ), "result.json in" ), ( checks_dir( world, "h_fail", history_pass=False ), "history-destination.json in" ) ]
    for path, fragment in cases:
        reason = refusal_for( world, stamped( ( "Tiberius 9f3a1b2c", approval( path, [ s[ "one" ] ] ) ) ) )
        assert fragment in reason, ( path, reason )


def test_the_real_temp_roots_are_the_usual_three_and_refuse_a_checks_directory_under_them():
    assert tb.TEMP_ROOTS == ( "/tmp", "/var/tmp", "/dev/shm" )
    for root in tb.TEMP_ROOTS:
        assert tb.checks_problem( f"{root}/some-checks", root ) == f"checks directory {root}/some-checks is under a temp directory"


def test_store_rows_reads_the_repository_directly_and_scoped( monkeypatch ):
    seen = {}
    item = types.SimpleNamespace( id="uuid-1", title="docs sweep: a", owner_persona="Rio", status="queued", body="b" )
    class FakeRepo:
        def __init__( self, session ): seen[ "session" ] = session
        def query_tasks( self, **kwargs ):
            seen[ "kwargs" ] = kwargs
            return [ item ]
    @contextlib.contextmanager
    def fake_get_db():
        yield "SESSION"
    monkeypatch.setitem( sys.modules, "cosa.rest.db.database", types.SimpleNamespace( get_db=fake_get_db ) )
    monkeypatch.setitem( sys.modules, "cosa.rest.db.repositories.task_repository", types.SimpleNamespace( TaskRepository=FakeRepo ) )
    assert tb.store_rows() == [ { "id": "uuid-1", "title": "docs sweep: a", "owner_persona": "Rio", "status": "queued", "body": "b" } ]
    assert seen[ "session" ] == "SESSION"
    assert seen[ "kwargs" ] == { "project": "lupin", "correlation_key": "epic:v022-docs-and-reuse", "include_terminal": True, "limit": 1000 }


def _write( path, content ):
    path.write_text( json.dumps( content ), encoding="utf-8" )
    return str( path )


def test_main_builds_a_train_json_from_rows_and_a_pinned_sweep_order( world, tmp_path ):
    s      = world.shas
    rows   = _write( tmp_path / "rows.json", [ claim( "a", stamped( ( "Tiberius 9f3a1b2c", approval( checks_dir( world, "mc" ), [ s[ "one" ] ] ) ) ) ), claim( "b", "x" ) ] )
    order  = _write( tmp_path / "order.json", { "packages": [ { "package": "b" }, { "package": "a" } ] } )
    stream = io.StringIO()
    code   = tb.main( [ "--repo-root", str( world.root ), "--out", str( tmp_path / "o" / "deep" ), "--rows-json", rows, "--sweep-json", order, "--data-root", str( world.data ) ], stream )
    result = json.loads( ( tmp_path / "o" / "deep" / "train.json" ).read_text( encoding="utf-8" ) )
    assert result[ "size" ] == 11 == tb.DEFAULT_SIZE
    assert code == 0 and result[ "bisect_order" ] == [ "a" ] and result[ "refused_run" ] is None and result[ "refused" ] == [ { "package": "b", "reason": "no approval amendment" } ]
    assert stream.getvalue() == f"REFUSED b: no approval amendment\ntrain of 1 packages, 1 commits, 1 refused, 0 deferred, at {result[ 'head' ]}\n"


def test_main_with_no_approved_package_exits_1_and_writes_every_key( world, tmp_path ):
    rows = _write( tmp_path / "rows.json", [ claim( "a", "x" ) ] )
    code = tb.main( [ "--repo-root", str( world.root ), "--out", str( tmp_path / "o" ), "--rows-json", rows, "--data-root", str( world.data ) ], io.StringIO() )
    result = json.loads( ( tmp_path / "o" / "train.json" ).read_text( encoding="utf-8" ) )
    assert code == 1 and result[ "packages" ] == [] and result[ "refused" ] == [ { "package": "a", "reason": "no approval amendment" } ]
    assert set( result ) == { "head", "size", "packages", "commits", "bisect_order", "deferred", "refused", "not_claimed", "refused_run" }


@pytest.mark.parametrize( "extra, message", [
    ( [ "--size", "0" ], "ValueError: --size must be at least 1" ),
    ( [ "--rows-json", "/no/such/rows.json" ], "FileNotFoundError" ),
    ( [ "--sweep-json", "EMPTY" ], "KeyError" ) ] )
def test_a_run_that_cannot_start_exits_2_with_a_full_train_json( world, tmp_path, extra, message ):
    rows  = _write( tmp_path / "rows.json", [] )
    extra = [ _write( tmp_path / "empty.json", {} ) if x == "EMPTY" else x for x in extra ]
    base  = [] if "--rows-json" in extra else [ "--rows-json", rows ]
    stream = io.StringIO()
    code   = tb.main( [ "--repo-root", str( world.root ), "--out", str( tmp_path / "o" ), *base, *extra ], stream )
    result = json.loads( ( tmp_path / "o" / "train.json" ).read_text( encoding="utf-8" ) )
    assert code == 2 and message in result[ "refused_run" ] and result[ "packages" ] == [] and result[ "head" ] is None
    assert stream.getvalue() == f"REFUSED: {result[ 'refused_run' ]}\n"


def test_main_reads_the_store_and_runs_a_live_sweep_when_no_files_are_given( world, tmp_path, monkeypatch, capsys ):
    s = world.shas
    monkeypatch.setattr( tb, "store_rows", lambda: [ claim( "a", stamped( ( "Tiberius 9f3a1b2c", approval( checks_dir( world, "live" ), [ s[ "one" ] ] ) ) ) ) ] )
    monkeypatch.setattr( "sys.argv", [ "x", "--repo-root", str( world.root ), "--out", str( tmp_path / "o" ), "--data-root", str( world.data ), "--size", "3" ] )
    assert tb.main() == 0
    result = json.loads( ( tmp_path / "o" / "train.json" ).read_text( encoding="utf-8" ) )
    assert result[ "bisect_order" ] == [ "a" ] and result[ "size" ] == 3 and result[ "not_claimed" ] == 3
    assert capsys.readouterr().out.startswith( "train of 1 packages" )


def test_the_train_keeps_sweep_order_not_alphabetical_order( world ):
    s    = world.shas
    rows = [ claim( p, stamped( ( "Tiberius 9f3a1b2c", approval( checks_dir( world, "k" + p ), [ s[ "one" ] ] ) ) ) ) for p in ( "a", "c" ) ]
    result = tb.build_train( world.root, rows, [ "c", "a" ], 11, str( world.data ) )
    assert result[ "bisect_order" ] == [ "c", "a" ] and [ p[ "package" ] for p in result[ "packages" ] ] == [ "c", "a" ]
