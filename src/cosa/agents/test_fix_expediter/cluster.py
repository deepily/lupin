"""
Phase 0 clustering for the TestFixExpediter.

Groups N pytest failures into K ≤ max_clusters coherent clusters, each
representing one shared root cause. The cluster list drives Phase 1
(per-cluster diagnosis), Phase 2 (per-cluster proposal), Phase 3 (per-cluster
fix application), and Phase 5 (per-cluster commits within one branch).

Design: src/rnd/v0.1.6/2026.04.10-test-fix-expediter/03-phase0-clustering-plan.md

Approach:
    1. Heuristic seed (`heuristic_seed`): group failures by
       (normalized_classname, first_non_pytest_traceback_frame). Pure
       Python, no LLM cost, handles ~80% of realworld cases.
    2. LLM refinement (`llm_refine`): optional pass that merges/splits/
       relabels the heuristic seeds via Opus. In step 7, the LLM path is
       a pass-through that caps by `max_clusters` via consolidation of
       smallest clusters. The real Claude Agent SDK call lands when Phase 1
       diagnose goes live (step 8) and we have a working SDK wiring path.
"""

import logging
import re
from typing import Callable, Optional

import cosa.utils.util as cu

from cosa.agents.test_fix_expediter.state import FailureCluster, TestRemediationContext

logger = logging.getLogger( __name__ )


# ─────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────

# Traceback frame sources to skip when looking for the first "real" frame.
# These are pytest infrastructure files that every failure traceback
# traverses — the real bug is in the NEXT frame after them.
_PYTEST_INFRA_FRAMES = (
    "_pytest/",
    "pytest/",
    "conftest.py",
    "unittest/",
    "python3",
    "runpy.py",
    "pluggy/",
)

# Sentinel used when a failure has no extractable source frame
# (e.g., collection errors, startup crashes, pytest internals).
_NO_FRAME_SENTINEL = "<no_frame>"

# Default cap when llm_refine is called without an explicit value
DEFAULT_MAX_CLUSTERS = 8


# ─────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────


def _normalize_classname( classname: str ) -> str:
    """
    Normalize a pytest classname to its stable prefix.

    Strips parameter suffixes that some pytest setups can add to classnames
    (rare but observed). The `name` field already has `[param]` suffixes —
    we don't want classname variation to split what is really one cluster.

    Requires:
        - classname is a string (may be empty)

    Ensures:
        - Returns a lowercase-preserving normalized classname
        - Empty string for empty input
    """
    if not classname:
        return ""
    # Strip any bracketed suffix (defensive — BFE's observed format doesn't use this)
    return re.sub( r"\[[^\]]*\]", "", classname ).strip()


def _extract_first_real_frame( traceback: str ) -> str:
    """
    Extract the first traceback frame that is NOT pytest infrastructure.

    pytest tracebacks generally contain interleaved frames from:
      - pytest / _pytest / pluggy (infrastructure)
      - the user's test file
      - the user's production code under test (when the assertion came from there)

    For clustering purposes, the most informative frame is usually the
    first non-pytest frame — either the test function or the tested code.

    Requires:
        - traceback is a string (may be empty)

    Ensures:
        - Returns "file.py:line" if a real frame is found
        - Returns the _NO_FRAME_SENTINEL if no real frame found
    """
    if not traceback:
        return _NO_FRAME_SENTINEL

    # Match `File "...", line N` and `file.py, line N` patterns
    # plus pytest's `>   line-of-code` markers for inline assertions
    file_matches = re.findall(
        r'File\s+"([^"]+)",\s*line\s*(\d+)',
        traceback,
    )

    # Fallback pattern: `at /path/to/file.py line N` (less formal)
    if not file_matches:
        file_matches = re.findall(
            r'(\S+\.py):(\d+)',
            traceback,
        )

    for file_path, line in file_matches:
        # Skip pytest infrastructure frames
        if any( infra in file_path for infra in _PYTEST_INFRA_FRAMES ):
            continue
        # Prefer frames inside src/ (project code) over library code
        return f"{file_path}:{line}"

    return _NO_FRAME_SENTINEL


def _compute_seed_key( failure: dict ) -> tuple[ str, str ]:
    """
    Compute the clustering seed key for a single failure.

    Requires:
        - failure is a dict with at least `classname` and `traceback` fields

    Ensures:
        - Returns a 2-tuple (normalized_classname, first_real_frame)
        - Both elements are non-None strings
    """
    classname = _normalize_classname( failure.get( "classname", "" ) )
    frame     = _extract_first_real_frame( failure.get( "traceback", "" ) )
    return ( classname, frame )


def _signature_from_key( key: tuple[ str, str ], sample_message: str = "" ) -> str:
    """
    Build a human-readable signature from a seed key.

    Requires:
        - key is a 2-tuple of (classname, frame)

    Ensures:
        - Returns a one-line summary suitable for UI + LLM prompts
    """
    classname, frame = key

    if frame == _NO_FRAME_SENTINEL:
        frame_desc = "(no source frame — likely collection or startup error)"
    else:
        frame_desc = f"at {frame}"

    if not classname:
        classname = "<unknown>"

    if sample_message:
        truncated = sample_message[ :80 ]
        return f"{classname} {frame_desc}: {truncated}"
    return f"{classname} {frame_desc}"


def _guess_affected_files(
    key: tuple[ str, str ],
    failures: list[ dict ],
    indices: list[ int ],
) -> list[ str ]:
    """
    Guess the affected source files from the classname + traceback frame.

    Requires:
        - key is a 2-tuple of (classname, frame)
        - failures is the full list of failure records
        - indices is the list of failure indices in this cluster

    Ensures:
        - Returns a deduped list of file paths:
          1. The file containing the test (derived from classname)
          2. The first non-pytest traceback frame file (from the key)
          3. Any other file paths extracted from the first failure's traceback
    """
    classname, frame = key
    files = []

    # 1. Derive test file from classname (`src.tests.unit.test_foo.TestClass` → `src/tests/unit/test_foo.py`)
    if classname and "." in classname:
        parts = classname.split( "." )
        # Drop the class name (last part) and convert module path to file path
        module_parts = parts[ :-1 ] if parts[ -1 ][ 0 ].isupper() else parts
        if module_parts:
            test_file = "/".join( module_parts ) + ".py"
            files.append( test_file )

    # 2. First non-pytest frame file (from key)
    if frame != _NO_FRAME_SENTINEL and ":" in frame:
        frame_file = frame.split( ":" )[ 0 ]
        if frame_file and frame_file not in files:
            files.append( frame_file )

    # 3. Any additional file paths in the first failure's traceback
    if indices:
        first_tb = failures[ indices[ 0 ] ].get( "traceback", "" )
        additional = re.findall( r'(\S+\.py):\d+', first_tb )
        for f in additional:
            if f not in files and not any( infra in f for infra in _PYTEST_INFRA_FRAMES ):
                files.append( f )

    return files[ :5 ]  # Cap at 5 to avoid noise


# ─────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────


def heuristic_seed( ctx: TestRemediationContext ) -> list[ FailureCluster ]:
    """
    Group failures by shared (classname, first_non_pytest_frame).

    Requires:
        - ctx is a valid TestRemediationContext (failures may be empty)

    Ensures:
        - Returns a list of FailureCluster, possibly empty if ctx.failures is empty
        - Every failure index from 0..N-1 appears in exactly one cluster
        - Clusters are ordered by first-appearance of their seed key (stable)
        - cluster_id is assigned sequentially: C1, C2, ...

    Args:
        ctx: TestRemediationContext with the flat failures list

    Returns:
        list[FailureCluster]: Ordered list of clusters covering all failures
    """
    if not ctx.failures:
        return []

    # Preserve first-appearance order of keys so cluster numbering is stable
    key_order: list[ tuple[ str, str ] ] = []
    key_to_indices: dict[ tuple[ str, str ], list[ int ] ] = {}

    for idx, failure in enumerate( ctx.failures ):
        key = _compute_seed_key( failure )
        if key not in key_to_indices:
            key_order.append( key )
            key_to_indices[ key ] = []
        key_to_indices[ key ].append( idx )

    clusters = []
    for i, key in enumerate( key_order, start=1 ):
        indices = key_to_indices[ key ]
        # Use the first failure's message as a sample for signature readability
        sample_msg = ctx.failures[ indices[ 0 ] ].get( "message", "" )
        cluster = FailureCluster(
            cluster_id              = f"C{i}",
            failure_indices         = indices,
            shared_error_signature  = _signature_from_key( key, sample_msg ),
            hypothesis              = "",
            affected_files_guess    = _guess_affected_files( key, ctx.failures, indices ),
            confidence              = 0.7,   # heuristic-only baseline
        )
        clusters.append( cluster )

    return clusters


async def llm_refine(
    ctx: TestRemediationContext,
    seed_clusters: list[ FailureCluster ],
    max_clusters: int = DEFAULT_MAX_CLUSTERS,
    refine_fn: Optional[ Callable ] = None,
) -> list[ FailureCluster ]:
    """
    Refine heuristic seed clusters, optionally via an LLM call.

    **Step 10 status**: If `refine_fn` is None (default), performs
    pure-Python cap enforcement: if the heuristic produced more than
    `max_clusters`, the smallest clusters are merged into a tail
    cluster labeled "mixed". The full LLM refinement wiring (real
    Claude Agent SDK call) lands when Phase 1 diagnose goes live —
    this module is already structured to plug it in via `refine_fn`.

    Requires:
        - ctx is a valid TestRemediationContext
        - seed_clusters is a list (possibly empty)
        - max_clusters is a positive int
        - refine_fn, if provided, is an async callable
          `(ctx, seed_clusters, max_clusters) -> list[FailureCluster]`
          that raises on error

    Ensures:
        - Returns between 0 and max_clusters clusters (0 iff input was empty)
        - Every failure index from the input seed clusters appears in exactly
          one output cluster
        - Falls back to cap-enforced seeds if refine_fn is None OR raises

    Args:
        ctx: Remediation context (passed through for refine_fn)
        seed_clusters: Heuristic seed clusters from `heuristic_seed`
        max_clusters: Upper bound K for output cluster count
        refine_fn: Optional async LLM-call function for real refinement

    Returns:
        list[FailureCluster]: Refined clusters (never exceeds max_clusters)
    """
    if not seed_clusters:
        return []

    if max_clusters < 1:
        max_clusters = 1

    # Try LLM refinement if a callback is provided
    if refine_fn is not None:
        try:
            refined = await refine_fn( ctx, seed_clusters, max_clusters )
            # Validate shape and index coverage; fall back on any issue
            if _validate_refined( refined, seed_clusters, max_clusters ):
                return refined
            logger.warning(
                "[TFE cluster] llm_refine returned invalid clusters — falling back to heuristic"
            )
        except Exception as e:
            logger.warning(
                f"[TFE cluster] llm_refine raised {type( e ).__name__}: {e} — falling back to heuristic"
            )

    # No refine_fn, or refine_fn failed/returned invalid — cap-enforce the seeds
    return _cap_enforce( seed_clusters, max_clusters )


def _cap_enforce(
    clusters: list[ FailureCluster ],
    max_clusters: int,
) -> list[ FailureCluster ]:
    """
    Consolidate excess clusters by merging the smallest ones.

    When the heuristic produces more than max_clusters clusters, the
    `max_clusters - 1` largest clusters are kept as-is, and the remainder
    are merged into a single "mixed" tail cluster.

    Requires:
        - clusters is a non-empty list
        - max_clusters is a positive int

    Ensures:
        - Returns at most max_clusters clusters
        - All failure indices from the input are preserved (no drops)
        - cluster_ids are re-sequenced C1, C2, ... in size-descending order
    """
    if len( clusters ) <= max_clusters:
        return clusters

    # Sort by size (descending), keep the largest (max_clusters - 1),
    # merge the rest into a tail cluster
    sorted_clusters = sorted(
        clusters, key=lambda c: len( c.failure_indices ), reverse=True
    )
    keep = sorted_clusters[ : max_clusters - 1 ]
    merge = sorted_clusters[ max_clusters - 1: ]

    # Build the tail cluster
    merged_indices = []
    merged_files = []
    for c in merge:
        merged_indices.extend( c.failure_indices )
        for f in c.affected_files_guess:
            if f not in merged_files:
                merged_files.append( f )

    tail = FailureCluster(
        cluster_id              = f"C{max_clusters}",
        failure_indices         = sorted( merged_indices ),
        shared_error_signature  = f"Mixed ({len( merge )} small clusters merged)",
        hypothesis              = "",
        affected_files_guess    = merged_files[ :5 ],
        confidence              = 0.4,   # lower because heterogeneous
    )

    # Re-sequence kept clusters' ids
    out = []
    for i, c in enumerate( keep, start=1 ):
        out.append( c.model_copy( update={ "cluster_id": f"C{i}" } ) )
    out.append( tail )

    return out


def _validate_refined(
    refined: list[ FailureCluster ],
    seed_clusters: list[ FailureCluster ],
    max_clusters: int,
) -> bool:
    """
    Validate that refined clusters preserve all seed failure indices.

    Ensures:
        - Returns True iff:
          * len(refined) is between 1 and max_clusters
          * Every failure index in the seeds appears in exactly one refined cluster
          * No duplicate indices across refined clusters
    """
    if not refined:
        return False
    if len( refined ) > max_clusters:
        return False

    all_seed_indices = set()
    for c in seed_clusters:
        all_seed_indices.update( c.failure_indices )

    all_refined_indices = []
    for c in refined:
        all_refined_indices.extend( c.failure_indices )

    if len( all_refined_indices ) != len( set( all_refined_indices ) ):
        return False   # duplicates across clusters

    if set( all_refined_indices ) != all_seed_indices:
        return False   # missing or extra indices

    return True


# ─────────────────────────────────────────────────────────────────────────
# Smoke test
# ─────────────────────────────────────────────────────────────────────────


def quick_smoke_test():
    """Quick smoke test for TFE cluster module."""
    from cosa.agents.test_fix_expediter.state import TestRemediationContext

    cu.print_banner( "TFE cluster Smoke Test", prepend_nl=True )

    try:
        # 1: Empty failures → empty clusters
        empty_ctx = TestRemediationContext(
            source_test_suite_job_id="ts-x", snapshot_path="p",
            snapshot={ "schema_version": "1.0" },
            suites_run=[], summary={ "all_passed": False },
            failures=[],
            original_test_types=[], user_id="u", user_email="e@e.com", session_id="s",
        )
        # snapshot_loader rejects empty failures, but cluster module should be robust
        assert heuristic_seed( empty_ctx ) == []
        print( "✓ Empty failures returns empty list" )

        # 2: Single failure → 1 cluster
        ctx1 = TestRemediationContext(
            source_test_suite_job_id="ts-x", snapshot_path="p",
            snapshot={ "schema_version": "1.0" },
            suites_run=[], summary={ "all_passed": False },
            failures=[
                {
                    "classname": "src.tests.unit.test_auth.TestLogin",
                    "name": "test_ok",
                    "traceback": 'File "src/cosa/auth/tokens.py", line 42, in refresh',
                    "message": "assert 401 == 200",
                }
            ],
            original_test_types=[], user_id="u", user_email="e@e.com", session_id="s",
        )
        clusters = heuristic_seed( ctx1 )
        assert len( clusters ) == 1
        assert clusters[ 0 ].cluster_id == "C1"
        assert clusters[ 0 ].failure_indices == [ 0 ]
        assert "src/cosa/auth/tokens.py" in clusters[ 0 ].affected_files_guess
        print( f"✓ Single failure → 1 cluster; files={clusters[ 0 ].affected_files_guess}" )

        # 3: Parametrized (same classname, different [param], same traceback frame) → 1 cluster
        ctx_param = TestRemediationContext(
            source_test_suite_job_id="ts-x", snapshot_path="p",
            snapshot={ "schema_version": "1.0" },
            suites_run=[], summary={ "all_passed": False },
            failures=[
                {
                    "classname": "src.tests.e2e.test_visual.TestVisualRegression",
                    "name": "test_visual_page[chromium-login]",
                    "traceback": 'File "src/tests/e2e/visual.py", line 88, in finalize',
                    "message": "Snapshots DO NOT match! login.png",
                },
                {
                    "classname": "src.tests.e2e.test_visual.TestVisualRegression",
                    "name": "test_visual_page[chromium-register]",
                    "traceback": 'File "src/tests/e2e/visual.py", line 88, in finalize',
                    "message": "Snapshots DO NOT match! register.png",
                },
            ],
            original_test_types=[], user_id="u", user_email="e@e.com", session_id="s",
        )
        clusters = heuristic_seed( ctx_param )
        assert len( clusters ) == 1
        assert sorted( clusters[ 0 ].failure_indices ) == [ 0, 1 ]
        print( "✓ Parametrized tests group into 1 cluster" )

        # 4: K different clusters
        ctx_k = TestRemediationContext(
            source_test_suite_job_id="ts-x", snapshot_path="p",
            snapshot={ "schema_version": "1.0" },
            suites_run=[], summary={ "all_passed": False },
            failures=[
                {
                    "classname": "src.tests.unit.test_auth.TestA",
                    "name": "t1", "message": "err1",
                    "traceback": 'File "src/cosa/auth/a.py", line 10, in f',
                },
                {
                    "classname": "src.tests.unit.test_queue.TestB",
                    "name": "t2", "message": "err2",
                    "traceback": 'File "src/cosa/rest/queue.py", line 20, in g',
                },
                {
                    "classname": "src.tests.unit.test_db.TestC",
                    "name": "t3", "message": "err3",
                    "traceback": 'File "src/cosa/db/c.py", line 30, in h',
                },
            ],
            original_test_types=[], user_id="u", user_email="e@e.com", session_id="s",
        )
        clusters = heuristic_seed( ctx_k )
        assert len( clusters ) == 3
        assert [ c.cluster_id for c in clusters ] == [ "C1", "C2", "C3" ]
        print( "✓ K=3 clusters from 3 distinct failures" )

        # 5: llm_refine stub path (no refine_fn) with cap enforcement
        import asyncio
        refined = asyncio.run( llm_refine( ctx_k, clusters, max_clusters=8 ) )
        assert len( refined ) == 3   # under cap, no consolidation
        print( "✓ llm_refine under cap returns seeds unchanged" )

        # 6: llm_refine cap enforcement (merge smallest)
        refined = asyncio.run( llm_refine( ctx_k, clusters, max_clusters=2 ) )
        assert len( refined ) == 2
        # All indices preserved
        all_indices = []
        for c in refined:
            all_indices.extend( c.failure_indices )
        assert sorted( all_indices ) == [ 0, 1, 2 ]
        # Last cluster is the "mixed" merge
        assert "Mixed" in refined[ -1 ].shared_error_signature
        print( "✓ llm_refine cap enforcement merges smallest clusters" )

        print( "\n✓ TFE cluster smoke test completed successfully" )

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
