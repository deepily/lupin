"""
Repair Attempt Tracker — Circuit breakers for the automated repair loop.

Tracks repair chains (original job → BFE → resubmit → ...) with:
- Iteration counting (max attempts per job)
- Cost budget tracking (cumulative API cost)
- Wall-clock timeout (elapsed since first failure)
- Semantic deduplication (Gister + embedding similarity)

Phase 6C of the Bug Fix Expediter pipeline.
"""

import threading
import time
from datetime import datetime
from typing import Optional

import numpy as np

import cosa.utils.util as cu


class RepairAttempt:
    """Record of a single repair attempt within a chain."""
    def __init__( self, attempt_number, bfe_job_id, fix_gist="", fix_gist_embedding=None,
                  cost_usd=0.0, outcome="pending" ):
        self.attempt_number     = attempt_number
        self.bfe_job_id         = bfe_job_id
        self.resubmitted_job_id = None
        self.fix_gist           = fix_gist
        self.fix_gist_embedding = fix_gist_embedding
        self.cost_usd           = cost_usd
        self.started_at         = datetime.now().isoformat()
        self.completed_at       = None
        self.outcome            = outcome   # pending | fixed | fix_failed | resubmit_failed | same_error | different_error | escalated

    def to_dict( self ):
        return {
            "attempt_number"     : self.attempt_number,
            "bfe_job_id"         : self.bfe_job_id,
            "resubmitted_job_id" : self.resubmitted_job_id,
            "fix_gist"           : self.fix_gist,
            "cost_usd"           : self.cost_usd,
            "started_at"         : self.started_at,
            "completed_at"       : self.completed_at,
            "outcome"            : self.outcome,
        }


class RepairChain:
    """Tracks all attempts for a single failed job."""
    def __init__( self, original_job_id, max_attempts=3, max_cost_usd=10.0, max_wall_clock_seconds=1800 ):
        self.original_job_id       = original_job_id
        self.max_attempts          = max_attempts
        self.max_cost_usd          = max_cost_usd
        self.max_wall_clock_seconds = max_wall_clock_seconds
        self.first_failure_time    = time.time()
        self.attempts              = []

    @property
    def attempt_count( self ):
        return len( self.attempts )

    @property
    def cumulative_cost( self ):
        return sum( a.cost_usd for a in self.attempts )

    @property
    def elapsed_seconds( self ):
        return time.time() - self.first_failure_time

    def can_attempt( self ) -> tuple:
        """
        Check if another repair attempt is allowed.

        Returns:
            tuple: (allowed: bool, reason: str)
        """
        if self.attempt_count >= self.max_attempts:
            return False, f"Max attempts ({self.max_attempts}) exhausted"

        if self.cumulative_cost >= self.max_cost_usd:
            return False, f"Cost budget (${self.max_cost_usd:.2f}) exceeded: ${self.cumulative_cost:.2f}"

        if self.elapsed_seconds >= self.max_wall_clock_seconds:
            return False, f"Wall-clock timeout ({self.max_wall_clock_seconds}s) exceeded: {self.elapsed_seconds:.0f}s"

        return True, "OK"

    def add_attempt( self, bfe_job_id ) -> RepairAttempt:
        """Record a new attempt."""
        attempt = RepairAttempt(
            attempt_number = self.attempt_count + 1,
            bfe_job_id     = bfe_job_id,
        )
        self.attempts.append( attempt )
        return attempt

    def get_latest_attempt( self ) -> Optional[ RepairAttempt ]:
        """Get the most recent attempt, or None."""
        return self.attempts[ -1 ] if self.attempts else None

    def to_dict( self ):
        return {
            "original_job_id"  : self.original_job_id,
            "attempt_count"    : self.attempt_count,
            "cumulative_cost"  : self.cumulative_cost,
            "elapsed_seconds"  : self.elapsed_seconds,
            "max_attempts"     : self.max_attempts,
            "max_cost_usd"     : self.max_cost_usd,
            "first_failure_time": self.first_failure_time,
            "attempts"         : [ a.to_dict() for a in self.attempts ],
        }


# ---------------------------------------------------------------------------
# Semantic Deduplication
# ---------------------------------------------------------------------------

def cosine_similarity( vec_a, vec_b ) -> float:
    """
    Compute cosine similarity between two vectors.

    Requires:
        - vec_a and vec_b are non-empty numeric sequences of equal length

    Ensures:
        - Returns float in [-1.0, 1.0]
        - Returns 0.0 if either vector is zero-length or all zeros

    Args:
        vec_a: First embedding vector
        vec_b: Second embedding vector

    Returns:
        float: Cosine similarity
    """
    a = np.array( vec_a, dtype=np.float32 )
    b = np.array( vec_b, dtype=np.float32 )

    norm_a = np.linalg.norm( a )
    norm_b = np.linalg.norm( b )

    if norm_a == 0 or norm_b == 0:
        return 0.0

    return float( np.dot( a, b ) / ( norm_a * norm_b ) )


def is_semantically_duplicate( new_gist_embedding, prior_attempts, threshold=0.92 ) -> tuple:
    """
    Check if a new fix gist is semantically equivalent to any prior attempt.

    Requires:
        - new_gist_embedding is a list of floats (embedding vector)
        - prior_attempts is a list of RepairAttempt objects

    Ensures:
        - Returns (is_duplicate: bool, max_similarity: float, matching_attempt: int or None)
        - Only compares against attempts that have embeddings

    Args:
        new_gist_embedding: Embedding of the new fix gist
        prior_attempts: List of prior RepairAttempt objects
        threshold: Cosine similarity threshold for duplicate detection

    Returns:
        tuple: (is_duplicate, max_similarity, matching_attempt_number)
    """
    if new_gist_embedding is None or len( new_gist_embedding ) == 0:
        return False, 0.0, None

    max_sim     = 0.0
    match_num   = None

    for attempt in prior_attempts:
        if attempt.fix_gist_embedding is None:
            continue
        sim = cosine_similarity( new_gist_embedding, attempt.fix_gist_embedding )
        if sim > max_sim:
            max_sim   = sim
            match_num = attempt.attempt_number

    is_dup = max_sim >= threshold
    return is_dup, max_sim, match_num


# ---------------------------------------------------------------------------
# Tracker Singleton
# ---------------------------------------------------------------------------

class RepairAttemptTracker:
    """
    Tracks repair chains across the system.

    Thread-safe in-memory storage with optional DB persistence.
    Provides circuit breaker checks (attempts, cost, wall-clock, semantic dedup).

    Requires:
        - config_mgr is an initialized ConfigurationManager

    Ensures:
        - get_or_create_chain() is thread-safe
        - Circuit breaker checks are atomic per chain
    """

    def __init__( self, config_mgr, debug=False ):
        self.config_mgr = config_mgr
        self.debug      = debug
        self._chains    = {}  # { original_job_id: RepairChain }
        self._lock      = threading.Lock()

        # Load config
        self.max_attempts   = config_mgr.get( "auto fix max attempts per job", default=3, return_type="int" )
        self.max_cost_usd   = config_mgr.get( "auto fix max cost usd", default=10.0, return_type="float" )
        self.max_wall_clock = config_mgr.get( "auto fix max wall clock seconds", default=1800, return_type="int" )

    def get_or_create_chain( self, original_job_id: str ) -> RepairChain:
        """Get existing chain or create new one. Thread-safe."""
        with self._lock:
            if original_job_id not in self._chains:
                self._chains[ original_job_id ] = RepairChain(
                    original_job_id,
                    max_attempts          = self.max_attempts,
                    max_cost_usd          = self.max_cost_usd,
                    max_wall_clock_seconds = self.max_wall_clock,
                )
            return self._chains[ original_job_id ]

    def can_attempt( self, original_job_id: str ) -> tuple:
        """Check if another attempt is allowed for this job."""
        chain = self.get_or_create_chain( original_job_id )
        return chain.can_attempt()

    def record_attempt( self, original_job_id: str, bfe_job_id: str ) -> RepairAttempt:
        """Record a new attempt in the chain."""
        chain = self.get_or_create_chain( original_job_id )
        attempt = chain.add_attempt( bfe_job_id )
        if self.debug:
            print( f"[RepairTracker] Attempt {attempt.attempt_number} for {original_job_id}: BFE={bfe_job_id}" )
        return attempt

    def update_attempt( self, original_job_id: str, cost_usd: float = 0.0,
                        outcome: str = "pending", resubmitted_job_id: str = None,
                        fix_gist: str = "", fix_gist_embedding=None ):
        """Update the latest attempt in a chain with results."""
        chain   = self.get_or_create_chain( original_job_id )
        attempt = chain.get_latest_attempt()
        if attempt is None:
            return

        attempt.cost_usd           = cost_usd
        attempt.outcome            = outcome
        attempt.completed_at       = datetime.now().isoformat()
        attempt.resubmitted_job_id = resubmitted_job_id
        attempt.fix_gist           = fix_gist
        attempt.fix_gist_embedding = fix_gist_embedding

    def check_semantic_dedup( self, original_job_id: str, new_gist_embedding, threshold=0.92 ) -> tuple:
        """
        Check if a new fix is semantically duplicate of prior attempts.

        Args:
            original_job_id: The original failed job
            new_gist_embedding: Embedding of the new fix gist
            threshold: Cosine similarity threshold

        Returns:
            tuple: (is_duplicate, max_similarity, matching_attempt_number)
        """
        chain = self.get_or_create_chain( original_job_id )
        return is_semantically_duplicate( new_gist_embedding, chain.attempts, threshold )

    def get_chain_summary( self, original_job_id: str ) -> Optional[ dict ]:
        """Get chain summary dict, or None if no chain exists."""
        with self._lock:
            chain = self._chains.get( original_job_id )
            if chain is None:
                return None
            return chain.to_dict()


# ---------------------------------------------------------------------------
# Module singleton
# ---------------------------------------------------------------------------

_tracker_instance: Optional[ RepairAttemptTracker ] = None


def init_tracker( config_mgr, debug=False ) -> RepairAttemptTracker:
    """Initialize the global tracker singleton."""
    global _tracker_instance
    _tracker_instance = RepairAttemptTracker( config_mgr, debug=debug )
    print( f"[RepairTracker] Initialized (max_attempts={_tracker_instance.max_attempts}, "
           f"max_cost=${_tracker_instance.max_cost_usd:.2f}, "
           f"max_wall_clock={_tracker_instance.max_wall_clock}s)" )
    return _tracker_instance


def get_tracker() -> Optional[ RepairAttemptTracker ]:
    """Get the global tracker instance."""
    return _tracker_instance


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

def quick_smoke_test():
    """Quick smoke test for RepairAttemptTracker."""
    cu.print_banner( "Repair Attempt Tracker Smoke Test", prepend_nl=True )

    try:
        # 1: RepairChain basics
        chain = RepairChain( "test-job-1", max_attempts=3, max_cost_usd=10.0, max_wall_clock_seconds=1800 )
        assert chain.attempt_count == 0
        assert chain.cumulative_cost == 0.0
        ok, _ = chain.can_attempt()
        assert ok
        print( "✓ RepairChain: empty chain allows attempts" )

        # 2: Add attempts
        a1 = chain.add_attempt( "bfe-001" )
        assert a1.attempt_number == 1
        a2 = chain.add_attempt( "bfe-002" )
        assert a2.attempt_number == 2
        assert chain.attempt_count == 2
        print( "✓ RepairChain: attempt counting works" )

        # 3: Max attempts
        chain.add_attempt( "bfe-003" )
        ok, reason = chain.can_attempt()
        assert not ok
        assert "max attempts" in reason.lower()
        print( "✓ RepairChain: max attempts enforced" )

        # 4: Cost budget
        chain2 = RepairChain( "test-job-2", max_attempts=10, max_cost_usd=5.0 )
        a = chain2.add_attempt( "bfe-010" )
        a.cost_usd = 3.0
        b = chain2.add_attempt( "bfe-011" )
        b.cost_usd = 2.5
        ok, reason = chain2.can_attempt()
        assert not ok
        assert "cost budget" in reason.lower()
        print( "✓ RepairChain: cost budget enforced" )

        # 5: Wall-clock timeout
        chain3 = RepairChain( "test-job-3", max_wall_clock_seconds=0 )
        ok, reason = chain3.can_attempt()
        assert not ok
        assert "wall-clock" in reason.lower()
        print( "✓ RepairChain: wall-clock timeout enforced" )

        # 6: Cosine similarity
        vec_a = [ 1.0, 0.0, 0.0 ]
        vec_b = [ 1.0, 0.0, 0.0 ]
        assert abs( cosine_similarity( vec_a, vec_b ) - 1.0 ) < 0.001
        print( "✓ cosine_similarity: identical vectors = 1.0" )

        vec_c = [ 0.0, 1.0, 0.0 ]
        assert abs( cosine_similarity( vec_a, vec_c ) ) < 0.001
        print( "✓ cosine_similarity: orthogonal vectors = 0.0" )

        vec_d = [ 0.0, 0.0, 0.0 ]
        assert cosine_similarity( vec_a, vec_d ) == 0.0
        print( "✓ cosine_similarity: zero vector = 0.0" )

        # 7: Semantic deduplication
        attempt1 = RepairAttempt( 1, "bfe-100" )
        attempt1.fix_gist_embedding = [ 1.0, 0.0, 0.0 ]

        # Same direction = duplicate
        is_dup, sim, match = is_semantically_duplicate( [ 1.0, 0.01, 0.0 ], [ attempt1 ], threshold=0.92 )
        assert is_dup, f"Should be duplicate (sim={sim})"
        assert match == 1
        print( "✓ is_semantically_duplicate: near-identical vectors detected" )

        # Different direction = not duplicate
        is_dup, sim, match = is_semantically_duplicate( [ 0.0, 1.0, 0.0 ], [ attempt1 ], threshold=0.92 )
        assert not is_dup, f"Should NOT be duplicate (sim={sim})"
        print( "✓ is_semantically_duplicate: orthogonal vectors pass through" )

        # No embedding = not duplicate
        is_dup, sim, match = is_semantically_duplicate( None, [ attempt1 ], threshold=0.92 )
        assert not is_dup
        print( "✓ is_semantically_duplicate: None embedding = not duplicate" )

        # 8: Tracker
        class MockCfg:
            def get( self, key, default=None, return_type=None ):
                vals = { "auto fix max attempts per job": 3, "auto fix max cost usd": 10.0, "auto fix max wall clock seconds": 1800 }
                val = vals.get( key, default )
                if return_type == "int":   return int( val )
                if return_type == "float": return float( val )
                return val

        tracker = RepairAttemptTracker( MockCfg(), debug=True )

        ok, _ = tracker.can_attempt( "job-A" )
        assert ok
        tracker.record_attempt( "job-A", "bfe-A1" )
        tracker.update_attempt( "job-A", cost_usd=2.5, outcome="fix_failed" )
        summary = tracker.get_chain_summary( "job-A" )
        assert summary[ "attempt_count" ] == 1
        assert summary[ "cumulative_cost" ] == 2.5
        print( "✓ RepairAttemptTracker: record + update + summary works" )

        # Semantic dedup via tracker
        tracker.update_attempt( "job-A", fix_gist_embedding=[ 1.0, 0.0, 0.0 ] )
        is_dup, sim, match = tracker.check_semantic_dedup( "job-A", [ 1.0, 0.01, 0.0 ] )
        assert is_dup
        print( "✓ RepairAttemptTracker: semantic dedup works" )

        print( "\n✓ Repair Attempt Tracker smoke test completed successfully" )

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
