"""The judging pipeline both the scorer and the proof run: vectors, pool, candidates, judge."""
import asyncio

from cosa.repo.duplicate_check import blind, body_vectors, candidates, judge


def judge_all( judged, all_defs, cfg, wiring, slot, max_calls=None, skip_breaching=False ):
    """
    Embed the pool, pick each definition's candidates and judge them once.

    Requires:
        - judged are the new definitions to rule on, all of them in all_defs; all_defs are the new and server definitions together
        - cfg is the frozen configuration
        - wiring holds client, cache_dir, scrub, structural_pairs (a callable taking all definitions), backend, ledger and parallel
        - slot is the pass number
        - max_calls is None for no cap, or judge_run's cap on backend calls
        - skip_breaching is judge_run's: True leaves a new definition that carries a scrub token unjudged and counted
        - wiring may also hold redact_tools, judge_run's flag; without it the tool names are refused as before

    Ensures:
        - returns judge_run's { verdicts, unjudged } for the judged definitions, each ruled against its fused candidates, and dropped:
          { count, ids }, the server definitions left out of the pool because they carry a scrub token
        - only a server definition is dropped; a new definition carrying a token is kept, so judge_run raises for it, or leaves it unjudged with skip_breaching
        - the same inputs and slot make the same calls, so a finished call is read from the ledger

    Raises:
        - DuplicateCheckError BLINDNESS_BREACH, and whatever judge_run, ensure_vectors or candidate_rows raise
    """
    redact   = "redact_tools" in wiring and wiring[ "redact_tools" ]
    dropped  = blind.breaching_ids( [ d for d in all_defs if d[ "origin" ] == "server" ], wiring[ "scrub" ], redact )
    all_defs = [ d for d in all_defs if d[ "id" ] not in set( dropped ) ]
    vectors  = body_vectors.ensure_vectors( all_defs, wiring[ "client" ], wiring[ "cache_dir" ], cfg[ "body_chars" ] )[ "vectors" ]
    pool     = candidates.build_pool( all_defs, vectors )
    partners = candidates.partner_map( wiring[ "structural_pairs" ]( all_defs ) )
    rows     = candidates.candidate_rows( judged, pool, candidates.word_index( pool ), partners, cfg )
    by_id    = { d[ "id" ]: d for d in pool[ "defs" ] }
    cands    = { row[ "id" ]: [ by_id[ c[ "id" ] ] for c in row[ "candidates" ] ] for row in rows }
    outcome  = asyncio.run( judge.judge_run( judged, cands, wiring[ "backend" ], wiring[ "ledger" ], slot, cfg, wiring[ "scrub" ], wiring[ "parallel" ], max_calls, skip_breaching, redact ) )
    return { **outcome, "dropped": { "count": len( dropped ), "ids": dropped } }
