#!/usr/bin/env python3
"""
CJ Flow v2 — live embedding-cost wrapper (row 41333974, Job 2).

The thin, sanctioned-venue wrapper around src/scripts/v2_embedding_cost.py. The
standalone `--live` CLI has no path through /api/test-suite/submit (that endpoint
dispatches pytest suites, not scripts), and a CLI-on-a-box is exactly the side door
the venue rule closes. This test IS the sanctioned path: marked
`embedding_cost_live`, deselected from every default run (pytest.ini addopts), and
selected explicitly with `-m embedding_cost_live` on a scheduled :8000 slot.

What it asserts — RUN-INTEGRITY ONLY (Cheech's ruling 2026-08-14): a real number
came back, in a sane range, and the cache round trip served a warm hit. It NEVER
asserts a cost threshold — a millisecond bound would go red for load/network reasons
that are not defects. The number the exercise wants is captured from the printed
report; this test only proves the measurement RAN and produced sane shape.

Venue: :8000 scheduled, post-midnight (off-peak rule). Real inference — never :7999.

Created: 2026-08-14 (CJ Flow v2 · unit C2 Job 2 · Sam 🎙️)
"""

import importlib.util

import pytest

import cosa.utils.util as cu

# A generous sanity ceiling — NOT a cost threshold. A single query embedding taking
# over two minutes means the run is broken (server down, thrashing), not "slow".
_SANE_MS_CEILING = 120_000.0


def _load_instrument():
    """Load the standalone instrument by path (src/scripts is not a package)."""
    path = cu.get_project_root() + "/src/scripts/v2_embedding_cost.py"
    spec = importlib.util.spec_from_file_location( "v2_embedding_cost", path )
    module = importlib.util.module_from_spec( spec )
    spec.loader.exec_module( module )
    return module


@pytest.mark.embedding_cost_live
@pytest.mark.integration
def test_embedding_cost_live_run_integrity():
    """
    Drive the real V2Cache tier-2 embedding path and assert run-integrity.

    Requires:
        - a live authenticated server + model server (the :8000 scheduled venue)

    Ensures:
        - the measurement produced a `generated` summary whose mean is a real,
          positive, sane-range millisecond number for every default question
        - at least one warm request served from the verbatim embedding cache
          (the R-C3 cache round trip worked live), so `cached` is present
        - NO cost-threshold assertion — only shape and sanity, per the ruling
        - the human-readable report is printed for the number to be lifted from
    """
    instrument = _load_instrument()

    result = instrument.measure( list( instrument.DEFAULT_QUESTIONS ), instrument._live_probe() )

    # Print the report so the scheduled-run log carries the actual number.
    print( "\n" + instrument.format_report( result ) )

    # --- run-integrity: a number came back, in a sane range -------------------
    generated = result[ "generated" ]
    assert generated is not None
    assert generated[ "n" ] == float( len( instrument.DEFAULT_QUESTIONS ) )   # every question measured
    assert isinstance( generated[ "mean" ], float )
    assert 0.0 < generated[ "mean" ] < _SANE_MS_CEILING                       # real, positive, sane
    assert 0.0 <= generated[ "min" ] <= generated[ "max" ] < _SANE_MS_CEILING

    # --- the cache round trip served a warm hit live (R-C3), not a cost bound -
    assert result[ "cached" ] is not None, "no warm request hit the verbatim embedding cache"
    assert result[ "cached" ][ "mean" ] >= 0.0
    if result[ "speedup" ] is not None:
        assert result[ "speedup" ] > 0.0                                      # shape, never a magnitude floor
