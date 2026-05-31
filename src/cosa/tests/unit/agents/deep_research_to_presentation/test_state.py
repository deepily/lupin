#!/usr/bin/env python3
"""
Unit tests for cosa.agents.deep_research_to_presentation.state

Target module: PipelineState (enum) + ChainedResult (dataclass) with its three
methods is_success(), is_partial(), get_summary(). The presentation bridge's
"partial" gate keys off yaml_path (not audio_path), and get_summary reports
YAML + Marp paths.

All assertions are discriminating: exact enum values, default fields, full
predicate truth tables, and literal get_summary() branch content. No external
boundaries exist in this module.
"""

import pytest

from cosa.agents.deep_research_to_presentation.state import PipelineState, ChainedResult


class TestPipelineState:
    """
    Pin the PipelineState enum surface for the presentation bridge.

    Ensures:
        - every member maps to its exact lowercase value
        - the member set is exactly the eight documented states
    """

    def test_enum_member_values_are_exact( self ):
        assert PipelineState.INITIALIZED.value              == "initialized"
        assert PipelineState.RUNNING_DEEP_RESEARCH.value    == "running_deep_research"
        assert PipelineState.DEEP_RESEARCH_DONE.value       == "deep_research_done"
        assert PipelineState.RUNNING_PRESENTATION_GEN.value == "running_presentation_gen"
        assert PipelineState.PRESENTATION_GEN_DONE.value    == "presentation_gen_done"
        assert PipelineState.COMPLETED.value                == "completed"
        assert PipelineState.FAILED.value                   == "failed"
        assert PipelineState.CANCELLED.value                == "cancelled"

    def test_enum_member_set_is_complete( self ):
        names = { member.name for member in PipelineState }
        assert names == {
            "INITIALIZED", "RUNNING_DEEP_RESEARCH", "DEEP_RESEARCH_DONE",
            "RUNNING_PRESENTATION_GEN", "PRESENTATION_GEN_DONE", "COMPLETED",
            "FAILED", "CANCELLED",
        }


class TestChainedResultDefaults:
    """
    Pin the ChainedResult default-construction contract.

    Ensures:
        - path/abstract/slide_count optionals default to None
        - cost/timing floats default to 0.0
        - state defaults to INITIALIZED, error None
        - artifact dicts default to independent empty dicts
    """

    def test_default_field_values( self ):
        result = ChainedResult()

        assert result.research_path     is None
        assert result.research_abstract is None
        assert result.yaml_path         is None
        assert result.marp_path         is None
        assert result.slide_count       is None

        assert result.total_cost       == 0.0
        assert result.dr_cost          == 0.0
        assert result.pg_cost          == 0.0
        assert result.duration_seconds == 0.0

        assert result.started_at   is None
        assert result.completed_at is None

        assert result.state == PipelineState.INITIALIZED
        assert result.error is None

        assert result.dr_artifacts == {}
        assert result.pg_artifacts == {}

    def test_artifact_dicts_are_not_shared_between_instances( self ):
        a = ChainedResult()
        b = ChainedResult()
        a.pg_artifacts[ "k" ] = "v"
        assert a.pg_artifacts == { "k": "v" }
        assert b.pg_artifacts == {}


class TestIsSuccess:
    """
    Truth table for ChainedResult.is_success().

    Ensures True iff state == COMPLETED AND error is None; False otherwise.
    """

    def test_true_when_completed_and_no_error( self ):
        assert ChainedResult( state=PipelineState.COMPLETED, error=None ).is_success() is True

    def test_false_when_state_not_completed( self ):
        assert ChainedResult( state=PipelineState.RUNNING_PRESENTATION_GEN ).is_success() is False

    def test_false_when_completed_but_error_set( self ):
        assert ChainedResult( state=PipelineState.COMPLETED, error="x" ).is_success() is False


class TestIsPartial:
    """
    Truth table for ChainedResult.is_partial().

    True iff state in {DEEP_RESEARCH_DONE, FAILED} AND research_path set AND
    yaml_path is None. Each False sub-condition is exercised.
    """

    def test_true_when_dr_done_with_research_and_no_yaml( self ):
        result = ChainedResult(
            state=PipelineState.DEEP_RESEARCH_DONE, research_path="/io/dr/r.md", yaml_path=None
        )
        assert result.is_partial() is True

    def test_true_when_failed_with_research_and_no_yaml( self ):
        result = ChainedResult(
            state=PipelineState.FAILED, research_path="/io/dr/r.md", yaml_path=None
        )
        assert result.is_partial() is True

    def test_false_when_state_not_in_partial_set( self ):
        result = ChainedResult(
            state=PipelineState.COMPLETED, research_path="/io/dr/r.md", yaml_path=None
        )
        assert result.is_partial() is False

    def test_false_when_research_path_missing( self ):
        result = ChainedResult(
            state=PipelineState.FAILED, research_path=None, yaml_path=None
        )
        assert result.is_partial() is False

    def test_false_when_yaml_already_present( self ):
        result = ChainedResult(
            state=PipelineState.DEEP_RESEARCH_DONE, research_path="/io/dr/r.md", yaml_path="/io/p/x.yaml"
        )
        assert result.is_partial() is False


class TestGetSummary:
    """
    Cover all three get_summary() branches (success / partial / failed-else).

    Ensures literal content for each: success reports YAML + Marp paths and the
    formatted cost/duration line; partial reports research/error/DR-cost; else
    reports the failure error and state value.
    """

    def test_success_summary_content( self ):
        result = ChainedResult(
            research_path    = "/io/dr/quantum.md",
            yaml_path        = "/io/pres/quantum.yaml",
            marp_path        = "/io/pres/quantum.md",
            total_cost       = 2.5,
            dr_cost          = 1.75,
            pg_cost          = 0.75,
            duration_seconds = 180.5,
            state            = PipelineState.COMPLETED,
        )
        summary = result.get_summary()
        assert "Pipeline completed successfully." in summary
        assert "Research: /io/dr/quantum.md"  in summary
        assert "YAML: /io/pres/quantum.yaml"  in summary
        assert "Marp: /io/pres/quantum.md"    in summary
        assert "Total cost: $2.5000 (DR: $1.7500, PG: $0.7500)" in summary
        assert "Duration: 180.5s" in summary

    def test_partial_summary_content( self ):
        result = ChainedResult(
            research_path    = "/io/dr/report.md",
            state            = PipelineState.DEEP_RESEARCH_DONE,
            error            = "Presentation generation failed",
            dr_cost          = 1.25,
            duration_seconds = 42.0,
        )
        summary = result.get_summary()
        assert "Pipeline partially completed (research done, presentation failed)." in summary
        assert "/io/dr/report.md"                    in summary
        assert "Error: Presentation generation failed" in summary
        assert "DR cost: $1.2500"                    in summary
        assert "Duration: 42.0s"                     in summary

    def test_failed_summary_content( self ):
        result = ChainedResult( state=PipelineState.FAILED, error="API key not found" )
        summary = result.get_summary()
        assert "Pipeline failed: API key not found" in summary
        assert "State: failed" in summary
        assert "completed successfully" not in summary
        assert "partially completed"    not in summary
