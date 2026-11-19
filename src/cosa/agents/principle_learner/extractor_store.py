"""
Reads and writes the principle tables for the extractor, and nothing else.

Evidence is append-only: a row is added and never updated. A second run over the same answer finds its rows
already there and adds nothing, so a replay is safe. The nearest-principle read keeps to one encoder version,
because a vector from another encoder cannot be compared with the query.
"""

import math
import uuid

from cosa.rest.postgres_models import PreferenceEvidence, PreferencePrinciple

NEIGHBOURS = 5


def _cosine( left, right ):
    """
    Give the cosine of two vectors.

    Requires:
        - left and right are equal-length sequences of numbers

    Ensures:
        - returns the cosine, or 0.0 when either vector has no length
    """
    norm = math.sqrt( sum( a * a for a in left ) ) * math.sqrt( sum( b * b for b in right ) )
    return sum( a * b for a, b in zip( left, right ) ) / norm if norm else 0.0


def fetch_neighbours( session, owner_id, encoder_version, query_vectors, k=NEIGHBOURS ):
    """
    Find the owner's principles nearest to the query vectors, within one encoder version.

    Requires:
        - session is an active SQLAlchemy session
        - owner_id is a string and encoder_version a non-empty string
        - query_vectors is a list of vectors made by that encoder

    Ensures:
        - returns at most k principle rows, nearest first, ties by id
        - a row is a candidate only when its owner and its encoder_version match and it has a vector
        - a principle of another encoder version is never read into the result, however near it is
        - a row's score is its best cosine over the query vectors
    """
    rows   = session.query( PreferencePrinciple ).filter( PreferencePrinciple.owner_id == owner_id,
                                                         PreferencePrinciple.encoder_version == encoder_version,
                                                         PreferencePrinciple.embedding.isnot( None ) ).all()
    scored = [ ( max( _cosine( list( row.embedding ), vector ) for vector in query_vectors ), str( row.id ), row ) for row in rows ]
    scored.sort( key=lambda item: ( -item[ 0 ], item[ 1 ] ) )
    return [ row for _, _, row in scored[ :k ] ]


def _find_or_create_principle( session, owner_id, kind, dimension, hypothesis, extractor_version, encoder_version, embed_fn, report ):
    """
    Return the principle for a hypothesis, creating it only when none matches.

    Requires:
        - hypothesis is a cleaned hypothesis from check_field
        - embed_fn takes a text and returns a vector

    Ensures:
        - an existing principle of the same owner, extractor version, kind, dimension, statement and scope is reused
        - otherwise one is added and flushed, with its embedding made from the statement and the rationale
        - report counts the principle as created or reused
    """
    match = session.query( PreferencePrinciple ).filter_by( owner_id=owner_id, extractor_version=extractor_version, kind=kind, dimension=dimension,
                                                           statement=hypothesis[ "statement" ], scope=hypothesis[ "scope" ] ).first()
    if match is not None:
        report[ "principles_reused" ] += 1
        return match
    text      = hypothesis[ "statement" ] + ( "\n" + hypothesis[ "rationale" ] if hypothesis[ "rationale" ] else "" )
    principle = PreferencePrinciple( id=uuid.uuid4(), owner_id=owner_id, kind=kind, dimension=dimension, statement=hypothesis[ "statement" ],
                                     rationale=hypothesis[ "rationale" ], scope=hypothesis[ "scope" ], embedding=embed_fn( text ),
                                     encoder_version=encoder_version, extractor_version=extractor_version )
    session.add( principle )
    session.flush()
    report[ "principles_created" ] += 1
    return principle


def _write_evidence( session, principle, notification_id, field_key, relation, condition, answered_at, extracted_at, extractor_version, report ):
    """
    Add one evidence row unless its unique key already exists.

    Requires:
        - principle is a flushed principle row

    Ensures:
        - a row with the same principle, notification, field, extractor version and source "extractor" is never added twice
        - report counts the row as written or already present
    """
    key = dict( principle_id=principle.id, notification_id=notification_id, field_key=field_key, extractor_version=extractor_version, source="extractor" )
    if session.query( PreferenceEvidence ).filter_by( **key ).first() is not None:
        report[ "evidence_existing" ] += 1
        return
    session.add( PreferenceEvidence( id=uuid.uuid4(), relation=relation, condition=condition, answered_at=answered_at, extracted_at=extracted_at, **key ) )
    session.flush()
    report[ "evidence_written" ] += 1


def apply_field( session, owner_id, notification_id, field_key, checked, neighbours, times, versions, embed_fn, report ):
    """
    Write what one checked field result adds: new principles and evidence rows.

    Requires:
        - checked is a check_field result for the field
        - neighbours is the list of principle rows the model was shown
        - times is ( answered_at, extracted_at ) as datetimes
        - versions is ( extractor_version, encoder_version )
        - report holds the counters principles_created, principles_reused, evidence_written, evidence_existing and dimension_mismatches

    Ensures:
        - a hypothesis joins every named principle whose scope equals the hypothesis scope, with the relation the model gave and
          the hypothesis condition; a named principle whose dimension differs from the field's is listed in dimension_mismatches
          and is still joined
        - a hypothesis that no named principle matches creates a principle, or reuses an identical one, with a supports row
        - with no hypothesis, each named principle gets one evidence row with the relation given and no condition
        - the same input written twice adds nothing the second time
    """
    answered_at, extracted_at   = times
    extractor_version, encoder_version = versions
    by_id = { str( row.id ): row for row in neighbours }
    named = { pid: relation for pid, relation in checked[ "relations" ].items() if pid in by_id }
    def record( principle, relation, condition ):
        if principle.dimension != checked[ "dimension" ]: report[ "dimension_mismatches" ].append( { "principle_id": str( principle.id ), "field_key": field_key } )
        _write_evidence( session, principle, notification_id, field_key, relation, condition, answered_at, extracted_at, extractor_version, report )
    if not checked[ "hypotheses" ]:
        for pid, relation in sorted( named.items() ): record( by_id[ pid ], relation, None )
        return
    for hypothesis in checked[ "hypotheses" ]:
        targets = sorted( pid for pid in named if by_id[ pid ].scope == hypothesis[ "scope" ] )
        for pid in targets: record( by_id[ pid ], named[ pid ], hypothesis[ "condition" ] )
        if not targets:
            principle = _find_or_create_principle( session, owner_id, checked[ "kind" ], checked[ "dimension" ], hypothesis, extractor_version, encoder_version, embed_fn, report )
            _write_evidence( session, principle, notification_id, field_key, "supports", hypothesis[ "condition" ], answered_at, extracted_at, extractor_version, report )
