"""
Principle retrieval, re-embedding and the prompt block, over in-memory SQLite.

SQLite stands in for Postgres for three tables. JSONB and vector columns render as JSON and text.
The cosine operator of pgvector does not exist there. So `dot_topk` is replaced by a stand-in.
The stand-in applies the real SQL filter it is given. A filter that lets another owner through is caught.
It ranks by cosine computed in Python. Rows are synthetic.

Each test names what it would catch:
  - contested principles using up slots                     -> test_contested_outrank_applicable_*
  - a future principle retrieved                            -> test_no_future_principle_*
  - vectors of two encoders compared                        -> test_same_encoder_only_*, test_reembed_*
  - a scope leak between plans with identical wording       -> test_collision_*
  - a block that carries answer text or can be forged       -> test_block_*
"""

import uuid
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest
from pgvector.sqlalchemy import Vector
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

import cosa.agents.prediction_engine.principle_retrieval as pr
from cosa.agents.prediction_engine.principle_retrieval import ( PrincipleBoundExceeded, embedding_text, encoder_version_of, load_owner_ledger, principle_block,
                                                                 reembed_principles, retrieve_principles, select_principles, session_lookup )
from cosa.rest.postgres_models import Notification, PreferenceEvidence, PreferencePrinciple

ASK   = datetime( 2026, 11, 10, 12, 0, tzinfo=timezone.utc )
HOUR  = timedelta( hours=1 )
OWNER = "owner-a"
ENC   = encoder_version_of( "model-x" )
EXT   = "sonnet|v1"


@compiles( JSONB, "sqlite" )
def _jsonb_as_json( element, compiler, **kw ):
    """Render JSONB as JSON when the dialect is SQLite."""
    return "JSON"


@compiles( Vector, "sqlite" )
def _vector_as_text( element, compiler, **kw ):
    """
    Render a pgvector column as a text column on SQLite.

    Render a pgvector column as a text column when the dialect is SQLite.
    """
    return "TEXT"


def vec( x, y ):
    """A 768-wide vector with two non-zero entries."""
    return [ float( x ), float( y ) ] + [ 0.0 ] * 766


def uid( n ):
    """A UUID with a letter in every group, so SQLite does not read it as a number."""
    return uuid.UUID( f"aaaaaaaa-0000-4000-8000-{n:012d}" )


@pytest.fixture
def db():
    """Give a session over empty copies of the three tables; the engine is disposed afterwards."""
    engine = create_engine( "sqlite://" )
    for model in ( PreferencePrinciple, PreferenceEvidence, Notification ): model.__table__.create( engine )
    with Session( engine ) as session: yield session
    engine.dispose()


@pytest.fixture( autouse=True )
def stand_in_topk( monkeypatch ):
    """
    Replace dot_topk with a stand-in that applies the real filter.

    Replace dot_topk with one that applies the real filter and ranks by cosine; record each call.
    """
    calls = []
    def fake( session, model, vector_column, query_embedding, limit, exclude_filter=None, threshold_pct=None, clamp=False, metric="dot" ):
        calls.append( { "limit": limit, "metric": metric, "filter": exclude_filter } )
        rows   = session.query( model ).filter( exclude_filter ).all()
        q      = np.array( query_embedding )
        scored = [ ( float( np.dot( q, r.embedding ) / ( np.linalg.norm( q ) * np.linalg.norm( r.embedding ) ) ) * 100.0, r ) for r in rows ]
        return sorted( scored, key=lambda pair: -pair[ 0 ] )[ :limit ]
    monkeypatch.setattr( pr, "dot_topk", fake )
    return calls


def add_principle( db, n, embedding=None, scope="global", owner=OWNER, encoder=ENC, version=EXT, statement=None, rationale=None, dimension="d" ):
    """Add a principle row and return it."""
    p = PreferencePrinciple( id=uid( n ), owner_id=owner, kind="decision", dimension=dimension, statement=statement or f"statement {n}", rationale=rationale,
                             scope=scope, embedding=embedding if embedding is not None else vec( 1, n ), encoder_version=encoder, extractor_version=version )
    db.add( p )
    db.commit()
    return p


def add_evidence( db, principle, note, relation="supports", answered=-HOUR, extracted=-HOUR, condition=None, version=EXT, source="extractor" ):
    """Add an evidence row for a principle."""
    db.add( PreferenceEvidence( id=uuid.uuid4(), principle_id=principle.id, notification_id=uid( 900 + note ), field_key="f", relation=relation, condition=condition,
                                answered_at=ASK + answered, extracted_at=ASK + extracted, extractor_version=version, source=source ) )
    db.commit()


def add_notification( db, note, sender ):
    """Add a notification the evidence can point at."""
    db.add( Notification( id=uid( 900 + note ), recipient_id=uid( 1 ), sender_id=sender, title="t", message="m", type="task", priority="low", response_requested=False ) )
    db.commit()


def two_sessions( db ):
    """Make notifications 1 and 2 come from two different sessions, so two supports establish."""
    add_notification( db, 1, "claude.code@lupin.deepily.ai#aaaa1111" )
    add_notification( db, 2, "claude.code@lupin.deepily.ai#bbbb2222" )


def retrieve( db, project=None, k=5, at=ASK, query=None, **kwargs ):
    """Call retrieve_principles with the module's fixed owner, encoder and extractor version."""
    return retrieve_principles( db, OWNER, project, query or vec( 1, 0 ), at, ENC, EXT, k=k, **kwargs )


def statements( result ):
    """The statements retrieved, in order."""
    return [ e[ "principle" ].statement for e in result[ "principles" ] ]


def test_embedding_text_and_encoder_version():
    """The embedded text is statement then rationale; the encoder version names model and recipe."""
    assert embedding_text( type( "P", (), { "statement": "s", "rationale": None } ) ) == "s"
    assert embedding_text( type( "P", (), { "statement": "s", "rationale": "r" } ) ) == "s\nr"
    assert encoder_version_of( "m" ) == "m|statement-and-rationale-v1"


def test_retrieval_ranks_by_cosine_and_keeps_k( db, stand_in_topk ):
    """
    Principles come back in cosine order, cut to k.

    Principles come back in cosine order, cut to k, from one cosine search over all that pass the filter.
    """
    ps = [ add_principle( db, n, embedding=vec( 10 - n, n ) ) for n in range( 1, 5 ) ]
    for n, p in enumerate( ps, 1 ):
        add_notification( db, n, f"claude.code@lupin.deepily.ai#s{n:04d}" )
        add_evidence( db, p, n )
    result = retrieve( db, k=3 )
    assert statements( result ) == [ "statement 1", "statement 2", "statement 3" ] and result[ "available" ] == 4 and result[ "short" ] is False
    assert [ ( c[ "limit" ], c[ "metric" ] ) for c in stand_in_topk ] == [ ( 4, "cosine" ) ]


def test_contested_outrank_applicable_does_not_cost_a_slot( db ):
    """Three contested principles ranked first leave five applicable ones, when that many exist."""
    two_sessions( db )
    for n in range( 1, 4 ):
        p = add_principle( db, n, embedding=vec( 1, 0.01 * n ) )
        add_evidence( db, p, 1 )
        add_evidence( db, p, 2, relation="contradicts" )
    for n in range( 4, 10 ):
        add_evidence( db, add_principle( db, n, embedding=vec( 1, n ) ), 1 )
    result = retrieve( db, k=5 )
    assert statements( result ) == [ f"statement {n}" for n in range( 4, 9 ) ]
    assert { e[ "status" ] for e in result[ "principles" ] } == { "hypothesis" }


def test_retracted_and_evidence_less_principles_are_dropped( db ):
    """
    A principle that is retracted or has no evidence is never retrieved.

    A principle with only contradicting evidence, and one with no evidence, are never retrieved.
    """
    add_evidence( db, add_principle( db, 1 ), 1, relation="contradicts" )
    add_principle( db, 2 )
    add_evidence( db, add_principle( db, 3 ), 1 )
    assert statements( retrieve( db ) ) == [ "statement 3" ]


def test_no_future_principle_when_its_only_evidence_comes_after_the_ask( db ):
    """
    Evidence after the ask hides the principle from that ask only.

    Evidence answered, or extracted, after the ask makes the principle invisible to that ask, and visible later.
    """
    add_evidence( db, add_principle( db, 1 ), 1, answered=HOUR )
    add_evidence( db, add_principle( db, 2 ), 2, extracted=HOUR )
    add_evidence( db, add_principle( db, 3 ), 3 )
    assert statements( retrieve( db ) ) == [ "statement 3" ]
    assert sorted( statements( retrieve( db, at=ASK + 2 * HOUR ) ) ) == [ "statement 1", "statement 2", "statement 3" ]


def test_ruling_is_as_of_through_retrieval( db ):
    """A contested principle returns once a ruling that existed at the ask stands, not before it."""
    two_sessions( db )
    p = add_principle( db, 1 )
    add_evidence( db, p, 1 )
    add_evidence( db, p, 2, relation="contradicts" )
    add_evidence( db, p, 3, source="review_card", answered=HOUR, extracted=HOUR )
    assert retrieve( db )[ "principles" ] == []
    assert statements( retrieve( db, at=ASK + 2 * HOUR ) ) == [ "statement 1" ]


def test_same_encoder_only_and_reembed_brings_the_table_back( db ):
    """A principle of another encoder is never compared; after a re-embed it is."""
    old = add_principle( db, 1, encoder="old-model|statement-and-rationale-v1" )
    add_evidence( db, old, 1 )
    add_evidence( db, add_principle( db, 2 ), 2 )
    assert statements( retrieve( db ) ) == [ "statement 2" ]
    class Provider:
        def __init__( self ): self.seen = []
        def generate_embeddings_batch( self, texts ):
            self.seen.append( texts )
            return [ vec( 1, 5 ) for _ in texts ]
    provider = Provider()
    assert reembed_principles( db, OWNER, provider, ENC ) == 1
    assert provider.seen == [ [ "statement 1" ] ]
    assert sorted( statements( retrieve( db ) ) ) == [ "statement 1", "statement 2" ]
    assert reembed_principles( db, OWNER, provider, ENC ) == 0 and len( provider.seen ) == 1


def test_reembed_also_fills_a_missing_embedding_and_uses_the_rationale( db ):
    """
    A principle with no vector is embedded from statement and rationale.

    A principle with no vector is embedded from its statement and rationale, and gets this encoder's name.
    """
    p = add_principle( db, 1, rationale="because" )
    p.embedding = None
    db.commit()
    class Provider:
        def generate_embeddings_batch( self, texts ): return [ vec( 3, 4 ) for _ in texts ] if texts == [ "statement 1\nbecause" ] else []
    assert reembed_principles( db, OWNER, Provider(), ENC ) == 1
    assert db.query( PreferencePrinciple ).one().embedding[ 1 ] == 4.0


def test_reembed_refuses_a_wrong_count_and_changes_nothing( db ):
    """A provider that returns too few vectors fails loudly and leaves the rows as they were."""
    add_principle( db, 1, encoder="old" )
    class Provider:
        def generate_embeddings_batch( self, texts ): return []
    with pytest.raises( ValueError, match="0 vectors for 1 principles" ): reembed_principles( db, OWNER, Provider(), ENC )
    assert db.query( PreferencePrinciple ).one().encoder_version == "old"


def test_reembed_touches_only_the_named_owner( db ):
    """Another owner's stale principle is left alone and costs no provider call."""
    add_principle( db, 1, owner="owner-b", encoder="old" )
    class Provider:
        def generate_embeddings_batch( self, texts ): raise AssertionError( "no call expected" )
    assert reembed_principles( db, OWNER, Provider(), ENC ) == 0


def test_another_owners_principles_are_never_retrieved( db ):
    """The SQL filter holds the owner: a stranger's principle with perfect evidence is absent."""
    add_evidence( db, add_principle( db, 1, owner="owner-b" ), 1 )
    assert retrieve( db ) == { "principles": [], "available": 0, "short": True }


def test_collision_identical_wording_over_two_plans_does_not_share_scoped_principles( db ):
    """
    Identical wording in two projects gets different blocks.

    Two asks with the same wording in two projects get different blocks; a model reading the block cites or abstains accordingly.
    """
    add_evidence( db, add_principle( db, 1, scope="project:alpha", statement="alpha only rule" ), 1 )
    add_evidence( db, add_principle( db, 2, scope="project:beta", statement="beta only rule" ), 2 )
    blocks = { project: principle_block( retrieve( db, project=project )[ "principles" ], suffix="abcd1234" ) for project in ( "alpha", "beta", "gamma", None ) }
    def model( block ): return { "abstain": True } if not block[ "text" ] else { "cites": block[ "principle_ids" ] }
    assert blocks[ "alpha" ][ "text" ] != blocks[ "beta" ][ "text" ]
    assert "alpha only rule" in blocks[ "alpha" ][ "text" ] and "beta only rule" not in blocks[ "alpha" ][ "text" ]
    assert model( blocks[ "alpha" ] ) == { "cites": [ uid( 1 ) ] } and model( blocks[ "beta" ] ) == { "cites": [ uid( 2 ) ] }
    assert model( blocks[ "gamma" ] ) == { "abstain": True } and model( blocks[ None ] ) == { "abstain": True }


def test_global_principles_reach_every_project( db ):
    """A global principle is retrieved for any project; a project one only for its own."""
    add_evidence( db, add_principle( db, 1, scope="global" ), 1 )
    add_evidence( db, add_principle( db, 2, scope="project:alpha" ), 2 )
    assert sorted( statements( retrieve( db, project="alpha" ) ) ) == [ "statement 1", "statement 2" ]
    assert statements( retrieve( db, project="beta" ) ) == [ "statement 1" ]


def test_short_is_reported_when_fewer_than_k_survive( db ):
    """
    Fewer than k survivors are flagged short.

    Fewer than k survivors still forecast, and the shortfall is flagged for the caller to record.
    """
    add_evidence( db, add_principle( db, 1 ), 1 )
    result = retrieve( db, k=5 )
    assert result[ "short" ] is True and result[ "available" ] == 1 and len( result[ "principles" ] ) == 1


def test_the_bound_is_refused_not_worked_around( db ):
    """Above the bound retrieval raises; at the bound it runs, with no multiplier."""
    for n in range( 1, 4 ): add_evidence( db, add_principle( db, n ), n )
    with pytest.raises( PrincipleBoundExceeded, match="3 principles" ): retrieve( db, bound=2 )
    assert len( retrieve( db, bound=3 )[ "principles" ] ) == 3


def test_load_owner_ledger_returns_every_version_and_only_this_owner( db ):
    """
    The owner's principles of every version come back with their evidence.

    A stranger's rows do not, and an owner with no principles has no evidence.
    """
    a, b = add_principle( db, 1, version="v1" ), add_principle( db, 2, version="v2" )
    other = add_principle( db, 3, owner="owner-b" )
    add_evidence( db, a, 1 )
    add_evidence( db, other, 2 )
    principles, evidence = load_owner_ledger( db, OWNER )
    assert { p.id for p in principles } == { a.id, b.id } and [ e.principle_id for e in evidence ] == [ a.id ]
    assert load_owner_ledger( db, "nobody" ) == ( [], [] )


def test_session_lookup_names_the_session_or_none( db ):
    """
    A notification gives its sender's session, or None.

    An unknown id, or a sender with no session, gives None; no ids means no query.
    """
    add_notification( db, 1, "claude.code@lupin.deepily.ai#aaaa1111" )
    add_notification( db, 2, "claude.code@lupin.deepily.ai" )
    lookup = session_lookup( db, [ uid( 901 ), uid( 902 ), uid( 999 ) ] )
    assert [ lookup( uid( 901 ) ), lookup( uid( 902 ) ), lookup( uid( 999 ) ) ] == [ "aaaa1111", None, None ]
    assert session_lookup( db, [] )( uid( 901 ) ) is None


def test_select_principles_keeps_order_and_k():
    """The first k usable principles are kept in the order given; unusable ones take no slot."""
    ps = [ type( "P", (), { "id": n } ) for n in range( 5 ) ]
    statuses = { 0: { "status": "contested", "conditions": [] }, 1: None, 2: { "status": "established", "conditions": [ "c" ] },
                 3: { "status": "hypothesis", "conditions": [] }, 4: { "status": "established", "conditions": [] } }
    kept = select_principles( [ ( 90 - n, p ) for n, p in enumerate( ps ) ], statuses, k=2 )
    assert [ ( e[ "principle" ].id, e[ "similarity_pct" ], e[ "conditions" ] ) for e in kept ] == [ ( 2, 88, [ "c" ] ), ( 3, 87, [] ) ]


def test_block_lists_statements_and_conditions_but_no_rationale_or_evidence( db ):
    """
    The block names each principle, its status, scope, dimension and conditions.

    The rationale stays out.
    """
    p = add_principle( db, 1, statement="link what you ask me to approve", rationale="Rick said: 'I never click blind'", dimension="ask.approval_needs_link" )
    add_evidence( db, p, 1, condition="field asks for approval" )
    block = principle_block( retrieve( db )[ "principles" ], suffix="beef0001" )
    assert block[ "principle_ids" ] == [ p.id ] and block[ "suffix" ] == "beef0001"
    assert block[ "text" ].startswith( "<principles_beef0001>" ) and block[ "text" ].endswith( "</principles_beef0001>" )
    assert "link what you ask me to approve" in block[ "text" ] and "applies when: field asks for approval" in block[ "text" ]
    assert "[hypothesis; global; ask.approval_needs_link]" in block[ "text" ] and "never click blind" not in block[ "text" ]


def test_block_without_conditions_has_no_when_clause_and_an_empty_selection_is_empty( db ):
    """No condition means no 'applies when'; nothing selected means no text at all."""
    p = add_principle( db, 1 )
    add_evidence( db, p, 1 )
    assert "applies when" not in principle_block( retrieve( db )[ "principles" ], suffix="beef0001" )[ "text" ]
    assert principle_block( [] ) == { "text": "", "principle_ids": [], "suffix": None }


def test_block_suffix_never_appears_in_a_statement( db, monkeypatch ):
    """
    A statement holding the first random suffix cannot close the block.

    Another suffix is drawn.
    """
    draws = iter( [ "deadbeef", "deadbeef", "cafe0002" ] )
    monkeypatch.setattr( pr.secrets, "token_hex", lambda n: next( draws ) )
    p = add_principle( db, 1, statement="never write deadbeef in a tag" )
    add_evidence( db, p, 1 )
    block = principle_block( retrieve( db )[ "principles" ] )
    assert block[ "suffix" ] == "cafe0002" and "deadbeef" in block[ "text" ] and "</principles_cafe0002>" in block[ "text" ]
