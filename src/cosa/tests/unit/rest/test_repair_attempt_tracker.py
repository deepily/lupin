"""
Unit tests for the repair-loop circuit breakers (cosa.rest.repair_attempt_tracker).

Covers RepairAttempt, RepairChain (all can_attempt circuit-breaker arms +
properties + helpers), cosine_similarity (identical / orthogonal / zero-vector),
is_semantically_duplicate (none / empty / missing-embedding skip / dup / non-dup),
RepairAttemptTracker (create/reuse chain, record, update incl. no-attempt
early-return, semantic dedup, summary), and the init_tracker / get_tracker module
singleton — to genuine 100% line + branch + function.

Pure-logic module (numpy + threading + datetime); ZERO external services.
"""

import unittest
from unittest.mock import patch

from cosa.rest import repair_attempt_tracker as rat
from cosa.rest.repair_attempt_tracker import (
    RepairAttempt,
    RepairChain,
    RepairAttemptTracker,
    cosine_similarity,
    is_semantically_duplicate,
    init_tracker,
    get_tracker,
)


class _MockCfg:
    """ConfigurationManager stand-in returning the three auto-fix keys."""
    def get( self, key, default=None, return_type=None ):
        vals = {
            "auto fix max attempts per job"   : 3,
            "auto fix max cost usd"           : 10.0,
            "auto fix max wall clock seconds" : 1800,
        }
        val = vals.get( key, default )
        if return_type == "int":   return int( val )
        if return_type == "float": return float( val )
        return val


class TestRepairAttempt( unittest.TestCase ):
    def test_defaults_and_to_dict( self ):
        a = RepairAttempt( attempt_number=1, bfe_job_id="bfe-1" )
        self.assertEqual( a.attempt_number, 1 )
        self.assertEqual( a.outcome, "pending" )
        self.assertIsNone( a.resubmitted_job_id )
        self.assertIsNotNone( a.started_at )
        d = a.to_dict()
        self.assertEqual( d[ "bfe_job_id" ], "bfe-1" )
        self.assertEqual( d[ "outcome" ], "pending" )
        self.assertIn( "started_at", d )


class TestRepairChain( unittest.TestCase ):
    def test_empty_chain_allows_attempt( self ):
        chain = RepairChain( "job-1" )
        self.assertEqual( chain.attempt_count, 0 )
        self.assertEqual( chain.cumulative_cost, 0.0 )
        ok, reason = chain.can_attempt()
        self.assertTrue( ok )
        self.assertEqual( reason, "OK" )

    def test_add_attempt_increments( self ):
        chain = RepairChain( "job-1" )
        a1 = chain.add_attempt( "bfe-1" )
        a2 = chain.add_attempt( "bfe-2" )
        self.assertEqual( a1.attempt_number, 1 )
        self.assertEqual( a2.attempt_number, 2 )
        self.assertEqual( chain.attempt_count, 2 )

    def test_max_attempts_breaker( self ):
        chain = RepairChain( "job-1", max_attempts=2 )
        chain.add_attempt( "b1" )
        chain.add_attempt( "b2" )
        ok, reason = chain.can_attempt()
        self.assertFalse( ok )
        self.assertIn( "Max attempts", reason )

    def test_cost_budget_breaker( self ):
        chain = RepairChain( "job-1", max_attempts=10, max_cost_usd=5.0 )
        a = chain.add_attempt( "b1" ); a.cost_usd = 3.0
        b = chain.add_attempt( "b2" ); b.cost_usd = 2.5
        self.assertAlmostEqual( chain.cumulative_cost, 5.5 )
        ok, reason = chain.can_attempt()
        self.assertFalse( ok )
        self.assertIn( "Cost budget", reason )

    def test_wall_clock_breaker( self ):
        chain = RepairChain( "job-1", max_wall_clock_seconds=0 )
        # 0 attempts, 0 cost → passes those, hits the wall-clock arm (elapsed >= 0)
        ok, reason = chain.can_attempt()
        self.assertFalse( ok )
        self.assertIn( "Wall-clock", reason )

    def test_get_latest_attempt_none_then_some( self ):
        chain = RepairChain( "job-1" )
        self.assertIsNone( chain.get_latest_attempt() )
        chain.add_attempt( "b1" )
        self.assertEqual( chain.get_latest_attempt().bfe_job_id, "b1" )

    def test_to_dict_includes_attempts( self ):
        chain = RepairChain( "job-1" )
        chain.add_attempt( "b1" )
        d = chain.to_dict()
        self.assertEqual( d[ "original_job_id" ], "job-1" )
        self.assertEqual( d[ "attempt_count" ], 1 )
        self.assertEqual( len( d[ "attempts" ] ), 1 )
        self.assertIn( "elapsed_seconds", d )


class TestCosineSimilarity( unittest.TestCase ):
    def test_identical_vectors( self ):
        self.assertAlmostEqual( cosine_similarity( [ 1.0, 0.0, 0.0 ], [ 1.0, 0.0, 0.0 ] ), 1.0, places=4 )

    def test_orthogonal_vectors( self ):
        self.assertAlmostEqual( cosine_similarity( [ 1.0, 0.0, 0.0 ], [ 0.0, 1.0, 0.0 ] ), 0.0, places=4 )

    def test_first_vector_zero_returns_zero( self ):
        self.assertEqual( cosine_similarity( [ 0.0, 0.0, 0.0 ], [ 1.0, 0.0, 0.0 ] ), 0.0 )

    def test_second_vector_zero_returns_zero( self ):
        self.assertEqual( cosine_similarity( [ 1.0, 0.0, 0.0 ], [ 0.0, 0.0, 0.0 ] ), 0.0 )


class TestIsSemanticallyDuplicate( unittest.TestCase ):
    def test_none_embedding_not_duplicate( self ):
        self.assertEqual( is_semantically_duplicate( None, [] ), ( False, 0.0, None ) )

    def test_empty_embedding_not_duplicate( self ):
        self.assertEqual( is_semantically_duplicate( [], [] ), ( False, 0.0, None ) )

    def test_skips_attempts_without_embeddings( self ):
        a = RepairAttempt( 1, "b1" )   # fix_gist_embedding defaults to None → skipped
        is_dup, sim, match = is_semantically_duplicate( [ 1.0, 0.0, 0.0 ], [ a ], threshold=0.92 )
        self.assertFalse( is_dup )
        self.assertEqual( sim, 0.0 )
        self.assertIsNone( match )

    def test_duplicate_above_threshold( self ):
        a = RepairAttempt( 1, "b1" ); a.fix_gist_embedding = [ 1.0, 0.0, 0.0 ]
        is_dup, sim, match = is_semantically_duplicate( [ 1.0, 0.01, 0.0 ], [ a ], threshold=0.92 )
        self.assertTrue( is_dup )
        self.assertEqual( match, 1 )

    def test_not_duplicate_below_threshold( self ):
        a = RepairAttempt( 1, "b1" ); a.fix_gist_embedding = [ 1.0, 0.0, 0.0 ]
        is_dup, sim, match = is_semantically_duplicate( [ 0.0, 1.0, 0.0 ], [ a ], threshold=0.92 )
        self.assertFalse( is_dup )
        # sim (0.0) never exceeds the initial max_sim (0.0) → no match recorded
        self.assertIsNone( match )


class TestRepairAttemptTracker( unittest.TestCase ):
    def test_init_loads_config( self ):
        t = RepairAttemptTracker( _MockCfg() )
        self.assertEqual( t.max_attempts, 3 )
        self.assertEqual( t.max_cost_usd, 10.0 )
        self.assertEqual( t.max_wall_clock, 1800 )

    def test_get_or_create_chain_creates_then_reuses( self ):
        t = RepairAttemptTracker( _MockCfg() )
        c1 = t.get_or_create_chain( "job-A" )
        c2 = t.get_or_create_chain( "job-A" )   # reuse branch
        self.assertIs( c1, c2 )

    def test_can_attempt_delegates( self ):
        t = RepairAttemptTracker( _MockCfg() )
        ok, _ = t.can_attempt( "job-A" )
        self.assertTrue( ok )

    def test_record_attempt_debug_on( self ):
        t = RepairAttemptTracker( _MockCfg(), debug=True )
        with patch( "builtins.print" ) as mp:
            attempt = t.record_attempt( "job-A", "bfe-1" )
        self.assertEqual( attempt.attempt_number, 1 )
        self.assertTrue( any( "RepairTracker" in str( c ) for c in mp.call_args_list ) )

    def test_record_attempt_debug_off( self ):
        t = RepairAttemptTracker( _MockCfg(), debug=False )
        attempt = t.record_attempt( "job-A", "bfe-1" )
        self.assertEqual( attempt.attempt_number, 1 )

    def test_update_attempt_no_attempt_is_noop( self ):
        t = RepairAttemptTracker( _MockCfg() )
        # update_attempt creates the chain, but it has no attempts yet →
        # get_latest_attempt() returns None → the early-return branch is taken.
        t.update_attempt( "job-A", cost_usd=5.0 )   # must not raise
        summary = t.get_chain_summary( "job-A" )
        self.assertEqual( summary[ "attempt_count" ], 0 )
        self.assertEqual( summary[ "attempts" ], [] )

    def test_update_attempt_populates_latest( self ):
        t = RepairAttemptTracker( _MockCfg() )
        t.record_attempt( "job-A", "bfe-1" )
        t.update_attempt( "job-A", cost_usd=2.5, outcome="fix_failed", resubmitted_job_id="r1", fix_gist="g" )
        summary = t.get_chain_summary( "job-A" )
        self.assertEqual( summary[ "attempt_count" ], 1 )
        self.assertEqual( summary[ "cumulative_cost" ], 2.5 )
        self.assertEqual( summary[ "attempts" ][ 0 ][ "outcome" ], "fix_failed" )

    def test_check_semantic_dedup( self ):
        t = RepairAttemptTracker( _MockCfg() )
        t.record_attempt( "job-A", "bfe-1" )
        t.update_attempt( "job-A", fix_gist_embedding=[ 1.0, 0.0, 0.0 ] )
        is_dup, sim, match = t.check_semantic_dedup( "job-A", [ 1.0, 0.01, 0.0 ] )
        self.assertTrue( is_dup )

    def test_get_chain_summary_none_for_unknown( self ):
        t = RepairAttemptTracker( _MockCfg() )
        self.assertIsNone( t.get_chain_summary( "no-such-job" ) )


class TestModuleSingleton( unittest.TestCase ):
    """Validate init_tracker / get_tracker against the module global."""

    def setUp( self ):
        self._saved = rat._tracker_instance

    def tearDown( self ):
        rat._tracker_instance = self._saved

    def test_get_tracker_none_before_init( self ):
        rat._tracker_instance = None
        self.assertIsNone( get_tracker() )

    def test_init_tracker_sets_and_returns_singleton( self ):
        with patch( "builtins.print" ):
            t = init_tracker( _MockCfg(), debug=False )
        self.assertIsInstance( t, RepairAttemptTracker )
        self.assertIs( get_tracker(), t )


def isolated_unit_test():
    """
    Run the repair_attempt_tracker unit tests in isolation.

    Ensures:
        - Returns (success, duration, message) for the smoke-runner harness
    """
    import time
    start_time = time.time()
    suite = unittest.TestLoader().loadTestsFromModule( __import__( __name__ ) )
    result = unittest.TextTestRunner( verbosity=2 ).run( suite )
    duration = time.time() - start_time
    success = result.wasSuccessful()
    message = f"{result.testsRun} run, {len( result.failures )} failed, {len( result.errors )} errors"
    return success, duration, message


if __name__ == "__main__":
    ok, secs, msg = isolated_unit_test()
    print( f"\n{'✅ PASS' if ok else '❌ FAIL'} repair_attempt_tracker tests in {secs:.3f}s — {msg}" )
