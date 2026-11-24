"""
Fetch the principles that apply to one ask, and shape them as a prompt block.

Retrieval is cosine over each principle's statement and rationale.
Owner, scope and ``encoder_version`` are columns, so they go in the SQL filter.
Status depends on the ask's moment, so it cannot be a SQL filter and is applied after the search.
Every principle that passes the SQL filter is fetched, and its status is derived as of the ask
(``principle_status.derive_statuses``). Contested, retracted and evidence-less ones are dropped, and the first ``k`` are kept.
Contested principles therefore never use up a slot.

The limit and the fetch multiplier are read from the INI file (``retrieval_limits``), shipped at 5,000 and 0 by Rick's ruling of 20 Nov 2026.
At or below the limit every principle is fetched and no multiplier is used.
Above it, a multiplier of 0 refuses, and a positive multiplier M fetches only the ``k x M`` nearest.

A change of encoder re-embeds the table (``reembed_principles``) and never mixes two encoders' vectors.
"""

import secrets

from sqlalchemy import and_

from cosa.agents.prediction_engine.principle_features import feature_lookup, notification_lookup
from cosa.agents.prediction_engine.principle_status import CONTESTED, RETRACTED, SOURCE_EXTRACT, SUPPORTING, derive_statuses, usable_at
from cosa.config.configuration_manager import ConfigurationManager
from cosa.rest.db.repositories.vector_search import dot_topk
from cosa.utils.iso_timestamp import aware_moment
from cosa.rest.postgres_models import Notification, PreferenceEvidence, PreferencePrinciple
from cosa.utils.notification_utils import sender_session_suffix

PRINCIPLE_BOUND  = 5000
FETCH_MULTIPLIER = 0
DEFAULT_K        = 5
RECIPE           = "statement-rationale-v1"
DROPPED          = ( CONTESTED, RETRACTED )
BOUND_KEY        = "prediction learner principle limit"
CAVEAT_MAX       = 200
APPLICABILITY_KEY = "principle learner applicability checks enabled"
RULE_ANTECEDENT  = "antecedent"
RULE_STAGE       = "stage"
CAVEATS_KEY      = "principle learner caveats enabled"
MULTIPLIER_KEY   = "prediction learner principle fetch multiplier"


class PrincipleBoundExceeded( RuntimeError ):
    """
    An owner holds more principles than the limit for fetching them all.

    Raised only when no fetch multiplier is set.
    """


def retrieval_limits():
    """
    Read the principle limit and the fetch multiplier from the INI file.

    Ensures:
        - returns { bound, multiplier } as ints, read from BOUND_KEY and MULTIPLIER_KEY
        - PRINCIPLE_BOUND and FETCH_MULTIPLIER are the shipped INI values and the parameter defaults; they are never a fallback here

    Raises:
        - MissingConfigKeyError if either key is absent
        - ValueError if the limit is not positive or the multiplier is negative
    """
    config     = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
    bound      = config.get_required( BOUND_KEY, return_type="int" )
    multiplier = config.get_required( MULTIPLIER_KEY, return_type="int" )
    if bound < 1: raise ValueError( f"{BOUND_KEY} must be a positive integer, got {bound}" )
    if multiplier < 0: raise ValueError( f"{MULTIPLIER_KEY} must be 0 or a positive integer, got {multiplier}" )
    return { "bound": bound, "multiplier": multiplier }


def embedding_text( statement, rationale ):
    """
    Build the text a principle is embedded from.

    Requires:
        - statement is a string; rationale is a string or None

    Ensures:
        - returns the statement, then the rationale on a new line when there is one
    """
    return statement if not rationale else f"{statement}\n{rationale}"


def encoder_version_of( model_name ):
    """
    Name an encoder as the table stores it: the embedding model and the text recipe.

    The extractor job stores its rows through this function, and retrieval filters on it, so the two cannot disagree.

    Requires:
        - model_name is a non-empty string

    Ensures:
        - returns "<model_name>:<RECIPE>", so a change of either re-embeds
    """
    return f"{model_name}:{RECIPE}"


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
    vectors = provider.generate_embeddings_batch( [ embedding_text( p.statement, p.rationale ) for p in stale ] )
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
    return notification_lookup( session, notification_ids, ( Notification.sender_id, ), lambda row: sender_session_suffix( row.sender_id ) )


def supporting_rows( principle_id, evidence, asked_at, extractor_version, relations=SUPPORTING ):
    """
    List one principle's evidence rows that count at the ask, support by default.

    Requires:
        - evidence comes from load_owner_ledger; asked_at is an aware datetime
        - relations is a tuple of relation words, or None for every relation

    Ensures:
        - returns the rows of this principle that are from the extractor, of the current extractor version, of one of the relations, and usable at the ask
        - by default the relations are the ones derive_statuses counts as support; nothing is written
    """
    return [ e for e in evidence if e.principle_id == principle_id and e.source == SOURCE_EXTRACT and e.extractor_version == extractor_version
             and ( relations is None or e.relation in relations ) and usable_at( e, asked_at ) ]


def applicability_rules( principles, evidence, asked_at, extractor_version, card, card_stage ):
    """
    Name the rule each principle fails for one card, from fields the extractor stored.

    Requires:
        - principles and evidence come from load_owner_ledger; asked_at is an aware datetime
        - card is the card's text; card_stage is the card's decision stage, or None when it is not known
        - an evidence row has antecedent and decision_stage, each a string or None

    Ensures:
        - returns { principle id: rule } for the failing principles only; no model is called and nothing is written
        - the antecedent belongs to the principle, so it is read from any usable extractor row of the current version that carries one, whatever its relation
        - RULE_ANTECEDENT: some such row quotes an antecedent and none of the quotes appears in the card, compared case-folded
        - RULE_STAGE: card_stage is given, some supporting row names a stage and none names the card's
        - a principle whose rows quote no antecedent, or name no stage, passes that rule; the antecedent rule is tried first
    """
    rules = {}
    for principle in principles:
        rows   = supporting_rows( principle.id, evidence, asked_at, extractor_version )
        quotes = [ e.antecedent for e in supporting_rows( principle.id, evidence, asked_at, extractor_version, relations=None ) if e.antecedent ]
        stages = { e.decision_stage for e in rows if e.decision_stage }
        if quotes and not any( q.casefold() in card.casefold() for q in quotes ): rules[ principle.id ] = RULE_ANTECEDENT
        elif card_stage is not None and stages and card_stage not in stages: rules[ principle.id ] = RULE_STAGE
    return rules


def latest_caveat( principle_id, evidence, asked_at, extractor_version ):
    """
    Pick the caveat a principle carries into the prompt.

    Requires:
        - evidence comes from load_owner_ledger; asked_at is an aware datetime; an evidence row has caveat, a string or None

    Ensures:
        - returns the caveat of the most recently answered row among supporting_rows that has a non-blank one, or None when none has
        - ties on the answer time go to the row met first; nothing is written
    """
    rows = [ e for e in supporting_rows( principle_id, evidence, asked_at, extractor_version ) if e.caveat and e.caveat.strip() ]
    return max( rows, key=lambda e: aware_moment( e.answered_at ) ).caveat if rows else None


def select_principles( scored, statuses, k=DEFAULT_K, rules=None, dropped=None ):
    """
    Keep the first k scored principles whose status lets them be used.

    Requires:
        - scored is [ ( similarity_pct, principle ) ] best first
        - statuses is derive_statuses' result
        - k is a positive int
        - rules is None or applicability_rules' result; dropped is None or a list to append to

    Ensures:
        - drops a principle with no usable evidence at the ask, a contested one and a retracted one
        - with rules, also drops a principle named in it, and appends { principle_id, rule } to dropped, in order
        - returns at most k entries { principle, similarity_pct, status, conditions }, in the order given
        - because the drop comes before the cut, dropped principles never take a slot
    """
    kept = []
    for similarity, principle in scored:
        state = statuses.get( principle.id )
        if state is None or state[ "status" ] in DROPPED: continue
        if rules is not None and principle.id in rules:
            if dropped is not None: dropped.append( { "principle_id": principle.id, "rule": rules[ principle.id ] } )
            continue
        kept.append( { "principle": principle, "similarity_pct": similarity, "status": state[ "status" ], "conditions": state[ "conditions" ] } )
        if len( kept ) == k: break
    return kept


def retrieve_principles( session, owner_id, project, query_embedding, asked_at, encoder_version, extractor_version, k=DEFAULT_K, bound=PRINCIPLE_BOUND,
                         multiplier=FETCH_MULTIPLIER, applicability=None, caveats=False ):
    """
    Retrieve the principles that apply to one ask, as of the ask.

    Requires:
        - session is an active SQLAlchemy session
        - project is the ask's project name, or None for global principles only
        - query_embedding came from the encoder named encoder_version
        - asked_at is an aware datetime; extractor_version is the version the config names
        - bound is a positive int; multiplier is 0 or a positive int (retrieval_limits reads both from the INI file)
        - applicability is None (no check) or { card, card_stage } when the applicability switch (APPLICABILITY_KEY) is on
        - caveats is True when the caveats switch (CAVEATS_KEY) is on

    Ensures:
        - the SQL filter holds owner, an embedding, the same encoder_version and scope global or project:<project>;
          no vector of another encoder is compared
        - at or below `bound`, every principle passing it is fetched, cosine order, none cut by SQL
        - above `bound` with a positive multiplier, only the k x multiplier nearest are fetched
        - returns { principles, available, short }: principles from select_principles, available the count that
          passed the SQL filter, short True when fewer than k were kept (the count is the caller's to record)
        - with a check, the result also has applicability, { principle_id, rule } for each principle applicability_rules dropped, in cosine order; with no check the result has no such key, so it is what it was before the switch
        - with caveats, each returned entry also has caveat, latest_caveat's pick for its principle; without, entries are what they were
        - nothing is written

    Raises:
        - PrincipleBoundExceeded when more than `bound` principles pass the filter and multiplier is 0
    """
    scopes  = [ "global" ] + ( [ f"project:{project}" ] if project else [] )
    allowed = and_( PreferencePrinciple.owner_id == owner_id, PreferencePrinciple.embedding.isnot( None ),
                    PreferencePrinciple.encoder_version == encoder_version, PreferencePrinciple.scope.in_( scopes ) )
    count   = session.query( PreferencePrinciple ).filter( allowed ).count()
    if count > bound and multiplier == 0: raise PrincipleBoundExceeded( f"owner {owner_id} holds {count} principles for this ask, above the limit {bound}" )
    if count == 0:
        empty = { "principles": [], "available": 0, "short": True }
        return empty if applicability is None else { **empty, "applicability": [] }
    limit   = count if count <= bound else k * multiplier
    # despite its name, dot_topk's exclude_filter is a filter() that keeps the matching rows, before the limit
    scored = dot_topk( session, PreferencePrinciple, PreferencePrinciple.embedding, query_embedding, limit=limit, exclude_filter=allowed, metric="cosine" )
    principles, evidence = load_owner_ledger( session, owner_id )
    statuses = derive_statuses( principles, evidence, asked_at, extractor_version, session_lookup( session, [ e.notification_id for e in evidence if e.session_key is None ] ),
                               feature_lookup( session, [ e.notification_id for e in evidence ] ) )
    rules    = None if applicability is None else applicability_rules( principles, evidence, asked_at, extractor_version, applicability[ "card" ], applicability[ "card_stage" ] )
    dropped  = []
    kept     = select_principles( scored, statuses, k, rules, dropped )
    if caveats:
        for entry in kept: entry[ "caveat" ] = latest_caveat( entry[ "principle" ].id, evidence, asked_at, extractor_version )
    result   = { "principles": kept, "available": count, "short": len( kept ) < k }
    return result if applicability is None else { **result, "applicability": dropped }


def clean_caveat( caveat ):
    """
    Shape one stored caveat as text that can sit on a principle's line.

    Requires:
        - caveat is a string or None

    Ensures:
        - returns the caveat with every run of whitespace, newlines included, as one space, cut to CAVEAT_MAX characters
          and trimmed; so a caveat can never start a new line of its own
        - returns "" for None or a caveat with no text
    """
    return "" if not caveat else " ".join( caveat.split() )[ :CAVEAT_MAX ].strip()


def principle_block( selected, suffix=None, caveats=False ):
    """
    Shape the selected principles as the block the forecast prompt carries.

    Requires:
        - selected is the principles list retrieve_principles returns
        - suffix is None, or a tag suffix that appears in no statement and, with caveats on, in no caveat
        - caveats is True only when the caveats switch (CAVEATS_KEY) is on; each entry then has caveat, a string or None, as retrieve_principles adds it

    Ensures:
        - returns { text, principle_ids, suffix }; text is "" when nothing was selected
        - each line holds the principle's id, status, scope, dimension and statement, and its conditions when it has any
        - no raw answer, rationale or evidence row is included; a statement is distilled from answers
        - with caveats off, the text is the same as before the switch existed, and an entry's caveat is not read
        - with caveats on, a principle whose entry has a caveat gets " | caveat: <clean_caveat>" at the end of its line; that is the only added text
        - the lines sit between tags carrying a random suffix that no statement or caveat contains, so neither can close the block
        - a caveat holds no newline and is at most CAVEAT_MAX characters, so a closing tag plus an instruction inside it stays one line inside the tags
        - principle_ids are in line order, for the forecast to cite
    """
    if not selected: return { "text": "", "principle_ids": [], "suffix": None }
    notes  = [ clean_caveat( s[ "caveat" ] ) if caveats else "" for s in selected ]
    texts  = [ s[ "principle" ].statement for s in selected ] + notes
    if suffix is None:
        suffix = secrets.token_hex( 4 )
        while any( suffix in t for t in texts ): suffix = secrets.token_hex( 4 )
    lines = []
    for entry, note in zip( selected, notes ):
        p     = entry[ "principle" ]
        when  = f" | applies when: {'; '.join( entry[ 'conditions' ] )}" if entry[ "conditions" ] else ""
        extra = f" | caveat: {note}" if note else ""
        lines.append( f"- id={p.id} [{entry[ 'status' ]}; {p.scope}; {p.dimension}] {p.statement}{when}{extra}" )
    return { "text": f"<principles_{suffix}>\n" + "\n".join( lines ) + f"\n</principles_{suffix}>", "principle_ids": [ s[ "principle" ].id for s in selected ], "suffix": suffix }
