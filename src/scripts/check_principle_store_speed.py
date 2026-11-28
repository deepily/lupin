"""
Replay an archive run's cards through the old and new principle code, and compare.

The old code is read from a git commit, so it is the code that ran, not a copy of it.
Each card is a stored principles forecast row. Its query vector comes from the run's own
embedding cache, so no model and no embedding service is called. The cosine search is the
replay's own, made once per card and handed to both sides.

For each card the script compares what retrieval returns, with the applicability check and
caveats off and then on, and the prompt block. It also compares the status of every principle.
The archive database is copied to a temporary folder and read there.

Run it pinned to the tree:
    cd <worktree> && LUPIN_ROOT="$PWD" PYTHONPATH="$PWD/src" .venv/bin/python src/scripts/check_principle_store_speed.py \
        --archive <main tree>/io/phase4-archive-run-2 --base 1b3cd8da9

Exit 0 is no difference, 1 is a difference, 2 is that no card retrieved a principle, so nothing was shown.
"""

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
import types
from contextlib import contextmanager
from statistics import mean, median
from unittest import mock

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import cosa.utils.util as cu
from cosa.agents.prediction_engine import principle_retrieval, principle_status
from cosa.agents.prediction_engine.card_stage import card_stage_of
from cosa.agents.prediction_engine.episode_view import card_text, episode_view
from cosa.agents.prediction_engine.principle_features import feature_lookup
from cosa.agents.prediction_engine.principles_forecast import ARM
from cosa.repo.doc_lint.split_check import read_old
from cosa.research.preference_replay import scratch_db  # noqa: F401  registers the SQLite hooks for JSONB and Vector
from cosa.research.preference_replay.archive_replay import scratch_topk
from cosa.research.preference_replay.service_embeddings import cache_key
from cosa.rest.postgres_models import Notification, PredictionArmForecast, PredictionLog, PreferenceEvidence, PreferencePrinciple
from cosa.utils.iso_timestamp import aware_moment
from scripts.full_answer_arm import add_missing_columns

STATUS_PATH    = "src/cosa/agents/prediction_engine/principle_status.py"
RETRIEVAL_PATH = "src/cosa/agents/prediction_engine/principle_retrieval.py"
SUFFIX         = "checkfix"


def module_at( root, sha, path ):
    """
    Load one source file as it was at a commit, as a module of its own.

    Requires:
        - root is a git work tree; sha names a commit holding the file at path

    Ensures:
        - returns a new module executed from that text; sys.modules and the tree are left alone

    Raises:
        - RuntimeError if the commit or the path does not exist
    """
    source = read_old( root, sha, path )
    module = types.ModuleType( f"at_{sha}_{os.path.basename( path )[ :-3 ]}" )
    exec( compile( source, f"{sha}:{path}", "exec" ), module.__dict__ )
    return module


def old_code( root, sha ):
    """
    Load a commit's status and retrieval modules, with retrieval bound to that status.

    Requires:
        - root and sha as module_at takes them

    Ensures:
        - returns ( status, retrieval ); every public name the old retrieval took from the status module is rebound to
          the commit's own, whichever function it derives with, so none of the tree's status code answers for the old side
    """
    status    = module_at( root, sha, STATUS_PATH )
    retrieval = module_at( root, sha, RETRIEVAL_PATH )
    for name, value in vars( status ).items():
        if not name.startswith( "_" ) and name in vars( retrieval ): setattr( retrieval, name, value )
    return status, retrieval


@contextmanager
def archive_copy( archive ):
    """
    Open a throwaway copy of an archive run's database.

    Requires:
        - archive is a folder holding archive.sqlite

    Ensures:
        - yields a function that opens a new session over the copy
        - the copy gains the nullable columns the models hold and the archive lacks, so both sides read the same empty values
        - the copy is removed on exit; the archive is only read
    """
    with tempfile.TemporaryDirectory() as folder:
        path = os.path.join( folder, "archive.sqlite" )
        shutil.copyfile( os.path.join( archive, "archive.sqlite" ), path )
        engine = create_engine( f"sqlite:///{path}" )
        try:
            add_missing_columns( engine, ( Notification, PredictionLog, PredictionArmForecast, PreferenceEvidence, PreferencePrinciple ) )
            yield lambda: Session( engine )
        finally:
            engine.dispose()


def shape( result, retrieval ):
    """
    Reduce a retrieval result to everything a forecast can see of it.

    Requires:
        - result is retrieve_principles' result; retrieval is the module that made it

    Ensures:
        - returns a comparable dict: each kept principle's id, similarity, status, conditions and caveat, in order,
          the available count, short, the dropped list when there is one, and the prompt block under a fixed suffix
    """
    kept = [ ( str( e[ "principle" ].id ), e[ "similarity_pct" ], e[ "status" ], e[ "conditions" ], e.get( "caveat" ) ) for e in result[ "principles" ] ]
    return { "kept": kept, "available": result[ "available" ], "short": result[ "short" ],
             "dropped": [ ( str( d[ "principle_id" ] ), d[ "rule" ] ) for d in result.get( "applicability", [] ) ],
             "block": retrieval.principle_block( result[ "principles" ], suffix=SUFFIX, caveats=any( "caveat" in e for e in result[ "principles" ] ) )[ "text" ] }


def timed( call ):
    """
    Run a call and time it.

    Ensures:
        - returns ( the call's result, milliseconds taken )
    """
    start  = time.perf_counter()
    result = call()
    return result, ( time.perf_counter() - start ) * 1000.0


def retrieve_both( opener, sides, arguments, extras, found ):
    """
    Run one ask through both retrievals, each in its own session, with one search result.

    Requires:
        - opener opens a session; sides is [ old retrieval, new retrieval ]
        - arguments are retrieve_principles' positional arguments after session; extras its keyword arguments
        - found is the cosine search's result for this ask

    Ensures:
        - returns [ ( shape, milliseconds ) ] in the order of sides
        - the time excludes the cosine search, which both sides share
    """
    out = []
    for retrieval in sides:
        with opener() as session, mock.patch.object( retrieval, "dot_topk", lambda *a, **k: found ):
            result, spent = timed( lambda: retrieval.retrieve_principles( session, *arguments, **extras ) )
            out.append( ( shape( result, retrieval ), spent ) )
    return out


def compare_card( opener, old_status, old_retrieval, card, bound ):
    """
    Compare one card: retrieval with the checks off and on, and every principle's status.

    Requires:
        - card is { id, episode, vector, encoder, extractor }; old_status and old_retrieval are old_code's modules
        - bound is at least the number of principles one owner holds, so every principle is fetched

    Ensures:
        - the owner is passed as text, as the live forecast passes it
        - returns { differences, retrieve_ms, derive_ms, kept_ids }: differences names each comparison that differed,
          the two time pairs are ( old, new ) milliseconds for retrieval with the checks off and for deriving every
          status, and kept_ids is what the new code kept with the checks off
        - the status comparison runs with the INI switches, and again with condition keys and source dedup both on
    """
    episode, vector = card[ "episode" ], card[ "vector" ]
    asked           = aware_moment( episode[ "asked_at" ] )
    owner           = episode[ "owner_id" ]
    with opener() as session:
        scopes  = [ "global" ] + ( [ f"project:{episode[ 'project' ]}" ] if episode[ "project" ] else [] )
        allowed = ( ( PreferencePrinciple.owner_id == owner ) & PreferencePrinciple.embedding.isnot( None )
                    & ( PreferencePrinciple.encoder_version == card[ "encoder" ] ) & PreferencePrinciple.scope.in_( scopes ) )
        found   = scratch_topk( session, PreferencePrinciple, None, vector, limit=bound, exclude_filter=allowed )
        arguments   = ( owner, episode[ "project" ], vector, asked, card[ "encoder" ], card[ "extractor" ] )
        differences = []
        sides       = [ old_retrieval, principle_retrieval ]
        plain       = retrieve_both( opener, sides, arguments, { "bound": bound }, found )
        check       = { "card": card_text( episode ), "card_stage": card_stage_of( episode ) }
        checked     = retrieve_both( opener, sides, arguments, { "bound": bound, "applicability": check, "caveats": True }, found )
        if plain[ 0 ][ 0 ] != plain[ 1 ][ 0 ]: differences.append( "retrieval" )
        if checked[ 0 ][ 0 ] != checked[ 1 ][ 0 ]: differences.append( "retrieval with applicability and caveats" )
        principles, evidence = principle_retrieval.load_owner_ledger( session, owner )
        sessions = principle_retrieval.session_lookup( session, [ e.notification_id for e in evidence if e.session_key is None ] )
        features = feature_lookup( session, [ e.notification_id for e in evidence ] )
        ledger   = ( principles, evidence, asked, card[ "extractor" ], sessions, features )
        old_all, old_ms = timed( lambda: old_status.derive_statuses( *ledger ) )
        new_all, new_ms = timed( lambda: principle_status.derive_statuses( *ledger ) )
        if old_all != new_all: differences.append( "standings" )
        switched = { "condition_keys": True, "source_dedup": True }
        if old_status.derive_statuses( *ledger, **switched ) != principle_status.derive_statuses( *ledger, **switched ):
            differences.append( "standings with both switches on" )
    return { "differences": differences, "retrieve_ms": ( plain[ 0 ][ 1 ], plain[ 1 ][ 1 ] ), "derive_ms": ( old_ms, new_ms ),
             "kept_ids": [ k[ 0 ] for k in plain[ 1 ][ 0 ][ "kept" ] ] }


def stored_cards( opener, every, limit, offset=0 ):
    """
    List the archive's principles forecast rows, oldest ask first.

    Requires:
        - every is a positive int; offset is 0 or more and below every; limit is None or a positive int

    Ensures:
        - returns [ ( notification id, stored evidence ids as text ) ], every `every`-th row starting at row `offset`, cut to limit, so `every` runs with each offset cover all rows once
    """
    with opener() as session:
        rows = session.query( PredictionArmForecast ).filter( PredictionArmForecast.arm == ARM ).order_by( PredictionArmForecast.input_cutoff ).all()
        found = [ ( row.notification_id, [ str( i ) for i in row.evidence_ids or [] ] ) for row in rows ]
    return found[ offset::every ][ :limit ]


def run_check( root, archive, base, every=1, limit=None, offset=0, out=print ):
    """
    Compare old and new on an archive run's cards.

    Requires:
        - archive holds archive.sqlite and embeddings.json; base is the commit holding the old code
        - the principles in the archive carry one encoder version and one extractor version

    Ensures:
        - returns a summary: cards, compared, without_vector, different (the card ids with what differed, at most 20),
          different_count, stored_selection_equal, principles, evidence, and the retrieve and derive times in
          milliseconds as { old_median, new_median, old_mean, new_mean }, empty when nothing was compared
        - a card whose text has no cached vector is counted and skipped, never embedded
        - with_principles counts compared cards where the new code kept at least one principle
        - stored_selection_equal counts cards whose new selection equals the ids the run stored; it is not a pass condition
        - a progress line goes to out every 100 cards
    """
    old_status, old_retrieval = old_code( root, base )
    with open( os.path.join( archive, "embeddings.json" ), encoding="utf-8" ) as handle: vectors = json.load( handle )
    different, times, missing, matched = [], [], 0, 0
    with archive_copy( archive ) as opener:
        with opener() as session:
            bound     = session.query( PreferencePrinciple ).count()
            evidence  = session.query( PreferenceEvidence ).count()
            encoder, extractor = session.query( PreferencePrinciple.encoder_version, PreferencePrinciple.extractor_version ).distinct().one()
        cards = stored_cards( opener, every, limit, offset )
        for number, ( note, stored ) in enumerate( cards, 1 ):
            with opener() as session: episode = episode_view( session, note, limit=1 )
            vector = vectors.get( cache_key( card_text( episode ), encoder ) )
            if vector is None:
                missing += 1
                continue
            card    = { "id": str( note ), "episode": episode, "vector": vector, "encoder": encoder, "extractor": extractor }
            outcome = compare_card( opener, old_status, old_retrieval, card, bound )
            if outcome[ "differences" ]: different.append( ( card[ "id" ], outcome[ "differences" ] ) )
            matched += outcome[ "kept_ids" ] == stored
            times.append( outcome )
            if number % 100 == 0: out( f"[check] {number}/{len( cards )} cards, {len( different )} differ" )
    summary = { "cards": len( cards ), "compared": len( times ), "with_principles": sum( 1 for t in times if t[ "kept_ids" ] ), "without_vector": missing, "different_count": len( different ), "different": different[ :20 ],
                "stored_selection_equal": matched, "principles": bound, "evidence": evidence }
    for name in ( "retrieve_ms", "derive_ms" ):
        old, new = [ t[ name ][ 0 ] for t in times ], [ t[ name ][ 1 ] for t in times ]
        summary[ name ] = {} if not times else { "old_median": median( old ), "new_median": median( new ), "old_mean": mean( old ), "new_mean": mean( new ) }
    return summary


def main( argv=None, out=print ):
    """
    Run the check from the command line and print its summary as JSON.

    Ensures:
        - returns 1 when any card differs, else 2 when no card kept a principle, else 0
    """
    parser = argparse.ArgumentParser( description="Compare old and new principle retrieval on an archive run." )
    parser.add_argument( "--archive", required=True, help="folder holding archive.sqlite and embeddings.json" )
    parser.add_argument( "--base", required=True, help="commit holding the old code" )
    parser.add_argument( "--every", type=int, default=1, help="check every Nth card" )
    parser.add_argument( "--offset", type=int, default=0, help="first card to check; with --every N, offsets 0 to N-1 split a full run" )
    parser.add_argument( "--limit", type=int, default=None, help="check at most this many cards" )
    args    = parser.parse_args( argv )
    summary = run_check( cu.get_project_root(), args.archive, args.base, every=args.every, limit=args.limit, offset=args.offset, out=out )
    out( json.dumps( summary, indent=2 ) )
    if summary[ "different_count" ]: return 1
    return 0 if summary[ "with_principles" ] else 2


if __name__ == "__main__":  # pragma: no cover - the script entry; main is tested directly
    sys.exit( main() )
