#!/usr/bin/env python3
"""
State definitions for Deep Research to Presentation pipeline.

Contains dataclasses for tracking pipeline state and results.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict, Any


class PipelineState( Enum ):
    """Pipeline execution state."""
    INITIALIZED              = "initialized"
    RUNNING_DEEP_RESEARCH    = "running_deep_research"
    DEEP_RESEARCH_DONE       = "deep_research_done"
    RUNNING_PRESENTATION_GEN = "running_presentation_gen"
    PRESENTATION_GEN_DONE    = "presentation_gen_done"
    COMPLETED                = "completed"
    FAILED                   = "failed"
    CANCELLED                = "cancelled"


@dataclass
class ChainedResult:
    """
    Result from the chained Deep Research → Presentation Generation pipeline.

    Attributes:
        research_path: Path to the generated research report markdown
        research_abstract: Brief summary of the research
        yaml_path: Path to the generated YAML intermediate file
        marp_path: Path to the generated Marp Markdown presentation
        slide_count: Number of slides in the generated presentation
        total_cost: Combined cost from both agents (USD)
        dr_cost: Cost from Deep Research (USD)
        pg_cost: Cost from Presentation Generator (USD)
        duration_seconds: Total pipeline execution time
        state: Final pipeline state
        error: Error message if pipeline failed
        dr_artifacts: Additional artifacts from Deep Research
        pg_artifacts: Additional artifacts from Presentation Generator
        started_at: Pipeline start timestamp
        completed_at: Pipeline completion timestamp
    """

    # Primary outputs
    research_path    : Optional[ str ] = None
    research_abstract: Optional[ str ] = None
    yaml_path        : Optional[ str ] = None
    marp_path        : Optional[ str ] = None
    slide_count      : Optional[ int ] = None

    # Cost tracking
    total_cost       : float = 0.0
    dr_cost          : float = 0.0
    pg_cost          : float = 0.0

    # Timing
    duration_seconds : float = 0.0
    started_at       : Optional[ str ] = None
    completed_at     : Optional[ str ] = None

    # State
    state            : PipelineState = PipelineState.INITIALIZED
    error            : Optional[ str ] = None

    # Additional artifacts
    dr_artifacts     : Dict[ str, Any ] = field( default_factory=dict )
    pg_artifacts     : Dict[ str, Any ] = field( default_factory=dict )

    def is_success( self ) -> bool:
        """Check if pipeline completed successfully."""
        return self.state == PipelineState.COMPLETED and self.error is None

    def is_partial( self ) -> bool:
        """Check if pipeline completed partially (DR done, PG failed)."""
        return (
            self.state in [ PipelineState.DEEP_RESEARCH_DONE, PipelineState.FAILED ]
            and self.research_path is not None
            and self.yaml_path is None
        )

    def get_summary( self ) -> str:
        """Get a human-readable summary of the result."""
        if self.is_success():
            return (
                f"Pipeline completed successfully.\n"
                f"  Research: {self.research_path}\n"
                f"  YAML: {self.yaml_path}\n"
                f"  Marp: {self.marp_path}\n"
                f"  Total cost: ${self.total_cost:.4f} "
                f"(DR: ${self.dr_cost:.4f}, PG: ${self.pg_cost:.4f})\n"
                f"  Duration: {self.duration_seconds:.1f}s"
            )
        elif self.is_partial():
            return (
                f"Pipeline partially completed (research done, presentation failed).\n"
                f"  Research: {self.research_path}\n"
                f"  Error: {self.error}\n"
                f"  DR cost: ${self.dr_cost:.4f}\n"
                f"  Duration: {self.duration_seconds:.1f}s"
            )
        else:
            return (
                f"Pipeline failed: {self.error}\n"
                f"  State: {self.state.value}"
            )


def quick_smoke_test():
    """Quick smoke test for state module."""
    import cosa.utils.util as cu

    cu.print_banner( "Deep Research to Presentation State Smoke Test", prepend_nl=True )

    try:
        # Test 1: PipelineState enum
        print( "Testing PipelineState enum..." )
        assert PipelineState.INITIALIZED.value == "initialized"
        assert PipelineState.COMPLETED.value == "completed"
        assert PipelineState.RUNNING_PRESENTATION_GEN.value == "running_presentation_gen"
        print( "✓ PipelineState enum works correctly" )

        # Test 2: ChainedResult creation
        print( "Testing ChainedResult creation..." )
        result = ChainedResult()
        assert result.state == PipelineState.INITIALIZED
        assert result.total_cost == 0.0
        assert result.research_path is None
        assert result.yaml_path is None
        print( "✓ ChainedResult default creation works" )

        # Test 3: ChainedResult with values
        print( "Testing ChainedResult with values..." )
        result = ChainedResult(
            research_path     = "/io/deep-research/user@test.com/2026.01.26-quantum.md",
            research_abstract = "Quantum computing overview",
            yaml_path         = "/io/presentations/user@test.com/2026.01.26-quantum.yaml",
            marp_path         = "/io/presentations/user@test.com/2026.01.26-quantum.md",
            total_cost        = 2.50,
            dr_cost           = 1.75,
            pg_cost           = 0.75,
            duration_seconds  = 180.5,
            state             = PipelineState.COMPLETED,
        )
        assert result.is_success()
        assert not result.is_partial()
        print( "✓ ChainedResult with values works" )

        # Test 4: Partial result
        print( "Testing partial result..." )
        partial = ChainedResult(
            research_path = "/io/deep-research/user@test.com/report.md",
            state         = PipelineState.DEEP_RESEARCH_DONE,
            error         = "Presentation generation failed",
        )
        assert not partial.is_success()
        assert partial.is_partial()
        print( "✓ Partial result detection works" )

        # Test 5: get_summary
        print( "Testing get_summary..." )
        summary = result.get_summary()
        assert "completed successfully" in summary
        assert "quantum" in summary
        print( "✓ get_summary works correctly" )

        # Test 6: Failed result summary
        print( "Testing failed result summary..." )
        failed = ChainedResult(
            state = PipelineState.FAILED,
            error = "API key not found",
        )
        summary = failed.get_summary()
        assert "failed" in summary.lower()
        assert "API key" in summary
        print( "✓ Failed result summary works" )

        print( "\n✓ State smoke test completed successfully" )

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
