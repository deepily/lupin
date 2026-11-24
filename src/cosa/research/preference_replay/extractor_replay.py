"""
Replay a context export through the principle extractor, in the order the asks were made.

The run uses replay_loop.replay as its one harness.
A recording arm stands in for the learner's forecasters, which do not exist yet.
It keeps what the harness handed it, so a test can check that nothing from the future arrived.
Before each ask the replay runs the extractor over every answer given and extracted by then.
So the principle tables fill in time order.

The output is plumbing and a list of principles for the owner to read. It makes no accuracy claim.
"""

import argparse
import asyncio
import copy
import json
import sys
from datetime import timedelta

from cosa.agents.prediction_engine.episode_view import episode_view
from cosa.agents.prediction_engine.history_derive import attribution_tier
from cosa.agents.prediction_engine.principle_features import feature_lookup
from cosa.agents.prediction_engine.principle_retrieval import load_owner_ledger, session_lookup
from cosa.agents.prediction_engine.principle_status import SOURCE_EXTRACT, derive_statuses, usable_at
from cosa.agents.prediction_engine.prediction_engine import PredictionEngine
from cosa.agents.principle_learner.extractor_job import PrincipleExtractorJob
from cosa.agents.principle_learner.extractor_prompt import current_extractor_version
from cosa.agents.principle_learner.vocabulary import heading_for
from cosa.repo.doc_lint import model_transport
from cosa.research.preference_replay.replay_loop import always_yes_arm, replay
from cosa.research.preference_replay.scratch_db import load_export, scratch_session, session_scope
from cosa.research.preference_replay.service_embeddings import CachedServiceEmbedder, record_neighbour_cosines
from cosa.rest.db.vector_store_models import EMBEDDING_DIM
from cosa.rest.postgres_models import Notification, PreferenceEvidence, PreferencePrinciple
from cosa.utils.iso_timestamp import aware_moment

RECORDER_ARM    = "recorder"
REPLAYED_TYPES  = ( "yes_no", "multiple_choice" )
SNAPSHOT_SHA    = "0" * 64
VECTOR_SCALE    = 20.0


class LeakageError( AssertionError ):
    """Raised when a provider handed an arm something that was not yet known at the ask."""


def stand_in_vector( text ):
    """
    Give a text a stable stand-in vector, so the replay never calls the embedding service.

    Requires:
        - text is a string

    Ensures:
        - returns a vector of the stored width with one non-zero entry, chosen by the text's bytes
        - the same text always gives the same vector
        - the vector's length is the 20 the engine's stored-vector band expects
    """
    axis   = sum( text.encode( "utf-8" ) ) % EMBEDDING_DIM
    vector = [ 0.0 ] * EMBEDDING_DIM
    vector[ axis ] = VECTOR_SCALE
    return vector


def canned_model( prompt, options ):
    """
    Stand in for the model: one grounded hypothesis per field, none for a bare yes.

    Requires:
        - prompt is the extractor's user prompt, with its answers block of JSON

    Ensures:
        - yields one assistant message and one result message holding JSON in the extractor's reply shape
        - each non-bare-yes answer gets one global hypothesis, with the field key in its statement and the answer as its condition
        - a bare yes gets none, and the same prompt always gets the same reply
    """
    from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock
    block   = prompt.split( "ANSWERS\n", 1 )[ 1 ].split( "\n\nEXISTING PRINCIPLES", 1 )[ 0 ]
    fields  = []
    for answer in json.loads( block ):
        hypotheses = [] if answer[ "bare_yes" ] else [ { "statement": f"The owner answers {answer[ 'field_key' ]} questions in this way.",
                                                         "rationale": "from the recorded answer", "scope": "global", "condition": answer[ "answer" ], "grounded_in": "answer" } ]
        fields.append( { "field_key": answer[ "field_key" ], "kind": "decision", "dimension": f"decision.{answer[ 'field_key' ]}", "hypotheses": hypotheses, "relations": {} } )
    text = json.dumps( { "fields": fields } )
    async def stream():
        yield AssistantMessage( content=[ TextBlock( text=text ) ], model="canned" )
        yield ResultMessage( subtype="success", duration_ms=1, duration_api_ms=1, is_error=False, num_turns=1, session_id="replay", result=text )
    return stream()


def asks_from_session( session, engine, embed_fn=stand_in_vector ):
    """
    Build the replay's ask dicts from every answered notification in the scratch copy.

    Requires:
        - session is an active session over loaded notifications
        - engine is a PredictionEngine, whose classifier names each ask's category
        - embed_fn maps a text to a vector of the stored width

    Ensures:
        - returns one dict per notification with a stored answer, in creation order, shaped as replay_loop.replay reads them
        - the case value and the actual value are the stored answer text; the answer source is human only for an answer
          attributed to its recipient, and unknown otherwise
        - the vector comes from embed_fn over the message, never from a service
    """
    asks = []
    for row in session.query( Notification ).filter( Notification.responded_at.isnot( None ) ).order_by( Notification.created_at, Notification.id ):
        value = row.response_value
        if not isinstance( value, dict ): continue
        raw   = { "recipient_id": str( row.recipient_id ), "response_type": row.response_type, "response_value": value }
        asks.append( { "id": str( row.id ), "question": row.message, "category": engine.classifier.classify( row.message, sender_id=row.sender_id )[ 0 ],
                       "decision_value": value.get( "value" ), "ratification_state": "not_required", "data_origin": "organic", "response_type": row.response_type,
                       "question_embedding": embed_fn( row.message ), "created_at": aware_moment( row.created_at ).isoformat(), "owner_user_id": str( row.recipient_id ),
                       "answer_source": "human" if attribution_tier( raw ) == "recipient" else "unknown", "responded_at": aware_moment( row.responded_at ),
                       "title": row.title, "message": row.message, "sender_id": row.sender_id, "asked_at": aware_moment( row.created_at ),
                       "recipient_id": str( row.recipient_id ), "response_options": row.response_options, "actual_value": value.get( "value" ) } )
    return asks


def principles_as_of( session, owner_id, asked_at, extractor_version ):
    """
    List the owner's principles at a moment, each with its derived status and evidence.

    Requires:
        - session is an active session; asked_at is an aware datetime
        - extractor_version is the version the run's extractor writes

    Ensures:
        - returns [ { id, kind, dimension, statement, scope, status, evidence } ] sorted by id
        - status is the one principle_status.derive_statuses gives as of asked_at, so a ruling and a contradiction
          count by the same one as-of rule; contested and retracted principles are listed with that status, not removed
        - evidence holds only this version's extractor rows usable at the ask: answered, extracted and not retracted by then
        - a principle with no usable evidence is absent
    """
    principles, ledger = load_owner_ledger( session, owner_id )
    statuses = derive_statuses( principles, ledger, asked_at, extractor_version, session_lookup( session, [ e.notification_id for e in ledger if e.session_key is None ] ),
                               feature_lookup( session, [ e.notification_id for e in ledger ] ) )
    found    = []
    for principle in sorted( principles, key=lambda p: str( p.id ) ):
        if statuses[ principle.id ] is None: continue
        rows = sorted( ( e for e in ledger if e.principle_id == principle.id and e.source == SOURCE_EXTRACT and e.extractor_version == extractor_version
                         and usable_at( e, asked_at ) ), key=lambda e: str( e.id ) )
        found.append( { "id": str( principle.id ), "kind": principle.kind, "dimension": principle.dimension, "statement": principle.statement, "scope": principle.scope,
                        "status": statuses[ principle.id ][ "status" ],
                        "evidence": [ { "notification_id": str( e.notification_id ), "field_key": e.field_key, "relation": e.relation, "condition": e.condition,
                                        "answered_at": aware_moment( e.answered_at ), "extracted_at": aware_moment( e.extracted_at ) } for e in rows ] } )
    return found


class ExtractorReplay:
    """
    Runs the extractor over answers in time order, from inside the replay's providers.

    Requires:
        - session is an active session over loaded notifications and empty principle tables
        - asks are the replay's ask dicts, each with an id and responded_at
        - lag is the time between an answer and its evidence being usable
        - timeout_seconds is the limit the extractor job gives one model call
        - query_fn is the model double or None, as the extractor job takes it; embed_fn maps a text to a vector

    Ensures:
        - each answered ask is extracted at most once
        - an answer is extracted only once responded_at + lag is at or before the moment the replay has reached
        - the evidence's extracted_at is exactly responded_at + lag
    """

    def __init__( self, session, asks, lag, query_fn=None, embed_fn=stand_in_vector, model="replay-model", encoder="replay-encoder:v1", timeout_seconds=30 ):
        self.session   = session
        self.pending   = sorted( asks, key=lambda ask: ( aware_moment( ask[ "responded_at" ] ), ask[ "id" ] ) )
        self.lag       = lag
        self.query_fn  = query_fn
        self.embed_fn  = embed_fn
        self.model     = model
        self.timeout   = timeout_seconds
        self.version   = current_extractor_version( model )
        self.encoder   = encoder
        self.summaries = []

    def catch_up( self, until ):
        """
        Extract every pending answer whose evidence is usable by a moment.

        Requires:
            - until is an aware datetime

        Ensures:
            - runs the extractor for each pending ask with responded_at + lag at or before until, in answer order
            - appends one { notification_id, summary } to summaries per run and removes the ask from pending
        """
        while self.pending and aware_moment( self.pending[ 0 ][ "responded_at" ] ) + self.lag <= until:
            ask   = self.pending.pop( 0 )
            ready = aware_moment( ask[ "responded_at" ] ) + self.lag
            job   = PrincipleExtractorJob( ask[ "id" ], ask[ "owner_user_id" ], "replay@example.com", query_fn=self.query_fn, embed_fn=self.embed_fn,
                                           session_factory=lambda: session_scope( self.session ), model=self.model, timeout_seconds=self.timeout,
                                           encoder=self.encoder, clock=lambda ready=ready: ready )
            self.summaries.append( { "notification_id": ask[ "id" ], "summary": json.loads( asyncio.run( job._execute() ) ) } )

    def episode_provider( self, ask_at_ask, visible_rows ):
        """
        Give an arm the ask's episode view.

        Requires:
            - ask_at_ask is the ask cut to the fields known at the ask; visible_rows are the cases answered by then

        Ensures:
            - returns episode_view for the ask, as of the ask's own time
        """
        return episode_view( self.session, ask_at_ask[ "id" ] )

    def principles_provider( self, ask_at_ask, asked_at ):
        """
        Extract what is usable by the ask, then give an arm the principles as of it.

        Requires:
            - asked_at is the ask's aware time

        Ensures:
            - runs catch_up to asked_at first, so every answer usable by then is in the tables
            - returns principles_as_of for the ask's owner and this run's extractor version, with only evidence usable at the ask
        """
        self.catch_up( asked_at )
        return principles_as_of( self.session, ask_at_ask[ "recipient_id" ], asked_at, self.version )


def make_recorder( seen ):
    """
    Build the recording arm.

    Requires:
        - seen is a list the arm appends to

    Ensures:
        - returns arm( ask_at_ask, visible_rows, episode_view=None, principles=None ) that forecasts like always_yes
          and appends one { ask_id, asked_at, episode, principles } per call, as deep copies
    """
    def recorder( ask_at_ask, visible_rows, episode_view=None, principles=None ):
        seen.append( { "ask_id": ask_at_ask[ "id" ], "asked_at": aware_moment( ask_at_ask[ "asked_at" ] ), "episode": copy.deepcopy( episode_view ),
                       "principles": copy.deepcopy( principles ) } )
        return always_yes_arm( ask_at_ask, visible_rows )
    return recorder


def check_no_leakage( seen ):
    """
    Check that no arm was handed evidence from after its ask.

    Requires:
        - seen is the list make_recorder filled

    Ensures:
        - returns the number of evidence rows checked
        - raises LeakageError naming the ask and the row for any evidence whose answered_at or extracted_at is after the ask
        - a time exactly at the ask is allowed
    """
    checked = 0
    for record in seen:
        for principle in record[ "principles" ]:
            for evidence in principle[ "evidence" ]:
                checked += 1
                if evidence[ "answered_at" ] > record[ "asked_at" ] or evidence[ "extracted_at" ] > record[ "asked_at" ]:
                    raise LeakageError( f"ask {record[ 'ask_id' ]} was handed evidence for {evidence[ 'notification_id' ]} answered "
                                        f"{evidence[ 'answered_at' ].isoformat()} and extracted {evidence[ 'extracted_at' ].isoformat()}" )
    return checked


def principle_list( session ):
    """
    List every principle with its status and evidence count, for the owner to read.

    Requires:
        - session is an active session over the principle tables

    Ensures:
        - returns [ { owner_id, scope, dimension, heading, statement, status, supports, contradicts, refines, answers } ] sorted by dimension, statement, id
        - heading is vocabulary.heading_for( dimension ): the approved heading, the heading an old name maps to, or None for an unknown name
        - each relation count is the number of evidence rows with that relation; answers is the number of distinct notifications behind them
        - status is the one principle_status.derive_statuses gives one second after the last extraction, owner by owner and
          extractor version by extractor version; it is None for a principle with no usable evidence then
    """
    moments  = [ aware_moment( row.extracted_at ) for row in session.query( PreferenceEvidence ) ]
    end      = max( moments ) + timedelta( seconds=1 ) if moments else None
    statuses = {}
    if end is not None:
        for owner_id, version in sorted( set( session.query( PreferencePrinciple.owner_id, PreferencePrinciple.extractor_version ) ) ):
            for found in principles_as_of( session, owner_id, end, version ): statuses[ found[ "id" ] ] = found[ "status" ]
    rows = []
    for principle in session.query( PreferencePrinciple ).order_by( PreferencePrinciple.dimension, PreferencePrinciple.statement, PreferencePrinciple.id ):
        evidence = session.query( PreferenceEvidence ).filter_by( principle_id=principle.id ).all()
        counts   = { relation: sum( 1 for row in evidence if row.relation == relation ) for relation in ( "supports", "contradicts", "refines" ) }
        rows.append( { "owner_id": principle.owner_id, "scope": principle.scope, "dimension": principle.dimension, "heading": heading_for( principle.dimension ),
                       "statement": principle.statement,
                       "status": statuses.get( str( principle.id ) ), **counts, "answers": len( { row.notification_id for row in evidence } ) } )
    return rows


def run_replay( session, engine, lag, query_fn=None, embed_fn=stand_in_vector, target_types=REPLAYED_TYPES, model="replay-model", timeout_seconds=30, encoder="replay-encoder:v1" ):
    """
    Replay the loaded asks in time order through the harness and the extractor.

    Requires:
        - session holds the loaded notifications and empty principle tables
        - engine is a PredictionEngine; lag is a timedelta; target_types names the response types the harness predicts
        - model is the id the extractor writes under and, with no query_fn, the model it calls; timeout_seconds limits each call
        - encoder is the encoder version the principles are stored and searched under

    Ensures:
        - returns { run, seen, extractions, counts, leakage_checked }
        - run is replay_loop.replay's result with the recording arm beside the engine
        - extraction continues past the last ask until every answer is extracted, so the tables hold every readable answer
        - counts is { principles, evidence } read from the tables after the run
        - leakage_checked is the number of evidence rows check_no_leakage verified; a leak raises LeakageError
    """
    asks   = asks_from_session( session, engine, embed_fn )
    runner = ExtractorReplay( session, asks, lag, query_fn=query_fn, embed_fn=embed_fn, model=model, timeout_seconds=timeout_seconds, encoder=encoder )
    seen   = []
    run    = replay( asks, engine, SNAPSHOT_SHA, baselines={ RECORDER_ARM: make_recorder( seen ) }, target_types=target_types, context_arms=( RECORDER_ARM, ),
                     episode_view_provider=runner.episode_provider, principles_provider=runner.principles_provider )
    if runner.pending: runner.catch_up( max( aware_moment( ask[ "responded_at" ] ) for ask in asks ) + lag )
    return { "run": run, "seen": seen, "extractions": runner.summaries,
             "counts": { "principles": session.query( PreferencePrinciple ).count(), "evidence": session.query( PreferenceEvidence ).count() },
             "leakage_checked": check_no_leakage( seen ) }


def main( argv=None, query_fn=None ):
    """
    Replay an export from the command line and write the principle list.

    Requires:
        - argv is a list of arguments or None for sys.argv; query_fn is None for the live model, or a double
        - a live run, with no --dry-run and no double, names its model with --model

    Ensures:
        - reads --export, loads it into a scratch copy, and runs one replay per --lag-seconds value (default 0 and 300)
        - with --dry-run the model is canned_model and no model is called; otherwise --model, with each call limited to --timeout-seconds,
          is called through model_transport.complete unless a query_fn double was given
        - without --dry-run, a double or --model, it exits with a usage error before it reads the export or makes any call
        - each variant also prints the extractor's totals: principles created, reused, off-vocabulary and rejected
        - each variant prints a line ending with the model id and the number of finished model calls, then a line with the token
          counts the transport reported for it; a call that failed or timed out is not counted in the first, so the second is the spend
          figure; its cost is the SDK's notional figure, not a charge, and a canned model reports none
        - with --embeddings service, vectors come from the embedding service through a side cache keyed by text and encoder version;
          an unreachable service stops the run with EmbeddingServiceUnavailable; the default stand-in never calls a service
        - with --neighbour-cosines-out, writes the cosine of every neighbour shown to the model, over all variants, as a JSON list
        - writes the last variant's principle list to --out as JSON, and prints one line of counts per variant
        - returns 0
    """
    parser = argparse.ArgumentParser( description="Replay a context export through the principle extractor" )
    parser.add_argument( "--export", required=True )
    parser.add_argument( "--out", required=True )
    parser.add_argument( "--lag-seconds", type=int, action="append", dest="lags" )
    parser.add_argument( "--dry-run", action="store_true" )
    parser.add_argument( "--model", default=None, help="model id for a live run; required unless --dry-run is given" )
    parser.add_argument( "--timeout-seconds", type=int, default=30 )
    parser.add_argument( "--embeddings", choices=( "stand-in", "service" ), default="stand-in", help="stand-in (default) calls no service; service uses the live extractor's embedding path" )
    parser.add_argument( "--embedding-cache", default=None, help="side file for service vectors; defaults to <out>.embeddings.json" )
    parser.add_argument( "--neighbour-cosines-out", default=None, help="write the cosines of the neighbours shown to the model, as JSON" )
    args = parser.parse_args( argv )
    if args.model is None and not args.dry_run and query_fn is None: parser.error( "--model is required for a live run: give --model <id>, or --dry-run for the canned model" )
    if args.model is None: args.model = "replay-model"
    with open( args.export, encoding="utf-8" ) as handle: export = json.load( handle )
    chosen = canned_model if args.dry_run else query_fn
    listing = []
    cosines = []
    embed   = stand_in_vector
    encoder = "replay-encoder:v1"
    if args.embeddings == "service":
        embed   = CachedServiceEmbedder( args.embedding_cache or f"{args.out}.embeddings.json" )
        encoder = embed.encoder
    for lag in args.lags or [ 0, 300 ]:
        usage_before = model_transport.claude_usage_summary()
        with scratch_session() as session, model_transport.record_calls() as calls, record_neighbour_cosines( cosines ):
            load_export( session, export )
            PredictionEngine.reset()
            outcome = run_replay( session, PredictionEngine( debug=False ), timedelta( seconds=lag ), query_fn=chosen, embed_fn=embed, model=args.model, timeout_seconds=args.timeout_seconds, encoder=encoder )
            listing = principle_list( session )
        print( f"lag {lag}s: {outcome[ 'counts' ]}, leakage checked {outcome[ 'leakage_checked' ]}, model {args.model}, finished model calls {len( calls )}", file=sys.stdout )
        done = [ item[ "summary" ] for item in outcome[ "extractions" ] ]
        print( f"  extractor totals: {sum( d[ 'principles_created' ] for d in done )} principles created, {sum( d[ 'principles_reused' ] for d in done )} reused, "
               f"{sum( len( d[ 'off_vocabulary' ] ) for d in done )} off-vocabulary, {sum( len( d[ 'rejected' ] ) for d in done )} rejected", file=sys.stdout )
        usage_after = model_transport.claude_usage_summary()
        used        = { key: usage_after[ key ] - usage_before[ key ] for key in usage_after }
        print( f"  usage reported by the transport: {used[ 'calls' ]} calls, input {used[ 'input_tokens' ]}, output {used[ 'output_tokens' ]}, "
               f"cache read {used[ 'cache_read_input_tokens' ]}, cache write {used[ 'cache_creation_input_tokens' ]}, notional cost {used[ 'cost_usd' ]:.2f} USD", file=sys.stdout )
    if args.embeddings == "service":
        embed.flush()
        print( f"embeddings: {embed.calls} service calls, {embed.hits} cache hits, encoder {encoder}", file=sys.stdout )
    if args.neighbour_cosines_out is not None:
        with open( args.neighbour_cosines_out, "w", encoding="utf-8" ) as handle: json.dump( cosines, handle )
    with open( args.out, "w", encoding="utf-8" ) as handle: json.dump( listing, handle, indent=1, sort_keys=True )
    return 0


if __name__ == "__main__":
    sys.exit( main() )
