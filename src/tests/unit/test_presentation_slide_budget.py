#!/usr/bin/env python3
"""
Unit tests for the presentation orchestrator's slide-budget resolution and the
soft-target drift warning.

Spec: src/rnd/v0.2.0/2026.08.05-presentation-slide-count-control.md (T1 + T2b).

These guard behavior that had ZERO unit coverage before this change:
    - the duration x slides_per_minute budget formula,
    - the explicit target_slide_count override that supersedes it (T1), and
    - the soft-target drift warning that fires ONLY when an explicit count was
      set and the outline missed it (T2b).

The orchestrator does no file I/O in __init__, so it is built directly here
with a hand-made PresentationConfig — no mocks, no API, no source file.
"""

import pytest

from cosa.agents.presentation_generator.config import PresentationConfig
from cosa.agents.presentation_generator.job import PresentationGeneratorJob
from cosa.agents.presentation_generator.orchestrator import PresentationOrchestratorAgent


def _agent( **config_overrides ):
    """
    Build an orchestrator around a config carrying the given overrides.

    Ensures:
        - Returns a PresentationOrchestratorAgent whose .config reflects the
          overrides; __init__ performs no file I/O so source_path is inert.
    """
    config = PresentationConfig( **config_overrides )
    return PresentationOrchestratorAgent( source_path="/tmp/inert.md", user_id="tester", config=config )


# =============================================================================
# T1 — _slide_budget()
# =============================================================================

class TestSlideBudget:
    """PresentationOrchestratorAgent._slide_budget() resolution."""

    def test_formula_when_count_unset( self ):
        """No explicit count -> duration x slides_per_minute (today's behavior)."""
        agent = _agent( target_duration_minutes=15, slides_per_minute=1.0, target_slide_count=None )
        assert agent._slide_budget() == 15

    def test_formula_respects_duration_and_pace( self ):
        """20 min x 1.5 slides/min -> 30."""
        agent = _agent( target_duration_minutes=20, slides_per_minute=1.5, target_slide_count=None )
        assert agent._slide_budget() == 30

    def test_formula_truncates_to_int( self ):
        """15 x 0.7 = 10.5 -> int() truncates to 10 (matches the pre-change code)."""
        agent = _agent( target_duration_minutes=15, slides_per_minute=0.7, target_slide_count=None )
        assert agent._slide_budget() == 10

    def test_explicit_count_overrides_formula( self ):
        """An explicit count wins over the formula (40 in a 15-min default slot)."""
        agent = _agent( target_duration_minutes=15, slides_per_minute=1.0, target_slide_count=40 )
        assert agent._slide_budget() == 40

    def test_explicit_count_wins_over_a_larger_duration( self ):
        """Even with a 60-min duration, an explicit 12 is honored verbatim."""
        agent = _agent( target_duration_minutes=60, slides_per_minute=1.0, target_slide_count=12 )
        assert agent._slide_budget() == 12


# =============================================================================
# T2b — _slide_count_drift_message()
# =============================================================================

class TestSlideCountDriftMessage:
    """PresentationOrchestratorAgent._slide_count_drift_message() — soft-target warn."""

    def test_silent_when_no_explicit_count( self ):
        """Default duration path: NEVER warn, even on a wide gap (additive-only)."""
        agent = _agent( target_slide_count=None )
        assert agent._slide_count_drift_message( 12, 15 ) is None

    def test_silent_when_count_hits_exactly( self ):
        """Explicit count, hit on the nose -> no warning."""
        agent = _agent( target_slide_count=40 )
        assert agent._slide_count_drift_message( 40, 40 ) is None

    def test_warns_with_both_numbers_when_under( self ):
        """Explicit 40 but 38 produced -> message names BOTH numbers."""
        agent = _agent( target_slide_count=40 )
        msg = agent._slide_count_drift_message( 38, 40 )
        assert msg is not None
        assert "40" in msg and "38" in msg

    def test_warns_with_both_numbers_when_over( self ):
        """Drift in the other direction is reported too (43 vs 40)."""
        agent = _agent( target_slide_count=40 )
        msg = agent._slide_count_drift_message( 43, 40 )
        assert msg is not None
        assert "40" in msg and "43" in msg


# =============================================================================
# The job -> config -> _slide_budget seam (Rachel's binding gate)
# =============================================================================

class TestJobToBudgetSeam:
    """
    A real caller's slide count must reach the number _slide_budget() returns.

    This is the seam the CLI / REST / voice break lived on: the job stores
    target_slide_count but, without the _apply_job_overrides copy, never puts it
    on the config that _slide_budget() reads — so config.target_slide_count is
    None on every non-INI path even when the user asked for 40, which ALSO
    silently disables the drift warning (it gates on that field). The prior
    budget tests built PresentationConfig directly and never traveled this seam,
    so they were green on a feature inert for 3 of 4 entry points.

    These start where the factory/CLI start — a JOB — and end at the budget.
    """

    def _job( self, **overrides ):
        base = dict( source_path="/io/inert.md", user_id="u", user_email="e@e.com",
                     session_id="s", dry_run=True )
        base.update( overrides )
        return PresentationGeneratorJob( **base )

    def _budget_via_job( self, config ):
        """Resolve the budget the way the pipeline does — through the orchestrator."""
        agent = PresentationOrchestratorAgent( source_path="/io/inert.md", user_id="u", config=config )
        return agent

    def test_job_slide_count_reaches_the_budget( self ):
        """JOB(target_slide_count=40) in a 60-min slot -> _slide_budget() == 40."""
        config = PresentationConfig()                       # INI-loaded defaults, count None
        self._job( target_slide_count=40, target_duration_minutes=60 )._apply_job_overrides( config )
        agent = self._budget_via_job( config )
        assert agent._slide_budget() == 40                  # NOT 60 (the formula)
        # And the drift warning is live on this path (was silenced when the copy was missing).
        assert agent._slide_count_drift_message( 38, 40 ) is not None

    def test_job_without_slide_count_uses_duration_formula( self ):
        """JOB with no slide count -> _slide_budget() follows duration (20 x 1.0)."""
        config = PresentationConfig()
        self._job( target_duration_minutes=20 )._apply_job_overrides( config )
        agent = self._budget_via_job( config )
        assert agent._slide_budget() == 20
        # No explicit count -> drift stays silent (additive-only on the default path).
        assert agent._slide_count_drift_message( 12, 20 ) is None
