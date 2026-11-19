"""
Fetch the principles that apply to one ask, and shape them as a prompt block.

Retrieval is cosine over each principle's statement and rationale.
Owner, scope and ``encoder_version`` are columns, so they go in the SQL filter.
Status depends on the ask's moment, so it cannot be a SQL filter and is applied after the search.
Every principle that passes the SQL filter is fetched, and its status is derived as of the ask
(``principle_status.derive_statuses``). Contested, retracted and evidence-less ones are dropped, and the first ``k`` are kept.
Contested principles therefore never use up a slot.

Below ``PRINCIPLE_BOUND`` principles per owner no multiplier is used.
Above it this module refuses, because the plan leaves the multiplier to be stated when the bound is first crossed.

A change of encoder re-embeds the table (``reembed_principles``) and never mixes two encoders' vectors.
"""

import secrets

from sqlalchemy import and_

from cosa.agents.prediction_engine.principle_status import CONTESTED, RETRACTED, derive_statuses
from cosa.rest.db.repositories.vector_search import dot_topk
from cosa.rest.postgres_models import Notification, PreferenceEvidence, PreferencePrinciple
from cosa.utils.notification_utils import sender_session_suffix

PRINCIPLE_BOUND = 500
DEFAULT_K       = 5
RECIPE          = "statement-and-rationale-v1"
DROPPED         = ( CONTESTED, RETRACTED )


class PrincipleBoundExceeded( RuntimeError ):
    """An owner holds more principles than the bound the plan set for fetching them all."""


def embedding_text( principle ):
    """
    Build the text a principle is embedded from.

    Requires:
        - principle has statement and rationale (a string or None)

    Ensures:
        - returns the statement, then the rationale on a new line when there is one
    """
    return principle.statement if not principle.rationale else f"{principle.statement}\n{principle.rationale}"


def encoder_version_of( model_name ):
    """
    Name an encoder as the table stores it: the embedding model and the text recipe.

    Requires:
        - model_name is a non-empty string

    Ensures:
        - returns "<model_name>|<RECIPE>", so a change of either re-embeds
    """
    return f"{model_name}|{RECIPE}"


def reembed_principles( session, owner_id, provider, encoder_version ):
    """
    Re-embed every principle of one owner that was not embedded by the given encoder.

    Requires:
        - session is an active SQLAlchemy session
        - provider has generate_embeddings_batch( texts ) returning one vector per text, in order
        - encoder_version is the name of the encoder the provider now is

    Ensures:
        - each principle with another encoder_version, or no embedding, gets a new embedding and this encoder_version
        - a principle already at this encoder_version is left alone, and the provider is not called when none needs it
        - the session is flushed, not committed
        - returns the number of principles re-embedded

    Raises:
        - ValueError when the provider returns a different number of vectors than texts; nothing is changed
    """
    stale = session.query( PreferencePrinciple ).filter( PreferencePrinciple.owner_id == owner_id ).all()
    stale = [ p for p in stale if p.encoder_version != encoder_version or p.embedding is None ]
    if not stale: return 0
    vectors = provider.generate_embeddings_batch( [ embedding_text( p ) for p in stale ] )
    if len( vectors ) != len( stale ): raise ValueError( f"the provider returned {len( vectors )} vectors for {len( stale )} principles" )
    for principle, vector in zip( stale, vectors ):
        principle.embedding       = vector
        principle.encoder_version = encoder_version
    session.flush()
    return len( stale )


def load_owner_ledger( session, owner_id ):
    """
    Read one owner's principles and their evidence rows, of every extractor version.

    Requires:
        - session is an active SQLAlchemy session

    Ensures:
        - returns ( principles, evidence ); a ruling may name a principle of an older version, so none is left out
        - reads only
    """
    principles = session.query( PreferencePrinciple ).filter( PreferencePrinciple.owner_id == owner_id ).all()
    ids        = [ p.id for p in principles ]
    evidence   = session.query( PreferenceEvidence ).filter( PreferenceEvidence.principle_id.in_( ids ) ).all() if ids else []
    return principles, evidence


def session_lookup( session, notification_ids ):
    """
    Build the function that names the session of an evidence row's notification.

    Requires:
        - session is an active SQLAlchemy session; notification_ids are notification ids

    Ensures:
        - returns session_of( notification_id ): the session part of the notification's sender, or None
          when the notification is not found or its sender carries no session
        - one query for all ids; reads only
    """
    ids = list( set( notification_ids ) )
    sessions = { row.id: sender_session_suffix( row.sender_id ) for row in session.query( Notification.id, Notification.sender_id ).filter( Notification.id.in_( ids ) ).all() } if ids else {}
    return lambda notification_id: sessions.get( notification_id )


def select_principles( scored, statuses, k=DEFAULT_K ):
    """
    Keep the first k scored principles whose status lets them be used.

    Requires:
        - scored is [ ( similarity_pct, principle ) ] best first
        - statuses is derive_statuses' result
        - k is a positive int

    Ensures:
        - drops a principle with no usable evidence at the ask, a contested one and a retracted one
        - returns at most k entries { principle, similarity_pct, status, conditions }, in the order given
        - because the drop comes before the cut, dropped principles never take a slot
    """
    kept = []
    for similarity, principle in scored:
        state = statuses.get( principle.id )
        if state is None or state[ "status" ] in DROPPED: continue
        kept.append( { "principle": principle, "similarity_pct": similarity, "status": state[ "status" ], "conditions": state[ "conditions" ] } )
        if len( kept ) == k: break
    return kept


def retrieve_principles( session, owner_id, project, query_embedding, asked_at, encoder_version, extractor_version, k=DEFAULT_K, bound=PRINCIPLE_BOUND ):
    """
    Retrieve the principles that apply to one ask, as of the ask.

    Requires:
        - session is an active SQLAlchemy session
        - project is the ask's project name, or None for global principles only
        - query_embedding came from the encoder named encoder_version
        - asked_at is an aware datetime; extractor_version is the version the config names

    Ensures:
        - the SQL filter holds owner, an embedding, the same encoder_version and scope global or project:<project>;
          no vector of another encoder is compared
        - every principle passing it is fetched, cosine order, none cut by SQL
        - returns { principles, available, short }: principles from select_principles, available the count that
          passed the SQL filter, short True when fewer than k were kept (the count is the caller's to record)
        - nothing is written

    Raises:
        - PrincipleBoundExceeded when more than `bound` principles pass the filter
    """
    scopes  = [ "global" ] + ( [ f"project:{project}" ] if project else [] )
    allowed = and_( PreferencePrinciple.owner_id == owner_id, PreferencePrinciple.embedding.isnot( None ),
                    PreferencePrinciple.encoder_version == encoder_version, PreferencePrinciple.scope.in_( scopes ) )
    count   = session.query( PreferencePrinciple ).filter( allowed ).count()
    if count > bound: raise PrincipleBoundExceeded( f"owner {owner_id} holds {count} principles for this ask, above the bound {bound}" )
    if count == 0: return { "principles": [], "available": 0, "short": True }
    # despite its name, dot_topk's exclude_filter is a filter() that keeps the matching rows, before the limit
    scored = dot_topk( session, PreferencePrinciple, PreferencePrinciple.embedding, query_embedding, limit=count, exclude_filter=allowed, metric="cosine" )
    principles, evidence = load_owner_ledger( session, owner_id )
    statuses = derive_statuses( principles, evidence, asked_at, extractor_version, session_lookup( session, [ e.notification_id for e in evidence ] ) )
    kept     = select_principles( scored, statuses, k )
    return { "principles": kept, "available": count, "short": len( kept ) < k }


def principle_block( selected, suffix=None ):
    """
    Shape the selected principles as the block the forecast prompt carries.

    Requires:
        - selected is the principles list retrieve_principles returns
        - suffix is None, or a tag suffix that appears in no statement

    Ensures:
        - returns { text, principle_ids, suffix }; text is "" when nothing was selected
        - each line holds the principle's id, status, scope, dimension and statement, and its conditions when it has any
        - no rationale and no evidence is included, so no answer text from another conversation can enter
        - the lines sit between tags carrying a random suffix that no statement contains, so a statement cannot close the block
        - principle_ids are in line order, for the forecast to cite
    """
    if not selected: return { "text": "", "principle_ids": [], "suffix": None }
    texts  = [ s[ "principle" ].statement for s in selected ]
    if suffix is None:
        suffix = secrets.token_hex( 4 )
        while any( suffix in t for t in texts ): suffix = secrets.token_hex( 4 )
    lines = []
    for entry in selected:
        p     = entry[ "principle" ]
        when  = f" | applies when: {'; '.join( entry[ 'conditions' ] )}" if entry[ "conditions" ] else ""
        lines.append( f"- id={p.id} [{entry[ 'status' ]}; {p.scope}; {p.dimension}] {p.statement}{when}" )
    return { "text": f"<principles_{suffix}>\n" + "\n".join( lines ) + f"\n</principles_{suffix}>", "principle_ids": [ s[ "principle" ].id for s in selected ], "suffix": suffix }
