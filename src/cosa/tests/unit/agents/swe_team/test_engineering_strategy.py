"""
Unit tests for swe_team/proxy/engineering_strategy.py — EngineeringStrategy:
  the full classify → gate → decide → evaluate pipeline, Thompson Sampling,
  conformal deferral, CBR shadow prediction, and ICRL fallback.

Collaborators (TrustTracker, CircuitBreaker, ConformalDecisionWrapper, classifier,
cbr_store, embedding_provider, llm_client) are mocked at the boundary. scipy's
beta_dist is patched for deterministic sampling/CDF — NO Monte-Carlo nondeterminism,
NO LLM/SDK/network.

Created 2026-05-31 by Extra 1 🪨 (CoSA coverage campaign, swe_team lane, complex tier).
"""

import io
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import cosa.agents.swe_team.proxy.engineering_strategy as es
from cosa.agents.swe_team.proxy.engineering_strategy import EngineeringStrategy


def _mk_strategy( **overrides ):
    """Build an EngineeringStrategy with mocked trust_tracker + circuit_breaker."""
    tt = MagicMock()
    tt.categories = {}
    cb = MagicMock()
    cb.check.return_value = True            # closed breaker by default
    kwargs = dict( trust_tracker=tt, circuit_breaker=cb, debug=False )
    kwargs.update( overrides )
    strat = EngineeringStrategy( **kwargs )
    return strat, tt, cb


class TestInit( unittest.TestCase ):

    def test_creates_default_collaborators_when_none( self ):
        # trust_tracker + circuit_breaker None → real instances created;
        # accepted_senders None → DEFAULT_ACCEPTED_SENDERS; cbr threshold default.
        with patch.object( es, "TrustTracker" ) as TT, \
             patch.object( es, "CircuitBreaker" ) as CB:
            TT.return_value.register_category = MagicMock()
            strat = EngineeringStrategy()
        self.assertEqual( strat.accepted_senders, es.DEFAULT_ACCEPTED_SENDERS )
        self.assertEqual( strat.cbr_confidence_threshold, es.DEFAULT_CBR_CONFIDENCE_THRESHOLD )
        TT.assert_called_once()
        CB.assert_called_once()
        # All 6 categories registered.
        self.assertEqual( TT.return_value.register_category.call_count, 6 )

    def test_explicit_senders_and_threshold( self ):
        strat, _, _ = _mk_strategy( accepted_senders=[ "a@x" ], cbr_confidence_threshold=0.42 )
        self.assertEqual( strat.accepted_senders, [ "a@x" ] )
        self.assertEqual( strat.cbr_confidence_threshold, 0.42 )

    def test_name_and_available_properties( self ):
        strat, _, _ = _mk_strategy()
        self.assertEqual( strat.name, "swe_engineering" )
        self.assertTrue( strat.available )


class TestCanHandle( unittest.TestCase ):

    def setUp( self ):
        self.strat, _, _ = _mk_strategy( accepted_senders=[ "swe.lead@x" ] )

    def test_accepted_sender( self ):
        self.assertTrue( self.strat.can_handle( { "sender_id": "swe.lead@x" } ) )

    def test_rejected_sender( self ):
        self.assertFalse( self.strat.can_handle( { "sender_id": "evil@x" } ) )

    def test_no_sender_id_allows( self ):
        self.assertTrue( self.strat.can_handle( { } ) )

    def test_non_dict_item_allows( self ):
        self.assertTrue( self.strat.can_handle( "not-a-dict" ) )


class TestClassify( unittest.TestCase ):

    def test_delegates_and_records_confidence( self ):
        strat, tt, cb = _mk_strategy()
        strat.classifier = MagicMock()
        strat.classifier.classify.return_value = ( "testing", 0.8 )
        cat, conf = strat.classify( "run tests", sender_id="swe.tester@x" )
        self.assertEqual( ( cat, conf ), ( "testing", 0.8 ) )
        cb.record_confidence.assert_called_once_with( "testing", 0.8 )


class TestGate( unittest.TestCase ):

    def test_circuit_breaker_tripped_defers( self ):
        strat, tt, cb = _mk_strategy( debug=True )
        cb.check.return_value = False
        buf = io.StringIO()
        with redirect_stdout( buf ):
            self.assertEqual( strat.gate( "deploy", 5, 0.9 ), "defer" )
        self.assertIn( "Circuit breaker tripped", buf.getvalue() )

    def test_shadow_mode_always_shadow( self ):
        strat, _, _ = _mk_strategy( trust_mode="shadow" )
        self.assertEqual( strat.gate( "testing", 5, 0.9 ), "shadow" )

    def test_suggest_mode_l2_plus_and_l1( self ):
        strat, _, _ = _mk_strategy( trust_mode="suggest" )
        self.assertEqual( strat.gate( "testing", 2, 0.9 ), "suggest" )
        self.assertEqual( strat.gate( "testing", 1, 0.9 ), "shadow" )

    def test_active_mode_gating_levels( self ):
        strat, _, _ = _mk_strategy( trust_mode="active" )
        self.assertEqual( strat.gate( "testing", 1, 0.9 ), "shadow" )
        self.assertEqual( strat.gate( "testing", 2, 0.9 ), "suggest" )
        self.assertEqual( strat.gate( "testing", 4, 0.9 ), "act" )

    def test_thompson_delegation( self ):
        strat, _, _ = _mk_strategy( trust_mode="active", thompson_enabled=True )
        with patch.object( strat, "_gate_thompson", return_value="act" ) as m:
            self.assertEqual( strat.gate( "testing", 3, 0.9 ), "act" )
        m.assert_called_once_with( "testing" )

    # --- conformal arcs ------------------------------------------------------

    def _cat_with_blr( self, prob=0.5 ):
        blr = MagicMock()
        blr._feature_sum   = 4.0
        blr._feature_count = 2.0
        blr.predict.return_value = ( prob, None )
        return SimpleNamespace( _blr_model=blr )

    def test_conformal_defer_when_should_defer( self ):
        strat, tt, _ = _mk_strategy( trust_mode="active", conformal_enabled=True, debug=True )
        tt.categories = { "testing": self._cat_with_blr( prob=0.4 ) }
        wrapper = MagicMock( is_calibrated=True )
        wrapper.should_defer.return_value = True
        with patch.object( strat, "_get_conformal_wrapper", return_value=wrapper ):
            buf = io.StringIO()
            with redirect_stdout( buf ):
                self.assertEqual( strat.gate( "testing", 3, 0.9 ), "defer" )
        self.assertIn( "Conformal defer", buf.getvalue() )

    def test_conformal_not_calibrated_falls_through( self ):
        strat, tt, _ = _mk_strategy( trust_mode="active", conformal_enabled=True )
        wrapper = MagicMock( is_calibrated=False )
        with patch.object( strat, "_get_conformal_wrapper", return_value=wrapper ):
            self.assertEqual( strat.gate( "testing", 4, 0.9 ), "act" )

    def test_conformal_calibrated_but_cat_missing_falls_through( self ):
        strat, tt, _ = _mk_strategy( trust_mode="active", conformal_enabled=True )
        tt.categories = {}   # cat is None
        wrapper = MagicMock( is_calibrated=True )
        with patch.object( strat, "_get_conformal_wrapper", return_value=wrapper ):
            self.assertEqual( strat.gate( "testing", 4, 0.9 ), "act" )

    def test_conformal_calibrated_no_blr_falls_through( self ):
        strat, tt, _ = _mk_strategy( trust_mode="active", conformal_enabled=True )
        tt.categories = { "testing": SimpleNamespace( _blr_model=None ) }
        wrapper = MagicMock( is_calibrated=True )
        with patch.object( strat, "_get_conformal_wrapper", return_value=wrapper ):
            self.assertEqual( strat.gate( "testing", 4, 0.9 ), "act" )

    def test_conformal_should_not_defer_falls_through( self ):
        strat, tt, _ = _mk_strategy( trust_mode="active", conformal_enabled=True )
        tt.categories = { "testing": self._cat_with_blr( prob=0.95 ) }
        wrapper = MagicMock( is_calibrated=True )
        wrapper.should_defer.return_value = False
        with patch.object( strat, "_get_conformal_wrapper", return_value=wrapper ):
            self.assertEqual( strat.gate( "testing", 4, 0.9 ), "act" )


class TestDecide( unittest.TestCase ):

    def test_high_risk_requires_review( self ):
        strat, _, _ = _mk_strategy()
        strat._get_cbr_prediction = MagicMock( return_value=None )
        self.assertEqual( strat.decide( "deploy now", "deployment" ), "requires_review" )

    def test_low_risk_approved( self ):
        strat, _, _ = _mk_strategy()
        strat._get_cbr_prediction = MagicMock( return_value=None )
        self.assertEqual( strat.decide( "add a test", "testing" ), "approved" )

    def test_cbr_shadow_agree_disagree_debug( self ):
        strat, _, _ = _mk_strategy( debug=True )
        pred = SimpleNamespace( verdict="approved", confidence=0.9, case_count=3,
                                similar_cases=[] )
        strat._get_cbr_prediction = MagicMock( return_value=pred )
        buf = io.StringIO()
        with redirect_stdout( buf ):
            out = strat.decide( "add a test", "testing" )   # heuristic approved → AGREE
        self.assertEqual( out, "approved" )
        self.assertIn( "AGREE", buf.getvalue() )

    def test_icrl_override_returns_value( self ):
        strat, _, _ = _mk_strategy( debug=True, icrl_enabled=True,
                                    llm_client=MagicMock(), cbr_confidence_threshold=0.8 )
        pred = SimpleNamespace( verdict="approved", confidence=0.3, case_count=2,
                                similar_cases=[ { "decision_value": "a" }, { "decision_value": "b" } ] )
        strat._get_cbr_prediction = MagicMock( return_value=pred )
        strat._get_icrl_decision = MagicMock( return_value="requires_review" )
        buf = io.StringIO()
        with redirect_stdout( buf ):
            out = strat.decide( "ambiguous", "testing" )
        self.assertEqual( out, "requires_review" )
        self.assertIn( "ICRL override", buf.getvalue() )

    def test_icrl_returns_none_falls_back_to_heuristic( self ):
        strat, _, _ = _mk_strategy( icrl_enabled=True, llm_client=MagicMock(),
                                    cbr_confidence_threshold=0.8 )
        pred = SimpleNamespace( verdict="approved", confidence=0.3, case_count=2,
                                similar_cases=[ { "decision_value": "a" }, { "decision_value": "b" } ] )
        strat._get_cbr_prediction = MagicMock( return_value=pred )
        strat._get_icrl_decision = MagicMock( return_value=None )
        self.assertEqual( strat.decide( "ambiguous", "testing" ), "approved" )


class TestGetCbrPrediction( unittest.TestCase ):

    def test_returns_none_without_store( self ):
        strat, _, _ = _mk_strategy()
        self.assertIsNone( strat._get_cbr_prediction( "q", "testing" ) )

    def test_success_path( self ):
        strat, _, _ = _mk_strategy()
        strat.cbr_store = MagicMock()
        strat.cbr_store.predict.return_value = "PRED"
        strat.embedding_provider = MagicMock()
        strat.embedding_provider.generate_embedding.return_value = [ 0.1 ]
        self.assertEqual( strat._get_cbr_prediction( "q", "testing" ), "PRED" )

    def test_exception_returns_none_debug( self ):
        strat, _, _ = _mk_strategy( debug=True )
        strat.cbr_store = MagicMock()
        strat.embedding_provider = MagicMock()
        strat.embedding_provider.generate_embedding.side_effect = RuntimeError( "embed fail" )
        buf = io.StringIO()
        with redirect_stdout( buf ):
            self.assertIsNone( strat._get_cbr_prediction( "q", "testing" ) )
        self.assertIn( "CBR prediction failed", buf.getvalue() )


class TestHasMixedVerdicts( unittest.TestCase ):

    def setUp( self ):
        self.strat, _, _ = _mk_strategy()

    def test_no_similar_cases_false( self ):
        self.assertFalse( self.strat._has_mixed_verdicts( SimpleNamespace( similar_cases=[] ) ) )

    def test_mixed_true( self ):
        pred = SimpleNamespace( similar_cases=[ { "decision_value": "a" }, { "decision_value": "b" } ] )
        self.assertTrue( self.strat._has_mixed_verdicts( pred ) )

    def test_unanimous_false( self ):
        pred = SimpleNamespace( similar_cases=[ { "decision_value": "a" },
                                                { "decision_value": "a" },
                                                { "decision_value": "" } ] )  # empty skipped
        self.assertFalse( self.strat._has_mixed_verdicts( pred ) )


class TestGetIcrlDecision( unittest.TestCase ):

    def _pred( self ):
        return SimpleNamespace( similar_cases=[ { "decision_value": "a" } ] )

    def test_valid_response( self ):
        strat, _, _ = _mk_strategy( debug=True, icrl_top_k=3 )
        strat.llm_client = MagicMock()
        strat.llm_client.run.return_value = "  Approved  "
        with patch.object( es, "build_icrl_prompt", create=True, return_value="P" ):
            with patch.dict( "sys.modules", {} ):
                buf = io.StringIO()
                with redirect_stdout( buf ):
                    out = strat._get_icrl_decision( "q", "testing", self._pred() )
        self.assertEqual( out, "approved" )

    def test_unexpected_response_returns_none( self ):
        strat, _, _ = _mk_strategy( debug=True )
        strat.llm_client = MagicMock()
        strat.llm_client.run.return_value = "maybe"
        buf = io.StringIO()
        with redirect_stdout( buf ):
            out = strat._get_icrl_decision( "q", "testing", self._pred() )
        self.assertIsNone( out )
        self.assertIn( "unexpected response", buf.getvalue() )

    def test_exception_returns_none( self ):
        strat, _, _ = _mk_strategy( debug=True )
        strat.llm_client = MagicMock()
        strat.llm_client.run.side_effect = RuntimeError( "llm down" )
        buf = io.StringIO()
        with redirect_stdout( buf ):
            out = strat._get_icrl_decision( "q", "testing", self._pred() )
        self.assertIsNone( out )
        self.assertIn( "ICRL failed", buf.getvalue() )


class TestConformalWrapper( unittest.TestCase ):

    def test_lazy_create_and_cache( self ):
        strat, _, _ = _mk_strategy( conformal_alpha=0.2 )
        with patch.object( es, "ConformalDecisionWrapper" ) as CW:
            w1 = strat._get_conformal_wrapper()
            w2 = strat._get_conformal_wrapper()
        self.assertIs( w1, w2 )
        CW.assert_called_once_with( alpha=0.2 )

    def test_calibrate_conformal_collects_blr_points( self ):
        strat, tt, _ = _mk_strategy()
        blr = MagicMock()
        blr._feature_count = 2
        blr._feature_sum   = 4.0
        blr.predict.return_value = ( 0.7, None )
        cat_with = SimpleNamespace( _blr_model=blr, total_decisions=3, total_successes=2 )
        cat_skip = SimpleNamespace( _blr_model=None )
        cat_zero = SimpleNamespace( _blr_model=MagicMock( _feature_count=0 ) )
        tt.categories = { "a": cat_with, "b": cat_skip, "c": cat_zero }
        wrapper = MagicMock()
        wrapper.get_status.return_value = { "calibrated": True }
        with patch.object( strat, "_get_conformal_wrapper", return_value=wrapper ):
            out = strat.calibrate_conformal()
        self.assertEqual( out, { "calibrated": True } )
        # 2 success + 1 fail = 3 calibration points.
        probs, labels = wrapper.calibrate.call_args.args
        self.assertEqual( len( probs ), 3 )
        self.assertEqual( labels.count( 1 ), 2 )
        self.assertEqual( labels.count( 0 ), 1 )

    def test_calibrate_conformal_no_decisions_skips_points( self ):
        strat, tt, _ = _mk_strategy()
        blr = MagicMock()
        blr._feature_count = 2
        blr._feature_sum   = 4.0
        blr.predict.return_value = ( 0.7, None )
        tt.categories = { "a": SimpleNamespace( _blr_model=blr, total_decisions=0, total_successes=0 ) }
        wrapper = MagicMock()
        with patch.object( strat, "_get_conformal_wrapper", return_value=wrapper ):
            strat.calibrate_conformal()
        probs, labels = wrapper.calibrate.call_args.args
        self.assertEqual( probs, [] )


class TestGateThompson( unittest.TestCase ):

    def test_unknown_category_shadow( self ):
        strat, tt, _ = _mk_strategy()
        tt.categories = {}
        self.assertEqual( strat._gate_thompson( "nope" ), "shadow" )

    def test_act_suggest_shadow_by_sample( self ):
        strat, tt, _ = _mk_strategy( debug=True,
                                     thompson_act_threshold=0.9, thompson_suggest_threshold=0.7 )
        tt.categories = { "testing": SimpleNamespace( total_successes=5, total_rejections=1 ) }
        with patch.object( es.beta_dist, "rvs", return_value=0.95 ):
            buf = io.StringIO()
            with redirect_stdout( buf ):
                self.assertEqual( strat._gate_thompson( "testing" ), "act" )
        self.assertIn( "TS draw", buf.getvalue() )
        with patch.object( es.beta_dist, "rvs", return_value=0.75 ):
            self.assertEqual( strat._gate_thompson( "testing" ), "suggest" )
        with patch.object( es.beta_dist, "rvs", return_value=0.10 ):
            self.assertEqual( strat._gate_thompson( "testing" ), "shadow" )

    def test_thompson_debug_off_skips_print( self ):
        # 496->500: debug False → skip the TS-draw print.
        strat, tt, _ = _mk_strategy( debug=False,
                                     thompson_act_threshold=0.9, thompson_suggest_threshold=0.7 )
        tt.categories = { "testing": SimpleNamespace( total_successes=1, total_rejections=1 ) }
        with patch.object( es.beta_dist, "rvs", return_value=0.95 ):
            self.assertEqual( strat._gate_thompson( "testing" ), "act" )


class TestThompsonDiagnostics( unittest.TestCase ):

    def test_diagnostics_per_category( self ):
        strat, tt, _ = _mk_strategy()
        tt.categories = { "testing": SimpleNamespace( total_successes=3, total_rejections=1 ) }
        with patch.object( es.beta_dist, "sf", return_value=0.2 ), \
             patch.object( es.beta_dist, "cdf", return_value=0.5 ):
            diag = strat.get_thompson_diagnostics()
        d = diag[ "testing" ]
        self.assertEqual( d[ "alpha" ], 4 )
        self.assertEqual( d[ "beta" ], 2 )
        self.assertEqual( d[ "observations" ], 4 )
        self.assertEqual( d[ "p_act" ], 0.2 )
        self.assertEqual( d[ "p_shadow" ], 0.5 )
        self.assertAlmostEqual( d[ "p_suggest" ], 0.3 )


class TestEvaluate( unittest.TestCase ):

    def test_evaluate_act_with_cbr_enrichment_debug( self ):
        strat, tt, cb = _mk_strategy( trust_mode="active", debug=True )
        strat.classifier = MagicMock()
        strat.classifier.classify.return_value = ( "testing", 0.85 )
        tt.get_level.return_value = 4          # → "act"
        pred = SimpleNamespace( verdict="approved", confidence=0.9, case_count=2 )
        strat._get_cbr_prediction = MagicMock( return_value=pred )
        buf = io.StringIO()
        with redirect_stdout( buf ):
            result = strat.evaluate( "run tests", sender_id="swe.tester@x" )
        self.assertEqual( result.action, "act" )
        self.assertEqual( result.value, "approved" )
        self.assertEqual( result.category, "testing" )
        self.assertEqual( result.trust_level, 4 )
        self.assertIn( "CBR:", result.reason )

    def test_evaluate_shadow_no_value_no_cbr( self ):
        strat, tt, cb = _mk_strategy( trust_mode="shadow" )
        strat.classifier = MagicMock()
        strat.classifier.classify.return_value = ( "general", 0.3 )
        tt.get_level.return_value = 1
        strat._get_cbr_prediction = MagicMock( return_value=None )
        result = strat.evaluate( "hello" )
        self.assertEqual( result.action, "shadow" )
        self.assertIsNone( result.value )
        self.assertNotIn( "CBR:", result.reason )


if __name__ == "__main__":
    unittest.main()
