#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
Prove that a replay slice makes no model call.

Every model entry point is replaced by one that raises. The script reads the cohort in a read-only
transaction and replays a slice through the replay harness. It prints how many model calls were attempted.
A positive control at the end calls a patched entry point directly. A counter that reads 0 is thereby
shown able to read more.

Run from a seat tree, pinning all three:

    cd <tree> && LUPIN_ROOT="$PWD" PYTHONPATH="$PWD/src" .venv/bin/python src/scripts/zero_model_proof.py \\
        --vectors <side file of question vectors> --per-type 25
"""

import argparse
import collections
import socket
import sys


def install_guards( calls ):
    """
    Make every model, embedding and outside-network entry point count and raise.

    Requires:
        - calls is a collections.Counter

    Ensures:
        - LlmClientFactory.get_client, PredictionEngine._get_llm_client and _generate_embedding,
          CachedServiceEmbedder.__call__, get_embedding_provider, anthropic.Anthropic and AsyncAnthropic,
          openai.OpenAI, and every non-loopback socket connect raise AssertionError and add one to calls[ name ]
        - a client library that is not installed is reported on stdout and skipped
    """
    from cosa.agents.prediction_engine.prediction_engine import PredictionEngine
    import cosa.agents.llm_client_factory as factory
    import cosa.memory.embedding_provider as provider
    import cosa.research.preference_replay.service_embeddings as service
    from cosa.utils.unit_network_guard import is_loopback

    def boom( name ):
        def _raise( *args, **kwargs ):
            calls[ name ] += 1
            raise AssertionError( f"MODEL CALL ATTEMPTED: {name}" )
        return _raise

    factory.LlmClientFactory.get_client            = boom( "LlmClientFactory.get_client" )
    PredictionEngine._get_llm_client               = boom( "PredictionEngine._get_llm_client" )
    PredictionEngine._generate_embedding           = boom( "PredictionEngine._generate_embedding" )
    service.CachedServiceEmbedder.__call__         = boom( "CachedServiceEmbedder.__call__" )
    provider.get_embedding_provider                = boom( "get_embedding_provider" )
    for module_name, attribute in ( ( "anthropic", "Anthropic" ), ( "anthropic", "AsyncAnthropic" ), ( "openai", "OpenAI" ) ):
        try: setattr( __import__( module_name ), attribute, boom( f"{module_name}.{attribute}" ) )
        except ImportError: print( f"({module_name} not installed)" )
    real_connect = socket.socket.connect

    def no_outside_net( sock, address ):
        if not is_loopback( address ):
            calls[ "socket.connect_external" ] += 1
            raise AssertionError( f"EXTERNAL CONNECT {address}" )
        return real_connect( sock, address )

    socket.socket.connect = no_outside_net


def pick_slice( asks, per_type ):
    """
    Choose the first per_type yes/no and per_type multiple-choice asks that carry a vector.

    Requires:
        - asks are cohort_asks dicts in cohort order; per_type is a positive integer

    Ensures:
        - returns ( ids, counts ) with ids in cohort order and counts the number taken per response type
    """
    from cosa.research.preference_replay.retune import eligible_asks
    ids    = []
    counts = collections.Counter()
    for ask in eligible_asks( asks ):
        kind = ask[ "response_type" ]
        if counts[ kind ] >= per_type: continue
        ids.append( ask[ "id" ] )
        counts[ kind ] += 1
    return ids, counts


def main( argv=None ):
    """
    Replay a slice with every model entry point raising, then report.

    Requires:
        - argv holds --vectors, a question-vector side file, and optionally --per-type
        - the database named by the configuration is reachable; it is read in a read-only transaction

    Ensures:
        - prints the cohort size, the slice, the records per arm, the attempt counter and a sample
        - returns 0 when the counter is 0 and the positive control fired, else 1
    """
    parser = argparse.ArgumentParser( description="Replay a slice with every model entry point raising." )
    parser.add_argument( "--vectors", required=True, help="a question-vector side file, as question_vectors.write_side_file makes" )
    parser.add_argument( "--per-type", type=int, default=25, help="asks to replay of each of yes/no and multiple choice" )
    args  = parser.parse_args( argv )
    calls = collections.Counter()
    install_guards( calls )
    from cosa.agents.prediction_engine.prediction_engine import PredictionEngine
    from cosa.research.preference_replay import replay_loop, three_way_report
    from cosa.research.preference_replay.question_vectors import load_side_file
    from cosa.research.preference_replay.retune_run import read_cohort
    from cosa.rest.db.database import get_db

    header, vectors = load_side_file( args.vectors )
    with get_db() as session: asks, facts = read_cohort( session, vectors )
    print( "cohort read", len( asks ), facts[ "database" ] )
    ids, counts = pick_slice( asks, args.per_type )
    PredictionEngine.reset()
    engine = PredictionEngine( debug=False )
    arm    = three_way_report.make_three_way_arm( engine.recency_half_life_days )
    run    = replay_loop.replay( asks, engine, "slice", baselines={ "always_yes": replay_loop.always_yes_arm, "three_way": arm },
                                 target_types=( "yes_no", "multiple_choice" ), target_ids=set( ids ) )
    print( "slice", dict( counts ), "replayed records per arm", { name: len( records ) for name, records in run[ "records" ].items() } )
    print( "not_replayable", run[ "not_replayable" ] if isinstance( run[ "not_replayable" ], int ) else len( run[ "not_replayable" ] ) )
    attempts = sum( calls.values() )
    print( "model-call attempts:", dict( calls ) or 0 )
    fired = False
    try: PredictionEngine._get_llm_client( engine )
    except AssertionError as error:
        fired = True
        print( "positive control fired:", error, "| attempts now", dict( calls ) )
    return 0 if attempts == 0 and fired else 1


if __name__ == "__main__":
    sys.exit( main() )
