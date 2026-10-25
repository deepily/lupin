"""
Probe: where is a definition written during a run lost? One layer at a time.

The embeddings client is a fake whose vector is a function of the text; the judge is a fake that answers reuse.
"""
import json
import pathlib

import numpy as np
import pytest
from fastapi import FastAPI

from cosa.repo.symindex import build as bd
from cosa.repo.symindex import candidate_build as cb
from cosa.repo.symindex.candidates import freshness as fr
from cosa.repo.symindex.candidates import search
from cosa.repo.symindex.candidates import vector_build as vb
from cosa.repo.symindex.candidates import vector_store as vs
from cosa.repo.symindex.candidates.resident import ResidentSearch
from cosa.rest.middleware.api_key_auth import require_api_key_or_jwt
from cosa.rest.routers import reuse_candidates as router
from lupin_mcp import reuse_candidates as rcand
from lupin_mcp import reuse_tools as rt
from tests.unit.include_tests_helpers import AllReuse
from tests.unit.symindex_helpers import make_lupin_repo
from tests.unit.test_candidates_vector_build import FakeClient, vec
from tests.unit.test_reuse_candidates_client import Bridge
from tests.unit.test_reuse_pack_route import no_jev_key                                         # noqa: F401  (a fixture)
from tests.unit.test_reuse_tools import NEED

NEW_ID   = "cosa.fresh_new.fetch_feed_titles"
NEW_CODE = 'def fetch_feed_titles( url ):\n    """Read an RSS feed and return its article titles."""\n    return url\n'


class ConfigFor:
    """The three storage keys, as the INI holds them."""

    def get( self, key, default=None, silent=False, return_type="string" ):
        return { "reuse candidate vectors subdir": "vec", "reuse candidate query cache subdir": "qc", "reuse candidate purpose lines subdir": "pl" }.get( key, default )


def no_writer( ids ): raise AssertionError( f"the run-time refresh waited for purpose lines: {ids}" )


def written( ids ): return { i: f"Return {i}." for i in ids }


class World:
    """A lupin tree, its index, a vector set and a candidate stage over the real resident search."""

    def __init__( self, tmp_path, monkeypatch, refresher=None ):
        self.root, self.data = make_lupin_repo( tmp_path ), tmp_path / "data"
        self.client          = FakeClient()
        cb.run( self.root, written, self.client, config=ConfigFor(), environ={}, out_dir=self.data )
        app = FastAPI()
        app.include_router( router.router )
        app.dependency_overrides[ require_api_key_or_jwt ] = lambda: "u"
        monkeypatch.setitem( router._held, "search", ResidentSearch( self.data, search.default_loader ) )
        refresher  = refresher if refresher is not None else rt.make_refresher( self.root, self.client, {}, config=ConfigFor(), out_dir=self.data )
        self.stage = rcand.CandidateStage( "http://lupin:7999", "k", self.data / "vec", self.data / "qc", self.client, purposes_path=self.data / "pl" / "purpose.jsonl",
                                           urlopen=Bridge( app ), refresher=refresher )
        self.ctx   = rt.ReuseContext( self.root, tmp_path / "rdata", transport=AllReuse(), candidate_stage=self.stage, purposes_path=self.data / "pl" / "purpose.jsonl" )

    def ask( self, need=NEED ): return rt.check_exists_impl( need, self.ctx, language="py" )

    def land_new_code( self ):
        ( self.root / "src" / "cosa" / "fresh_new.py" ).write_text( NEW_CODE, encoding="utf-8" )

    def layers( self ):
        """Return, per layer, whether the new definition is there now."""
        gen    = bd.ensure( self.root )
        rec    = next( ( r for r in bd.read_searchable( gen ) if r[ "id" ] == NEW_ID ), None )
        table  = { "symbol_index": rec is not None }
        live   = vs.load_vectors( self.data / "vec" )
        table[ "vector_set" ]    = NEW_ID in live.ids
        if table[ "vector_set" ]:
            row   = live.ids.index( NEW_ID )
            texts = vb.entry_texts( rec, "" )
            for name in vs.MATRICES:
                want = np.asarray( vec( *vs.DOCUMENT_ROLES[ name ], texts[ name ] ), dtype="<f4" )
                table[ "vector_set" ] = table[ "vector_set" ] and bool( np.array_equal( np.asarray( live.matrices[ name ][ row ] ), want ) )
        lines  = json.loads( ( self.data / "pl" / "purpose.jsonl" ).read_text( encoding="utf-8" ).splitlines()[ 0 ] )
        stored = { json.loads( l )[ "pin" ] for l in ( self.data / "pl" / "purpose.jsonl" ).read_text( encoding="utf-8" ).splitlines() }
        info   = fr.read_build_info( self.data / "vec" )
        table[ "purpose_line" ]  = "present" if rec is not None and rec[ "pin" ] in stored else ( "unwritten" if rec is not None and rec[ "pin" ] in info[ "unwritten_pins" ] else "lost" )
        cached = [ json.loads( p.read_text( encoding="utf-8" ) ) for p in ( self.data / "qc" ).glob( "*.json" ) ]
        table[ "query_cache" ]   = bool( cached ) and all( c[ "manifest_hash" ] == live.manifest_hash for c in cached )
        sweep  = rt.sweep_need_impl( NEED, None, self.ctx, language="py" )
        table[ "full_sweep" ]    = NEW_ID in [ s[ "id" ] for s in sweep[ "shortlist" ] + sweep[ "nearest" ] ]
        return table


@pytest.fixture
def world( tmp_path, monkeypatch ):
    return World( tmp_path, monkeypatch, refresher=None )


def test_probe_a_definition_written_during_a_run_is_in_every_layer_by_the_next_call( world ):
    # The probe: every layer, one table. The first layer that reads False is the defect to fix.
    first = world.ask()
    assert first[ "status" ] == "ok" and NEW_ID not in [ s[ "id" ] for s in first[ "shortlist" ] ]
    world.land_new_code()
    second = world.ask()
    assert second[ "status" ] == "ok" and NEW_ID in [ s[ "id" ] for s in second[ "shortlist" ] + second[ "nearest" ] ]
    table = world.layers()
    print( "\nPROBE", table )
    assert table == { "symbol_index": True, "vector_set": True, "purpose_line": "unwritten", "query_cache": True, "full_sweep": True }


def test_probe_control_a_refresher_that_does_nothing_leaves_the_vector_layer_missing( tmp_path, monkeypatch ):
    # red when: the probe cannot tell a refreshed vector set from a stale one (a constant fake would make both green)
    w = World( tmp_path, monkeypatch, refresher=lambda: { "rows": 0 } )
    w.ask()
    w.land_new_code()
    w.ask()
    table = w.layers()
    assert table[ "symbol_index" ] is True and table[ "vector_set" ] is False and table[ "full_sweep" ] is True


def test_the_old_refresher_that_waits_for_the_purpose_job_leaves_the_stage_stale( tmp_path, monkeypatch ):
    # The defect the probe found in the code as it stood: the run-time refresh asked the bounded job for purpose lines and waited for it.
    def waits( ids ): raise TimeoutError( "no response file within 1800 s" )
    old = lambda: cb.run( root_of( tmp_path ), waits, FakeClient(), config=ConfigFor(), environ={}, out_dir=tmp_path / "data", skip_if_current=True )
    w   = World( tmp_path, monkeypatch, refresher=old )
    w.ask()
    w.land_new_code()
    second = w.ask()
    assert second[ "status" ] == "ok" and w.layers()[ "vector_set" ] is False                       # the new row never reached the vector set


def root_of( tmp_path ): return tmp_path / "lupin"


def test_a_new_private_method_reaches_the_index_and_the_vector_set_too( tmp_path, monkeypatch ):
    w = World( tmp_path, monkeypatch )
    w.ask()
    ( w.root / "src" / "cosa" / "fresh_new.py" ).write_text( 'def _hidden_titles( url ):\n    """Read an RSS feed and return its article titles."""\n    return url\n', encoding="utf-8" )
    w.ask()
    live = vs.load_vectors( w.data / "vec" )
    assert "cosa.fresh_new._hidden_titles" in live.ids
    assert "cosa.fresh_new._hidden_titles" in [ r[ "id" ] for r in bd.read_searchable( bd.ensure( w.root ) ) ]


def test_a_changed_signature_changes_search_sha_and_the_index_sha_of_the_next_call( tmp_path, monkeypatch ):
    # red when: index_sha takes the public listing's hash, which a private change never moves
    w = World( tmp_path, monkeypatch )
    ( w.root / "src" / "cosa" / "fresh_new.py" ).write_text( 'def _hidden( url ):\n    """Hidden."""\n    return url\n', encoding="utf-8" )
    one, sha_one = w.ask(), bd.read_header( bd.ensure( w.root ) )[ "search_sha" ]
    ( w.root / "src" / "cosa" / "fresh_new.py" ).write_text( 'def _hidden( url, depth ):\n    """Hidden."""\n    return url\n', encoding="utf-8" )
    two, sha_two = w.ask(), bd.read_header( bd.ensure( w.root ) )[ "search_sha" ]
    assert sha_one != sha_two and one[ "index_sha" ] != two[ "index_sha" ]


def test_purposes_skip_writes_no_line_calls_no_writer_and_lists_the_pin_as_unwritten( tmp_path ):
    root, data = make_lupin_repo( tmp_path ), tmp_path / "data"
    cb.run( root, written, FakeClient(), config=ConfigFor(), environ={}, out_dir=data )
    before = ( data / "pl" / "purpose.jsonl" ).read_text( encoding="utf-8" )
    ( root / "src" / "cosa" / "fresh_new.py" ).write_text( NEW_CODE, encoding="utf-8" )
    report = cb.run( root, None, FakeClient(), config=ConfigFor(), environ={}, out_dir=data, purposes="skip" )
    assert ( data / "pl" / "purpose.jsonl" ).read_text( encoding="utf-8" ) == before and report[ "purposes" ] == { "skipped": True }
    assert len( report[ "unwritten_pins" ] ) == 1 and report[ "rows" ] == 4
    with pytest.raises( ValueError, match="purposes must be" ): cb.run( root, None, FakeClient(), config=ConfigFor(), environ={}, out_dir=data, purposes="later" )


def test_a_refresh_that_passes_the_bound_is_named_in_the_result_and_never_silent( world ):
    # red when: the note is dropped or the bound is not read from the clock. A fake clock moves 20 s per reading; the call reads it at its start,
    # at the end of prepare and at the end of the lookup.
    class Clock:
        def __init__( self, step ): self.t, self.step = -step, step
        def __call__( self ): self.t += self.step; return self.t
    world.ctx.clock = Clock( 20 )
    r = world.ask()
    assert [ n[ "note" ] for n in r[ "notes" ] ] == [ "INDEX_REFRESH_SLOW" ] and "40 s" in r[ "notes" ][ 0 ][ "detail" ] and r[ "status" ] == "ok"
    world.ctx.clock = Clock( 5 )
    assert world.ask( NEED + " again" )[ "notes" ] == []
    world.ctx.clock = Clock( 40 )                                                                    # slow already at the end of prepare: one note, not two
    assert [ n[ "note" ] for n in world.ask( NEED + " third" )[ "notes" ] ] == [ "INDEX_REFRESH_SLOW" ]
    assert rt.INDEX_REFRESH_BOUND_SECONDS == 30


def test_a_context_that_never_ran_prepare_notes_nothing( tmp_path ):
    ctx = rt.ReuseContext( tmp_path, tmp_path / "d", clock=lambda: 10 ** 6 )
    rt.note_if_slow( ctx )
    assert ctx.notes == [] and ctx.started is None


def test_two_contexts_with_separate_data_directories_keep_separate_receipts_and_one_shared_directory_does_not( tmp_path ):
    root = make_lupin_repo( tmp_path )
    mk   = lambda data: rt.ReuseContext( root, tmp_path / data, out_dir=tmp_path / "out", transport=AllReuse() )
    a, b, c = mk( "data-a" ), mk( "data-b" ), mk( "data-a" )
    rid = rt.check_exists_impl( NEED, a, language="py" )[ "receipt_id" ]
    assert rt.load_receipt( a, rid )[ "id" ] == rid and rt.load_receipt( c, rid )[ "id" ] == rid        # the control: a shared directory shows the receipt
    with pytest.raises( rt.ReuseError ) as e: rt.load_receipt( b, rid )
    assert e.value.name == "RECEIPT_MISSING"


def test_the_context_from_the_environment_reports_what_chose_its_folders( tmp_path, monkeypatch ):
    root = make_lupin_repo( tmp_path )
    monkeypatch.delenv( "LUPIN_REUSE_DATA_DIR", raising=False ); monkeypatch.delenv( "LUPIN_REUSE_OUT_DIR", raising=False )
    monkeypatch.delenv( rt.PACK_SIZE_VARIABLE, raising=False )
    monkeypatch.setattr( rt, "data_dir", lambda top: tmp_path / "fleet" )
    d = rt.context_from_environment( root )
    assert ( d.data_source, d.out_source, d.data ) == ( "default", "default", tmp_path / "fleet" )
    monkeypatch.setenv( "LUPIN_REUSE_DATA_DIR", str( tmp_path / "mine" ) ); monkeypatch.setenv( "LUPIN_REUSE_OUT_DIR", str( tmp_path / "out" ) )
    s = rt.context_from_environment( root )
    assert ( s.data_source, s.out_source, s.data, s.out_dir ) == ( "LUPIN_REUSE_DATA_DIR", "LUPIN_REUSE_OUT_DIR", tmp_path / "mine", tmp_path / "out" )
