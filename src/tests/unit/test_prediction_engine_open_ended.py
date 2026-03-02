"""
Unit tests for PredictionEngine open-ended and open-ended batch prediction.

Tests Slices 4 + 5: two-tier retrieval (exact match) + LLM synthesis
for open_ended and open_ended_batch response types.
"""

import json
import pytest
from unittest.mock import MagicMock, patch, PropertyMock


# ---------------------------------------------------------------------------
# TestPredictOpenEndedExactMatch — Tier 1 exact match retrieval
# ---------------------------------------------------------------------------

class TestPredictOpenEndedExactMatch:
    """Test _predict_open_ended() Tier 1: exact normalized question match."""

    def setup_method( self ):
        from cosa.agents.prediction_engine.prediction_engine import PredictionEngine
        PredictionEngine.reset()

    def _make_engine( self ):
        from cosa.agents.prediction_engine.prediction_engine import PredictionEngine
        engine = PredictionEngine( debug=True )
        engine._embedding_store    = MagicMock()
        engine._embedding_provider = MagicMock()
        return engine

    def test_cold_start_no_embedding( self ):
        """No embedding → cold_start."""
        engine = self._make_engine()
        result = engine._predict_open_ended( "What naming?", "input", None )
        assert result.strategy == "cold_start"
        assert result.metadata[ "reason" ] == "no_embedding"

    def test_cold_start_no_store( self ):
        """No embedding store → cold_start."""
        engine = self._make_engine()
        engine._get_embedding_store = MagicMock( return_value=None )
        result = engine._predict_open_ended( "What naming?", "input", [ 0.1 ] * 768 )
        assert result.strategy == "cold_start"
        assert result.metadata[ "reason" ] == "no_embedding_store"

    def test_cold_start_no_similar_cases( self ):
        """Empty similar cases → cold_start."""
        engine = self._make_engine()
        engine._embedding_store.find_similar.return_value = []
        result = engine._predict_open_ended( "What naming?", "input", [ 0.1 ] * 768 )
        assert result.strategy == "cold_start"
        assert result.metadata[ "reason" ] == "no_similar_cases"

    def test_exact_match_returns_top_case( self ):
        """Exact normalized match returns top case decision_value directly."""
        engine = self._make_engine()
        engine._embedding_store.find_similar.return_value = [
            ( 95.0, { "question": "What naming convention?", "decision_value": "snake_case" } ),
            ( 80.0, { "question": "Which naming pattern?", "decision_value": "camelCase" } ),
        ]
        result = engine._predict_open_ended( "What naming convention?", "input", [ 0.1 ] * 768 )

        assert result.strategy == "cbr_retrieval"
        assert result.predicted_value == "snake_case"
        assert result.metadata[ "tier" ] == "exact_match"

    def test_exact_match_confidence_is_similarity( self ):
        """Confidence equals top case similarity for exact match."""
        engine = self._make_engine()
        engine._embedding_store.find_similar.return_value = [
            ( 92.0, { "question": "  What naming?  ", "decision_value": "snake_case" } ),
        ]
        result = engine._predict_open_ended( "what naming?", "input", [ 0.1 ] * 768 )

        assert result.strategy == "cbr_retrieval"
        assert abs( result.confidence - 0.92 ) < 0.001


# ---------------------------------------------------------------------------
# TestPredictOpenEndedLLMSynthesis — Tier 2 LLM synthesis
# ---------------------------------------------------------------------------

class TestPredictOpenEndedLLMSynthesis:
    """Test _predict_open_ended() Tier 2: LLM synthesis when no exact match."""

    def setup_method( self ):
        from cosa.agents.prediction_engine.prediction_engine import PredictionEngine
        PredictionEngine.reset()

    def _make_engine( self ):
        from cosa.agents.prediction_engine.prediction_engine import PredictionEngine
        engine = PredictionEngine( debug=True )
        engine._embedding_store    = MagicMock()
        engine._embedding_provider = MagicMock()
        return engine

    def _mock_llm_xml_response( self, answer="snake_case", reasoning="consistent pattern", confidence="0.85" ):
        """Build a valid XML response string for OpenEndedSynthesisResponse."""
        return (
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<open_ended_synthesis_response>\n'
            f'    <predicted_answer>{answer}</predicted_answer>\n'
            f'    <reasoning>{reasoning}</reasoning>\n'
            f'    <confidence>{confidence}</confidence>\n'
            '</open_ended_synthesis_response>'
        )

    def test_no_exact_match_triggers_llm( self ):
        """Non-identical question triggers LLM synthesis."""
        engine = self._make_engine()
        engine._embedding_store.find_similar.return_value = [
            ( 90.0, { "question": "Which naming convention?", "decision_value": "snake_case" } ),
        ]

        mock_client = MagicMock()
        mock_client.run.return_value = self._mock_llm_xml_response()
        engine._llm_client = mock_client

        # Mock template loading
        with patch( "cosa.utils.util.get_file_as_string", return_value="### Instruction:\n{current_question}\n{case_count}\n{formatted_cases}\n{{PYDANTIC_XML_EXAMPLE}}\n### Response:" ):
            result = engine._predict_open_ended( "What naming pattern should I use?", "input", [ 0.1 ] * 768 )

        assert result.strategy == "llm_synthesis"
        assert result.predicted_value == "snake_case"

    def test_llm_synthesis_strategy( self ):
        """LLM synthesis returns STRATEGY_LLM_SYNTHESIS."""
        engine = self._make_engine()
        engine._embedding_store.find_similar.return_value = [
            ( 88.0, { "question": "Which naming?", "decision_value": "camelCase" } ),
        ]

        mock_client = MagicMock()
        mock_client.run.return_value = self._mock_llm_xml_response( answer="snake_case" )
        engine._llm_client = mock_client

        with patch( "cosa.utils.util.get_file_as_string", return_value="{current_question}\n{case_count}\n{formatted_cases}\n{{PYDANTIC_XML_EXAMPLE}}" ):
            result = engine._predict_open_ended( "What naming style?", "input", [ 0.1 ] * 768 )

        assert result.strategy == "llm_synthesis"
        assert result.metadata[ "tier" ] == "llm_synthesis"

    def test_llm_failure_falls_back_to_retrieval( self ):
        """LLM call failure falls back to top case retrieval."""
        engine = self._make_engine()
        engine._embedding_store.find_similar.return_value = [
            ( 88.0, { "question": "Which naming?", "decision_value": "camelCase" } ),
        ]

        mock_client = MagicMock()
        mock_client.run.side_effect = RuntimeError( "LLM unavailable" )
        engine._llm_client = mock_client

        with patch( "cosa.utils.util.get_file_as_string", return_value="{current_question}\n{case_count}\n{formatted_cases}\n{{PYDANTIC_XML_EXAMPLE}}" ):
            result = engine._predict_open_ended( "What naming style?", "input", [ 0.1 ] * 768 )

        assert result.strategy == "cbr_retrieval"
        assert result.predicted_value == "camelCase"
        assert result.metadata[ "tier" ] == "llm_fallback"

    def test_confidence_capped_by_similarity( self ):
        """Final confidence is min(similarity, llm_confidence)."""
        engine = self._make_engine()
        engine._embedding_store.find_similar.return_value = [
            ( 80.0, { "question": "Which naming?", "decision_value": "camelCase" } ),
        ]

        mock_client = MagicMock()
        # LLM says 0.95 confidence but similarity is only 0.80
        mock_client.run.return_value = self._mock_llm_xml_response( confidence="0.95" )
        engine._llm_client = mock_client

        with patch( "cosa.utils.util.get_file_as_string", return_value="{current_question}\n{case_count}\n{formatted_cases}\n{{PYDANTIC_XML_EXAMPLE}}" ):
            result = engine._predict_open_ended( "What naming style?", "input", [ 0.1 ] * 768 )

        assert result.confidence <= 0.80 + 0.001

    def test_reasoning_in_metadata( self ):
        """Synthesis reasoning appears in metadata."""
        engine = self._make_engine()
        engine._embedding_store.find_similar.return_value = [
            ( 90.0, { "question": "Which naming?", "decision_value": "camelCase" } ),
        ]

        mock_client = MagicMock()
        mock_client.run.return_value = self._mock_llm_xml_response( reasoning="user prefers snake_case consistently" )
        engine._llm_client = mock_client

        with patch( "cosa.utils.util.get_file_as_string", return_value="{current_question}\n{case_count}\n{formatted_cases}\n{{PYDANTIC_XML_EXAMPLE}}" ):
            result = engine._predict_open_ended( "What naming style?", "input", [ 0.1 ] * 768 )

        assert "snake_case consistently" in result.metadata[ "synthesis_reasoning" ]

    def test_formatted_cases_in_prompt( self ):
        """_build_synthesis_prompt includes formatted cases."""
        engine = self._make_engine()
        similar_cases = [
            ( 90.0, { "question": "Which naming?", "decision_value": "snake_case" } ),
            ( 85.0, { "question": "What convention?", "decision_value": "camelCase" } ),
        ]

        with patch( "cosa.utils.util.get_file_as_string", return_value="{current_question}\n{case_count}\n{formatted_cases}\n{{PYDANTIC_XML_EXAMPLE}}" ):
            prompt = engine._build_synthesis_prompt( "What style?", similar_cases )

        assert 'n="1"' in prompt
        assert 'n="2"' in prompt
        assert "snake_case" in prompt
        assert "camelCase" in prompt
        assert "What style?" in prompt


# ---------------------------------------------------------------------------
# TestPredictOpenEndedBatch — open_ended_batch prediction
# ---------------------------------------------------------------------------

class TestPredictOpenEndedBatch:
    """Test _predict_open_ended_batch()."""

    def setup_method( self ):
        from cosa.agents.prediction_engine.prediction_engine import PredictionEngine
        PredictionEngine.reset()

    def _make_engine( self ):
        from cosa.agents.prediction_engine.prediction_engine import PredictionEngine
        engine = PredictionEngine( debug=True )
        engine._embedding_store    = MagicMock()
        engine._embedding_provider = MagicMock()
        return engine

    def _mock_llm_xml_response( self, answer='{"answers": {"Topic": "quantum"}}', reasoning="common pattern", confidence="0.80" ):
        return (
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<open_ended_synthesis_response>\n'
            f'    <predicted_answer>{answer}</predicted_answer>\n'
            f'    <reasoning>{reasoning}</reasoning>\n'
            f'    <confidence>{confidence}</confidence>\n'
            '</open_ended_synthesis_response>'
        )

    def test_cold_start_no_embedding( self ):
        """No embedding → cold_start."""
        engine = self._make_engine()
        result = engine._predict_open_ended_batch( "Questions", "input", None )
        assert result.strategy == "cold_start"
        assert result.response_type == "open_ended_batch"

    def test_exact_match_returns_parsed_dict( self ):
        """Exact match returns JSON-parsed dict with answers."""
        engine = self._make_engine()
        batch_json = json.dumps( { "answers": { "Topic": "quantum", "Budget": "none" } } )
        engine._embedding_store.find_similar.return_value = [
            ( 95.0, { "question": "project details", "decision_value": batch_json } ),
        ]
        result = engine._predict_open_ended_batch( "project details", "input", [ 0.1 ] * 768 )

        assert result.strategy == "cbr_retrieval"
        assert isinstance( result.predicted_value, dict )
        assert result.predicted_value[ "answers" ][ "Topic" ] == "quantum"

    def test_llm_synthesis_returns_compound_answers( self ):
        """LLM synthesis returns compound dict."""
        engine = self._make_engine()
        engine._embedding_store.find_similar.return_value = [
            ( 88.0, { "question": "project info", "decision_value": json.dumps( { "answers": { "Topic": "AI" } } ) } ),
        ]

        mock_client = MagicMock()
        mock_client.run.return_value = self._mock_llm_xml_response()
        engine._llm_client = mock_client

        with patch( "cosa.utils.util.get_file_as_string", return_value="{current_question}\n{case_count}\n{formatted_cases}\n{{PYDANTIC_XML_EXAMPLE}}" ):
            result = engine._predict_open_ended_batch( "project details", "input", [ 0.1 ] * 768 )

        assert result.strategy == "llm_synthesis"

    def test_json_parse_fallback_returns_string( self ):
        """Non-JSON decision value returns raw string."""
        engine = self._make_engine()
        engine._embedding_store.find_similar.return_value = [
            ( 95.0, { "question": "project details", "decision_value": "just a plain text answer" } ),
        ]
        result = engine._predict_open_ended_batch( "project details", "input", [ 0.1 ] * 768 )

        assert result.strategy == "cbr_retrieval"
        assert result.predicted_value == "just a plain text answer"

    def test_batch_strategy( self ):
        """Response type is open_ended_batch."""
        engine = self._make_engine()
        engine._embedding_store.find_similar.return_value = []
        result = engine._predict_open_ended_batch( "details", "input", [ 0.1 ] * 768 )
        assert result.response_type == "open_ended_batch"


# ---------------------------------------------------------------------------
# TestBuildSynthesisPrompt
# ---------------------------------------------------------------------------

class TestBuildSynthesisPrompt:
    """Test _build_synthesis_prompt() template building."""

    def setup_method( self ):
        from cosa.agents.prediction_engine.prediction_engine import PredictionEngine
        PredictionEngine.reset()

    def _make_engine( self ):
        from cosa.agents.prediction_engine.prediction_engine import PredictionEngine
        engine = PredictionEngine( debug=True )
        return engine

    def test_template_loaded( self ):
        """Template file is loaded via cu.get_file_as_string."""
        engine = self._make_engine()
        cases  = [ ( 90.0, { "question": "Q1", "decision_value": "A1" } ) ]

        with patch( "cosa.utils.util.get_file_as_string", return_value="TEMPLATE {current_question} {case_count} {formatted_cases} {{PYDANTIC_XML_EXAMPLE}}" ) as mock_get:
            prompt = engine._build_synthesis_prompt( "test question", cases )
            mock_get.assert_called_once()
            assert "test question" in prompt

    def test_cases_formatted_as_xml( self ):
        """Cases appear as numbered XML blocks."""
        engine = self._make_engine()
        cases  = [
            ( 90.0, { "question": "Q1", "decision_value": "A1" } ),
            ( 85.0, { "question": "Q2", "decision_value": "A2" } ),
        ]

        with patch( "cosa.utils.util.get_file_as_string", return_value="{current_question} {case_count} {formatted_cases} {{PYDANTIC_XML_EXAMPLE}}" ):
            prompt = engine._build_synthesis_prompt( "test", cases )

        assert '<case n="1"' in prompt
        assert '<case n="2"' in prompt
        assert "<question>Q1</question>" in prompt
        assert "<response>A2</response>" in prompt

    def test_current_question_injected( self ):
        """Current question replaces {current_question} placeholder."""
        engine = self._make_engine()
        cases  = [ ( 90.0, { "question": "Q1", "decision_value": "A1" } ) ]

        with patch( "cosa.utils.util.get_file_as_string", return_value="{current_question} {case_count} {formatted_cases} {{PYDANTIC_XML_EXAMPLE}}" ):
            prompt = engine._build_synthesis_prompt( "my specific question", cases )

        assert "my specific question" in prompt

    def test_pydantic_example_present( self ):
        """{{PYDANTIC_XML_EXAMPLE}} is replaced with XML example."""
        engine = self._make_engine()
        cases  = [ ( 90.0, { "question": "Q1", "decision_value": "A1" } ) ]

        with patch( "cosa.utils.util.get_file_as_string", return_value="{current_question} {case_count} {formatted_cases} {{PYDANTIC_XML_EXAMPLE}}" ):
            prompt = engine._build_synthesis_prompt( "test", cases )

        assert "<open_ended_synthesis_response>" in prompt
        assert "</stop>" in prompt


# ---------------------------------------------------------------------------
# TestCompareOpenEnded
# ---------------------------------------------------------------------------

class TestCompareOpenEnded:
    """Test compare_open_ended() with dual strategy."""

    def test_embedding_sim_above_threshold( self ):
        """Embedding similarity >= 0.85 → match."""
        from cosa.agents.prediction_engine.accuracy_comparators import compare_open_ended
        match, detail = compare_open_ended(
            { "value": "snake_case" },
            { "value": "use snake_case", "_embedding_similarity": 0.92 }
        )
        assert match is True
        assert detail[ "method" ] == "embedding_similarity"

    def test_embedding_sim_below_threshold( self ):
        """Embedding similarity < 0.85 → no match."""
        from cosa.agents.prediction_engine.accuracy_comparators import compare_open_ended
        match, detail = compare_open_ended(
            { "value": "snake_case" },
            { "value": "camelCase", "_embedding_similarity": 0.60 }
        )
        assert match is False
        assert detail[ "threshold" ] == 0.85

    def test_exact_match_fallback( self ):
        """No embedding sim → falls back to exact match."""
        from cosa.agents.prediction_engine.accuracy_comparators import compare_open_ended
        match, detail = compare_open_ended(
            { "value": "snake_case" },
            { "value": "snake_case" }
        )
        assert match is True
        assert detail[ "method" ] == "exact_match"

    def test_none_handling( self ):
        """None predicted → (None, reason)."""
        from cosa.agents.prediction_engine.accuracy_comparators import compare_open_ended
        match, detail = compare_open_ended( None, { "value": "test" } )
        assert match is None
        assert detail[ "reason" ] == "missing_data"

    def test_detail_method_field( self ):
        """Detail dict includes method field."""
        from cosa.agents.prediction_engine.accuracy_comparators import compare_open_ended
        _, detail = compare_open_ended(
            { "value": "a" },
            { "value": "b", "_embedding_similarity": 0.50 }
        )
        assert "method" in detail


# ---------------------------------------------------------------------------
# TestCompareOpenEndedBatch
# ---------------------------------------------------------------------------

class TestCompareOpenEndedBatch:
    """Test compare_open_ended_batch() with per-header similarity."""

    def test_per_header_sim_above_threshold( self ):
        """Per-header embedding similarity above threshold → match."""
        from cosa.agents.prediction_engine.accuracy_comparators import compare_open_ended_batch
        match, detail = compare_open_ended_batch(
            { "answers": { "Topic": "quantum", "Budget": "none" } },
            { "answers": { "Topic": "quantum", "Budget": "none" },
              "_embedding_similarity": { "Topic": 0.95, "Budget": 0.90 } }
        )
        assert match is True
        assert detail[ "avg_similarity" ] >= 0.85

    def test_mixed_headers( self ):
        """Mixed high/low similarity → below threshold."""
        from cosa.agents.prediction_engine.accuracy_comparators import compare_open_ended_batch
        match, detail = compare_open_ended_batch(
            { "answers": { "Topic": "quantum", "Budget": "none" } },
            { "answers": { "Topic": "quantum", "Budget": "none" },
              "_embedding_similarity": { "Topic": 0.95, "Budget": 0.30 } }
        )
        avg = ( 0.95 + 0.30 ) / 2.0
        assert match is ( avg >= 0.85 )

    def test_exact_match_fallback( self ):
        """No embedding sim → exact match per header."""
        from cosa.agents.prediction_engine.accuracy_comparators import compare_open_ended_batch
        match, detail = compare_open_ended_batch(
            { "answers": { "Topic": "quantum" } },
            { "answers": { "Topic": "quantum" } }
        )
        assert match is True
        assert detail[ "header_details" ][ "Topic" ][ "method" ] == "exact_match"

    def test_none_handling( self ):
        """None predicted → (None, reason)."""
        from cosa.agents.prediction_engine.accuracy_comparators import compare_open_ended_batch
        match, detail = compare_open_ended_batch( None, { "answers": { "Topic": "q" } } )
        assert match is None

    def test_empty_answers( self ):
        """Empty answers → (None, reason)."""
        from cosa.agents.prediction_engine.accuracy_comparators import compare_open_ended_batch
        match, detail = compare_open_ended_batch(
            { "answers": {} },
            { "answers": { "Topic": "q" } }
        )
        assert match is None
        assert detail[ "reason" ] == "empty_answers"


# ---------------------------------------------------------------------------
# TestEnrichEmbeddingSimilarity
# ---------------------------------------------------------------------------

class TestEnrichEmbeddingSimilarity:
    """Test _enrich_with_embedding_similarity()."""

    def setup_method( self ):
        from cosa.agents.prediction_engine.prediction_engine import PredictionEngine
        PredictionEngine.reset()

    def _make_engine( self ):
        from cosa.agents.prediction_engine.prediction_engine import PredictionEngine
        engine = PredictionEngine( debug=True )
        engine._embedding_provider = MagicMock()
        return engine

    def test_open_ended_sim_injected( self ):
        """open_ended: _embedding_similarity injected as float."""
        from cosa.agents.prediction_engine.prediction_result import PredictionResult
        import numpy as np

        engine = self._make_engine()
        # Mock embeddings that give cosine sim ~ 0.9
        vec_a = np.random.randn( 768 ).astype( float )
        vec_a = ( vec_a / np.linalg.norm( vec_a ) ).tolist()
        engine._generate_embedding = MagicMock( return_value=vec_a )

        actual_dict = { "value": "snake_case" }
        pred_result = PredictionResult(
            response_type   = "open_ended",
            category        = "input",
            strategy        = "llm_synthesis",
            predicted_value = "snake_case",
            confidence      = 0.85
        )
        engine._enrich_with_embedding_similarity( actual_dict, pred_result, "open_ended" )

        assert "_embedding_similarity" in actual_dict
        # Same vector → cosine sim = 1.0
        assert abs( actual_dict[ "_embedding_similarity" ] - 1.0 ) < 0.01

    def test_batch_per_header_sim( self ):
        """open_ended_batch: per-header similarity dict injected."""
        from cosa.agents.prediction_engine.prediction_result import PredictionResult
        import numpy as np

        engine = self._make_engine()
        vec = np.random.randn( 768 ).astype( float )
        vec = ( vec / np.linalg.norm( vec ) ).tolist()
        engine._generate_embedding = MagicMock( return_value=vec )

        actual_dict = { "answers": { "Topic": "quantum", "Budget": "none" } }
        pred_result = PredictionResult(
            response_type   = "open_ended_batch",
            category        = "input",
            strategy        = "llm_synthesis",
            predicted_value = { "answers": { "Topic": "quantum", "Budget": "none" } },
            confidence      = 0.80
        )
        engine._enrich_with_embedding_similarity( actual_dict, pred_result, "open_ended_batch" )

        assert "_embedding_similarity" in actual_dict
        assert isinstance( actual_dict[ "_embedding_similarity" ], dict )
        assert "Topic" in actual_dict[ "_embedding_similarity" ]

    def test_cold_start_no_enrichment( self ):
        """Cold start prediction (predicted_value=None) → no enrichment."""
        from cosa.agents.prediction_engine.prediction_result import PredictionResult

        engine = self._make_engine()
        actual_dict = { "value": "test" }
        pred_result = PredictionResult(
            response_type = "open_ended",
            category      = "input",
            strategy      = "cold_start",
        )
        engine._enrich_with_embedding_similarity( actual_dict, pred_result, "open_ended" )
        assert "_embedding_similarity" not in actual_dict

    def test_embedding_failure_graceful( self ):
        """Embedding generation failure → no exception, no key injected."""
        from cosa.agents.prediction_engine.prediction_result import PredictionResult

        engine = self._make_engine()
        engine._generate_embedding = MagicMock( return_value=None )

        actual_dict = { "value": "test" }
        pred_result = PredictionResult(
            response_type   = "open_ended",
            category        = "input",
            strategy        = "llm_synthesis",
            predicted_value = "test",
            confidence      = 0.80
        )
        # Should not raise
        engine._enrich_with_embedding_similarity( actual_dict, pred_result, "open_ended" )
        assert "_embedding_similarity" not in actual_dict


# ---------------------------------------------------------------------------
# TestGetComparatorOpenEnded
# ---------------------------------------------------------------------------

class TestGetComparatorOpenEnded:
    """Test get_comparator() dispatch for open-ended types."""

    def test_open_ended_dispatch( self ):
        """open_ended → compare_open_ended."""
        from cosa.agents.prediction_engine.accuracy_comparators import get_comparator, compare_open_ended
        comp = get_comparator( "open_ended" )
        assert comp is compare_open_ended

    def test_open_ended_batch_dispatch( self ):
        """open_ended_batch → compare_open_ended_batch."""
        from cosa.agents.prediction_engine.accuracy_comparators import get_comparator, compare_open_ended_batch
        comp = get_comparator( "open_ended_batch" )
        assert comp is compare_open_ended_batch
