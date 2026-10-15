"""
The need redactor sits in front of every request that carries a need.

A recording stand-in for Jev answers anything and keeps every request body it was sent. Each test then reads
the bodies for the five kinds, so a path that skipped the redactor fails here on its own output.
"""
import json
import pathlib
import threading

import pytest

from cosa.repo.doc_lint import jev_transport
from lupin_mcp import reuse_pack as rp
from lupin_mcp import reuse_redact as rr
from lupin_mcp import reuse_tools as rt
from tests.unit.symindex_helpers import make_lupin_repo
from tests.unit.test_reuse_pack_route import probs_of
from tests.unit.test_reuse_tools import UNREL

ROUTER = '''"""Routes."""
from fastapi import APIRouter

router = APIRouter( prefix="/api/v2" )


@router.post( "/submit" )
def submit():
    """Submit a job."""
    return 1
'''

WHERE = '''"""Paths."""


def where():
    """Reads /projects/acme/secret.py."""
    return 1
'''

RAW_NEED = "wrap /api/v2/submit and read /projects/acme/secret.py for bob@example.com at 10.0.0.1 via https://x.example/y with sk-abcdefghijklm"
SENT_NEED = "wrap /api/v2/submit and read [path] for [email] at [ip] via [url] with [secret]"
SENT_NEED_NO_ROUTES = "wrap [path] and read [path] for [email] at [ip] via [url] with [secret]"
RAW_TOKENS = ( "/projects/acme/secret.py", "bob@example.com", "10.0.0.1", "https://x.example/y", "sk-abcdefghijklm" )


class Recording:
    """Answers every question as unrelated and keeps each body it was sent."""

    def __init__( self ):
        self.bodies, self.lock = [], threading.Lock()

    def post( self, body ):
        with self.lock: self.bodies.append( body )
        return UNREL

    def post_with_meta( self, body ):
        with self.lock: self.bodies.append( body )
        out = { key: { "probabilities": probs_of( UNREL ) } for key in body[ "questions" ] }
        return { "answers": out, "model": body[ "model" ], "usage": { "input_tokens": 10, "output_tokens": 2 } }, \
               { "status": 200, "attempts": 1, "retry_after": None, "latency_ms": 1 }

    def sent( self ): return json.dumps( self.bodies, sort_keys=True )

    def needs( self ): return { b[ "state" ][ "need" ] for b in self.bodies }


@pytest.fixture( autouse=True )
def no_jev_key( monkeypatch ):
    monkeypatch.delenv( jev_transport.KEY_VARIABLE, raising=False )


@pytest.fixture
def env( tmp_path ):
    root = make_lupin_repo( tmp_path )
    ( root / "src" / "cosa" / "web.py" ).write_text( ROUTER, encoding="utf-8" )
    return root, tmp_path / "data", tmp_path / "out"


@pytest.fixture
def env_with_where( env ):
    """The same repo with one entry naming a path outside sendable()'s roots."""
    ( env[ 0 ] / "src" / "cosa" / "paths.py" ).write_text( WHERE, encoding="utf-8" )
    return env


def plain_ctx( env, fake ):
    return rt.ReuseContext( env[ 0 ], env[ 1 ], out_dir=env[ 2 ], transport=fake )


def packed_ctx( env, fake, size=10 ):
    return rt.ReuseContext( env[ 0 ], env[ 1 ], out_dir=env[ 2 ], transport=fake, sweeper=rp.packed_sweeper( size ), request_shape=rp.SHAPE, pack_size=size )


def stored( env, r ): return json.loads( ( env[ 1 ] / "receipts" / f"{r[ 'receipt_id' ]}.json" ).read_text( encoding="utf-8" ) )


@pytest.mark.parametrize( "make_ctx", [ plain_ctx, packed_ctx ] )
def test_a_need_reaches_jev_redacted_with_the_known_route_kept( env, make_ctx ):
    fake = Recording()
    r    = rt.check_exists_impl( RAW_NEED, make_ctx( env, fake ) )
    assert r[ "status" ] == "ok" and fake.bodies
    assert fake.needs() == { SENT_NEED }
    assert not any( token in fake.sent() for token in RAW_TOKENS )
    assert r[ "need_redactions" ] == [ { "kind": "email", "count": 1 }, { "kind": "ip", "count": 1 }, { "kind": "path", "count": 1 },
                                       { "kind": "secret", "count": 1 }, { "kind": "url", "count": 1 } ]
    rec = stored( env, r )
    assert ( rec[ "query" ], rec[ "need_sent" ], rec[ "routes_source" ] ) == ( SENT_NEED, SENT_NEED, "index" )
    assert rec[ "need_redactions" ] == r[ "need_redactions" ]


def test_an_index_with_no_route_list_redacts_every_absolute_path_and_says_so( env, monkeypatch ):
    monkeypatch.setattr( rt, "known_routes_of", lambda gen: ( (), "none" ) )
    fake = Recording()
    r    = rt.check_exists_impl( RAW_NEED, plain_ctx( env, fake ) )
    assert fake.needs() == { SENT_NEED_NO_ROUTES }
    assert stored( env, r )[ "routes_source" ] == "none"


def test_a_need_the_redactor_leaves_alone_keeps_the_receipt_it_had_before( env ):
    need = "read an RSS feed [clean]"
    fake = Recording()
    r    = rt.check_exists_impl( need, plain_ctx( env, fake ) )
    rec  = stored( env, r )
    assert fake.needs() == { need } and rec[ "query" ] == need
    assert "need_redactions" not in rec and "need_sent" not in rec and "routes_source" not in rec
    assert r[ "need_redactions" ] == []


@pytest.mark.parametrize( "call", [ lambda c: rt.sweep_need_impl( RAW_NEED, None, c ), lambda c: rt.page_route_need_impl( RAW_NEED, None, c ),
                                    lambda c: rt.unstored_need_impl( RAW_NEED, None, c ), lambda c: rt.unstored_need_impl( RAW_NEED, None, c, page_route=True ) ] )
def test_every_entry_that_takes_a_free_text_need_redacts_it( env, call ):
    fake = Recording()
    r    = call( plain_ctx( env, fake ) )
    assert r[ "status" ] == "ok"
    assert fake.needs() == { SENT_NEED } and not any( t in fake.sent() for t in RAW_TOKENS )


def test_the_pair_question_redacts_the_need_too( env ):
    fake = Recording()
    r    = rt.unstored_need_impl( RAW_NEED, None, packed_ctx( env, fake ), question="provides" )
    assert r[ "status" ] in ( "ok", "error" ) and fake.bodies
    assert not any( t in fake.sent() for t in RAW_TOKENS )


def test_fetch_similar_redacts_the_text_of_the_entry_it_sends_as_a_need( env_with_where ):
    env  = env_with_where
    fake = Recording()
    r    = rt.fetch_similar_impl( "cosa.paths.where", plain_ctx( env, fake ) )
    assert r[ "status" ] == "ok"
    assert fake.needs() == { "cosa.paths.where() — Reads [path]." }
    assert "/projects/acme/secret.py" not in json.dumps( [ b[ "state" ][ "need" ] for b in fake.bodies ] )
    assert r[ "need_redactions" ] == [ { "kind": "path", "count": 1 } ]
    assert stored( env, r )[ "query" ] == "cosa.paths.where"                      # the id is not a need and is not redacted


def test_a_replay_of_a_redacted_receipt_reads_the_cache_it_wrote( env_with_where ):
    env  = env_with_where
    fake = Recording()
    ctx  = packed_ctx( env, fake )
    r    = rt.check_exists_impl( RAW_NEED, ctx )
    rep  = rt.replay_impl( r[ "receipt_id" ], ctx )
    assert rep[ "status" ] == "ok" and rep[ "differences" ] == { "frozen": [], "head": [] }
    f    = rt.fetch_similar_impl( "cosa.paths.where", plain_ctx( env, Recording() ) )
    rep2 = rt.replay_impl( f[ "receipt_id" ], plain_ctx( env, Recording() ) )
    assert rep2[ "status" ] == "ok" and rep2[ "differences" ][ "frozen" ] == []


def test_known_routes_come_from_the_generation_and_default_to_none( env, tmp_path ):
    prepared = rt.prepare( plain_ctx( env, Recording() ) )
    assert rt.known_routes_of( prepared[ 3 ] ) == ( ( "/api/v2/submit", ), "index" )
    assert rt.known_routes_of( None ) == ( (), "none" )
    assert rt.known_routes_of( tmp_path / "no-such-generation" ) == ( (), "none" )
    assert rr.routes_from_text( ( pathlib.Path( prepared[ 3 ] ) / "routes.md" ).read_text( encoding="utf-8" ) ) == ( "/api/v2/submit", )
