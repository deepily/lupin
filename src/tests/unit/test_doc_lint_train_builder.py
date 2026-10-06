"""
train_builder: which approved packages go in one train, read from sweep claim rows.

The claim rows are plain dicts shaped like the store's rows. Their bodies use the format
TaskRepository.apply_amendment stamps, and a test asserts the repository's own stamp pattern sees them.
Everything else is real: a small git repo in a temp directory, real commits, real checks directories.
"""

import contextlib
import hashlib
import io
import json
import subprocess
import sys
import types
from datetime import datetime, timezone

import pytest

from cosa.repo.doc_lint import train_builder as tb, word_list
from cosa.rest.task_store_prose_refs import strip_amendment_stamps

OWNER  = "Cheech"
TS     = "2026-10-05T22:02:28.169063+00:00"
WRITER = "Mr. Radio"
TIB    = "Tiberius 9f3a1b2c"


def _git( root, *args ):
    res = subprocess.run( [ "git", "-C", str( root ), "-c", "user.email=t@t", "-c", "user.name=t", *args ], capture_output=True, text=True )
    assert res.returncode == 0, res.stderr
    return res.stdout.strip()


def stamped( *blocks ):
    """Join ( actor, note ) blocks as apply_amendment does: a divider line, then the note."""
    return "\n\n".join( f"[amendment · {actor} · {TS}]\n{note}" for actor, note in blocks )


def hashes_of( checks ):
    return { name: hashlib.sha256( ( checks / name ).read_bytes() ).hexdigest() for name in tb.CHECK_FILES }


def approval( checks, commits, verdict="pass", hashes=None ):
    return tb.APPROVAL_PREFIX + " " + json.dumps( { "checks": str( checks ), "commits": commits, "verdict": verdict, "sha256": hashes_of( checks ) if hashes is None else hashes } )


def claim_line( package, writer=WRITER ):
    return tb.CLAIM_PREFIX + " " + json.dumps( { "package": package, "writer": writer } )


def event( actor=TIB, transition="amended", ts=TS ):
    return { "actor": actor, "transition": transition, "ts": ts }


def claim( package, blocks=(), writer=WRITER, owner=OWNER, status="queued", title=None, events=None, row_id=None, claim_text=None ):
    """A claim row as the store hands it over: claim line, stamped amendments, audit trail."""
    body = ( claim_text if claim_text is not None else claim_line( package, writer ) ) + ( "\n\n" + stamped( *blocks ) if blocks else "" )
    return { "id": row_id or f"id-{package}", "title": title or f"docs sweep: {package}", "owner_persona": owner, "status": status, "body": body,
             "events": [ event( actor ) for actor, _ in blocks ] if events is None else events }


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


def checks_dir( world, name, package="a", result_pass=True, history_pass=True ):
    path = world.data / name
    path.mkdir()
    ( path / "result.json" ).write_text( json.dumps( { "pass": result_pass, "package": package } ), encoding="utf-8" )
    ( path / "history-destination.json" ).write_text( json.dumps( { "pass": history_pass } ), encoding="utf-8" )
    return path


def approved_row( world, package="a", name=None, commits=None, **kw ):
    checks = checks_dir( world, name or "c" + package, package )
    return claim( package, [ ( TIB, approval( checks, commits or [ world.shas[ "one" ] ] ) ) ], **kw ), checks


def train( world, rows, size=11, order=( "a", "b", "c", "d" ) ):
    return tb.build_train( world.root, rows, list( order ), size, str( world.data ) )


def refusal_for( world, row ):
    result = train( world, [ row ] )
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


def test_the_claim_line_is_read_from_the_text_before_the_first_amendment_and_malformed_ones_are_errors():
    line = claim_line( "pkg/x", "María" )
    assert tb.claim_of( "intro\n" + line + "\n\nmore" ) == { "package": "pkg/x", "writer": "María" }
    assert tb.claim_of( None ) is None and tb.claim_of( "" ) is None and tb.claim_of( "no claim here" ) is None
    assert tb.claim_of( "x\n\n" + stamped( ( TIB, line ) ) ) is None
    assert tb.claim_of( "see " + line ) is None
    for bad, message in ( ( tb.CLAIM_PREFIX + " {nope", "the claim line is not JSON" ), ( tb.CLAIM_PREFIX + " [1]", "the claim line needs a package and a writer" ),
                          ( tb.CLAIM_PREFIX + ' {"package": "a"}', "the claim line needs a package and a writer" ), ( tb.CLAIM_PREFIX + ' {"package": "a", "writer": 3}', "the claim line needs" ),
                          ( tb.CLAIM_PREFIX + ' {"package": 3, "writer": "w"}', "the claim line needs" ) ):
        with pytest.raises( ValueError, match=message ):
            tb.claim_of( bad )


@pytest.mark.parametrize( "events, actor, stamp, expected", [
    ( [ event() ], TIB, TS, True ),
    ( [ event( transition="amended_post_terminal" ) ], TIB, TS, True ),
    ( [ event( ts="2026-10-05T22:03:28.000000+00:00" ) ], TIB, TS, True ),
    ( [ event( ts="2026-10-05T22:04:29.000000+00:00" ) ], TIB, TS, False ),
    ( [ event( ts="2026-10-05T22:00:27.000000+00:00" ) ], TIB, TS, False ),
    ( [ event( actor="Maria 1a2b3c4d" ) ], TIB, TS, False ),
    ( [ event( transition="queued->in_progress" ) ], TIB, TS, False ),
    ( [ event( ts="2026-10-05T22:02:28.169063" ) ], TIB, TS, True ),
    ( [ event() ], TIB, "2026-10-05T22:02:28.169063", True ),
    ( [ event() ], TIB, "not a time", False ),
    ( [ event( ts="not a time" ) ], TIB, TS, False ),
    ( [ { "actor": TIB, "transition": "amended" } ], TIB, TS, False ),
    ( [ event( ts=None ) ], TIB, TS, False ),
    ( [], TIB, TS, False ) ] )
def test_event_agrees_needs_a_real_amended_event_by_that_actor_within_two_minutes( events, actor, stamp, expected ):
    assert tb.event_agrees( events, actor, stamp ) is expected


def test_a_train_holds_the_approved_packages_in_sweep_order_with_commits_and_bisect_order( world ):
    s = world.shas
    row_c, check_c = approved_row( world, "c", commits=[ s[ "three" ], s[ "two" ] ], title="[LUPIN] docs sweep: c" )
    row_a, check_a = approved_row( world, "a", commits=[ s[ "one" ], s[ "two" ] ] )
    stray = [ claim( "a", title=t ) for t in ( "other thing:a", "note: docs sweep: a", "[LUPIN] [LUPIN] docs sweep: a", "docs sweep:a", "docs sweep: " ) ]
    result = train( world, [ row_c, row_a, claim( "b" ), *stray ] )
    assert [ p[ "package" ] for p in result[ "packages" ] ] == [ "a", "c" ] and result[ "bisect_order" ] == [ "a", "c" ]
    assert result[ "commits" ] == [ s[ "one" ], s[ "two" ], s[ "three" ] ]
    assert result[ "refused" ] == [ { "package": "b", "reason": "no approval amendment" } ] and result[ "not_claimed" ] == 1 and result[ "deferred" ] == []
    assert result[ "head" ] == _git( world.root, "rev-parse", "HEAD" ) and result[ "size" ] == 11
    assert result[ "packages" ][ 0 ] == { "package": "a", "row_id": "id-a", "approver": TIB, "checks": str( check_a ), "commits": [ s[ "one" ], s[ "two" ] ] }


def test_the_size_cut_defers_the_rest_and_takes_only_the_cut_packages_commits( world ):
    s    = world.shas
    rows = [ approved_row( world, p, commits=[ s[ "one" ] if p == "a" else s[ "three" ] ] )[ 0 ] for p in ( "a", "b", "c" ) ]
    result = train( world, rows, size=1 )
    assert [ p[ "package" ] for p in result[ "packages" ] ] == [ "a" ] and result[ "bisect_order" ] == [ "a" ]
    assert result[ "deferred" ] == [ "b", "c" ] and result[ "commits" ] == [ s[ "one" ] ]


def test_the_train_keeps_sweep_order_not_alphabetical_order( world ):
    rows   = [ approved_row( world, p )[ 0 ] for p in ( "a", "c" ) ]
    result = train( world, rows, order=( "c", "a" ) )
    assert result[ "bisect_order" ] == [ "c", "a" ] and [ p[ "package" ] for p in result[ "packages" ] ] == [ "c", "a" ]


def test_the_latest_approval_wins_and_a_later_failing_verdict_refuses( world ):
    checks, s = checks_dir( world, "c1" ), world.shas
    good = approval( checks, [ s[ "one" ] ] )
    bad  = approval( checks, [ s[ "one" ] ], "fail" )
    assert refusal_for( world, claim( "a", [ ( TIB, "reviewed the six checks\n" + good ), ( "Maria 1a2b3c4d", bad ) ] ) ) == "verdict is 'fail', not pass"
    assert refusal_for( world, claim( "a", [ ( "Maria 1a2b3c4d", bad ), ( TIB, good ) ] ) )[ 0 ][ "approver" ] == TIB


def test_an_approval_line_must_start_a_line_a_note_quoting_it_is_not_an_approval( world ):
    checks = checks_dir( world, "q" )
    quoted = "the format is " + approval( checks, [ world.shas[ "one" ] ] )
    assert refusal_for( world, claim( "a", [ ( TIB, quoted ) ] ) ) == "no approval amendment"


def test_a_stamp_typed_into_the_body_with_no_amended_event_is_refused_as_forged( world ):
    row, _ = approved_row( world )
    row[ "events" ] = []
    assert refusal_for( world, row ) == f"no amended event by {TIB} confirms the approval stamp"
    row[ "events" ] = [ event( actor="Somebody 1a2b3c4d" ) ]
    assert refusal_for( world, row ) == f"no amended event by {TIB} confirms the approval stamp"
    row[ "events" ] = None
    assert refusal_for( world, row ) == f"no amended event by {TIB} confirms the approval stamp"
    del row[ "events" ]
    assert refusal_for( world, row ) == f"no amended event by {TIB} confirms the approval stamp"


def test_the_approver_is_neither_the_writer_named_on_the_row_nor_its_owner( world ):
    row, _ = approved_row( world, writer="Tiberius" )
    assert refusal_for( world, row ) == f"approved by its writer ({TIB})"
    row, _ = approved_row( world, name="c2", writer="María", owner="tiberius" )
    assert refusal_for( world, row ) == f"approved by its owner ({TIB})"
    row, _ = approved_row( world, name="c3", writer="Tiberius", owner=None )
    assert "approved by its writer" in refusal_for( world, row )
    row, _ = approved_row( world, name="c4", owner=None )
    assert refusal_for( world, row )[ 0 ][ "package" ] == "a"


def test_the_claim_line_is_required_and_must_name_this_package( world ):
    row, _ = approved_row( world )
    row[ "body" ] = row[ "body" ].replace( claim_line( "a" ) + "\n\n", "" )
    assert refusal_for( world, row ) == "no docs-sweep-claim line naming the writer"
    row, _ = approved_row( world, name="c2", claim_text=claim_line( "other" ) )
    assert refusal_for( world, row ) == "the claim line names 'other', not 'a'"
    row, _ = approved_row( world, name="c3", claim_text=tb.CLAIM_PREFIX + " {nope" )
    assert refusal_for( world, row ).startswith( "the claim line is not JSON" )


@pytest.mark.parametrize( "status", [ "not_approved", "queued", "in_progress", "blocked" ] )
def test_a_claim_row_in_a_live_status_may_go( world, status ):
    row, _ = approved_row( world, status=status )
    assert train( world, [ row ] )[ "bisect_order" ] == [ "a" ]


def test_a_done_claim_row_is_left_out_and_listed_as_landed_not_refused( world ):
    done, _ = approved_row( world, row_id="r-done", status="done" )
    live, _ = approved_row( world, package="b", name="cb", commits=[ world.shas[ "two" ] ] )
    result  = train( world, [ done, live ] )
    assert result[ "bisect_order" ] == [ "b" ] and result[ "commits" ] == [ world.shas[ "two" ] ]
    assert result[ "landed" ] == [ { "package": "a", "row_ids": [ "r-done" ] } ] and result[ "refused" ] == []


def test_a_done_row_beside_a_live_row_for_the_same_package_is_ignored_not_counted_as_a_second_claim( world ):
    done, _ = approved_row( world, row_id="r-done", status="done" )
    live, _ = approved_row( world, row_id="r-live", name="c2", status="in_progress" )
    result  = train( world, [ done, live ] )
    assert result[ "bisect_order" ] == [ "a" ] and result[ "landed" ] == [] and result[ "refused" ] == []


@pytest.mark.parametrize( "status", [ "dropped", "parked" ] )
def test_a_dropped_or_parked_claim_row_is_refused( world, status ):
    row, _ = approved_row( world, status=status )
    assert refusal_for( world, row ) == f"the claim row is {status}"


def test_the_approval_line_and_verdict_refusals_each_name_their_reason( world ):
    checks, s = checks_dir( world, "ok" ), world.shas
    def refuse( line ): return refusal_for( world, claim( "a", [ ( TIB, line ) ] ) )
    assert refuse( approval( checks, [ s[ "one" ] ], " PASS " ) )[ 0 ][ "package" ] == "a"
    assert refuse( approval( checks, [ s[ "one" ] ], "pass with findings" ) ) == "verdict is 'pass with findings', not pass"
    for line in ( tb.APPROVAL_PREFIX + " {nope", tb.APPROVAL_PREFIX + " [1]" ):
        assert "approval line is not" in refuse( line )
    good = { "checks": str( checks ), "commits": [ s[ "one" ] ], "verdict": "pass", "sha256": hashes_of( checks ) }
    for key, value in ( ( "checks", None ), ( "commits", [] ), ( "commits", s[ "one" ] ), ( "commits", [ 1 ] ), ( "verdict", True ), ( "sha256", None ), ( "sha256", [ "x" ] ) ):
        payload = { k: v for k, v in good.items() if k != key } if value is None else { **good, key: value }
        assert refuse( tb.APPROVAL_PREFIX + " " + json.dumps( payload ) ) == "the approval line needs checks (a path), commits (a non-empty list), verdict and sha256 (a dict)", ( key, value )


def test_a_listed_commit_must_be_a_full_sha_that_exists( world ):
    checks, s = checks_dir( world, "ok" ), world.shas
    def refuse( commits ): return refusal_for( world, claim( "a", [ ( TIB, approval( checks, commits ) ) ] ) )
    assert refuse( [ s[ "one" ][ :12 ] ] ) == f"commit {s[ 'one' ][ :12 ]} is not a full 40-character sha"
    assert refuse( [ "HEAD" ] ) == "commit HEAD is not a full 40-character sha"
    assert refuse( [ s[ "one" ].upper() ] ) == f"commit {s[ 'one' ].upper()} is not a full 40-character sha"
    assert refuse( [ s[ "one" ] + "0" ] ).endswith( "is not a full 40-character sha" )
    assert refuse( [ "0" * 40 ] ) == f"commit {'0' * 40} does not exist"
    assert refuse( [ s[ "one" ], "0" * 40 ] ) == f"commit {'0' * 40} does not exist"


def test_the_checks_directory_must_be_durable_whole_passing_and_this_packages( world, tmp_path ):
    s     = world.shas
    other = tmp_path / "other"
    other.mkdir()
    sibling = tmp_path / "data-mobile"
    sibling.mkdir()
    hot = tmp_path / "hot" / "real"
    hot.mkdir( parents=True )
    ( hot / "result.json" ).write_text( '{"pass": true, "package": "a"}', encoding="utf-8" )
    ( world.data / "link" ).symlink_to( hot )
    broken = world.data / "broken"
    broken.mkdir()
    ( broken / "result.json" ).write_text( "not json", encoding="utf-8" )
    ( broken / "history-destination.json" ).write_text( '{"pass": true}', encoding="utf-8" )
    nolist = world.data / "nolist"
    nolist.mkdir()
    ( nolist / "result.json" ).write_text( "[1]", encoding="utf-8" )
    partial = world.data / "partial"
    partial.mkdir()
    ( partial / "result.json" ).write_text( '{"pass": true, "package": "a"}', encoding="utf-8" )
    truthy = world.data / "truthy"
    truthy.mkdir()
    ( truthy / "result.json" ).write_text( '{"pass": "yes", "package": "a"}', encoding="utf-8" )
    ( truthy / "history-destination.json" ).write_text( '{"pass": true}', encoding="utf-8" )
    cases = [
        ( truthy, "does not say pass" ), ( hot, "is under a temp directory" ), ( world.data / "link", "is under a temp directory" ), ( other, "is not under" ), ( sibling, "is not under" ),
        ( world.data / "gone", "does not exist" ), ( broken, "result.json in" ), ( nolist, "does not say pass" ), ( partial, "history-destination.json in" ),
        ( checks_dir( world, "r_fail", result_pass=False ), "result.json in" ), ( checks_dir( world, "h_fail", history_pass=False ), "history-destination.json in" ),
        ( checks_dir( world, "wrongpkg", package="src/cosa/OTHER" ), "is for 'src/cosa/OTHER', not 'a'" ) ]
    for path, fragment in cases:
        reason = refusal_for( world, claim( "a", [ ( TIB, approval( path, [ s[ "one" ] ], hashes={ n: ( hashlib.sha256( ( path / n ).read_bytes() ).hexdigest() if ( path / n ).exists() else "x" ) for n in tb.CHECK_FILES } ) ) ] ) )
        assert fragment in reason, ( path, reason )
    row, checks = approved_row( world, name="edited" )
    ( checks / "history-destination.json" ).write_text( '{"pass": true, "note": "edited later"}', encoding="utf-8" )
    assert refusal_for( world, row ) == f"history-destination.json in {checks} has changed since it was approved"
    ( checks / "result.json" ).write_text( '{"pass": true, "package": "a", "extra": 1}', encoding="utf-8" )
    row2, checks2 = approved_row( world, name="edited2" )
    row2[ "body" ] = row2[ "body" ].replace( hashes_of( checks2 )[ "result.json" ], "0" * 64 )
    assert refusal_for( world, row2 ) == f"result.json in {checks2} has changed since it was approved"
    nohash, _ = approved_row( world, name="nohash" )
    nohash[ "body" ] = nohash[ "body" ].replace( '"sha256": {', '"sha256": {"x": "y", ' ).replace( '"result.json": "', '"renamed.json": "', 1 )
    assert "has changed since it was approved" in refusal_for( world, nohash )


def test_the_real_temp_roots_and_data_root_are_pinned_and_the_exact_temp_root_is_refused():
    assert tb.TEMP_ROOTS == ( "/tmp", "/var/tmp", "/dev/shm" )
    assert tb.DEFAULT_DATA_ROOT == "/mnt/DATA01/include/www.deepily.ai/projects-data/lupin" and tb.DEFAULT_SIZE == 11
    for root in tb.TEMP_ROOTS:
        assert tb.checks_problem( f"{root}/some-checks", root, "a", {} ) == f"checks directory {root}/some-checks is under a temp directory"
        assert tb.checks_problem( root, root, "a", {} ) == f"checks directory {root} is under a temp directory"
    assert tb.checks_problem( "/mnt/DATA01/include/www.deepily.ai/projects-data/lupin-mobile/x", tb.DEFAULT_DATA_ROOT, "a", {} ).endswith( f"is not under {tb.DEFAULT_DATA_ROOT}" )
    assert tb.checks_problem( "/etc", tb.DEFAULT_DATA_ROOT, "a", {} ).endswith( f"is not under {tb.DEFAULT_DATA_ROOT}" )


def test_a_claim_for_a_package_not_in_the_sweep_list_is_refused_by_name_and_two_rows_are_refused( world ):
    good, _ = approved_row( world )
    typo = claim( "a/", title="docs sweep: a/" )
    result = train( world, [ good, typo, claim( "zzz" ) ] )
    assert result[ "bisect_order" ] == [ "a" ]
    assert result[ "refused" ] == [ { "package": "a/", "reason": "a claim for a package that is not in the sweep list" }, { "package": "zzz", "reason": "a claim for a package that is not in the sweep list" } ]
    two = [ claim( "b", row_id="r1" ), claim( "b", row_id="r2" ) ]
    assert train( world, two )[ "refused" ] == [ { "package": "b", "reason": "2 claim rows for this package" } ]


def test_store_rows_reads_the_repository_directly_scoped_and_with_each_rows_audit_trail( monkeypatch ):
    seen = {}
    item = types.SimpleNamespace( id="uuid-1", title="docs sweep: a", owner_persona="Rio", status="queued", body="b" )
    when = datetime( 2026, 10, 5, 22, 2, 28, tzinfo=timezone.utc )
    class FakeRepo:
        def __init__( self, session ): seen[ "session" ] = session
        def query_tasks( self, **kwargs ):
            seen[ "kwargs" ] = kwargs
            return [ item ]
        def get_events( self, item_id ):
            seen[ "events_for" ] = item_id
            return [ types.SimpleNamespace( actor=TIB, transition="amended", ts=when, reason=None ) ]
    @contextlib.contextmanager
    def fake_get_db():
        yield "SESSION"
    monkeypatch.setitem( sys.modules, "cosa.rest.db.database", types.SimpleNamespace( get_db=fake_get_db ) )
    monkeypatch.setitem( sys.modules, "cosa.rest.db.repositories.task_repository", types.SimpleNamespace( TaskRepository=FakeRepo ) )
    assert tb.store_rows() == [ { "id": "uuid-1", "title": "docs sweep: a", "owner_persona": "Rio", "status": "queued", "body": "b", "events": [ { "actor": TIB, "transition": "amended", "ts": when.isoformat(), "reason": None } ] } ]
    assert seen[ "session" ] == "SESSION" and seen[ "events_for" ] == "uuid-1"
    assert seen[ "kwargs" ] == { "project": "lupin", "correlation_key": "epic:v022-docs-and-reuse", "include_terminal": True, "limit": 1000 }


def _write( path, content ):
    path.write_text( json.dumps( content ), encoding="utf-8" )
    return str( path )


def test_main_builds_a_train_json_from_rows_and_a_pinned_sweep_order( world, tmp_path ):
    row, _ = approved_row( world, name="mc" )
    rows   = _write( tmp_path / "rows.json", [ row, claim( "b" ) ] )
    order  = _write( tmp_path / "order.json", { "packages": [ { "package": "b" }, { "package": "a" } ] } )
    stream = io.StringIO()
    code   = tb.main( [ "--repo-root", str( world.root ), "--out", str( tmp_path / "o" / "deep" ), "--rows-json", rows, "--sweep-json", order, "--data-root", str( world.data ) ], stream )
    result = json.loads( ( tmp_path / "o" / "deep" / "train.json" ).read_text( encoding="utf-8" ) )
    assert result[ "size" ] == 11
    assert code == 0 and result[ "bisect_order" ] == [ "a" ] and result[ "refused_run" ] is None and result[ "refused" ] == [ { "package": "b", "reason": "no approval amendment" } ]
    assert stream.getvalue() == f"REFUSED b: no approval amendment\ntrain of 1 packages, 1 commits, 1 refused, 0 landed, 0 deferred, at {result[ 'head' ]}\n"


def test_main_with_no_approved_package_exits_1_and_writes_every_key( world, tmp_path ):
    rows = _write( tmp_path / "rows.json", [ claim( "a" ) ] )
    code = tb.main( [ "--repo-root", str( world.root ), "--out", str( tmp_path / "o" ), "--rows-json", rows, "--data-root", str( world.data ) ], io.StringIO() )
    result = json.loads( ( tmp_path / "o" / "train.json" ).read_text( encoding="utf-8" ) )
    assert code == 1 and result[ "packages" ] == [] and result[ "refused" ] == [ { "package": "a", "reason": "no approval amendment" } ]
    assert set( result ) == { "head", "size", "packages", "commits", "bisect_order", "deferred", "refused", "landed", "not_claimed", "refused_run" }


@pytest.mark.parametrize( "extra, message", [
    ( [ "--size", "0" ], "ValueError: --size must be at least 1" ),
    ( [ "--rows-json", "/no/such/rows.json" ], "FileNotFoundError" ),
    ( [ "--sweep-json", "EMPTY" ], "KeyError" ),
    ( [ "--rows-json", "NULLTITLE" ], "TypeError" ),
    ( [ "--rows-json", "BADROW" ], "KeyError" ) ] )
def test_a_run_that_cannot_start_exits_2_with_a_full_train_json( world, tmp_path, extra, message ):
    rows  = _write( tmp_path / "rows.json", [] )
    swaps = { "EMPTY": _write( tmp_path / "empty.json", {} ), "NULLTITLE": _write( tmp_path / "null.json", [ { "id": "x", "title": None } ] ), "BADROW": _write( tmp_path / "bad.json", [ { "id": "x" } ] ) }
    extra = [ swaps.get( x, x ) for x in extra ]
    base  = [] if "--rows-json" in extra else [ "--rows-json", rows ]
    stream = io.StringIO()
    code   = tb.main( [ "--repo-root", str( world.root ), "--out", str( tmp_path / "o" ), *base, *extra ], stream )
    result = json.loads( ( tmp_path / "o" / "train.json" ).read_text( encoding="utf-8" ) )
    assert code == 2 and message in result[ "refused_run" ] and result[ "packages" ] == [] and result[ "head" ] is None
    assert stream.getvalue() == f"REFUSED: {result[ 'refused_run' ]}\n"


def test_any_other_exception_still_writes_a_full_train_json( world, tmp_path, monkeypatch ):
    def boom( *args ): raise ZeroDivisionError( "odd" )
    monkeypatch.setattr( tb, "build_train", boom )
    rows = _write( tmp_path / "rows.json", [] )
    code = tb.main( [ "--repo-root", str( world.root ), "--out", str( tmp_path / "o" ), "--rows-json", rows ], io.StringIO() )
    assert code == 2 and json.loads( ( tmp_path / "o" / "train.json" ).read_text( encoding="utf-8" ) )[ "refused_run" ] == "ZeroDivisionError: odd"


def test_main_reads_the_store_and_runs_a_live_sweep_when_no_files_are_given( world, tmp_path, monkeypatch, capsys ):
    row, _ = approved_row( world, name="live" )
    monkeypatch.setattr( tb, "store_rows", lambda: [ row ] )
    monkeypatch.setattr( "sys.argv", [ "x", "--repo-root", str( world.root ), "--out", str( tmp_path / "o" ), "--data-root", str( world.data ), "--size", "3" ] )
    assert tb.main() == 0
    result = json.loads( ( tmp_path / "o" / "train.json" ).read_text( encoding="utf-8" ) )
    assert result[ "bisect_order" ] == [ "a" ] and result[ "size" ] == 3 and result[ "not_claimed" ] == 3
    assert capsys.readouterr().out.startswith( "train of 1 packages" )


def test_a_title_that_runs_over_a_second_line_is_not_a_claim( world ):
    result = train( world, [ claim( "a", title="docs sweep: a\nand a second line" ) ] )
    assert result[ "refused" ] == [] and result[ "not_claimed" ] == 4


@pytest.mark.parametrize( "ts, expected", [
    ( "2026-10-05T22:04:28.169063+00:00", True ),
    ( "2026-10-05T22:04:28.169064+00:00", False ),
    ( "2026-10-05T22:00:28.169063+00:00", True ),
    ( "2026-10-05T22:00:28.169062+00:00", False ) ] )
def test_event_agrees_at_the_exact_two_minute_edge_counts_but_one_microsecond_past_it_does_not( ts, expected ):
    assert tb.event_agrees( [ event( ts=ts ) ], TIB, TS ) is expected


def test_persona_of_strips_only_a_whole_trailing_8_hex_session_id_after_trimming_the_edges():
    assert tb.persona_of( "Tiberius 9f3a1b2c0" ) == "tiberius9f3a1b2c0"
    assert tb.persona_of( "Tiberius 9f3a1b2c " ) == "tiberius"


def test_a_checks_directory_whose_name_only_begins_like_a_temp_root_is_not_under_it( world ):
    sibling = world.root / "hotel"
    path    = sibling / "ca"
    path.mkdir( parents=True )
    ( path / "result.json" ).write_text( json.dumps( { "pass": True, "package": "a" } ), encoding="utf-8" )
    ( path / "history-destination.json" ).write_text( json.dumps( { "pass": True } ), encoding="utf-8" )
    assert tb.checks_problem( str( path ), str( sibling ), "a", hashes_of( path ) ) is None


def test_a_data_root_given_as_a_link_is_resolved_before_the_checks_directory_is_compared_to_it( world ):
    link   = world.root / "datalink"
    link.symlink_to( world.data )
    checks = checks_dir( world, "viaLink" )
    assert tb.checks_problem( str( checks ), str( link ), "a", hashes_of( checks ) ) is None


def test_the_data_root_itself_passes_the_location_check_and_fails_only_for_what_it_lacks( world ):
    assert "cannot be read" in tb.checks_problem( str( world.data ), str( world.data ), "a", {} )


def test_a_listed_annotated_tag_is_resolved_to_the_commit_it_names( world ):
    _git( world.root, "tag", "-a", "v1", "-m", "tag", world.shas[ "one" ] )
    tag_sha = _git( world.root, "rev-parse", "v1" )
    assert tag_sha != world.shas[ "one" ]
    row, _  = approved_row( world, commits=[ tag_sha ] )
    assert train( world, [ row ] )[ "packages" ][ 0 ][ "commits" ] == [ world.shas[ "one" ] ]


def test_main_writes_train_json_into_an_out_directory_that_already_exists( world, tmp_path ):
    ( tmp_path / "o" ).mkdir()
    rows = _write( tmp_path / "rows.json", [ claim( "a" ) ] )
    code = tb.main( [ "--repo-root", str( world.root ), "--out", str( tmp_path / "o" ), "--rows-json", rows, "--data-root", str( world.data ) ], io.StringIO() )
    assert code == 1 and ( tmp_path / "o" / "train.json" ).is_file()


def test_a_run_that_cannot_start_keeps_the_size_it_was_asked_for( world, tmp_path ):
    code = tb.main( [ "--repo-root", str( world.root ), "--out", str( tmp_path / "o" ), "--rows-json", "/no/such/rows.json", "--size", "5" ], io.StringIO() )
    assert code == 2 and json.loads( ( tmp_path / "o" / "train.json" ).read_text( encoding="utf-8" ) )[ "size" ] == 5


def patched( reason, actor="Cheech 78067fb5", ts="2026-10-05T22:30:00+00:00" ):
    return { **event( actor, "patched", ts ), "reason": reason }


OVERWRITE = "body: 'old' -> 'new'"


def test_an_approved_row_whose_body_was_overwritten_afterwards_is_refused_naming_who_and_when( world ):
    row, _ = approved_row( world, events=[ event(), patched( OVERWRITE, "Maya 1a2b3c4d", "2026-10-05T23:15:00+00:00" ) ] )
    assert refusal_for( world, row ) == "the claim row body was overwritten by Maya 1a2b3c4d at 2026-10-05T23:15:00+00:00; mint a new claim row"


def test_a_body_overwrite_before_the_approval_is_refused_too( world ):
    row, _ = approved_row( world, events=[ patched( OVERWRITE ), event() ] )
    assert "was overwritten by Cheech 78067fb5" in refusal_for( world, row )


def test_a_row_with_only_amended_events_is_approved( world ):
    row, _ = approved_row( world, events=[ event(), event( "Maria 1a2b3c4d" ) ] )
    assert refusal_for( world, row )[ 0 ][ "package" ] == "a"


@pytest.mark.parametrize( "reason", [ "owner_persona: 'Rio' -> 'Maya'", "no-op patch (no field changed)", None, "priority: 1 -> 2 | reason: the body: of the row", "title: 'x' -> 'y'" ] )
def test_an_edit_that_does_not_change_the_body_is_not_an_overwrite( world, reason ):
    row, _ = approved_row( world, events=[ event(), patched( reason ) ] )
    assert refusal_for( world, row )[ 0 ][ "package" ] == "a"


@pytest.mark.parametrize( "reason", [ "body: 'a' -> 'b'", "title: 'x' -> 'y'; body: 'a' -> 'b'", "body: 'a' -> 'b' | reason: fix" ] )
def test_a_body_delta_is_found_first_or_after_other_fields( world, reason ):
    row, _ = approved_row( world, events=[ event(), patched( reason ) ] )
    assert "was overwritten" in refusal_for( world, row )


def test_a_body_delta_on_an_event_that_is_not_a_patch_is_not_an_overwrite( world ):
    row, _ = approved_row( world, events=[ event(), { **event( transition="amended_post_terminal" ), "reason": OVERWRITE } ] )
    assert refusal_for( world, row )[ 0 ][ "package" ] == "a"


def test_overwrite_event_returns_the_first_one_and_none_when_there_is_none():
    first, second = patched( OVERWRITE, "A 11111111" ), patched( OVERWRITE, "B 22222222" )
    assert tb.overwrite_event( [ event(), first, second ] ) is first and tb.overwrite_event( [ event() ] ) is None and tb.overwrite_event( [] ) is None


def test_store_rows_carries_each_events_reason( monkeypatch ):
    item = types.SimpleNamespace( id="u", title="docs sweep: a", owner_persona="Rio", status="queued", body="b" )
    when = datetime( 2026, 10, 5, 22, 2, 28, tzinfo=timezone.utc )
    class FakeRepo:
        def __init__( self, session ): pass
        def query_tasks( self, **kwargs ): return [ item ]
        def get_events( self, item_id ): return [ types.SimpleNamespace( actor=TIB, transition="patched", ts=when, reason=OVERWRITE ) ]
    @contextlib.contextmanager
    def fake_get_db():
        yield "SESSION"
    monkeypatch.setitem( sys.modules, "cosa.rest.db.database", types.SimpleNamespace( get_db=fake_get_db ) )
    monkeypatch.setitem( sys.modules, "cosa.rest.db.repositories.task_repository", types.SimpleNamespace( TaskRepository=FakeRepo ) )
    assert tb.store_rows()[ 0 ][ "events" ] == [ { "actor": TIB, "transition": "patched", "ts": when.isoformat(), "reason": OVERWRITE } ]


def test_a_title_with_another_bracket_prefix_is_not_a_claim( world ):
    result = train( world, [ claim( "a", title="[COSA] docs sweep: a" ), claim( "a", title="[LUPIN]docs sweep: a" ) ] )
    assert result[ "refused" ] == [] and result[ "not_claimed" ] == 4


def test_a_checks_file_that_differs_from_the_approved_one_by_a_trailing_newline_is_refused( world ):
    row, checks = approved_row( world )
    with open( checks / "result.json", "a", encoding="utf-8" ) as handle: handle.write( "\n" )
    assert refusal_for( world, row ) == f"result.json in {checks} has changed since it was approved"


def test_a_body_with_two_claim_lines_uses_the_first():
    body = claim_line( "pkg/first", "One" ) + "\n" + claim_line( "pkg/second", "Two" )
    assert tb.claim_of( body ) == { "package": "pkg/first", "writer": "One" }


WITHDRAWAL = tb.WITHDRAWAL_PREFIX + " reopened after a finding"


def test_a_withdrawal_line_voids_every_earlier_approval_and_names_who_and_when( world ):
    checks, s = checks_dir( world, "w1" ), world.shas
    good = approval( checks, [ s[ "one" ] ] )
    row  = claim( "a", [ ( TIB, good ), ( "Maria 1a2b3c4d", good ), ( TIB, WITHDRAWAL ) ] )
    assert refusal_for( world, row ) == f"the approval was withdrawn by {TIB} at {TS}"


def test_a_withdrawal_with_no_approval_line_is_a_withdrawal_not_a_missing_approval( world ):
    assert refusal_for( world, claim( "a", [ ( TIB, WITHDRAWAL ) ] ) ) == f"the approval was withdrawn by {TIB} at {TS}"


def test_an_approval_after_the_withdrawal_stands_and_one_before_it_does_not( world ):
    checks, s = checks_dir( world, "w2" ), world.shas
    good = approval( checks, [ s[ "one" ] ] )
    again = refusal_for( world, claim( "a", [ ( TIB, good ), ( TIB, WITHDRAWAL ), ( "Maria 1a2b3c4d", good ) ] ) )
    assert again[ 0 ][ "approver" ] == "Maria 1a2b3c4d"
    assert tb.approval_of( claim( "a", [ ( TIB, good ), ( TIB, WITHDRAWAL ) ] )[ "body" ] ) == ( None, None, None )


def test_line_order_inside_one_amendment_decides_which_of_approval_and_withdrawal_wins( world ):
    checks, s = checks_dir( world, "w3" ), world.shas
    good = approval( checks, [ s[ "one" ] ] )
    assert refusal_for( world, claim( "a", [ ( TIB, good + "\n" + WITHDRAWAL ) ] ) ) == f"the approval was withdrawn by {TIB} at {TS}"
    assert refusal_for( world, claim( "a", [ ( TIB, WITHDRAWAL + "\n" + good ) ] ) )[ 0 ][ "approver" ] == TIB


def test_a_note_that_only_quotes_the_withdrawal_prefix_mid_line_voids_nothing( world ):
    checks, s = checks_dir( world, "w4" ), world.shas
    row = claim( "a", [ ( TIB, approval( checks, [ s[ "one" ] ] ) ), ( TIB, "to undo, write a line starting " + WITHDRAWAL ) ] )
    assert refusal_for( world, row )[ 0 ][ "package" ] == "a"
    assert tb.withdrawal_of( row[ "body" ] ) is None


def test_a_withdrawal_needs_no_confirming_event_because_it_only_ever_blocks_a_package( world ):
    checks, s = checks_dir( world, "w5" ), world.shas
    row = claim( "a", [ ( TIB, approval( checks, [ s[ "one" ] ] ) ), ( "Maria 1a2b3c4d", WITHDRAWAL ) ], events=[ event( TIB ) ] )
    assert refusal_for( world, row ) == f"the approval was withdrawn by Maria 1a2b3c4d at {TS}"


def test_withdrawal_of_returns_the_last_unanswered_withdrawal_and_none_for_an_empty_body():
    body = stamped( ( TIB, WITHDRAWAL ), ( "Maria 1a2b3c4d", WITHDRAWAL ) )
    assert tb.withdrawal_of( body ) == ( "Maria 1a2b3c4d", TS )
    assert tb.withdrawal_of( None ) is None and tb.withdrawal_of( "" ) is None
    assert tb.withdrawal_of( stamped( ( TIB, WITHDRAWAL ), ( TIB, tb.APPROVAL_PREFIX + " {}" ) ) ) is None


BAD_LINE = tb.APPROVAL_PREFIX + ' {"checks": "x",}'


def test_a_bad_approval_line_that_a_later_good_approval_replaces_is_ignored( world ):
    checks, s = checks_dir( world, "w6" ), world.shas
    row = claim( "a", [ ( TIB, BAD_LINE ), ( TIB, approval( checks, [ s[ "one" ] ] ) ) ] )
    assert refusal_for( world, row )[ 0 ][ "package" ] == "a"


def test_a_bad_approval_line_that_a_later_withdrawal_voids_is_a_withdrawal_not_a_parse_error( world ):
    row = claim( "a", [ ( TIB, BAD_LINE ), ( TIB, WITHDRAWAL ) ] )
    assert refusal_for( world, row ) == f"the approval was withdrawn by {TIB} at {TS}"
    assert tb.approval_of( row[ "body" ] ) == ( None, None, None )


def test_a_bad_latest_approval_line_still_refuses_even_after_a_good_one_and_a_withdrawn_one( world ):
    checks, s = checks_dir( world, "w7" ), world.shas
    good = approval( checks, [ s[ "one" ] ] )
    assert "approval line is not JSON" in refusal_for( world, claim( "a", [ ( TIB, good ), ( TIB, BAD_LINE ) ] ) )
    assert "approval line is not JSON" in refusal_for( world, claim( "a", [ ( TIB, good ), ( TIB, WITHDRAWAL ), ( TIB, BAD_LINE ) ] ) )
    assert "approval line is not a JSON object" in refusal_for( world, claim( "a", [ ( TIB, good ), ( TIB, tb.APPROVAL_PREFIX + " [1]" ) ] ) )


def test_the_literal_withdrawal_string_the_brief_tells_reviewers_to_type_voids_the_approval( world ):
    checks, s = checks_dir( world, "w8" ), world.shas
    row = claim( "a", [ ( TIB, approval( checks, [ s[ "one" ] ] ) ), ( TIB, "docs-sweep-withdrawal: found a real loss" ) ] )
    assert refusal_for( world, row ) == f"the approval was withdrawn by {TIB} at {TS}"
    assert tb.WITHDRAWAL_PREFIX == "docs-sweep-withdrawal:" and tb.APPROVAL_PREFIX == "docs-sweep-approval:"


def test_main_prints_one_line_per_landed_package_and_keeps_it_in_train_json( world, tmp_path ):
    done, _ = approved_row( world, row_id="r-done", status="done" )
    live, _ = approved_row( world, package="b", name="cb", commits=[ world.shas[ "two" ] ] )
    rows    = _write( tmp_path / "rows.json", [ done, live ] )
    stream  = io.StringIO()
    code    = tb.main( [ "--repo-root", str( world.root ), "--out", str( tmp_path / "o" ), "--rows-json", rows, "--data-root", str( world.data ) ], stream )
    result  = json.loads( ( tmp_path / "o" / "train.json" ).read_text( encoding="utf-8" ) )
    assert code == 0 and result[ "landed" ] == [ { "package": "a", "row_ids": [ "r-done" ] } ]
    assert stream.getvalue() == f"LANDED a: r-done\ntrain of 1 packages, 1 commits, 0 refused, 1 landed, 0 deferred, at {result[ 'head' ]}\n"


def test_two_done_claim_rows_for_one_package_are_both_listed_as_landed_in_row_order( world ):
    first, _  = approved_row( world, row_id="r-done-1", status="done" )
    second, _ = approved_row( world, row_id="r-done-2", name="c2", status="done" )
    result    = train( world, [ first, second ] )
    assert result[ "landed" ] == [ { "package": "a", "row_ids": [ "r-done-1", "r-done-2" ] } ]
    assert result[ "packages" ] == [] and result[ "refused" ] == []
