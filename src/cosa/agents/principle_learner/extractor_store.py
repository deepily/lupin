"""
Reads and writes the principle tables for the extractor, and nothing else.

Evidence is append-only: a row is added and never updated. A second run over the same answer finds its rows
already there and adds nothing, so a replay is safe. The nearest-principle read keeps to one encoder version,
because a vector from another encoder cannot be compared with the query.
"""

import hashlib
import uuid

from cosa.agents.prediction_engine.principle_retrieval import embedding_text
from cosa.agents.prediction_engine.principle_status import CONDITION_KEYS_SWITCH, SOURCE_DEDUP_SWITCH, compute_condition_key, normalise_key, switch_on
from cosa.agents.principle_learner.vocabulary import same_heading
from cosa.rest.postgres_models import PreferenceEvidence, PreferencePrinciple
from cosa.rest.repair_attempt_tracker import cosine_similarity

NEIGHBOURS = 5


def fetch_neighbours( session, owner_id, encoder_version, query_vectors, before, k=NEIGHBOURS ):
    """
    Find the owner's principles nearest to the query vectors, within one encoder version.

    Requires:
        - session is an active SQLAlchemy session
        - owner_id is a string and encoder_version a non-empty string
        - query_vectors is a list of vectors made by that encoder
        - before is a timezone-aware datetime: the run's time

    Ensures:
        - returns at most k principle rows, nearest first, ties by id
        - a row is a candidate only when its owner and its encoder_version match and it has a vector
        - a principle of another encoder version is never read into the result, however near it is
        - a row's score is its best cosine over the query vectors
        - a row is a candidate only when its created_at is strictly before the run's time, so a rerun at an earlier time
          never sees a principle made later
    """
    rows   = session.query( PreferencePrinciple ).filter( PreferencePrinciple.owner_id == owner_id,
                                                         PreferencePrinciple.encoder_version == encoder_version,
                                                         PreferencePrinciple.embedding.isnot( None ),
                                                         PreferencePrinciple.created_at < before ).all()
    scored = [ ( max( cosine_similarity( list( row.embedding ), vector ) for vector in query_vectors ), str( row.id ), row ) for row in rows ]
    scored.sort( key=lambda item: ( -item[ 0 ], item[ 1 ] ) )
    return [ row for _, _, row in scored[ :k ] ]


def _find_or_create_principle( session, owner_id, kind, dimension, hypothesis, extractor_version, encoder_version, embed_fn, continues, created_at, report ):
    """
    Return the principle for a hypothesis, creating it only when none matches.

    Requires:
        - hypothesis is a cleaned hypothesis from check_field
        - embed_fn takes a text and returns a vector
        - continues is the id of the earlier-version principle a new principle continues, or None
        - created_at is the run's time; a new principle takes it, never the database default

    Ensures:
        - an existing principle of the same owner, extractor version, kind, dimension, statement and scope is reused
        - otherwise one is added and flushed, with its embedding made from the statement and the rationale
        - a new principle carries continues_principle_id from continues; a reused one is never changed
        - report counts the principle as created or reused
        - two jobs for one answer at the same moment could both add a principle, since the table has no unique key
          on this match; the job is queued once per answer, so that is not guarded
    """
    match = session.query( PreferencePrinciple ).filter_by( owner_id=owner_id, extractor_version=extractor_version, kind=kind, dimension=dimension,
                                                           statement=hypothesis[ "statement" ], scope=hypothesis[ "scope" ] ).first()
    if match is not None:
        report[ "principles_reused" ] += 1
        return match
    text      = embedding_text( hypothesis[ "statement" ], hypothesis[ "rationale" ] )
    principle = PreferencePrinciple( id=uuid.uuid4(), owner_id=owner_id, kind=kind, dimension=dimension, statement=hypothesis[ "statement" ],
                                     rationale=hypothesis[ "rationale" ], scope=hypothesis[ "scope" ], embedding=embed_fn( text ),
                                     encoder_version=encoder_version, extractor_version=extractor_version,
                                     continues_principle_id=continues, created_at=created_at )
    session.add( principle )
    session.flush()
    report[ "principles_created" ] += 1
    return principle


def source_key_for( card, answer ):
    """
    Name the one source behind an answer, so a card asked twice shares a key.

    Requires:
        - card and answer are strings or None

    Ensures:
        - returns the first 32 hex digits of the sha-256 of the normalised card text and the normalised answer text
        - texts that differ only in case, spacing or end punctuation give one key
    """
    return hashlib.sha256( f"{normalise_key( card ) or ''}\x1f{normalise_key( answer ) or ''}".encode( "utf-8" ) ).hexdigest()[ :32 ]


def evidence_keys( session, principle, condition, hypothesis, source_key, complete ):
    """
    Work out the stored keys of one evidence row, each behind its own switch.

    Requires:
        - principle is a flushed principle row; hypothesis is the checked hypothesis dict, or None
        - complete maps ( system, user ) to a model reply, or is None

    Ensures:
        - with the condition-keys switch off, or no condition, no condition_key is returned
        - with it on, condition_key is the key compute_condition_key gives, reusing the keys already stored for the principle;
          with complete None it is the normalised condition and no model is called
        - with the source-dedup switch off, neither source_key nor standing_quote is returned
        - with it on, source_key is the one given, and standing_quote is the hypothesis's stripped standing_quote, or None when it has none
    """
    keys = {}
    if condition and switch_on( CONDITION_KEYS_SWITCH ):
        stored = [ key for ( key, ) in session.query( PreferenceEvidence.condition_key ).filter( PreferenceEvidence.principle_id == principle.id,
                                                                                                    PreferenceEvidence.condition_key.isnot( None ) ).distinct() ]
        keys[ "condition_key" ] = normalise_key( condition ) if complete is None else compute_condition_key( condition, stored, complete )
    if switch_on( SOURCE_DEDUP_SWITCH ):
        keys[ "source_key"     ] = source_key
        keys[ "standing_quote" ] = ( ( hypothesis or {} ).get( "standing_quote" ) or "" ).strip() or None
    return keys


def _write_evidence( session, principle, notification_id, field_key, relation, condition, answered_at, extracted_at, extractor_version, session_key, report, keys=None ):
    """
    Add one evidence row unless its unique key already exists.

    Requires:
        - principle is a flushed principle row
        - session_key is the session of the answered notification, or None

    Ensures:
        - a row with the same principle, notification, field, extractor version and source "extractor" is never added twice
        - a new row carries session_key, so status can count sessions after the notification is pruned
        - a new row also carries each of keys, a dict of evidence column to value, or none when keys is None
        - report counts the row as written or already present
    """
    key = dict( principle_id=principle.id, notification_id=notification_id, field_key=field_key, extractor_version=extractor_version, source="extractor" )
    if session.query( PreferenceEvidence ).filter_by( **key ).first() is not None:
        report[ "evidence_existing" ] += 1
        return
    fields = { "id": uuid.uuid4(), "relation": relation, "condition": condition, "answered_at": answered_at, "extracted_at": extracted_at,
               "session_key": session_key }
    fields.update( keys or {} )
    session.add( PreferenceEvidence( **fields, **key ) )
    session.flush()
    report[ "evidence_written" ] += 1


def apply_field( session, owner_id, notification_id, field_key, checked, neighbours, times, versions, embed_fn, session_key, report, key_complete=None, source_key=None ):
    """
    Write what one checked field result adds: new principles and evidence rows.

    Requires:
        - checked is a check_field result for the field
        - neighbours is the list of principle rows the model was shown
        - times is ( answered_at, extracted_at ) as datetimes
        - versions is ( extractor_version, encoder_version )
        - session_key is the session of the answered notification, or None
        - report holds the counters principles_created, principles_reused, evidence_written, evidence_existing and dimension_mismatches
        - key_complete is None or maps ( system, user ) to a model reply, for the condition key; source_key is None or the source's key

    Ensures:
        - a hypothesis joins every named principle whose scope equals the hypothesis scope, with the relation the model gave and
          the hypothesis condition; a named principle whose dimension files under another heading than the field's is listed in dimension_mismatches
          and is still joined
        - a hypothesis that no named principle matches creates a principle, or reuses an identical one, with a supports row
        - a principle created here carries continues_principle_id: the lowest id among the named principles of another extractor
          version, or None when none is named; a relation within one version never sets it, whatever the relation word
        - every evidence row written carries session_key
        - with the condition-keys or source-dedup switch on, a row also carries what evidence_keys gives; with both off, nothing is added
        - with no hypothesis, each named principle gets one evidence row with the relation given and no condition
        - the same input written twice adds nothing the second time
    """
    answered_at, extracted_at   = times
    extractor_version, encoder_version = versions
    by_id = { str( row.id ): row for row in neighbours }
    named = { pid: relation for pid, relation in checked[ "relations" ].items() if pid in by_id }
    def record( principle, relation, condition, hypothesis=None ):
        if not same_heading( principle.dimension, checked[ "dimension" ] ): report[ "dimension_mismatches" ].append( { "principle_id": str( principle.id ), "field_key": field_key } )
        _write_evidence( session, principle, notification_id, field_key, relation, condition, answered_at, extracted_at, extractor_version, session_key, report,
                         keys=evidence_keys( session, principle, condition, hypothesis, source_key, key_complete ) )
    if not checked[ "hypotheses" ]:
        for pid, relation in sorted( named.items() ): record( by_id[ pid ], relation, None )
        return
    for hypothesis in checked[ "hypotheses" ]:
        targets = sorted( pid for pid in named if by_id[ pid ].scope == hypothesis[ "scope" ] )
        for pid in targets: record( by_id[ pid ], named[ pid ], hypothesis[ "condition" ], hypothesis )
        if not targets:
            earlier   = sorted( pid for pid in named if by_id[ pid ].extractor_version != extractor_version )
            continues = by_id[ earlier[ 0 ] ].id if earlier else None
            principle = _find_or_create_principle( session, owner_id, checked[ "kind" ], checked[ "dimension" ], hypothesis, extractor_version, encoder_version, embed_fn, continues, extracted_at, report )
            _write_evidence( session, principle, notification_id, field_key, "supports", hypothesis[ "condition" ], answered_at, extracted_at, extractor_version, session_key, report,
                             keys=evidence_keys( session, principle, hypothesis[ "condition" ], hypothesis, source_key, key_complete ) )
