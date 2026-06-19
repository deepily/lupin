#!/usr/bin/env python3
"""
Circuit Breaker for the Decision Proxy Agent.

Monitors decision health metrics and automatically demotes trust levels
when anomalies are detected:
  - Error rate spike: rejection rate exceeds threshold
  - Confidence collapse: average classification confidence drops
  - Auto-demotion: drops trust level by configured number of levels
  - Recovery cooldown: prevents immediate re-graduation after trip

Dependency Rule:
    This module NEVER imports from notification_proxy or swe_team.
"""

import time
from typing import Optional

from cosa.agents.decision_proxy.config import (
    DEFAULT_CB_ERROR_RATE_THRESHOLD,
    DEFAULT_CB_CONFIDENCE_COLLAPSE_THRESHOLD,
    DEFAULT_CB_AUTO_DEMOTION_LEVELS,
    DEFAULT_CB_RECOVERY_COOLDOWN_SECONDS,
)


class CircuitBreaker:
    """
    Health monitor that auto-demotes trust levels on anomaly detection.

    Monitors per-category metrics and trips when thresholds are exceeded.
    After tripping, enters a cooldown period before allowing trust to climb.

    Requires:
        - trust_tracker is a TrustTracker instance
        - Thresholds are 0.0-1.0 floats

    Ensures:
        - check() evaluates health for a category
        - trip() demotes and enters cooldown
        - is_tripped() returns current state
        - Recovery is automatic after cooldown expires
    """

    def __init__(
        self,
        trust_tracker,
        error_rate_threshold        = DEFAULT_CB_ERROR_RATE_THRESHOLD,
        confidence_collapse_threshold = DEFAULT_CB_CONFIDENCE_COLLAPSE_THRESHOLD,
        auto_demotion_levels        = DEFAULT_CB_AUTO_DEMOTION_LEVELS,
        recovery_cooldown_seconds   = DEFAULT_CB_RECOVERY_COOLDOWN_SECONDS,
        on_trip_callback            = None,
        debug                       = False
    ):
        """
        Initialize the circuit breaker.

        Args:
            trust_tracker: TrustTracker instance to demote on trip
            error_rate_threshold: Error rate that triggers trip (0.0-1.0)
            confidence_collapse_threshold: Confidence drop that triggers trip (0.0-1.0)
            auto_demotion_levels: Levels to demote on trip
            recovery_cooldown_seconds: Seconds before recovery
            on_trip_callback: Optional callback( category, reason ) on trip
            debug: Enable debug output
        """
        self.trust_tracker                = trust_tracker
        self.error_rate_threshold         = error_rate_threshold
        self.confidence_collapse_threshold = confidence_collapse_threshold
        self.auto_demotion_levels         = auto_demotion_levels
        self.recovery_cooldown_seconds    = recovery_cooldown_seconds
        self.on_trip_callback             = on_trip_callback
        self.debug                        = debug

        # Per-category trip state: category_name → trip_timestamp (or None)
        self._tripped = {}

        # Running confidence averages: category_name → list of recent confidences
        self._confidence_window = {}
        self._confidence_window_size = 20  # Last N classifications

    def is_tripped( self, category_name ):
        """
        Check if the circuit breaker is currently tripped for a category.

        Requires:
            - category_name is a string

        Ensures:
            - Returns True if tripped and still within cooldown
            - Returns False if not tripped or cooldown has expired

        Args:
            category_name: Category to check

        Returns:
            bool: True if currently tripped
        """
        trip_time = self._tripped.get( category_name )
        if trip_time is None:
            return False

        elapsed = time.time() - trip_time
        if elapsed >= self.recovery_cooldown_seconds:
            # Cooldown expired — auto-recover
            del self._tripped[ category_name ]
            if self.debug: print( f"[CircuitBreaker] {category_name}: recovered after cooldown" )
            return False

        return True

    def record_confidence( self, category_name, confidence ):
        """
        Record a classification confidence value for monitoring.

        Requires:
            - category_name is a string
            - confidence is 0.0-1.0

        Ensures:
            - Confidence is added to the sliding window
            - Window is trimmed to max size

        Args:
            category_name: Category name
            confidence: Classification confidence (0.0-1.0)
        """
        if category_name not in self._confidence_window:
            self._confidence_window[ category_name ] = []

        window = self._confidence_window[ category_name ]
        window.append( confidence )

        # Trim to window size
        if len( window ) > self._confidence_window_size:
            self._confidence_window[ category_name ] = window[ -self._confidence_window_size: ]

    def get_average_confidence( self, category_name ):
        """
        Get the average confidence for a category's recent classifications.

        Returns:
            float: Average confidence, or 1.0 if no data
        """
        window = self._confidence_window.get( category_name, [] )
        if not window:
            return 1.0
        return sum( window ) / len( window )

    def check( self, category_name ):
        """
        Evaluate health metrics for a category and trip if thresholds exceeded.

        Checks:
            1. Error rate spike: rejection rate > error_rate_threshold
            2. Confidence collapse: average confidence < confidence_collapse_threshold

        Requires:
            - category_name is a string
            - Category has decision history in trust_tracker

        Ensures:
            - Returns True if healthy (no trip)
            - Returns False if tripped (trust demoted)
            - Calls trip() if any threshold exceeded

        Args:
            category_name: Category to check

        Returns:
            bool: True if healthy, False if tripped
        """
        if self.is_tripped( category_name ):
            return False

        cat = self.trust_tracker.categories.get( category_name )
        if cat is None:
            return True  # Unknown category — no data to check

        # Check 1: Error rate spike
        if cat.total_decisions >= 10:  # Need minimum sample
            if cat.error_rate > self.error_rate_threshold:
                reason = f"Error rate {cat.error_rate:.2%} exceeds threshold {self.error_rate_threshold:.2%}"
                self.trip( category_name, reason )
                return False

        # Check 2: Confidence collapse
        avg_confidence = self.get_average_confidence( category_name )
        if len( self._confidence_window.get( category_name, [] ) ) >= 5:
            if avg_confidence < self.confidence_collapse_threshold:
                reason = f"Avg confidence {avg_confidence:.2f} below threshold {self.confidence_collapse_threshold:.2f}"
                self.trip( category_name, reason )
                return False

        return True

    def trip( self, category_name, reason="" ):
        """
        Trip the circuit breaker for a category.

        Requires:
            - category_name is a string

        Ensures:
            - Trust level is demoted by auto_demotion_levels
            - Trip timestamp is recorded (starts cooldown)
            - on_trip_callback is called if set

        Args:
            category_name: Category to trip
            reason: Human-readable reason for the trip
        """
        self._tripped[ category_name ] = time.time()

        # Demote trust level
        self.trust_tracker.demote_category( category_name, self.auto_demotion_levels )

        if self.debug:
            print( f"[CircuitBreaker] TRIPPED: {category_name} — {reason}" )
            print( f"[CircuitBreaker] Demoted {self.auto_demotion_levels} levels, cooldown {self.recovery_cooldown_seconds}s" )

        if self.on_trip_callback:
            self.on_trip_callback( category_name, reason )

    def reset( self, category_name ):
        """
        Manually reset the circuit breaker for a category.

        Ensures:
            - Removes trip state
            - Clears confidence window

        Args:
            category_name: Category to reset
        """
        self._tripped.pop( category_name, None )
        self._confidence_window.pop( category_name, None )

    def get_status( self ):
        """
        Get circuit breaker status for all categories.

        Returns:
            Dict mapping category_name → { tripped, cooldown_remaining, avg_confidence }
        """
        now = time.time()
        status = {}

        for category_name in self.trust_tracker.categories:
            trip_time = self._tripped.get( category_name )
            tripped = self.is_tripped( category_name )
            cooldown_remaining = 0

            if trip_time and tripped:
                cooldown_remaining = self.recovery_cooldown_seconds - ( now - trip_time )

            status[ category_name ] = {
                "tripped"             : tripped,
                "cooldown_remaining"  : max( 0, int( cooldown_remaining ) ),
                "avg_confidence"      : round( self.get_average_confidence( category_name ), 4 ),
            }

        return status
