"""
Guard the similarity SCALE and the gate that trusts it (bug 78f21b1b).

WHAT WENT WRONG. `dot_topk` scored matches as ``dot_product * 100``. That is a
real percentage ONLY IF BOTH VECTORS ARE UNIT LENGTH — true while embeddings came
from OpenAI ``text-embedding-3-small`` (L2-normalized, so dot IS cosine), and
false once the provider moved to the local ``nomic-ai`` models, which do not
normalize. Measured: query norm 19.809 against stored OpenAI-era rows at 1.000.

Same arithmetic, ~20x the number. A live voice question scored 1024.15% for a
TRUE COSINE of 0.517, and `push_job` read ``>= 100.0`` as a PERFECT EXACT MATCH —
so it replayed an unrelated cached row ("Concurrent question 7: What is 70?")
in 0 ms instead of routing to an agent. Agentic routing was unreachable, and the
failure looked like success because it was instant.

Nothing failed loudly because both models emit 768 dimensions: the vectors stayed
SHAPE-compatible while becoming SCALE-incompatible. A dimension mismatch would
have thrown on day one.

WHAT THIS FILE PINS, in two independent layers — deliberately, because either
alone leaves the door open:

  1. SCALE  — cosine scoring divides by BOTH norms, so a non-unit vector cannot
              inflate the score. Correct for any future embedding model.
  2. GATE   — a score outside [0,100] is a BROKEN MEASUREMENT, not a strong
              match. It must route, never auto-accept.

⚠️ A NOTE ON THE OBVIOUS-LOOKING FIX, pinned here so it is not "simplified" back
in: `dot_topk(clamp=True)` does NOT solve this. Clamping maps 1024.15 to exactly
100.0, which still satisfies ``>= 100.0`` and still auto-accepts. The clamp hides
the evidence while preserving the bug. There is a test below that says so.

Venue: :7999 — pure arithmetic and a hand-built decision harness. No DB, no
server, no network.
"""

import numpy as np
import pytest


# --------------------------------------------------------------------------- #
# Layer 1 — the SCALE. Pure arithmetic, mirroring what dot_topk computes for
# each metric, so the property is pinned without needing a live pgvector session.
# --------------------------------------------------------------------------- #

def _dot_pct( stored, query ):
    """What metric='dot' yields: -(col <#> q) * 100  ==  dot * 100."""
    return float( np.dot( stored, query ) ) * 100.0


def _cosine_pct( stored, query ):
    """What metric='cosine' yields: (1 - (col <=> q)) * 100  ==  cosine * 100."""
    denom = float( np.linalg.norm( stored ) * np.linalg.norm( query ) )
    return float( np.dot( stored, query ) ) / denom * 100.0


def _vectors_reproducing_the_live_failure():
    """
    A unit stored vector and a 19.809-length query at ~0.517 cosine — the exact
    shape measured in production on 2026-08-02.
    """
    dim    = 768
    rng    = np.random.default_rng( 20260802 )
    stored = rng.normal( size=dim )
    stored = stored / np.linalg.norm( stored )

    # Build a query at a KNOWN cosine to `stored`, then scale it to the measured
    # nomic norm. Constructing it this way means the test asserts against a
    # cosine we chose, not one we discovered after the fact.
    target_cos = 0.517
    orthogonal = rng.normal( size=dim )
    orthogonal = orthogonal - np.dot( orthogonal, stored ) * stored
    orthogonal = orthogonal / np.linalg.norm( orthogonal )

    query = target_cos * stored + np.sqrt( 1.0 - target_cos ** 2 ) * orthogonal
    query = query * 19.809
    return stored, query, target_cos


def test_dot_scoring_exceeds_100_for_a_non_unit_query():
    """
    THE DEFECT ITSELF. This is the red-proof: it asserts the OLD behaviour is
    genuinely broken, so a green suite cannot be mistaken for 'the bug never
    existed'. If this ever fails, the premise changed and the rest of this file
    needs re-reading.
    """
    stored, query, _ = _vectors_reproducing_the_live_failure()

    pct = _dot_pct( stored, query )

    assert pct > 100.0, (
        f"expected the dot scale to overflow for a non-unit query, got {pct:.2f}%. "
        f"If this no longer overflows, embeddings may now be normalized at the "
        f"source — verify before deleting this test."
    )
    # ~1024%, matching the live observation
    assert 900.0 < pct < 1200.0, f"overflow magnitude changed unexpectedly: {pct:.2f}%"


def test_cosine_scoring_stays_in_range_and_recovers_the_true_similarity():
    """The fix: dividing by both norms makes the query's length irrelevant."""
    stored, query, target_cos = _vectors_reproducing_the_live_failure()

    pct = _cosine_pct( stored, query )

    assert 0.0 <= pct <= 100.0, f"cosine must stay in [0,100], got {pct:.2f}%"
    assert pct == pytest.approx( target_cos * 100.0, abs=0.5 ), (
        f"cosine should recover the true similarity ~{target_cos * 100:.1f}%, got {pct:.2f}%"
    )


@pytest.mark.parametrize( "scale", [ 0.1, 1.0, 19.809, 250.0 ] )
def test_cosine_is_invariant_to_query_length( scale ):
    """
    The property that makes cosine the RIGHT fix rather than a patch: the score
    does not move when the embedding model's output scale changes. Normalizing
    the query would also fix today's numbers, but would re-establish an unwritten
    precondition — and that precondition already failed once, silently, for months.
    """
    stored, query, target_cos = _vectors_reproducing_the_live_failure()
    rescaled = query / np.linalg.norm( query ) * scale

    pct = _cosine_pct( stored, rescaled )

    assert pct == pytest.approx( target_cos * 100.0, abs=0.5 ), (
        f"cosine moved with query scale {scale}: {pct:.2f}%"
    )


# --------------------------------------------------------------------------- #
# Layer 2 — the GATE. Mirrors push_job's decision so the branch is pinned
# without standing up the whole queue.
# --------------------------------------------------------------------------- #

ASK_FLOOR = 90.0


def _gate_decision( best_score ):
    """
    The decision in todo_fifo_queue.push_job, extracted.

    Returns one of: "reject-out-of-range" | "auto-accept" | "confirm" | "route".
    """
    if best_score < 0.0 or best_score > 100.0:
        return "reject-out-of-range"
    if best_score >= 100.0:
        return "auto-accept"
    if best_score >= ASK_FLOOR:
        return "confirm"
    return "route"


@pytest.mark.parametrize( "score", [ 1024.15, 1006.07, 943.0, 1123.9, 100.01, -0.01 ] )
def test_out_of_range_scores_are_refused_not_trusted( score ):
    """
    Every one of these was observed live and auto-accepted. An impossible
    percentage means the SCORER is wrong; treating it as maximum confidence is
    what made the failure silent.
    """
    assert _gate_decision( score ) == "reject-out-of-range", (
        f"{score}% must be refused as a broken measurement, not treated as a match"
    )


def test_the_real_match_now_routes_instead_of_replaying():
    """
    End of the story: the live case that answered "70" scores 51.7% under cosine,
    which is below the ask floor, so it routes to the agent.
    """
    stored, query, _ = _vectors_reproducing_the_live_failure()
    pct = _cosine_pct( stored, query )

    assert _gate_decision( pct ) == "route", (
        f"a ~52% match must route, not replay a cached answer (got {pct:.2f}%)"
    )


def test_clamping_alone_would_not_have_fixed_this():
    """
    Pinned because `dot_topk(clamp=True)` is the change a future reader is most
    likely to reach for. Clamping maps the overflow to exactly 100.0 — which
    still satisfies `>= 100.0` and still auto-accepts. It hides the evidence and
    keeps the bug.
    """
    clamped = max( 0.0, min( 100.0, 1024.15 ) )

    assert clamped == 100.0
    assert _gate_decision( clamped ) == "auto-accept", (
        "if this no longer auto-accepts, the gate changed and this warning can go"
    )
    # ...whereas the unclamped value is correctly refused.
    assert _gate_decision( 1024.15 ) == "reject-out-of-range"


def test_the_mirror_above_still_matches_the_real_gate():
    """
    ⚠️ READ THIS BEFORE TRUSTING THE TESTS ABOVE.

    `_gate_decision` is a MIRROR of the branch in todo_fifo_queue.push_job, not
    the branch itself. A mirror can drift from what it mirrors, and then the whole
    layer-2 section would keep passing while production regressed — a test that
    describes the thing instead of touching it.

    Standing up the real push_job needs a queue, a snapshot manager, a DB session
    and a websocket, which is why the mirror exists. So this test does the one
    thing it honestly can: assert the real source still contains the rejection
    branch, and that it is ordered BEFORE the perfect-match branch (ordering is
    the whole fix — a rejection placed after `>= 100.0` would never be reached).

    This is a CONTACT check, not a behavioural one. It proves the branch exists
    and is positioned correctly. It does NOT prove it executes. If you are adding
    coverage here, an integration test that drives a real out-of-range score
    through push_job is strictly better than this.
    """
    import os

    root = os.environ.get( "LUPIN_ROOT" )
    assert root, "LUPIN_ROOT not set — export LUPIN_ROOT=/path/to/project"

    with open( os.path.join( root, "src/cosa/rest/todo_fifo_queue.py" ) ) as fh:
        src = fh.read()

    reject_at = src.find( "best_score < 0.0 or best_score > 100.0" )
    accept_at = src.find( "elif best_score >= 100.0:" )

    assert reject_at != -1, (
        "the out-of-range rejection branch is GONE from push_job — bug 78f21b1b "
        "is unguarded and every layer-2 test above is now measuring nothing"
    )
    assert accept_at != -1, "the perfect-match branch is gone; this test needs rewriting"
    assert reject_at < accept_at, (
        "the rejection branch must come BEFORE the >= 100.0 branch. Ordered after "
        "it, an out-of-range score would be auto-accepted first and the guard "
        "would never run."
    )
    assert "needs_llm_routing = True" in src[ reject_at : accept_at ], (
        "the rejection branch must set needs_llm_routing = True. Emptying "
        "similar_snapshots instead does NOT work: the length check has already "
        "passed, so the outer else is unreachable and the request would fall "
        "through doing nothing — a worse failure than the one being fixed. "
        "(This exact mistake was made and caught while writing the fix.)"
    )


def test_legitimate_exact_matches_still_auto_accept():
    """
    The gate must not become so suspicious that it breaks the real cache. L1/L2
    exact matches return exactly 100.0 and must still short-circuit.
    """
    assert _gate_decision( 100.0 ) == "auto-accept"
    assert _gate_decision( 95.0 )  == "confirm"
    assert _gate_decision( 51.7 )  == "route"
    assert _gate_decision( 0.0 )   == "route"
