"""The judging pipeline both the scorer and the proof run: vectors, pool, candidates, judge."""
import asyncio

from cosa.repo.semdup import body_vectors, candidates, judge


def judge_all( judged, all_defs, cfg, wiring, slot ):
    """
    Embed the pool, pick each definition's candidates and judge them once.

    Requires:
        - judged are the new definitions to rule on, all of them in all_defs; all_defs are the new and server definitions together
        - cfg is the frozen configuration
        - wiring holds client, cache_dir, scrub, structural_pairs (a callable taking all definitions), backend, ledger and parallel
        - slot is the pass number

    Ensures:
        - returns judge_run's { verdicts, unjudged } for the judged definitions, each ruled against its fused candidates
        - the same inputs and slot make the same calls, so a finished call is read from the ledger

    Raises:
        - SemdupError BLINDNESS_BREACH, and whatever judge_run, ensure_vectors or candidate_rows raise
    """
    vectors  = body_vectors.ensure_vectors( all_defs, wiring[ "client" ], wiring[ "cache_dir" ], cfg[ "body_chars" ] )[ "vectors" ]
    pool     = candidates.build_pool( all_defs, vectors )
    partners = candidates.partner_map( wiring[ "structural_pairs" ]( all_defs ) )
    rows     = candidates.candidate_rows( judged, pool, candidates.word_index( pool ), partners, cfg )
    by_id    = { d[ "id" ]: d for d in pool[ "defs" ] }
    cands    = { row[ "id" ]: [ by_id[ c[ "id" ] ] for c in row[ "candidates" ] ] for row in rows }
    return asyncio.run( judge.judge_run( judged, cands, wiring[ "backend" ], wiring[ "ledger" ], slot, cfg, wiring[ "scrub" ], wiring[ "parallel" ] ) )
