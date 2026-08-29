#!/usr/bin/env python3
"""
CJ Flow v2 — embedding-cost measurement (unit C2 deliverable).

Answers the question the plan REFUSES to assume (design §6): on the tier-2
similar path, how expensive is embedding the query, and how much does the
verbatim embedding cache (R-C3) save on a warm repeat?

    generated  — a query embedding computed by the model server (a round trip).
    cached     — the SAME query served from QuestionEmbeddingRepository, no model
                 call (a btree lookup).

The instrument measures BOTH per question and reports the delta. The generate
side spends real inference and needs a live authenticated server, so this is a
CLI — kept OUT of the run-*.sh rotation (same call the plan makes for the eval
harness) and run on the :8000 scheduled venue, never :7999.

The measurement LOOP + the summary math are pure and injectable, so they are
unit-tested with a fake probe (no live server). Only ``--live`` wires the real
V2Cache against get_db + the embedding provider.

Usage:
    python src/scripts/v2_embedding_cost.py --live            # real measurement
    python src/scripts/v2_embedding_cost.py --live -q "..."   # extra questions

Created: 2026-08-14 (CJ Flow v2 · unit C2 · Sam 🎙️)
"""

import argparse
import json
import time
from typing import Callable, Dict, List, Tuple

# A small, intent-diverse default corpus (one per phase-1 command family). The
# eval harness (unit F) drives the full corpus; this probe only needs enough
# questions to make the generate-vs-cached delta legible.
DEFAULT_QUESTIONS = (
    "what time is it",
    "what is 2 plus 2",
    "what is the weather in Tokyo",
    "what is on my calendar today",
    "what is today's date",
)


def summarize( times_ms: List[float] ) -> Dict[str, float]:
    """
    Summary statistics for a list of millisecond timings.

    Requires:
        - times_ms is a non-empty list of floats

    Ensures:
        - returns { n, mean, p50, p95, min, max } with p50/p95 by nearest-rank
          on the sorted sample

    Raises:
        - ValueError if times_ms is empty
    """
    if not times_ms:
        raise ValueError( "summarize requires at least one timing" )
    ordered = sorted( times_ms )
    n       = len( ordered )

    def _pct( p: float ) -> float:
        # nearest-rank: index = ceil( p/100 * n ) - 1, clamped to [0, n-1]
        rank = int( ( p / 100.0 ) * n + 0.9999 ) - 1
        return ordered[ max( 0, min( n - 1, rank ) ) ]

    return {
        "n"    : float( n ),
        "mean" : sum( ordered ) / n,
        "p50"  : _pct( 50.0 ),
        "p95"  : _pct( 95.0 ),
        "min"  : ordered[ 0 ],
        "max"  : ordered[ -1 ],
    }


def measure( questions: List[str], embed_once: Callable[ [str, bool], Tuple[bool, float] ] ) -> Dict:
    """
    Run each question through ``embed_once`` cold (generate) then warm (cached).

    Requires:
        - questions is a non-empty list of strings
        - embed_once( question, warm ) -> ( embed_cached, elapsed_ms ): the probe;
          warm=False is the first (cold) call, warm=True the repeat

    Ensures:
        - returns { rows, generated, cached, speedup }:
            rows      — per-question ( question, cold_ms, warm_ms, warm_cached )
            generated — summary of cold timings (cache misses that generated)
            cached    — summary of warm timings reported as cache hits
            speedup   — generated.mean / cached.mean, or None if nothing cached
        - a warm call that did NOT report a cache hit is excluded from ``cached``
          (honest: only genuine hits count toward the saved cost)
    """
    rows          : List[Tuple[str, float, float, bool]] = []
    cold_times    : List[float] = []
    warm_hit_times: List[float] = []

    for question in questions:
        _cold_cached, cold_ms = embed_once( question, False )
        warm_cached, warm_ms  = embed_once( question, True )
        rows.append( ( question, cold_ms, warm_ms, warm_cached ) )
        cold_times.append( cold_ms )
        if warm_cached:
            warm_hit_times.append( warm_ms )

    result = {
        "rows"      : rows,
        "generated" : summarize( cold_times ),
        "cached"    : summarize( warm_hit_times ) if warm_hit_times else None,
        "speedup"   : None,
    }
    if result[ "cached" ] is not None and result[ "cached" ][ "mean" ] > 0:
        result[ "speedup" ] = result[ "generated" ][ "mean" ] / result[ "cached" ][ "mean" ]
    return result


def format_report( result: Dict ) -> str:
    """Render the measurement as a markdown table + headline line."""
    lines = [ "| question | cold (generate) ms | warm ms | warm cached |",
              "|---|---:|---:|:--:|" ]
    for question, cold_ms, warm_ms, warm_cached in result[ "rows" ]:
        hit = "✓" if warm_cached else "—"
        lines.append( f"| {question} | {cold_ms:.1f} | {warm_ms:.1f} | {hit} |" )
    gen = result[ "generated" ]
    lines.append( "" )
    lines.append( f"generate: mean={gen['mean']:.1f}ms p50={gen['p50']:.1f} p95={gen['p95']:.1f} (n={int(gen['n'])})" )
    if result[ "cached" ] is not None:
        cch = result[ "cached" ]
        lines.append( f"cached:   mean={cch['mean']:.1f}ms p50={cch['p50']:.1f} p95={cch['p95']:.1f} (n={int(cch['n'])})" )
    if result[ "speedup" ] is not None:
        lines.append( f"speedup:  {result['speedup']:.0f}x (a warm repeat skips the model call)" )
    return "\n".join( lines )


def _live_probe():  # pragma: no cover — needs a live server + model server (:8000 scheduled)
    """
    Build a probe that measures the REAL V2Cache tier-2 embedding path.

    A cold call clears the verbatim cache row and times a generate; a warm call
    times the cache hit that write-back's cache population leaves behind. Needs a
    live authenticated server + model server — :8000 scheduled venue only.
    """
    from cosa.rest.db.database import get_db
    from cosa.rest.db.repositories.question_embedding_repository import QuestionEmbeddingRepository
    from cosa.rest.v2.cache import V2Cache

    cache = V2Cache()

    def _embed_once( question: str, warm: bool ) -> Tuple[bool, float]:
        with get_db() as session:                       # noqa: F841 — scope commits
            repo = QuestionEmbeddingRepository( session )
            if not warm and repo.get_embedding( question ) is None:
                # cold: ensure a miss so we time a real generate, then seed cache
                vec = cache._embedding_provider.generate_embedding( question, content_type="prose" )
                t0  = time.perf_counter_ns()
                cache._embedding_provider.generate_embedding( question, content_type="prose" )
                cold_ms = ( time.perf_counter_ns() - t0 ) / 1_000_000.0
                repo.add_embedding( question, vec )
                return False, cold_ms
            t0     = time.perf_counter_ns()
            cached = repo.get_embedding( question )
            return cached is not None, ( time.perf_counter_ns() - t0 ) / 1_000_000.0

    return _embed_once


def main() -> None:
    parser = argparse.ArgumentParser( description="CJ Flow v2 embedding-cost measurement" )
    parser.add_argument( "--live", action="store_true", help="measure against the live server + model server (:8000 scheduled)" )
    parser.add_argument( "-q", "--question", action="append", default=[], help="extra question(s) to measure" )
    args = parser.parse_args()

    questions = list( DEFAULT_QUESTIONS ) + list( args.question )
    if not args.live:
        print( "This is the measurement INSTRUMENT. Re-run with --live on a scheduled :8000 "
               "server to produce real numbers (real inference; not a :7999 job)." )
        return

    result = measure( questions, _live_probe() )                             # pragma: no cover — live infra
    print( format_report( result ) )                                         # pragma: no cover — live infra
    print( "\n" + json.dumps( { "generated": result[ "generated" ],          # pragma: no cover — live infra
                                "cached": result[ "cached" ],
                                "speedup": result[ "speedup" ] } ) )


if __name__ == "__main__":
    main()
