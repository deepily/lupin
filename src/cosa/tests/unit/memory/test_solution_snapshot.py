"""
Unit tests for cosa.memory.solution_snapshot.SolutionSnapshot.

REWRITTEN 2026-05-31 by Sam 🎙️ (memory takeover, CoSA coverage campaign). The
prior tests were value-object assertion drift, not dep-mock wiring:
  - test_static_methods / test_hash_generation asserted generate_id_hash()
    differs by push_counter — but the CURRENT contract (documented) IGNORES
    push_counter and hashes run_date ONLY (sha256(run_date)). Re-synced: same
    run_date → SAME hash; different run_date → different. (Verified intended,
    not a bug — no STOP-flag.)
  - the question_normalized tests left get_embedding_provider UNMOCKED, so
    constructing SolutionSnapshot(question=...) fired the REAL lupin-model-server
    embedding call (the M1 trap). Both module-bound deps (EmbeddingManager +
    get_embedding_provider) are now mocked.
  - test_initialization_with_content referenced an undefined mock_write_file and
    asserted on the wrong embedding object (_embedding_mgr vs the real
    _embedding_provider). Rewritten against the real provider path.

Reviewed by Mr. Radio (no self-audit).
"""
import unittest
from collections import OrderedDict
from contextlib import contextmanager
from unittest.mock import Mock, patch

from cosa.memory.solution_snapshot import SolutionSnapshot

_DUMMY_EMB = [ 0.1 ] * 768


@contextmanager
def _embed_mocked( generate_returns=None ):
    """Mock the construction-time embedding deps so no real model-server I/O occurs."""
    provider = Mock()
    if generate_returns is not None:
        provider.generate_embedding.side_effect = generate_returns
    else:
        provider.generate_embedding.return_value = _DUMMY_EMB
    with patch( "cosa.memory.solution_snapshot.EmbeddingManager" ), \
         patch( "cosa.memory.solution_snapshot.get_embedding_provider", return_value=provider ), \
         patch( "cosa.memory.solution_snapshot.du.get_current_datetime", return_value="2025-08-05-12-00-00" ), \
         patch( "builtins.print" ):
        yield provider


class TestStaticMethods( unittest.TestCase ):
    """Pure static utilities — no construction needed."""

    def test_get_timestamp( self ):
        with patch( "cosa.memory.solution_snapshot.du.get_current_datetime", return_value="2025-08-05-12-00-00" ):
            self.assertEqual( SolutionSnapshot.get_timestamp(), "2025-08-05-12-00-00" )

    def test_remove_non_alphanumerics( self ):
        self.assertEqual( SolutionSnapshot.remove_non_alphanumerics( "Hello, World!" ), "hello world" )
        self.assertEqual( SolutionSnapshot.remove_non_alphanumerics( "Test-123_ABC" ), "test123abc" )

    def test_escape_single_quotes( self ):
        self.assertEqual( SolutionSnapshot.escape_single_quotes( "It's working" ), "Its working" )
        self.assertEqual( SolutionSnapshot.escape_single_quotes( "No quotes" ), "No quotes" )

    def test_generate_id_hash_run_date_only( self ):
        # Documented contract: push_counter is IGNORED; only run_date drives the hash.
        h1 = SolutionSnapshot.generate_id_hash( 1, "2025-08-05" )
        h2 = SolutionSnapshot.generate_id_hash( 2, "2025-08-05" )   # same date, diff counter
        h3 = SolutionSnapshot.generate_id_hash( 1, "2025-08-06" )   # diff date
        self.assertEqual( h1, h2 )                                  # counter ignored
        self.assertNotEqual( h1, h3 )                               # date drives uniqueness
        self.assertEqual( h1, SolutionSnapshot.generate_id_hash( 1, "2025-08-05" ) )  # deterministic
        self.assertEqual( len( h1 ), 64 )                           # sha256 hex

    def test_default_stats_dict( self ):
        stats = SolutionSnapshot.get_default_stats_dict()
        for key in ( "first_run_ms", "run_count", "total_ms", "mean_run_ms", "last_run_ms", "time_saved_ms" ):
            self.assertIn( key, stats )
            self.assertIsInstance( stats[ key ], ( int, float ) )

    def test_embedding_similarity( self ):
        self.assertEqual( SolutionSnapshot.get_embedding_similarity( [ 1.0, 0.0, 0.0 ], [ 1.0, 0.0, 0.0 ] ), 100.0 )
        self.assertEqual( SolutionSnapshot.get_embedding_similarity( [ 1.0, 0.0, 0.0 ], [ 0.0, 1.0, 0.0 ] ), 0.0 )


class TestInitialization( unittest.TestCase ):
    """Construction: minimal (no embeddings), with-content, pre-existing embeddings."""

    def test_minimal_generates_no_embeddings( self ):
        with _embed_mocked() as provider:
            snap = SolutionSnapshot( debug=False )
        self.assertEqual( snap.push_counter, -1 )
        self.assertEqual( snap.question, "" )
        self.assertIsInstance( snap.runtime_stats, dict )
        provider.generate_embedding.assert_not_called()      # no content → no embeds

    def test_with_content_generates_embeddings_via_provider( self ):
        with _embed_mocked() as provider:
            snap = SolutionSnapshot(
                push_counter=1,
                question="What's 2+2?",
                question_gist="what is two plus two",
                code=[ "result = 2 + 2", "print(result)" ],
                debug=False,
            )
        # Embeddings come from the REAL provider path (_embedding_provider), not _embedding_mgr.
        self.assertTrue( provider.generate_embedding.called )
        self.assertEqual( snap.question_embedding, _DUMMY_EMB )
        self.assertEqual( snap.code_embedding, _DUMMY_EMB )
        self.assertEqual( snap.question_gist, "what is two plus two" )

    def test_existing_embeddings_are_preserved_not_regenerated( self ):
        existing_q = [ 0.5 ] * 768
        existing_code = [ 0.7 ] * 768
        with _embed_mocked() as provider:
            snap = SolutionSnapshot(
                question="Test question",
                question_gist="test gist",
                code=[ "test code" ],
                question_embedding=existing_q,
                question_gist_embedding=[ 0.6 ] * 768,
                code_embedding=existing_code,
                debug=False,
            )
        provider.generate_embedding.assert_not_called()
        self.assertEqual( snap.question_embedding, existing_q )
        self.assertEqual( snap.code_embedding, existing_code )

    def test_metadata_preserved( self ):
        with _embed_mocked():
            snap = SolutionSnapshot(
                runtime_stats={ "custom_stat": 42 },
                user_id="test_user_123",
                solution_directory="/custom/path/",
                programming_language="JavaScript",
                language_version="ES2021",
                debug=False,
            )
        self.assertEqual( snap.runtime_stats, { "custom_stat": 42 } )
        self.assertEqual( snap.user_id, "test_user_123" )
        self.assertEqual( snap.programming_language, "JavaScript" )


class TestHashAndSynonyms( unittest.TestCase ):
    """id_hash auto-generation/preservation + synonymous-question storage."""

    def test_auto_hash_and_provided_hash( self ):
        with _embed_mocked():
            auto = SolutionSnapshot( push_counter=1, debug=False )
            custom = SolutionSnapshot( push_counter=2, id_hash="custom_hash_123", debug=False )
        self.assertIsInstance( auto.id_hash, str )
        self.assertNotEqual( auto.id_hash, "" )
        self.assertEqual( custom.id_hash, "custom_hash_123" )   # provided hash preserved

    def test_same_run_date_yields_same_hash( self ):
        # Both snapshots get the same patched run_date → identical id_hash (counter ignored).
        with _embed_mocked():
            s1 = SolutionSnapshot( push_counter=1, debug=False )
            s3 = SolutionSnapshot( push_counter=3, debug=False )
        self.assertEqual( s1.id_hash, s3.id_hash )

    def test_synonymous_questions_preserved( self ):
        syn_q = OrderedDict( [ ( "What is 2+2?", 95.0 ), ( "Calculate 2+2", 90.0 ) ] )
        syn_g = OrderedDict( [ ( "two plus two", 95.0 ) ] )
        with _embed_mocked():
            snap = SolutionSnapshot(
                question="What's 2+2?", question_gist="whats two plus two",
                synonymous_questions=syn_q, synonymous_question_gists=syn_g, debug=False,
            )
        self.assertEqual( snap.synonymous_questions, syn_q )
        self.assertEqual( snap.synonymous_question_gists, syn_g )


class TestQuestionNormalizedField( unittest.TestCase ):
    """The three-level question_normalized field (init / absence / edge cases)."""

    def test_field_initialized( self ):
        with _embed_mocked():
            snap = SolutionSnapshot(
                question="What time is it?", question_normalized="what time be it",
                answer="It is 3:00 PM", debug=False,
            )
        self.assertEqual( snap.question_normalized, "what time be it" )
        self.assertEqual( snap.question, "What time is it?" )
        self.assertEqual( snap.answer, "It is 3:00 PM" )

    def test_absent_is_derived_from_question( self ):
        # When question_normalized is not supplied, __init__ derives it from the
        # question (alnum-lowercased): "What time is it?" → "what time is it".
        with _embed_mocked():
            snap = SolutionSnapshot( question="What time is it?", answer="3 PM", debug=False )
        self.assertEqual( snap.question_normalized, "what time is it" )

    def test_edge_cases_falsy_derived_truthy_preserved( self ):
        with _embed_mocked():
            empty = SolutionSnapshot( question="q", question_normalized="", answer="a", debug=False )
            long_text = "very long normalized text " * 100
            long_ = SolutionSnapshot( question="q", question_normalized=long_text, answer="a", debug=False )
        self.assertEqual( empty.question_normalized, "q" )       # falsy → derived from question
        self.assertEqual( long_.question_normalized, long_text ) # truthy → preserved verbatim


if __name__ == "__main__":
    unittest.main()
