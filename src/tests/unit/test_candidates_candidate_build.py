"""
Unit tests for the manual build driver: the job writer, the run and the command line.

The index, the job transport and the embeddings client are fakes. The run is checked end to end
against a real sealed set in a temporary folder.
"""
import json

import pytest

from cosa.repo.symindex import candidate_build as cb
from cosa.repo.symindex.candidates import purpose_lines as pl
from cosa.repo.symindex.candidates import vector_store as vs
from cosa.repo.symindex.candidates.errors import CandidateError, STORAGE_KEY_MISSING

import test_candidates_vector_build as tvb


# ── the bounded-job writer ──────────────────────────────────────────────────


class Clock:
    def __init__( self ): self.now = 0.0
    def __call__( self ):   return self.now
    def sleep( self, s ):   self.now += s


def test_writer_sends_ids_and_two_file_names_then_reads_the_response( tmp_path ):
    sent = []

    def submit( payload ):
        sent.append( payload )
        resp = [ p for p in payload[ "args" ][ "prompt" ].split() if "response-" in p ][ 0 ].rstrip( "," ).rstrip( "." )
        pathlib_write( resp, [ { "id": "m.a", "purpose": "Return a." }, { "id": "m.b", "purpose": "Return b." } ] )

    w = cb.BoundedJobWriter( tmp_path / "work", submit )
    assert w( [ "m.a", "m.b" ] ) == { "m.a": "Return a.", "m.b": "Return b." }
    assert sent[ 0 ][ "command" ] == "agent router go to claude code"
    assert sent[ 0 ][ "args" ][ "task_type" ] == "BOUNDED"
    prompt = sent[ 0 ][ "args" ][ "prompt" ]
    assert prompt.startswith( pl.PROMPT_TEXT )
    request = next( tmp_path.glob( "work/request-*.json" ) )
    assert json.loads( request.read_text() ) == { "ids": [ "m.a", "m.b" ] }
    assert str( request ) in prompt


def pathlib_write( path, obj ):
    import pathlib
    pathlib.Path( path ).write_text( json.dumps( obj ), encoding="utf-8" )


def test_writer_removes_a_stale_response_before_it_submits( tmp_path ):
    work = tmp_path / "work"
    work.mkdir()
    ids  = [ "m.a" ]
    import hashlib
    key  = hashlib.sha256( "m.a".encode() ).hexdigest()[ :12 ]
    ( work / f"response-{key}.json" ).write_text( json.dumps( [ { "id": "m.a", "purpose": "STALE." } ] ) )
    seen = {}

    def submit( payload ):
        seen[ "stale_gone" ] = not ( work / f"response-{key}.json" ).exists()
        pathlib_write( work / f"response-{key}.json", [ { "id": "m.a", "purpose": "Fresh." } ] )

    assert cb.BoundedJobWriter( work, submit )( ids ) == { "m.a": "Fresh." }
    assert seen[ "stale_gone" ] is True


def test_writer_waits_by_polling_until_the_file_appears( tmp_path ):
    clock = Clock()
    state = { "n": 0 }

    def submit( payload ): pass

    def sleep( s ):
        clock.sleep( s )
        state[ "n" ] += 1
        if state[ "n" ] == 3:
            import hashlib
            key = hashlib.sha256( b"m.a" ).hexdigest()[ :12 ]
            pathlib_write( tmp_path / "work" / f"response-{key}.json", [ { "id": "m.a", "purpose": "Done." } ] )

    w = cb.BoundedJobWriter( tmp_path / "work", submit, timeout=100, poll=5, sleep=sleep, clock=clock )
    assert w( [ "m.a" ] ) == { "m.a": "Done." }
    assert state[ "n" ] == 3 and clock.now == 15


def test_writer_times_out_when_no_response_comes( tmp_path ):
    clock = Clock()
    w = cb.BoundedJobWriter( tmp_path / "work", lambda p: None, timeout=20, poll=10, sleep=clock.sleep, clock=clock )
    with pytest.raises( TimeoutError, match="no response file" ):
        w( [ "m.a" ] )


@pytest.mark.parametrize( "body", [ { "id": "m.a" }, [ { "id": "m.a" } ], [ "m.a" ] ] )
def test_writer_refuses_a_response_that_is_not_a_list_of_id_purpose_objects( tmp_path, body ):
    import hashlib
    key = hashlib.sha256( b"m.a" ).hexdigest()[ :12 ]
    w = cb.BoundedJobWriter( tmp_path / "work", lambda p: pathlib_write( tmp_path / "work" / f"response-{key}.json", body ) )
    with pytest.raises( ValueError, match="not a list" ):
        w( [ "m.a" ] )


# ── the run ─────────────────────────────────────────────────────────────────


@pytest.fixture
def world( tmp_path, monkeypatch ):
    """A fake index of two public entries, and a data directory inside tmp_path."""
    symbols = [ tvb.entry( "b", "pb", doc="Does b." ), tvb.entry( "a", "pa" ) ]
    for s in symbols: s.update( lang="py", kind="function", line=1, public=True )
    monkeypatch.setattr( cb.sx_build, "ensure", lambda root: "gen" )
    monkeypatch.setattr( cb.sx_build, "read_symbols", lambda gen: symbols )
    monkeypatch.setattr( cb.sx_build, "read_header", lambda gen: { "manifest": { "m.py": [ 1, 2 ] }, "symbols_sha": "sha-1" } )
    monkeypatch.setattr( cb, "data_dir", lambda root: tmp_path / "data" )
    environ = {}
    return { "root": tmp_path / "repo", "data": tmp_path / "data", "environ": environ, "symbols": symbols }


class ConfigFor:
    def get( self, key, default=None, silent=False, return_type="string" ):
        return { "reuse candidate vectors subdir": "vec", "reuse candidate query cache subdir": "qc",
                 "reuse candidate purpose lines subdir": "pl" }.get( key, default )


def answering_writer( calls ):
    def w( ids ):
        calls.append( list( ids ) )
        return { i: f"Return {i}." for i in ids }
    return w


def test_run_writes_lines_builds_the_set_swaps_it_in_and_clears_stale_queries( world, tmp_path, screen_fixture=None ):
    calls, client = [], tvb.FakeClient()
    stale = tmp_path / "data" / "qc"
    stale.mkdir( parents=True )
    ( stale / "old.json" ).write_text( json.dumps( { "manifest_hash": "gone", "vectors": {} } ) )

    report = cb.run( world[ "root" ], answering_writer( calls ), client, config=ConfigFor(), environ={} )

    assert calls == [ [ "m.a", "m.b" ] ] or sorted( calls[ 0 ] ) == [ "m.a", "m.b" ]
    assert report[ "purposes" ][ "written" ] == 2
    assert report[ "rows" ] == 2
    assert report[ "stale_queries_cleared" ] == 1
    live = tmp_path / "data" / "vec"
    s    = vs.load_vectors( live )
    assert s.ids == [ "m.a", "m.b" ] and s.manifest_hash == report[ "manifest_hash" ]
    assert not ( tmp_path / "data" / "vec.new" ).exists()
    rows = pl.load_lines( tmp_path / "data" / "pl" / "purpose.jsonl" )
    assert { r[ "writer_version" ] for r in rows.values() } == { cb.WRITER_VERSION }
    assert any( "Return m.a." in t for c in client.calls for t in c[ 2 ] )     # the stored line reached the embedded text


def test_a_second_run_sends_no_ids_to_the_writer_and_replaces_a_leftover_new_folder( world, tmp_path ):
    calls = []
    cb.run( world[ "root" ], answering_writer( calls ), tvb.FakeClient(), config=ConfigFor(), environ={} )
    leftover = tmp_path / "data" / "vec.new"
    leftover.mkdir()
    ( leftover / "junk" ).write_text( "x" )
    r2 = cb.run( world[ "root" ], answering_writer( calls ), tvb.FakeClient(), config=ConfigFor(), environ={} )
    assert len( calls ) == 1
    assert r2[ "purposes" ][ "kept" ] == 2 and r2[ "purposes" ][ "written" ] == 0
    assert not leftover.exists()


def test_a_run_whose_build_fails_leaves_the_live_set_alone( world, tmp_path ):
    cb.run( world[ "root" ], answering_writer( [] ), tvb.FakeClient(), config=ConfigFor(), environ={} )
    before = vs.load_vectors( tmp_path / "data" / "vec" ).manifest_hash
    with pytest.raises( CandidateError ):
        cb.run( world[ "root" ], answering_writer( [] ), tvb.FakeClient( revision=None ), config=ConfigFor(), environ={} )
    assert vs.load_vectors( tmp_path / "data" / "vec" ).manifest_hash == before


# ── the command line ────────────────────────────────────────────────────────


def test_main_prints_the_report_and_returns_zero( capsys ):
    seen = {}

    def fake_run( root, writer, client, environ=None, batch_size=25 ):
        seen.update( root=root, writer=writer, client=client, batch_size=batch_size )
        return { "rows": 3 }

    import cosa.repo.symindex.candidate_build as mod
    orig, mod.run = mod.run, fake_run
    try:
        rc = cb.main( [ "--root", "/repo" ], environ={}, writer_factory=lambda args: "WRITER", client="CLIENT" )
    finally:
        mod.run = orig
    assert rc == 0
    assert json.loads( capsys.readouterr().out ) == { "rows": 3 }
    assert seen == { "root": "/repo", "writer": "WRITER", "client": "CLIENT", "batch_size": 25 }


def test_main_builds_the_default_writer_from_the_test_credentials( monkeypatch, tmp_path, capsys ):
    submitted = []
    monkeypatch.setattr( cb.harness_schedule, "submit", lambda payload, url, email, pw: submitted.append( ( payload, url, email, pw ) ) )
    monkeypatch.setattr( cb, "data_dir", lambda root: tmp_path )
    seen = {}

    def fake_run( root, writer, client, environ=None, batch_size=25 ):
        seen[ "writer" ] = writer
        writer.submit( { "x": 1 } )
        return { "rows": 0 }

    monkeypatch.setattr( cb, "run", fake_run )
    monkeypatch.setattr( cb.sp, "main_checkout", lambda root: tmp_path / "main" )
    monkeypatch.setattr( cb, "default_out_dir", lambda root: root / "src" / "docs" / "index" )
    env = { "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL": "e@x", "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD": "pw",
            "LUPIN_REUSE_CANDIDATE_HANDOFF_DIR": str( tmp_path / "main" / "io" / "h" ),
            "LUPIN_REUSE_CANDIDATE_CONTAINER_ROOT": "/var/lupin" }
    assert cb.main( [ "--root", str( tmp_path / "main" ) ], environ=env, client="C" ) == 0
    w = seen[ "writer" ]
    assert isinstance( w, cb.BoundedJobWriter )
    assert w.work_dir == tmp_path / "main" / "io" / "h"
    assert w.index_path == "/var/lupin/src/docs/index/current/symbols.jsonl"
    assert w.to_container( tmp_path / "main" / "io" / "h" / "r.json" ) == "/var/lupin/io/h/r.json"
    assert submitted == [ ( { "x": 1 }, "http://localhost:7999", "e@x", "pw" ) ]


def test_main_uses_the_server_url_variable_and_the_endpoint_client_by_default( monkeypatch, tmp_path ):
    monkeypatch.setattr( cb, "data_dir", lambda root: tmp_path )
    seen = {}
    monkeypatch.setattr( cb, "run", lambda root, writer, client, environ=None, batch_size=25: seen.update( client=client ) or { "rows": 0 } )
    monkeypatch.setattr( cb.sp, "main_checkout", lambda root: tmp_path )
    monkeypatch.setattr( cb, "default_out_dir", lambda root: root / "src" / "docs" / "index" )
    env = { "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL": "e", "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD": "p",
            "LUPIN_APP_SERVER_URL": "http://test:8000", "LUPIN_REUSE_CANDIDATE_HANDOFF_DIR": str( tmp_path / "io" ),
            "LUPIN_REUSE_CANDIDATE_CONTAINER_ROOT": "/var/lupin" }
    assert cb.main( [ "--root", str( tmp_path ) ], environ=env ) == 0
    assert isinstance( seen[ "client" ], cb.vb.EndpointClient )


def test_main_reports_a_named_error_and_returns_two( capsys ):
    def factory( args ): raise CandidateError( STORAGE_KEY_MISSING, "no key" )

    assert cb.main( [ "--root", "/repo" ], environ={}, writer_factory=factory, client="C" ) == 2
    assert json.loads( capsys.readouterr().out ) == { "error": "STORAGE_KEY_MISSING", "detail": "no key" }


# ── container paths in the prompt, and the sample mode ──────────────────────


def test_the_prompt_names_the_container_paths_and_the_index( tmp_path ):
    sent = []
    key  = None

    def submit( payload ):
        sent.append( payload )
        import hashlib
        k = hashlib.sha256( b"m.a" ).hexdigest()[ :12 ]
        pathlib_write( tmp_path / "work" / f"response-{k}.json", [ { "id": "m.a", "purpose": "Return a." } ] )

    to_c = lambda p: str( p ).replace( str( tmp_path ), "/var/lupin" )
    w = cb.BoundedJobWriter( tmp_path / "work", submit, to_container=to_c, index_path="/var/lupin/src/docs/index/current/symbols.jsonl" )
    assert w( [ "m.a" ] ) == { "m.a": "Return a." }
    prompt = sent[ 0 ][ "args" ][ "prompt" ]
    assert "/var/lupin/work/request-" in prompt and "/var/lupin/work/response-" in prompt
    assert str( tmp_path ) not in prompt
    assert "/var/lupin/src/docs/index/current/symbols.jsonl" in prompt


def test_sample_purposes_takes_every_kth_entry_into_its_own_store( world, tmp_path, screen_for_sample=None ):
    symbols = world[ "symbols" ]
    for i in range( 6 ): symbols.append( { **tvb.entry( f"z{i}", f"pz{i}" ), "lang": "py", "kind": "function", "line": 1, "public": True } )
    # the index holds m.b, m.a, m.z0..m.z5; sorted that is a, b, z0..z5 (8 entries), count 4 gives step 2.
    # The pins run in the reverse of the id order, so a sort by pin would choose other entries.
    for rank, sym in enumerate( sorted( symbols, key=lambda e: e[ "id" ] ) ): sym[ "pin" ] = f"p{len( symbols ) - rank:02d}"
    calls = []
    report = cb.sample_purposes( world[ "root" ], answering_writer( calls ), tmp_path / "s" / "sample.jsonl", 4, batch_size=2 )
    assert report[ "ids" ] == [ "m.a", "m.z0", "m.z2", "m.z4" ]
    assert calls == [ [ "m.a", "m.z0" ], [ "m.z2", "m.z4" ] ]
    assert report[ "written" ] == 4
    assert not ( tmp_path / "data" / "pl" ).exists()
    again = cb.sample_purposes( world[ "root" ], answering_writer( [] ), tmp_path / "s2" / "sample.jsonl", 4 )
    assert again[ "ids" ] == report[ "ids" ]


def test_sample_purposes_takes_at_most_count_when_the_step_leaves_a_tail( world, tmp_path ):
    symbols = world[ "symbols" ]
    for i in range( 3 ): symbols.append( { **tvb.entry( f"y{i}", f"py{i}" ), "lang": "py", "kind": "function", "line": 1, "public": True } )
    # sorted: a, b, y0, y1, y2 (5 entries), count 3 gives step 1 and the first three
    report = cb.sample_purposes( world[ "root" ], answering_writer( [] ), tmp_path / "t.jsonl", 3 )
    assert report[ "ids" ] == [ "m.a", "m.b", "m.y0" ]


def test_main_sample_mode_writes_the_store_and_builds_nothing( world, tmp_path, capsys ):
    argv = [ "--root", str( world[ "root" ] ), "--sample", "2", "--store", str( tmp_path / "s.jsonl" ), "--batch-size", "1" ]
    calls = []
    assert cb.main( argv, environ={}, writer_factory=lambda a: answering_writer( calls ), client="NOT USED" ) == 0
    out = json.loads( capsys.readouterr().out )
    assert out[ "written" ] == 2 and len( out[ "ids" ] ) == 2
    assert [ len( c ) for c in calls ] == [ 1, 1 ]


def test_run_passes_the_batch_size_through( world, tmp_path ):
    world[ "symbols" ].append( { **tvb.entry( "c", "pc" ), "lang": "py", "kind": "function", "line": 1, "public": True } )
    calls = []
    cb.run( world[ "root" ], answering_writer( calls ), tvb.FakeClient(), config=ConfigFor(), environ={}, batch_size=2 )
    assert calls == [ [ "m.b", "m.a" ], [ "m.c" ] ]


def test_main_hands_the_batch_size_to_run( monkeypatch ):
    seen = {}
    monkeypatch.setattr( cb, "run", lambda root, writer, client, environ=None, batch_size=25: seen.update( batch_size=batch_size ) or { "rows": 0 } )
    assert cb.main( [ "--root", "/repo", "--batch-size", "7" ], environ={}, writer_factory=lambda a: "W", client="C" ) == 0
    assert seen == { "batch_size": 7 }


# ── refused arguments ───────────────────────────────────────────────────────


@pytest.mark.parametrize( "argv, named", [
    ( [ "--root", "/repo", "--batch-size", "0" ],                            "--batch-size must be 1 or more, got 0" ),
    ( [ "--root", "/repo", "--sample", "-3", "--store", "/s.jsonl" ],        "--sample must be 1 or more" ),
    ( [ "--root", "/repo", "--sample", "5" ],                                "--sample needs --store" ),
] )
def test_main_refuses_a_bad_option_by_name( argv, named, capsys ):
    with pytest.raises( SystemExit ) as e:
        cb.main( argv, environ={}, writer_factory=lambda a: pytest.fail( "the writer must not be built" ), client="C" )
    assert e.value.code == 2
    assert named in capsys.readouterr().err


def test_main_refuses_a_worktree_root_and_names_the_main_checkout( monkeypatch, tmp_path, capsys ):
    monkeypatch.setattr( cb.sp, "main_checkout", lambda root: tmp_path / "main" )
    env = { "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL": "e", "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD": "p" }
    with pytest.raises( SystemExit ) as e:
        cb.main( [ "--root", str( tmp_path / "wt" ) ], environ=env, client="C" )
    assert e.value.code == 2
    err = capsys.readouterr().err
    assert f"--root {tmp_path / 'wt'} is a worktree" in err and f"Pass --root {tmp_path / 'main'}" in err


# ── build info, the build lock and the extracted job writer ─────────────────


def test_run_writes_the_build_info_into_the_new_set_before_the_swap_and_returns_it( world, tmp_path ):
    from cosa.repo.symindex.candidates import freshness as fr
    report = cb.run( world[ "root" ], answering_writer( [] ), tvb.FakeClient(), config=ConfigFor(), environ={}, built_at="2026-10-15T14:00:00+00:00" )
    info   = fr.read_build_info( tmp_path / "data" / "vec" )
    assert info == { "index_manifest": fr.index_manifest( { "manifest": { "m.py": [ 1, 2 ] } } ), "symbols_sha": "sha-1", "built_at": "2026-10-15T14:00:00+00:00",
                     "unwritten_pins": [] }
    assert report[ "index_manifest" ] == info[ "index_manifest" ] and report[ "built_at" ] == info[ "built_at" ]
    assert vs.load_vectors( tmp_path / "data" / "vec" ).manifest_hash == report[ "manifest_hash" ]


def test_the_build_info_does_not_enter_the_manifest_hash( world, tmp_path ):
    one = cb.run( world[ "root" ], answering_writer( [] ), tvb.FakeClient(), config=ConfigFor(), environ={}, built_at="2026-10-15T14:00:00+00:00" )
    two = cb.run( world[ "root" ], answering_writer( [] ), tvb.FakeClient(), config=ConfigFor(), environ={}, built_at="2026-10-16T09:00:00+00:00" )
    assert one[ "manifest_hash" ] == two[ "manifest_hash" ] and one[ "built_at" ] != two[ "built_at" ]


def test_run_stamps_the_current_utc_time_when_no_time_is_given( world ):
    report = cb.run( world[ "root" ], answering_writer( [] ), tvb.FakeClient(), config=ConfigFor(), environ={} )
    assert report[ "built_at" ].endswith( "+00:00" )


def test_make_job_writer_refuses_a_worktree_by_value_error_and_a_missing_credential_by_name( monkeypatch, tmp_path ):
    monkeypatch.setattr( cb.sp, "main_checkout", lambda root: tmp_path / "main" )
    with pytest.raises( ValueError, match="is a worktree" ):
        cb.make_job_writer( str( tmp_path / "wt" ), "http://x", {} )
    with pytest.raises( CandidateError ) as e:
        cb.make_job_writer( str( tmp_path / "main" ), "http://x", { "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL": "e" } )
    assert e.value.code == "DEPENDENCY_MISSING" and "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" in e.value.detail


def test_the_build_info_is_in_the_new_set_at_the_moment_of_the_swap( world, monkeypatch ):
    seen = {}
    real = cb.vs.swap_in

    def watching( new_dir, live_dir ):
        seen[ "info_in_new_set" ] = ( new_dir / "build-info.json" ).is_file()
        real( new_dir, live_dir )

    monkeypatch.setattr( cb.vs, "swap_in", watching )
    cb.run( world[ "root" ], answering_writer( [] ), tvb.FakeClient(), config=ConfigFor(), environ={} )
    assert seen == { "info_in_new_set": True }


# ── the run lends the live set's vectors to the next build ──────────────────


def test_a_second_run_after_one_changed_docstring_reuses_the_other_rows( world, tmp_path ):
    cb.run( world[ "root" ], answering_writer( [] ), tvb.FakeClient(), config=ConfigFor(), environ={} )
    world[ "symbols" ][ 0 ][ "doc" ] = "Does b differently."
    client = tvb.FakeClient()
    report = cb.run( world[ "root" ], answering_writer( [] ), client, config=ConfigFor(), environ={} )
    assert report[ "vectors" ][ "code" ] == { "reused": 2, "embedded": 0 }
    assert report[ "vectors" ][ "prose" ] == { "reused": 1, "embedded": 1 }
    assert sum( len( c[ 2 ] ) for c in client.calls if c[ 2 ] != [ tvb.vb.WARM_TEXT ] ) == 2
    assert vs.load_vectors( tmp_path / "data" / "vec" ).manifest_hash == report[ "manifest_hash" ]


def test_a_live_set_that_does_not_load_is_rebuilt_in_full_with_no_error( world, tmp_path ):
    cb.run( world[ "root" ], answering_writer( [] ), tvb.FakeClient(), config=ConfigFor(), environ={} )
    ( tmp_path / "data" / "vec" / "row_texts.jsonl" ).write_text( "{bad\n" )
    report = cb.run( world[ "root" ], answering_writer( [] ), tvb.FakeClient(), config=ConfigFor(), environ={} )
    assert report[ "vectors" ] == { n: { "reused": 0, "embedded": 2 } for n in vs.MATRICES }
    assert vs.load_vectors( tmp_path / "data" / "vec" ).row_texts is not None


def test_the_first_run_has_no_live_set_to_lend_and_embeds_everything( world ):
    report = cb.run( world[ "root" ], answering_writer( [] ), tvb.FakeClient(), config=ConfigFor(), environ={} )
    assert report[ "vectors" ] == { n: { "reused": 0, "embedded": 2 } for n in vs.MATRICES }
