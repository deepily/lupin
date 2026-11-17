#!/usr/bin/env python3
"""
Unit tests for the diagnosis reader the two fix expediters share.

The two orchestrator tests prove each expediter still builds its own result type from it.
"""

import pytest

from cosa.agents.shared.diagnosis_json import parse_diagnosis_json
from cosa.agents.bug_fix_expediter.orchestrator import BFEOrchestrator
from cosa.agents.test_fix_expediter.orchestrator import TFEOrchestrator


class TestParseDiagnosisJson:
    """Fence stripping, extraction and parsing, with the failure named."""

    def test_clean_json( self ):
        assert parse_diagnosis_json( '{"root_cause": "x"}' ) == ( { "root_cause": "x" }, None )

    def test_fenced_json_and_trailing_prose( self ):
        raw = 'Here is my analysis:\n\n```json\n{"root_cause": "x", "confidence": 0.9}\n```\n\nThat is my diagnosis.'
        assert parse_diagnosis_json( raw ) == ( { "root_cause": "x", "confidence": 0.9 }, None )

    def test_prose_with_braces_after_the_fence_is_cut_off( self ):
        """Without the cut at the closing fence, the last braces in the text would be the prose's."""
        raw = '```json\n{"root_cause": "x"}\n```\n\nNote {see above}'
        assert parse_diagnosis_json( raw ) == ( { "root_cause": "x" }, None )

    def test_json_embedded_in_prose( self ):
        assert parse_diagnosis_json( 'I think {"root_cause": "x"} is it' ) == ( { "root_cause": "x" }, None )

    def test_no_object( self ):
        assert parse_diagnosis_json( "no json here" ) == ( None, "no JSON object found" )

    def test_unparseable_object( self ):
        data, failure = parse_diagnosis_json( "{not: json}" )
        assert data is None
        assert failure.startswith( "invalid JSON: " )


class TestExpediterOrchestratorsUseIt:
    """Each expediter keeps its own result type and its own fallback."""

    RAW = '```json\n{"root_cause": "bad import", "error_category": "import", "confidence": 0.8, "evidence": ["e"], "affected_components": ["c"], "is_transient": false}\n```'

    def test_bfe_builds_its_diagnosis_result( self ):
        orch   = BFEOrchestrator.__new__( BFEOrchestrator )
        result = orch._parse_diagnosis_result( self.RAW )
        assert ( result.root_cause, result.confidence ) == ( "bad import", 0.8 )

    def test_bfe_falls_back_on_no_json( self ):
        orch   = BFEOrchestrator.__new__( BFEOrchestrator )
        result = orch._parse_diagnosis_result( "no json here" )
        assert ( result.root_cause, result.confidence ) == ( "no json here", 0.1 )

    def test_tfe_fills_in_the_cluster_id( self ):
        orch   = TFEOrchestrator.__new__( TFEOrchestrator )
        result = orch._parse_diagnosis_result( self.RAW, "C7" )
        assert ( result.cluster_id, result.root_cause ) == ( "C7", "bad import" )

    def test_tfe_falls_back_on_unparseable_object( self ):
        orch   = TFEOrchestrator.__new__( TFEOrchestrator )
        result = orch._parse_diagnosis_result( "{not: json}", "C7" )
        assert ( result.cluster_id, result.confidence ) == ( "C7", 0.1 )
