#!/usr/bin/env python3
"""
SWE Engineering Strategy — concrete decision strategy for SWE team operations.

Implements the full classify → gate → decide pipeline for engineering decisions.
Uses EngineeringClassifier for classification and TrustTracker for trust-gated
decision-making.

Dependency Rule:
    This module imports from decision_proxy (Layer 3) for base classes.
    This module NEVER imports from notification_proxy.
"""

from scipy.stats import beta as beta_dist

from cosa.agents.decision_proxy.base_decision_strategy import BaseDecisionStrategy, DecisionResult
from cosa.agents.decision_proxy.trust_tracker import TrustTracker
from cosa.agents.decision_proxy.circuit_breaker import CircuitBreaker
from cosa.agents.decision_proxy.conformal_wrapper import ConformalDecisionWrapper
from cosa.agents.decision_proxy.config import DEFAULT_CBR_CONFIDENCE_THRESHOLD

from cosa.agents.swe_team.proxy.engineering_classifier import EngineeringClassifier
from cosa.agents.swe_team.proxy.engineering_categories import (
    ENGINEERING_CATEGORIES,
    get_category_names,
    get_category_cap_level,
)
from cosa.agents.swe_team.proxy.config import DEFAULT_ACCEPTED_SENDERS


class EngineeringStrategy( BaseDecisionStrategy ):
    """
    Concrete decision strategy for SWE team engineering decisions.

    Wires together:
        - EngineeringClassifier for question → category mapping
        - TrustTracker for per-category trust levels
        - CircuitBreaker for anomaly detection and auto-demotion
        - Thompson Sampling for probabilistic gate routing (optional)
        - Conformal Prediction for coverage-guaranteed deferral (optional)
        - ICRL for LLM-augmented disambiguation of ambiguous CBR (optional)

    Requires:
        - trust_tracker: TrustTracker instance (categories registered at init)
        - circuit_breaker: CircuitBreaker instance (optional)
        - accepted_senders: List of accepted sender IDs

    Ensures:
        - classify() delegates to EngineeringClassifier
        - gate() enforces trust level caps and mode restrictions
        - decide() provides default decision values per category
        - evaluate() runs the full pipeline with trust_tracker integration
        - Thompson Sampling draws from Beta posterior when enabled
    """

    def __init__(
        self,
        trust_tracker              = None,
        circuit_breaker            = None,
        accepted_senders           = None,
        trust_mode                 = "shadow",
        cbr_store                  = None,
        embedding_provider         = None,
        thompson_enabled           = False,
        thompson_act_threshold     = 0.90,
        thompson_suggest_threshold = 0.70,
        conformal_enabled          = False,
        conformal_alpha            = 0.10,
        icrl_enabled               = False,
        icrl_top_k                 = 5,
        llm_client                 = None,
        cbr_confidence_threshold   = None,
        debug                      = False
    ):
        """
        Initialize the SWE engineering strategy.

        Requires:
            - trust_mode is one of "shadow", "suggest", "active"
            - thompson_act_threshold > thompson_suggest_threshold

        Args:
            trust_tracker: TrustTracker instance (created if None)
            circuit_breaker: CircuitBreaker instance (created if None)
            accepted_senders: List of accepted sender IDs
            trust_mode: Operating mode ("shadow", "suggest", "active")
            cbr_store: Optional CBRDecisionStore for case-based reasoning
            embedding_provider: Optional EmbeddingProvider for generating query embeddings
            thompson_enabled: Enable Thompson Sampling for gate routing
            thompson_act_threshold: Sampled rate threshold for "act" (default 0.90)
            thompson_suggest_threshold: Sampled rate threshold for "suggest" (default 0.70)
            conformal_enabled: Enable conformal prediction for coverage-guaranteed deferral
            conformal_alpha: Significance level for conformal sets (default 0.10)
            icrl_enabled: Enable ICRL fallback for ambiguous CBR cases
            icrl_top_k: Number of similar cases to include in ICRL prompt
            llm_client: Optional LlmClient for ICRL queries
            cbr_confidence_threshold: Threshold below which CBR is considered low-confidence
            debug: Enable debug output
        """
        self.debug                      = debug
        self.trust_mode                 = trust_mode
        self.accepted_senders           = accepted_senders or DEFAULT_ACCEPTED_SENDERS
        self.cbr_store                  = cbr_store
        self.embedding_provider         = embedding_provider
        self.thompson_enabled           = thompson_enabled
        self.thompson_act_threshold     = thompson_act_threshold
        self.thompson_suggest_threshold = thompson_suggest_threshold
        self.conformal_enabled          = conformal_enabled
        self.conformal_alpha            = conformal_alpha
        self.icrl_enabled               = icrl_enabled
        self.icrl_top_k                 = icrl_top_k
        self.llm_client                 = llm_client
        self.cbr_confidence_threshold   = cbr_confidence_threshold if cbr_confidence_threshold is not None else DEFAULT_CBR_CONFIDENCE_THRESHOLD

        # Conformal wrapper (lazy-initialized on first use)
        self._conformal_wrapper = None

        # Create trust tracker if not provided
        self.trust_tracker = trust_tracker or TrustTracker( debug=debug )

        # Register all engineering categories with their cap levels
        for cat_name in get_category_names():
            cap = get_category_cap_level( cat_name )
            self.trust_tracker.register_category( cat_name, cap_level=cap )

        # Create circuit breaker if not provided
        self.circuit_breaker = circuit_breaker or CircuitBreaker(
            trust_tracker = self.trust_tracker,
            debug         = debug
        )

        # Classifier
        self.classifier = EngineeringClassifier( debug=debug )

    @property
    def name( self ):
        """Strategy identifier."""
        return "swe_engineering"

    @property
    def available( self ):
        """Strategy is always available once constructed."""
        return True

    def can_handle( self, item ):
        """
        Check if the event comes from an accepted SWE sender.

        Requires:
            - item is a dict with optional 'sender_id' key

        Ensures:
            - Returns True if sender_id is in accepted_senders
            - Returns True if no sender_id (allows generic routing)
            - Returns False if sender_id is not in accepted_senders

        Args:
            item: Event payload dict

        Returns:
            bool
        """
        sender_id = item.get( "sender_id", "" ) if isinstance( item, dict ) else ""
        if not sender_id:
            return True  # No sender filtering if sender unknown
        return sender_id in self.accepted_senders

    def classify( self, question, sender_id="", context=None ):
        """
        Classify using the EngineeringClassifier.

        Requires:
            - question is a non-empty string

        Ensures:
            - Returns ( category, confidence ) tuple
            - Records confidence in circuit breaker

        Args:
            question: Decision question text
            sender_id: Requesting agent's sender ID
            context: Optional context dict

        Returns:
            Tuple of ( category_name, confidence )
        """
        category, confidence = self.classifier.classify( question, sender_id, context )

        # Record confidence for circuit breaker monitoring
        self.circuit_breaker.record_confidence( category, confidence )

        return ( category, confidence )

    def gate( self, category, trust_level, confidence ):
        """
        Gate decision based on trust level, mode, and circuit breaker.

        Requires:
            - category is a valid category name
            - trust_level is 1-5
            - confidence is 0.0-1.0

        Ensures:
            - In "shadow" mode: always returns "shadow"
            - In "suggest" mode: returns "suggest" for L2+, "shadow" for L1
            - In "active" mode: trust-level gating (L1=shadow, L2=suggest, L3+=act)
            - Circuit breaker tripped → returns "defer"

        Args:
            category: Decision category name
            trust_level: Current trust level
            confidence: Classification confidence

        Returns:
            Action string: "shadow", "suggest", "act", or "defer"
        """
        # Circuit breaker check
        if not self.circuit_breaker.check( category ):
            if self.debug: print( f"[EngineeringStrategy] Circuit breaker tripped for {category}" )
            return "defer"

        # Shadow mode — always shadow regardless of trust
        if self.trust_mode == "shadow":
            return "shadow"

        # Conformal prediction check (Phase 3) — defer on ambiguity
        if self.conformal_enabled:
            wrapper = self._get_conformal_wrapper()
            if wrapper.is_calibrated:
                cat = self.trust_tracker.categories.get( category )
                if cat is not None and cat._blr_model is not None:
                    x_bar = cat._blr_model._feature_sum / cat._blr_model._feature_count
                    prob, _ = cat._blr_model.predict( x_bar )
                    if wrapper.should_defer( prob ):
                        if self.debug: print( f"[EngineeringStrategy] Conformal defer: {category} (prob={prob:.4f})" )
                        return "defer"

        # Thompson Sampling — probabilistic gate routing
        if self.thompson_enabled:
            return self._gate_thompson( category )

        # Suggest mode — suggest at L2+, shadow at L1
        if self.trust_mode == "suggest":
            if trust_level >= 2:
                return "suggest"
            return "shadow"

        # Active mode — full trust-level gating
        if trust_level <= 1:
            return "shadow"
        elif trust_level == 2:
            return "suggest"
        else:
            return "act"

    def decide( self, question, category, context=None ):
        """
        Produce a decision value for the given question.

        Returns a simple heuristic decision. If a CBR store is configured,
        generates a CBR prediction in shadow mode (logged but not used).

        Requires:
            - question is a non-empty string
            - category is a valid category name

        Ensures:
            - Returns a decision value string
            - Returns "approved" for low-risk categories (testing, general)
            - Returns "requires_review" for high-risk categories
            - CBR prediction is logged but does not override heuristic

        Args:
            question: Decision question text
            category: Classified category
            context: Optional context dict

        Returns:
            Decision value string
        """
        # Heuristic decision (always used)
        if category in ( "deployment", "destructive", "architecture" ):
            heuristic_value = "requires_review"
        else:
            heuristic_value = "approved"

        # CBR shadow mode: predict but don't override
        cbr_prediction = self._get_cbr_prediction( question, category )

        if cbr_prediction is not None and cbr_prediction.verdict is not None:
            agreement = "AGREE" if cbr_prediction.verdict == heuristic_value else "DISAGREE"
            if self.debug:
                print( f"[EngineeringStrategy] CBR shadow: {agreement} "
                       f"(heuristic='{heuristic_value}', cbr='{cbr_prediction.verdict}', "
                       f"confidence={cbr_prediction.confidence:.3f}, cases={cbr_prediction.case_count})" )

        # ICRL fallback for ambiguous CBR (Phase 3)
        if ( self.icrl_enabled
             and self.llm_client is not None
             and cbr_prediction is not None
             and cbr_prediction.confidence < self.cbr_confidence_threshold
             and self._has_mixed_verdicts( cbr_prediction ) ):
            icrl_value = self._get_icrl_decision( question, category, cbr_prediction )
            if icrl_value is not None:
                if self.debug: print( f"[EngineeringStrategy] ICRL override: {icrl_value}" )
                return icrl_value

        return heuristic_value

    def _get_cbr_prediction( self, question, category ):
        """
        Generate a CBR prediction if store and embedding provider are available.

        Ensures:
            - Returns CBRPrediction or None
            - Failure is logged but never propagates

        Args:
            question: Decision question text
            category: Decision category

        Returns:
            CBRPrediction or None
        """
        if self.cbr_store is None or self.embedding_provider is None:
            return None

        try:
            query_embedding = self.embedding_provider.generate_embedding( question[ :500 ], content_type="prose" )
            return self.cbr_store.predict( question, category, query_embedding )
        except Exception as e:
            if self.debug: print( f"[EngineeringStrategy] CBR prediction failed (non-fatal): {e}" )
            return None

    def _has_mixed_verdicts( self, cbr_prediction ):
        """
        Check if CBR prediction contains mixed verdicts (not unanimous).

        Requires:
            - cbr_prediction is a CBRPrediction instance

        Ensures:
            - Returns True if similar_cases contain > 1 unique decision_value
            - Returns False if unanimous or empty

        Args:
            cbr_prediction: CBRPrediction from CBR store

        Returns:
            bool
        """
        if not cbr_prediction.similar_cases:
            return False

        verdicts = set()
        for case in cbr_prediction.similar_cases:
            value = case.get( "decision_value", "" )
            if value:
                verdicts.add( value )

        return len( verdicts ) > 1

    def _get_icrl_decision( self, question, category, cbr_prediction ):
        """
        Query an LLM to disambiguate a mixed-verdict CBR prediction.

        Builds an ICRL prompt with the top-k similar cases and calls
        the LLM client for a decision. Gracefully degrades on any error.

        Requires:
            - self.llm_client is not None
            - cbr_prediction has similar_cases

        Ensures:
            - Returns "approved" or "requires_review" on success
            - Returns None on error or unexpected LLM response
            - Never raises exceptions

        Args:
            question: Decision question text
            category: Decision category
            cbr_prediction: CBRPrediction with similar cases

        Returns:
            Decision value string or None
        """
        try:
            from cosa.agents.decision_proxy.prompts.icrl_decision import build_icrl_prompt

            cases  = cbr_prediction.similar_cases[ :self.icrl_top_k ]
            prompt = build_icrl_prompt( question, category, cases )

            response = self.llm_client.run( prompt )
            parsed   = response.strip().lower()

            if parsed in ( "approved", "requires_review" ):
                if self.debug: print( f"[EngineeringStrategy] ICRL returned: {parsed}" )
                return parsed

            if self.debug: print( f"[EngineeringStrategy] ICRL unexpected response: '{parsed}'" )
            return None

        except Exception as e:
            if self.debug: print( f"[EngineeringStrategy] ICRL failed (non-fatal): {e}" )
            return None

    def _get_conformal_wrapper( self ):
        """
        Lazily initialize and return the conformal wrapper.

        Ensures:
            - Returns ConformalDecisionWrapper instance
            - Only creates once per strategy lifetime

        Returns:
            ConformalDecisionWrapper
        """
        if self._conformal_wrapper is None:
            self._conformal_wrapper = ConformalDecisionWrapper( alpha=self.conformal_alpha )
        return self._conformal_wrapper

    def calibrate_conformal( self ):
        """
        Calibrate the conformal wrapper using BLR predictions across categories.

        Collects BLR predict() probabilities and corresponding labels from
        all categories that have trained BLR models, then calibrates the
        conformal wrapper.

        Ensures:
            - Conformal wrapper is calibrated if sufficient BLR data exists
            - Safe to call even if no BLR models are trained

        Returns:
            Dict with calibration status
        """
        wrapper = self._get_conformal_wrapper()

        probabilities = []
        labels        = []

        for cat_name, cat in self.trust_tracker.categories.items():
            if cat._blr_model is None or cat._blr_model._feature_count == 0:
                continue

            x_bar = cat._blr_model._feature_sum / cat._blr_model._feature_count
            prob, _ = cat._blr_model.predict( x_bar )

            # Use category success rate as proxy for true label
            if cat.total_decisions > 0:
                n_success = cat.total_successes
                n_total   = cat.total_decisions
                # Generate calibration points proportional to category size
                for _ in range( n_success ):
                    probabilities.append( prob )
                    labels.append( 1 )
                for _ in range( n_total - n_success ):
                    probabilities.append( prob )
                    labels.append( 0 )

        wrapper.calibrate( probabilities, labels )
        return wrapper.get_status()

    def _gate_thompson( self, category ):
        """
        Thompson Sampling gate: draw from Beta posterior to decide action.

        Uses the category's global Beta counters (total_successes, total_rejections)
        as the posterior parameters. Draws a single sample and routes based on
        configurable thresholds.

        Requires:
            - category is a registered category name
            - self.thompson_enabled is True

        Ensures:
            - Returns "act" if sampled_rate >= thompson_act_threshold
            - Returns "suggest" if sampled_rate >= thompson_suggest_threshold
            - Returns "shadow" otherwise

        Args:
            category: Decision category name

        Returns:
            Action string: "shadow", "suggest", or "act"
        """
        cat = self.trust_tracker.categories.get( category )
        if cat is None:
            return "shadow"

        alpha = cat.total_successes  + 1  # Beta(1,1) uniform prior
        beta  = cat.total_rejections + 1

        sampled_rate = beta_dist.rvs( alpha, beta )

        if self.debug:
            print( f"[EngineeringStrategy] TS draw: {category} "
                   f"alpha={alpha}, beta={beta}, sample={sampled_rate:.4f}" )

        if sampled_rate >= self.thompson_act_threshold:
            return "act"
        elif sampled_rate >= self.thompson_suggest_threshold:
            return "suggest"
        else:
            return "shadow"

    def get_thompson_diagnostics( self ):
        """
        Return per-category Thompson Sampling diagnostics.

        Uses analytical Beta CDF (scipy beta_dist.sf) to compute exact
        action probabilities without Monte Carlo sampling.

        Ensures:
            - Returns dict keyed by category name
            - Each entry has alpha, beta, mean_rate, observations,
              p_act, p_suggest, p_shadow
            - p_act + p_suggest + p_shadow ≈ 1.0

        Returns:
            Dict of per-category diagnostics
        """
        diagnostics = {}

        for cat_name, cat in self.trust_tracker.categories.items():
            alpha = cat.total_successes  + 1
            beta  = cat.total_rejections + 1
            n     = alpha + beta - 2  # total observations

            mean_rate = alpha / ( alpha + beta )

            # Analytical probabilities via Beta survival function
            p_act     = float( beta_dist.sf( self.thompson_act_threshold, alpha, beta ) )
            p_shadow  = float( beta_dist.cdf( self.thompson_suggest_threshold, alpha, beta ) )
            p_suggest = 1.0 - p_act - p_shadow

            diagnostics[ cat_name ] = {
                "alpha"        : alpha,
                "beta"         : beta,
                "mean_rate"    : round( mean_rate, 4 ),
                "observations" : n,
                "p_act"        : round( p_act, 4 ),
                "p_suggest"    : round( p_suggest, 4 ),
                "p_shadow"     : round( p_shadow, 4 ),
            }

        return diagnostics

    def evaluate( self, question, sender_id="", context=None ):
        """
        Run the full pipeline with trust tracker integration.

        Overrides base evaluate() to use the trust tracker for accurate
        per-category trust levels instead of the default L1. Enriches
        the reason string with CBR metadata when available.

        Requires:
            - question is a non-empty string

        Ensures:
            - Returns DecisionResult with accurate trust level
            - Circuit breaker check is performed
            - CBR metadata appended to reason string

        Args:
            question: Decision question text
            sender_id: Requesting agent's sender ID
            context: Optional context dict

        Returns:
            DecisionResult
        """
        category, confidence = self.classify( question, sender_id, context )

        # Get actual trust level from tracker (not default L1)
        trust_level = self.trust_tracker.get_level( category )

        action = self.gate( category, trust_level, confidence )

        value = None
        if action in ( "act", "suggest" ):
            value = self.decide( question, category, context )

        reason = f"Category '{category}' at L{trust_level} ({self.trust_mode} mode) → {action}"

        # Enrich reason with CBR metadata if available
        cbr_prediction = self._get_cbr_prediction( question, category )
        if cbr_prediction is not None and cbr_prediction.verdict is not None:
            reason += ( f" | CBR: verdict='{cbr_prediction.verdict}', "
                        f"confidence={cbr_prediction.confidence:.3f}, "
                        f"cases={cbr_prediction.case_count}" )

        if self.debug:
            print( f"[EngineeringStrategy] {reason}" )

        return DecisionResult(
            action      = action,
            value       = value,
            category    = category,
            confidence  = confidence,
            trust_level = trust_level,
            reason      = reason
        )
