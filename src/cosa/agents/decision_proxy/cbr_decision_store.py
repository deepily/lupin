#!/usr/bin/env python3
"""
Case-Based Reasoning (CBR) Decision Store.

Implements a Retrieve → Reuse CBR pipeline for proxy decisions:
  1. Retrieve: Find most similar past decisions via embedding similarity
  2. Reuse: Majority vote among retrieved cases to predict a verdict

The CBR store is stateless — it delegates retrieval to ProxyDecisionEmbeddings
and computes predictions from the returned cases.

Dependency Rule:
    This module NEVER imports from notification_proxy or swe_team.
"""

from dataclasses import dataclass, field
from typing import List, Optional
from collections import Counter


@dataclass
class CBRPrediction:
    """
    Result of a CBR prediction.

    Attributes:
        verdict: Predicted decision value (majority vote) or None if no cases
        confidence: Combined confidence score (0.0-1.0) = max_similarity * consistency
        similar_cases: List of retrieved similar case dicts
        case_count: Number of cases used in prediction
    """
    verdict       : Optional[ str ]
    confidence    : float
    similar_cases : List[ dict ] = field( default_factory=list )
    case_count    : int          = 0


class CBRDecisionStore:
    """
    Case-Based Reasoning engine for proxy decision prediction.

    Uses ProxyDecisionEmbeddings for retrieval and computes verdict via
    majority vote with confidence scoring.

    Requires:
        - embedding_store is a ProxyDecisionEmbeddings instance
        - top_k is a positive integer
        - confidence_threshold is 0.0-1.0

    Ensures:
        - predict() returns a CBRPrediction with verdict and confidence
        - Empty store returns verdict=None, confidence=0.0
        - Confidence is product of max_similarity and verdict_consistency
    """

    def __init__( self, embedding_store, top_k=5, confidence_threshold=0.60, debug=False ):
        """
        Initialize the CBR decision store.

        Args:
            embedding_store: ProxyDecisionEmbeddings instance for retrieval
            top_k: Number of most-similar cases to retrieve
            confidence_threshold: Minimum confidence for actionable predictions
            debug: Enable debug output
        """
        self.embedding_store      = embedding_store
        self.top_k                = top_k
        self.confidence_threshold = confidence_threshold
        self.debug                = debug

    def predict( self, question, category, query_embedding ):
        """
        Predict a decision value using CBR retrieval and majority vote.

        Algorithm:
            1. Retrieve top_k similar cases from embedding store
            2. If 0 cases: return empty prediction
            3. Majority vote on decision_value among retrieved cases
            4. confidence = max_similarity * verdict_consistency

        Requires:
            - question is a non-empty string
            - category is a non-empty string
            - query_embedding is a list of floats (768-dim)

        Ensures:
            - Returns CBRPrediction with verdict, confidence, cases, count
            - verdict is None if no cases found
            - confidence is 0.0 if no cases found

        Args:
            question: Decision question text
            category: Decision category for filtering
            query_embedding: 768-dim query embedding vector

        Returns:
            CBRPrediction
        """
        # Step 1: Retrieve similar cases
        results = self.embedding_store.find_similar(
            query_embedding,
            category  = category,
            limit     = self.top_k,
            threshold = 0.0,  # Retrieve all, let confidence scoring filter
        )

        # Step 2: No cases → empty prediction
        if not results:
            if self.debug: print( "[CBRDecisionStore] No similar cases found" )
            return CBRPrediction( verdict=None, confidence=0.0, similar_cases=[], case_count=0 )

        # Step 3: Majority vote on decision_value
        cases    = [ record for _, record in results ]
        verdicts = [ case.get( "decision_value", "" ) for case in cases ]
        counter  = Counter( verdicts )

        majority_verdict, majority_count = counter.most_common( 1 )[ 0 ]

        # Step 4: Compute confidence
        max_similarity      = results[ 0 ][ 0 ] / 100.0  # Normalize from percentage to 0-1
        verdict_consistency  = majority_count / len( cases )
        confidence           = max_similarity * verdict_consistency

        if self.debug:
            print( f"[CBRDecisionStore] Prediction: '{majority_verdict}' "
                   f"(confidence={confidence:.3f}, cases={len( cases )}, "
                   f"max_sim={max_similarity:.3f}, consistency={verdict_consistency:.2f})" )

        return CBRPrediction(
            verdict       = majority_verdict,
            confidence    = confidence,
            similar_cases = cases,
            case_count    = len( cases ),
        )
