"""
Load a captured slice of a real principle store and observe the principle code on it.

The slice is a JSON file with principles, evidence rows, notifications and cards. Ids, session
names and conditions are renamed, and no statement text is held. Each card carries the cosine
order the real vectors gave, so no vector is stored. The capture and the test both go through
this module, so the expected values and the compared values are made the same way.
"""

import uuid
from contextlib import contextmanager
from datetime import datetime
from unittest import mock

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from cosa.agents.prediction_engine.principle_features import feature_lookup
from cosa.research.preference_replay import scratch_db  # noqa: F401  registers the SQLite hooks for JSONB and Vector
from cosa.rest.postgres_models import Notification, PreferenceEvidence, PreferencePrinciple

OWNER   = "owner-slice"
ENCODER = "slice-encoder"
VECTOR  = [ 1.0 ] + [ 0.0 ] * 767


def row_id( name ):
    """
    Turn a slice name into a stable UUID.

    Ensures:
        - the same name gives the same id, and the id has letters, so SQLite does not read it as a number
    """
    return uuid.uuid5( uuid.NAMESPACE_URL, f"principle-slice/{name}" )


def _moment( text ):
    """Read a stored ISO time, or None."""
    return None if text is None else datetime.fromisoformat( text )


@contextmanager
def slice_session( data ):
    """
    Open a session over an in-memory database holding the slice.

    Requires:
        - data is the slice dict: extractor, principles, evidence, notifications, cards

    Ensures:
        - yields the session; the engine is disposed on exit
    """
    engine = create_engine( "sqlite://" )
    for model in ( PreferencePrinciple, PreferenceEvidence, Notification ): model.__table__.create( engine )
    with Session( engine ) as session:
        for p in data[ "principles" ]:
            session.add( PreferencePrinciple( id=row_id( p[ "id" ] ), owner_id=OWNER, kind="decision", dimension="d", statement=f"statement {p[ 'id' ]}", scope="global",
                                              embedding=VECTOR, encoder_version=ENCODER, extractor_version=data[ "extractor" ],
                                              continues_principle_id=None if p[ "continues" ] is None else row_id( p[ "continues" ] ) ) )
        for principle, note, field, relation, condition, answered, extracted, retracted, source, session_key, version in data[ "evidence" ]:
            session.add( PreferenceEvidence( id=uuid.uuid4(), principle_id=row_id( principle ), notification_id=row_id( note ), field_key=field, relation=relation,
                                             condition=condition, answered_at=_moment( answered ), extracted_at=_moment( extracted ), retracted_at=_moment( retracted ),
                                             source=source, session_key=session_key, extractor_version=version ) )
        for note, sender, response_type, kind in data[ "notifications" ]:
            session.add( Notification( id=row_id( note ), recipient_id=row_id( "recipient" ), sender_id=sender, response_type=response_type, type=kind,
                                       title="t", message="m", priority="low", response_requested=False ) )
        session.commit()
        yield session
    engine.dispose()


def observe( data, session, retrieval, status ):
    """
    Ask the given modules about every card of the slice.

    Requires:
        - session is slice_session's, over the same data
        - retrieval has retrieve_principles, load_owner_ledger, session_lookup and dot_topk; status has derive_statuses

    Ensures:
        - returns, per card, { kept: [ [ name, similarity, status, conditions ] ], available, short, standings }
        - standings maps each principle name with usable evidence to [ status, conditions, episodes, sessions, ruled ]
        - the comparison switches are off, as shipped; the result is JSON-shaped
    """
    names  = { row_id( p[ "id" ] ): p[ "id" ] for p in data[ "principles" ] }
    rows   = { p.id: p for p in session.query( PreferencePrinciple ).all() }
    result = []
    for card in data[ "cards" ]:
        asked = _moment( card[ "asked_at" ] )
        found = [ ( similarity, rows[ row_id( name ) ] ) for name, similarity in card[ "order" ] ]
        with mock.patch.object( retrieval, "dot_topk", lambda *a, **k: found ):
            got = retrieval.retrieve_principles( session, OWNER, None, VECTOR, asked, ENCODER, data[ "extractor" ] )
        principles, evidence = retrieval.load_owner_ledger( session, OWNER )
        sessions  = retrieval.session_lookup( session, [ e.notification_id for e in evidence if e.session_key is None ] )
        standings = status.derive_statuses( principles, evidence, asked, data[ "extractor" ], sessions,
                                            feature_lookup( session, [ e.notification_id for e in evidence ] ), condition_keys=False, source_dedup=False )
        result.append( {
            "kept"      : [ [ names[ e[ "principle" ].id ], e[ "similarity_pct" ], e[ "status" ], e[ "conditions" ] ] for e in got[ "principles" ] ],
            "available" : got[ "available" ],
            "short"     : got[ "short" ],
            "standings" : { names[ key ]: [ s[ "status" ], s[ "conditions" ], s[ "episodes" ], s[ "sessions" ], s[ "ruled" ] ] for key, s in standings.items() if s is not None },
        } )
    return result
