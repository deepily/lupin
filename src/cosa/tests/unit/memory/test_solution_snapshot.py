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


def _codeless_agent():
    """
    A stand-in for an agent whose prompt_response_dict carries NO "code" key.

    CalculatorAgent's dispatch path is exactly this shape: it answers from pure
    Python and never generates code, so `.get( "code", ... )` falls to its default.
    """
    agent = Mock()
    agent.last_question_asked  = "How much is 789 minus 456?"
    agent.question             = "How much is 789 minus 456?"
    agent.question_gist        = "how much is 789 minus 456"
    agent.routing_command      = "agent router go to calculator"
    agent.answer_conversational = "789 minus 456 is 333."
    agent.user_id              = "u1"
    agent.user_email           = "e@example.com"
    agent.session_id           = "s1"
    agent.id_hash              = "abc123"
    agent.prompt_response_dict = { "operation": "arithmetic", "confidence": "0.98" }
    agent.code_response_dict   = { "return_code": 0, "output": 333 }
    return agent


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


class TestEmptyCodeNeverReachesTheEmbedder( unittest.TestCase ):
    """
    Falsification suite for bug b35af923.

    A job that has already produced and notified its answer must not then die in
    the dead queue because the snapshot tried to embed an empty string. Two
    independently-sufficient ends are pinned here: the PRODUCER default that
    manufactured [ "" ], and the CONSUMER guard that tested the list's length
    instead of the text it joins to.
    """

    # ── the CONSUMER end: a list that joins to nothing must not be embedded ──

    def test_list_holding_one_empty_string_is_not_embedded( self ):
        """[ "" ] has length 1 but joins to "" — the exact shape that 422'd."""
        with _embed_mocked() as provider:
            snap = SolutionSnapshot( question="q", code=[ "" ], debug=False )
        for call in provider.generate_embedding.call_args_list:
            self.assertNotEqual( call[ 0 ][ 0 ], "", "an empty string reached the embedder" )
        self.assertEqual( snap.code_embedding, [] )

    def test_list_of_several_empty_strings_is_not_embedded( self ):
        """[ "", "" ] joins to " " — whitespace only, still nothing to embed."""
        with _embed_mocked() as provider:
            snap = SolutionSnapshot( question="q", code=[ "", "" ], debug=False )
        for call in provider.generate_embedding.call_args_list:
            self.assertTrue( call[ 0 ][ 0 ].strip(), "a blank string reached the embedder" )
        self.assertEqual( snap.code_embedding, [] )

    def test_whitespace_only_lines_are_not_embedded( self ):
        """Indentation-only lines carry no code."""
        with _embed_mocked() as provider:
            snap = SolutionSnapshot( question="q", code=[ "   ", "\t" ], debug=False )
        for call in provider.generate_embedding.call_args_list:
            self.assertTrue( call[ 0 ][ 0 ].strip() )
        self.assertEqual( snap.code_embedding, [] )

    def test_empty_list_is_not_embedded( self ):
        """The already-correct case stays correct."""
        with _embed_mocked() as provider:
            snap = SolutionSnapshot( question="q", code=[], debug=False )
        self.assertEqual( snap.code_embedding, [] )

    def test_real_code_is_still_embedded( self ):
        """The guard must not become so strict that it stops embedding real code."""
        with _embed_mocked() as provider:
            snap = SolutionSnapshot( question="q", code=[ "x = 1", "print( x )" ], debug=False )
        self.assertEqual( snap.code_embedding, _DUMMY_EMB )
        embedded = [ c[ 0 ][ 0 ] for c in provider.generate_embedding.call_args_list ]
        self.assertIn( "x = 1 print( x )", embedded )

    def test_code_with_one_blank_line_among_real_lines_is_embedded( self ):
        """A blank line inside real code is not a reason to skip the embedding."""
        with _embed_mocked() as provider:
            snap = SolutionSnapshot( question="q", code=[ "x = 1", "", "print( x )" ], debug=False )
        self.assertEqual( snap.code_embedding, _DUMMY_EMB )

    # ── the PRODUCER end: the default handed to the constructor ──

    def test_create_defaults_missing_code_to_empty_list( self ):
        """
        An agent with no "code" key — CalculatorAgent's dispatch path is exactly
        this — must yield [], matching the constructor's own default, not [ "" ].
        """
        agent = _codeless_agent()
        with _embed_mocked():
            snap = SolutionSnapshot.create( agent )
        self.assertEqual( snap.code, [] )

    def test_create_on_a_codeless_agent_embeds_no_empty_string( self ):
        """The end-to-end shape of the bug: create() must not 422."""
        agent = _codeless_agent()
        with _embed_mocked() as provider:
            snap = SolutionSnapshot.create( agent )
        for call in provider.generate_embedding.call_args_list:
            self.assertTrue( call[ 0 ][ 0 ].strip(), "create() sent an empty string to the embedder" )
        self.assertEqual( snap.code_embedding, [] )

    def test_create_still_carries_real_code_through( self ):
        """A code-bearing agent is unaffected by the default change."""
        agent = _codeless_agent()
        agent.prompt_response_dict[ "code" ] = [ "print( 2 + 2 )" ]
        with _embed_mocked():
            snap = SolutionSnapshot.create( agent )
        self.assertEqual( snap.code, [ "print( 2 + 2 )" ] )
        self.assertEqual( snap.code_embedding, _DUMMY_EMB )


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


class TestInitEmbeddingBranches( unittest.TestCase ):
    """The remaining content→embedding generation arms in __init__ (solution / thoughts / gists)."""

    def test_solution_summary_generates_solution_embedding( self ):
        """solution_summary present + no solution_embedding → provider generates one."""
        with _embed_mocked() as provider:
            snap = SolutionSnapshot( solution_summary="A summary of the solution", debug=False )
        self.assertEqual( snap.solution_embedding, _DUMMY_EMB )
        self.assertTrue( provider.generate_embedding.called )

    def test_thoughts_generates_thoughts_embedding( self ):
        """thoughts present + no thoughts_embedding → provider generates one."""
        with _embed_mocked() as provider:
            snap = SolutionSnapshot( thoughts="some chain of thought", debug=False )
        self.assertEqual( snap.thoughts_embedding, _DUMMY_EMB )
        self.assertTrue( provider.generate_embedding.called )

    def test_provided_gist_embeddings_preserved_not_regenerated( self ):
        """Truthy question_gist_embedding + solution_gist_embedding are stored verbatim."""
        q_gist_emb = [ 0.3 ] * 768
        s_gist_emb = [ 0.9 ] * 768
        with _embed_mocked():
            snap = SolutionSnapshot(
                question_gist_embedding=q_gist_emb,
                solution_gist_embedding=s_gist_emb,
                debug=False,
            )
        self.assertEqual( snap.question_gist_embedding, q_gist_emb )
        self.assertEqual( snap.solution_gist_embedding, s_gist_emb )

    def test_corrupt_synonymous_questions_reset_to_ordereddict( self ):
        """Non-dict synonymous_questions (debug on) → warning branch resets to OrderedDict."""
        with _embed_mocked():
            snap = SolutionSnapshot(
                question="What is 2+2?",
                synonymous_questions=[ "not", "a", "dict" ],   # invalid type
                debug=True,
            )
        self.assertIsInstance( snap.synonymous_questions, OrderedDict )
        # Empty-after-reset → recycles the current question with score 100.0
        self.assertEqual( snap.synonymous_questions[ "What is 2+2?" ], 100.0 )

    def test_corrupt_synonymous_gists_reset_to_ordereddict( self ):
        """Non-dict synonymous_question_gists (debug on) → warning branch resets to OrderedDict."""
        with _embed_mocked():
            snap = SolutionSnapshot(
                question_gist="two plus two",
                synonymous_question_gists="totally not a dict",   # invalid type
                debug=True,
            )
        self.assertIsInstance( snap.synonymous_question_gists, OrderedDict )
        self.assertEqual( snap.synonymous_question_gists[ "two plus two" ], 100.0 )


class TestSynonymousQuestionMethods( unittest.TestCase ):
    """add_synonymous_question + get_last_synonymous_question."""

    def test_add_with_salutation_records_new( self ):
        """Salutation present → last_question_asked is prefixed; new question stored with score."""
        with _embed_mocked():
            snap = SolutionSnapshot( question="What time is it?", debug=False )
            snap.add_synonymous_question( "what is the time", salutation="Hey Lupin,", score=88.0 )
        self.assertEqual( snap.last_question_asked, "Hey Lupin, what is the time" )
        self.assertEqual( snap.synonymous_questions[ "Hey Lupin, what is the time" ], 88.0 )

    def test_add_without_salutation_records_new( self ):
        """No salutation → last_question_asked equals the bare question."""
        with _embed_mocked():
            snap = SolutionSnapshot( question="What time is it?", debug=False )
            snap.add_synonymous_question( "tell me the time", score=77.0 )
        self.assertEqual( snap.last_question_asked, "tell me the time" )
        self.assertEqual( snap.synonymous_questions[ "tell me the time" ], 77.0 )

    def test_add_duplicate_prints_and_skips( self ):
        """Question already present → already-listed branch (no new key added)."""
        with _embed_mocked():
            snap = SolutionSnapshot( question="What time is it?", debug=False )
            # First add seeds "the time"; second add of same bare question hits the
            # `question in self.synonymous_questions` guard (already-listed branch).
            snap.add_synonymous_question( "the time" )
            count_after_first = len( snap.synonymous_questions )
            snap.add_synonymous_question( "the time" )
        self.assertEqual( len( snap.synonymous_questions ), count_after_first )

    def test_get_last_synonymous_question( self ):
        """Returns the most-recently inserted synonymous-question key."""
        with _embed_mocked():
            snap = SolutionSnapshot( question="first question", debug=False )
            snap.add_synonymous_question( "second question" )
        self.assertEqual( snap.get_last_synonymous_question(), "second question" )


class TestCompletionAndSetters( unittest.TestCase ):
    """complete() + set_code() + set_solution_summary()."""

    def test_set_code_generates_embedding( self ):
        """set_code stores the list and regenerates code_embedding from the joined code."""
        with _embed_mocked() as provider:
            snap = SolutionSnapshot( debug=False )
            provider.generate_embedding.reset_mock()
            snap.set_code( [ "x = 1", "print(x)" ] )
        self.assertEqual( snap.code, [ "x = 1", "print(x)" ] )
        self.assertEqual( snap.code_embedding, _DUMMY_EMB )
        provider.generate_embedding.assert_called_once()

    def test_set_solution_summary_generates_embedding( self ):
        """set_solution_summary stores the text and regenerates solution_embedding."""
        with _embed_mocked() as provider:
            snap = SolutionSnapshot( debug=False )
            provider.generate_embedding.reset_mock()
            snap.set_solution_summary( "the new summary" )
        self.assertEqual( snap.solution_summary, "the new summary" )
        self.assertEqual( snap.solution_embedding, _DUMMY_EMB )
        provider.generate_embedding.assert_called_once()

    def test_complete_sets_answer_code_and_summary( self ):
        """complete() fans out into answer + set_code + set_solution_summary."""
        with _embed_mocked():
            snap = SolutionSnapshot( debug=False )
            snap.complete( "the answer", code=[ "y = 2" ], solution_summary="done" )
        self.assertEqual( snap.answer, "the answer" )
        self.assertEqual( snap.code, [ "y = 2" ] )
        self.assertEqual( snap.solution_summary, "done" )


class TestSimilarityMethods( unittest.TestCase ):
    """get_question_similarity / get_solution_summary_similarity / get_code_similarity."""

    def test_question_similarity_success( self ):
        """Both snapshots have question embeddings → returns dot-product * 100."""
        with _embed_mocked():
            a = SolutionSnapshot( question="q a", debug=False )
            b = SolutionSnapshot( question="q b", debug=False )
        # _DUMMY_EMB · _DUMMY_EMB = 768 * 0.01 = 7.68 → * 100 = 768.0
        self.assertAlmostEqual( a.get_question_similarity( b ), 768.0, places=3 )

    def test_question_similarity_missing_embedding_raises( self ):
        """Empty question embedding on either side → ValueError."""
        with _embed_mocked():
            a = SolutionSnapshot( question="q a", debug=False )
            empty = SolutionSnapshot( debug=False )   # question="" → no embedding
        with self.assertRaises( ValueError ):
            a.get_question_similarity( empty )

    def test_solution_summary_similarity_success_and_raise( self ):
        """Solution-embedding present → score; missing → ValueError."""
        with _embed_mocked():
            a = SolutionSnapshot( solution_summary="sum a", debug=False )
            b = SolutionSnapshot( solution_summary="sum b", debug=False )
            empty = SolutionSnapshot( debug=False )
        self.assertAlmostEqual( a.get_solution_summary_similarity( b ), 768.0, places=3 )
        with self.assertRaises( ValueError ):
            a.get_solution_summary_similarity( empty )

    def test_code_similarity_success_and_raise( self ):
        """Code-embedding present → score; missing → ValueError."""
        with _embed_mocked():
            a = SolutionSnapshot( code=[ "a = 1" ], debug=False )
            b = SolutionSnapshot( code=[ "b = 2" ], debug=False )
            empty = SolutionSnapshot( debug=False )
        self.assertAlmostEqual( a.get_code_similarity( b ), 768.0, places=3 )
        with self.assertRaises( ValueError ):
            a.get_code_similarity( empty )


class TestCopyAndSerialization( unittest.TestCase ):
    """get_copy / to_jsons / for_current_user."""

    def test_get_copy_without_email( self ):
        """Shallow copy carries the same field values; user_email untouched when blank."""
        with _embed_mocked():
            snap = SolutionSnapshot( question="copy me", user_email="orig@example.com", debug=False )
            dup = snap.get_copy()
        self.assertEqual( dup.question, "copy me" )
        self.assertEqual( dup.user_email, "orig@example.com" )

    def test_get_copy_with_email_override( self ):
        """Providing user_email injects it onto the copy (TTS routing at copy time)."""
        with _embed_mocked():
            snap = SolutionSnapshot( question="copy me", debug=False )
            dup = snap.get_copy( user_email="new@example.com" )
        self.assertEqual( dup.user_email, "new@example.com" )

    def test_to_jsons_excludes_normalizer_and_sensitive_fields( self ):
        """
        to_jsons() serializes cleanly, excluding the unserializable/sensitive fields.

        Was an armed expectedFailure TRIPWIRE: to_jsons()'s fields_to_exclude list
        (solution_snapshot.py:639) omitted '_normalizer' — a Normalizer instance set
        unconditionally in __init__ — so json.dumps() hit an unserializable object
        and raised TypeError, making the whole (deprecated) method unusable. The
        sibling embedding objects were excluded; _normalizer was added later without
        updating the list. Bug fixed 2026-05-31 (added '_normalizer' to the list);
        decorator removed, this now asserts the correct serialize contract.
        """
        import json as _json
        with _embed_mocked():
            snap = SolutionSnapshot( question="serialize me", debug=False )
            payload = snap.to_jsons()
        data = _json.loads( payload )
        for excluded in ( "_embedding_mgr", "_embedding_provider", "_normalizer", "user_id", "user_email" ):
            self.assertNotIn( excluded, data )
        self.assertEqual( data[ "question" ], "serialize me" )

    def test_for_current_user_overrides_context_and_marks_cache_hit( self ):
        """for_current_user copies + overrides user/session and flags cache hit."""
        with _embed_mocked():
            snap = SolutionSnapshot( question="who am i", user_id="owner", debug=False )
            user_copy = snap.for_current_user( user_id="requester", session_id="sess-9" )
        self.assertEqual( user_copy.user_id, "requester" )
        self.assertEqual( user_copy.session_id, "sess-9" )
        self.assertTrue( user_copy.is_cache_hit )
        self.assertEqual( snap.user_id, "owner" )   # original untouched


class TestRuntimeStatsAndReplay( unittest.TestCase ):
    """update_runtime_stats (first-run + subsequent) + record_replay."""

    def test_update_runtime_stats_first_run( self ):
        """run_count == -1 → records first_run_ms and flips run_count to 0."""
        with _embed_mocked():
            snap = SolutionSnapshot( debug=False )
        timer = Mock()
        timer.get_delta_ms.return_value = 250
        snap.update_runtime_stats( timer )
        self.assertEqual( snap.runtime_stats[ "first_run_ms" ], 250 )
        self.assertEqual( snap.runtime_stats[ "run_count" ], 0 )

    def test_update_runtime_stats_subsequent_run( self ):
        """run_count >= 0 → accumulates total/mean/last and computes time_saved."""
        with _embed_mocked():
            snap = SolutionSnapshot( debug=False )
        snap.runtime_stats = {
            "first_run_ms" : 1000,
            "run_count"    : 1,
            "total_ms"     : 200,
            "mean_run_ms"  : 200,
            "last_run_ms"  : 200,
            "time_saved_ms": 0,
        }
        timer = Mock()
        timer.get_delta_ms.return_value = 100
        snap.update_runtime_stats( timer )
        self.assertEqual( snap.runtime_stats[ "run_count" ], 2 )
        self.assertEqual( snap.runtime_stats[ "total_ms" ], 300 )
        self.assertEqual( snap.runtime_stats[ "mean_run_ms" ], 150 )       # 300 / 2
        self.assertEqual( snap.runtime_stats[ "last_run_ms" ], 100 )
        self.assertEqual( snap.runtime_stats[ "time_saved_ms" ], 1700 )    # 1000*2 - 300

    def test_record_replay_first_event_and_aggregates( self ):
        """First replay seeds first_replayed, appends unique user + history entry."""
        with _embed_mocked():
            snap = SolutionSnapshot( debug=False )
        snap.record_replay( user_id="u1", session_id="s1", time_saved_ms=500 )
        self.assertEqual( snap.replay_stats[ "total_replays" ], 1 )
        self.assertEqual( snap.replay_stats[ "total_time_saved_ms" ], 500 )
        self.assertIn( "u1", snap.replay_stats[ "unique_users" ] )
        self.assertIsNotNone( snap.replay_stats[ "first_replayed" ] )
        self.assertEqual( len( snap.replay_history ), 1 )

    def test_record_replay_bounds_history_and_dedupes_users( self ):
        """max_history caps the rolling history; repeated user_id not double-counted."""
        with _embed_mocked():
            snap = SolutionSnapshot( debug=False )
        # Three replays from the SAME user with max_history=2 → history capped at 2,
        # unique_users holds exactly one entry, total_replays counts all three.
        snap.record_replay( user_id="u1", session_id="s1", time_saved_ms=10, max_history=2 )
        snap.record_replay( user_id="u1", session_id="s2", time_saved_ms=20, max_history=2 )
        snap.record_replay( user_id="u1", session_id="s3", time_saved_ms=30, max_history=2 )
        self.assertEqual( snap.replay_stats[ "total_replays" ], 3 )
        self.assertEqual( snap.replay_stats[ "unique_users" ], [ "u1" ] )
        self.assertEqual( len( snap.replay_history ), 2 )                   # bounded


class TestRunCode( unittest.TestCase ):
    """run_code() — codeless CalculatorAgent replay, empty-code guard, routing dispatch."""

    def test_calculator_agent_with_answer_short_circuits( self ):
        """CalculatorAgent + cached answer → synthesized code_response_dict, no execution."""
        with _embed_mocked():
            snap = SolutionSnapshot( agent_class_name="CalculatorAgent", answer="42", debug=False )
        result = snap.run_code()
        self.assertEqual( result, { "return_code": 0, "output": "42" } )

    def test_calculator_agent_without_answer_raises( self ):
        """CalculatorAgent with neither code nor answer → ValueError (corruption)."""
        with _embed_mocked():
            snap = SolutionSnapshot( agent_class_name="CalculatorAgent", debug=False )
        snap.answer = ""   # ensure falsy
        with self.assertRaises( ValueError ):
            snap.run_code()

    def test_empty_code_non_calculator_raises( self ):
        """Non-codeless agent with empty code → ValueError empty-code guard."""
        with _embed_mocked():
            snap = SolutionSnapshot( debug=False )   # code=[] default
        with self.assertRaises( ValueError ):
            snap.run_code()

    def test_run_code_todo_routing( self ):
        """routing_command 'todo list' selects the todo CSV path and runs the code."""
        with _embed_mocked():
            snap = SolutionSnapshot(
                code=[ "result = 1" ],
                routing_command="agent router go to todo list",
                debug=False,
            )
        with patch( "cosa.memory.solution_snapshot.ucr.assemble_and_run_solution",
                    return_value={ "output": "todo-ok" } ) as mock_run:
            result = snap.run_code()
        self.assertEqual( result[ "output" ], "todo-ok" )
        self.assertEqual( snap.answer, "todo-ok" )
        self.assertEqual( mock_run.call_args.kwargs[ "path_to_df" ], "/src/conf/long-term-memory/todo.csv" )

    def test_run_code_calendar_routing( self ):
        """routing_command 'calendar' selects the events CSV path."""
        with _embed_mocked():
            snap = SolutionSnapshot(
                code=[ "result = 1" ],
                routing_command="agent router go to calendar",
                debug=False,
            )
        with patch( "cosa.memory.solution_snapshot.ucr.assemble_and_run_solution",
                    return_value={ "output": "cal-ok" } ) as mock_run:
            snap.run_code()
        self.assertEqual( mock_run.call_args.kwargs[ "path_to_df" ], "/src/conf/long-term-memory/events.csv" )

    def test_run_code_default_routing_and_debug_verbose_banner( self ):
        """Unknown routing → path_to_df None; debug+verbose prints the output banner."""
        with _embed_mocked():
            snap = SolutionSnapshot( code=[ "result = 1" ], debug=False )
        with patch( "cosa.memory.solution_snapshot.ucr.assemble_and_run_solution",
                    return_value={ "output": "line-1\nline-2" } ) as mock_run, \
             patch( "cosa.memory.solution_snapshot.du.print_banner" ), \
             patch( "builtins.print" ):
            result = snap.run_code( debug=True, verbose=True )
        self.assertEqual( result[ "output" ], "line-1\nline-2" )
        self.assertIsNone( mock_run.call_args.kwargs[ "path_to_df" ] )


class TestRunFormatter( unittest.TestCase ):
    """run_formatter() — MathAgent terse/verbose/error, CalculatorAgent, default formatter."""

    def test_math_agent_terse_returns_formatted( self ):
        """MathAgent.apply_formatting returns a string → terse path returns it directly."""
        with _embed_mocked():
            snap = SolutionSnapshot( agent_class_name="MathAgent", answer="4", debug=False )
        with patch( "cosa.agents.math_agent.MathAgent" ) as mock_math, \
             patch( "cosa.config.configuration_manager.ConfigurationManager" ):
            mock_math.apply_formatting.return_value = "four"
            result = snap.run_formatter()
        self.assertEqual( result, "four" )
        self.assertEqual( snap.answer_conversational, "four" )

    def test_math_agent_verbose_falls_through_to_default( self ):
        """apply_formatting returns None (verbose mode) → falls through to LLM formatter."""
        with _embed_mocked():
            snap = SolutionSnapshot( agent_class_name="MathAgent", answer="4",
                                     last_question_asked="what is 2+2", debug=False )
        with patch( "cosa.agents.math_agent.MathAgent" ) as mock_math, \
             patch( "cosa.config.configuration_manager.ConfigurationManager" ), \
             patch( "cosa.memory.solution_snapshot.RawOutputFormatter" ) as mock_fmt:
            mock_math.apply_formatting.return_value = None
            mock_fmt.return_value.run_formatter.return_value = "It is four"
            result = snap.run_formatter()
        self.assertEqual( result, "It is four" )

    def test_math_agent_formatting_exception_falls_back( self ):
        """apply_formatting raises → except branch logs (debug) and falls to default formatter."""
        with _embed_mocked():
            snap = SolutionSnapshot( agent_class_name="MathAgent", answer="4",
                                     last_question_asked="what is 2+2", debug=True )
        with patch( "cosa.agents.math_agent.MathAgent" ) as mock_math, \
             patch( "cosa.config.configuration_manager.ConfigurationManager" ), \
             patch( "cosa.memory.solution_snapshot.RawOutputFormatter" ) as mock_fmt, \
             patch( "builtins.print" ):
            mock_math.apply_formatting.side_effect = Exception( "boom" )
            mock_fmt.return_value.run_formatter.return_value = "fallback answer"
            result = snap.run_formatter()
        self.assertEqual( result, "fallback answer" )

    def test_calculator_agent_already_formatted( self ):
        """CalculatorAgent with answer_conversational set → returns it as-is."""
        with _embed_mocked():
            snap = SolutionSnapshot( agent_class_name="CalculatorAgent", debug=False )
            snap.answer_conversational = "already conversational"
        result = snap.run_formatter()
        self.assertEqual( result, "already conversational" )

    def test_calculator_agent_without_conversational_uses_raw_answer( self ):
        """CalculatorAgent missing answer_conversational → falls back to raw answer."""
        with _embed_mocked():
            snap = SolutionSnapshot( agent_class_name="CalculatorAgent", answer="55", debug=True )
            snap.answer_conversational = ""
        with patch( "builtins.print" ):
            result = snap.run_formatter()
        self.assertEqual( result, "55" )

    def test_default_formatter_for_unknown_agent( self ):
        """No agent_class_name → default RawOutputFormatter path."""
        with _embed_mocked():
            snap = SolutionSnapshot( question="q", last_question_asked="q?", debug=False )
        with patch( "cosa.memory.solution_snapshot.RawOutputFormatter" ) as mock_fmt:
            mock_fmt.return_value.run_formatter.return_value = "default conv"
            result = snap.run_formatter()
        self.assertEqual( result, "default conv" )
        self.assertEqual( snap.answer_conversational, "default conv" )

    def test_math_agent_terse_debug_verbose_logs( self ):
        """debug+verbose terse path prints the 'Used MathAgent terse formatting' line."""
        with _embed_mocked():
            snap = SolutionSnapshot( agent_class_name="MathAgent", answer="4",
                                     debug=True, verbose=True )
        with patch( "cosa.agents.math_agent.MathAgent" ) as mock_math, \
             patch( "cosa.config.configuration_manager.ConfigurationManager" ), \
             patch( "builtins.print" ):
            mock_math.apply_formatting.return_value = "four"
            result = snap.run_formatter()
        self.assertEqual( result, "four" )

    def test_math_agent_verbose_fallthrough_debug_verbose_logs( self ):
        """debug+verbose verbose-mode fall-through logs both the signal + default-formatter lines."""
        with _embed_mocked():
            snap = SolutionSnapshot( agent_class_name="MathAgent", answer="4",
                                     last_question_asked="what is 2+2", debug=True, verbose=True )
        with patch( "cosa.agents.math_agent.MathAgent" ) as mock_math, \
             patch( "cosa.config.configuration_manager.ConfigurationManager" ), \
             patch( "cosa.memory.solution_snapshot.RawOutputFormatter" ) as mock_fmt, \
             patch( "builtins.print" ):
            mock_math.apply_formatting.return_value = None
            mock_fmt.return_value.run_formatter.return_value = "It is four"
            result = snap.run_formatter()
        self.assertEqual( result, "It is four" )

    def test_math_agent_exception_debug_false_silent_fallback( self ):
        """apply_formatting raises with debug off → silent except branch (no log), still falls back."""
        with _embed_mocked():
            snap = SolutionSnapshot( agent_class_name="MathAgent", answer="4",
                                     last_question_asked="what is 2+2", debug=False )
        with patch( "cosa.agents.math_agent.MathAgent" ) as mock_math, \
             patch( "cosa.config.configuration_manager.ConfigurationManager" ), \
             patch( "cosa.memory.solution_snapshot.RawOutputFormatter" ) as mock_fmt:
            mock_math.apply_formatting.side_effect = Exception( "boom" )
            mock_fmt.return_value.run_formatter.return_value = "fallback answer"
            result = snap.run_formatter()
        self.assertEqual( result, "fallback answer" )

    def test_calculator_agent_already_formatted_debug_verbose_logs( self ):
        """debug+verbose CalculatorAgent already-formatted prints the 'already formatted' line."""
        with _embed_mocked():
            snap = SolutionSnapshot( agent_class_name="CalculatorAgent", debug=True, verbose=True )
            snap.answer_conversational = "already conversational"
        with patch( "builtins.print" ):
            result = snap.run_formatter()
        self.assertEqual( result, "already conversational" )

    def test_calculator_agent_without_conversational_debug_false( self ):
        """CalculatorAgent missing conversational, debug off → silent raw-answer fallback."""
        with _embed_mocked():
            snap = SolutionSnapshot( agent_class_name="CalculatorAgent", answer="55", debug=False )
            snap.answer_conversational = ""
        result = snap.run_formatter()
        self.assertEqual( result, "55" )

    def test_default_formatter_debug_verbose_logs( self ):
        """debug+verbose unknown-agent default path prints the 'Used default LLM formatter' line."""
        with _embed_mocked():
            snap = SolutionSnapshot( question="q", last_question_asked="q?",
                                     debug=True, verbose=True )
        with patch( "cosa.memory.solution_snapshot.RawOutputFormatter" ) as mock_fmt, \
             patch( "builtins.print" ):
            mock_fmt.return_value.run_formatter.return_value = "default conv"
            result = snap.run_formatter()
        self.assertEqual( result, "default conv" )


class TestProtocolHelpers( unittest.TestCase ):
    """formatter_ran_to_completion / do_all / job_type."""

    def test_formatter_ran_to_completion( self ):
        """True once answer_conversational is non-None; False when None."""
        with _embed_mocked():
            snap = SolutionSnapshot( debug=False )
        snap.answer_conversational = None
        self.assertFalse( snap.formatter_ran_to_completion() )
        snap.answer_conversational = "done"
        self.assertTrue( snap.formatter_ran_to_completion() )

    def test_do_all_runs_code_then_formatter( self ):
        """do_all chains run_code + run_formatter and returns the conversational answer."""
        with _embed_mocked():
            # CalculatorAgent path keeps both calls dependency-light (cached answer / conv).
            snap = SolutionSnapshot( agent_class_name="CalculatorAgent", answer="42", debug=False )
            snap.answer_conversational = "forty two"
        result = snap.do_all()
        self.assertEqual( result, "forty two" )

    def test_job_type_with_and_without_agent_class( self ):
        """job_type mirrors agent_class_name, falling back to 'unknown'."""
        with _embed_mocked():
            with_agent = SolutionSnapshot( agent_class_name="MathAgent", debug=False )
            without    = SolutionSnapshot( debug=False )
        self.assertEqual( with_agent.job_type, "MathAgent" )
        self.assertEqual( without.job_type, "unknown" )


class TestClassmethodsAndDeprecatedIO( unittest.TestCase ):
    """from_json_file / create / write_current_state_to_file / delete_file."""

    def test_from_json_file_loads_and_constructs( self ):
        """Deprecated loader reads JSON then constructs via cls(**data) (debug print on)."""
        with _embed_mocked(), \
             patch( "builtins.open" ), \
             patch( "cosa.memory.solution_snapshot.json.load",
                    return_value={ "push_counter": 7, "question": "" } ), \
             patch( "warnings.warn" ):
            snap = SolutionSnapshot.from_json_file( "/fake/path.json", debug=True )
        self.assertEqual( snap.push_counter, 7 )

    def test_create_from_agent( self ):
        """create() maps an agent's prompt/code dicts onto a new snapshot."""
        agent = Mock()
        agent.last_question_asked  = "What is 2+2?"
        agent.question             = "What is 2+2?"
        agent.question_gist        = "two plus two"
        agent.routing_command      = "agent router go to math"
        agent.answer_conversational = "It is four"
        agent.user_id              = "u-1"
        agent.user_email           = "u@example.com"
        agent.session_id           = "sess-1"
        agent.id_hash              = "agent-hash-1"
        agent.prompt_response_dict = {
            "error"      : "",
            "explanation": "Add the numbers",
            "code"       : [ "result = 2 + 2" ],
            "returns"    : "int",
            "example"    : "result = 2 + 2",
            "thoughts"   : "simple addition",
        }
        agent.code_response_dict   = { "output": "4" }

        with _embed_mocked():
            snap = SolutionSnapshot.create( agent )

        self.assertEqual( snap.question, "What is 2+2?" )
        self.assertEqual( snap.id_hash, "agent-hash-1" )            # agent id_hash preserved
        self.assertEqual( snap.agent_class_name, type( agent ).__name__ )
        self.assertEqual( snap.routing_command, "agent router go to math" )
        self.assertEqual( snap.answer, "4" )
        self.assertEqual( snap.solution_summary, "Add the numbers" )

    def test_write_current_state_new_file_generates_name( self ):
        """
        solution_file None → generates a unique filename, writes JSON, chmods 0o666.

        to_jsons() is mocked here to isolate write_current_state_to_file's OWN
        logic (name generation + chmod) from the separately-tripwired to_jsons
        _normalizer bug (which would otherwise raise at the f.write() call).
        """
        with _embed_mocked():
            snap = SolutionSnapshot( question="write me", debug=False )
            snap.solution_file = None
        with patch( "cosa.memory.solution_snapshot.du.get_project_root", return_value="/root" ), \
             patch( "cosa.memory.solution_snapshot.glob.glob", return_value=[] ), \
             patch.object( SolutionSnapshot, "to_jsons", return_value="{}" ), \
             patch( "builtins.open" ), \
             patch( "cosa.memory.solution_snapshot.os.chmod" ) as mock_chmod, \
             patch( "warnings.warn" ), \
             patch( "builtins.print" ):
            snap.write_current_state_to_file()
        self.assertIsNotNone( snap.solution_file )                  # name was generated
        self.assertTrue( snap.solution_file.endswith( "-0.json" ) ) # file_count == 0
        mock_chmod.assert_called_once()

    def test_write_current_state_existing_file( self ):
        """
        solution_file provided → uses it directly (else branch), writes + chmods.

        to_jsons() mocked (see new-file test) to isolate from the to_jsons bug.
        """
        with _embed_mocked():
            snap = SolutionSnapshot( question="write me", debug=False )
            snap.solution_file = "preset.json"
        with patch( "cosa.memory.solution_snapshot.du.get_project_root", return_value="/root" ), \
             patch.object( SolutionSnapshot, "to_jsons", return_value="{}" ), \
             patch( "builtins.open" ), \
             patch( "cosa.memory.solution_snapshot.os.chmod" ) as mock_chmod, \
             patch( "warnings.warn" ), \
             patch( "builtins.print" ):
            snap.write_current_state_to_file()
        self.assertEqual( snap.solution_file, "preset.json" )
        mock_chmod.assert_called_once()

    def test_delete_file_existing( self ):
        """delete_file removes the file when present."""
        with _embed_mocked():
            snap = SolutionSnapshot( debug=False )
            snap.solution_file = "x.json"
        with patch( "cosa.memory.solution_snapshot.du.get_project_root", return_value="/root" ), \
             patch( "cosa.memory.solution_snapshot.os.path.isfile", return_value=True ), \
             patch( "cosa.memory.solution_snapshot.os.remove" ) as mock_remove, \
             patch( "warnings.warn" ), \
             patch( "builtins.print" ):
            snap.delete_file()
        mock_remove.assert_called_once()

    def test_delete_file_missing( self ):
        """delete_file no-ops (prints) when the file is absent."""
        with _embed_mocked():
            snap = SolutionSnapshot( debug=False )
            snap.solution_file = "missing.json"
        with patch( "cosa.memory.solution_snapshot.du.get_project_root", return_value="/root" ), \
             patch( "cosa.memory.solution_snapshot.os.path.isfile", return_value=False ), \
             patch( "cosa.memory.solution_snapshot.os.remove" ) as mock_remove, \
             patch( "warnings.warn" ), \
             patch( "builtins.print" ):
            snap.delete_file()
        mock_remove.assert_not_called()


if __name__ == "__main__":
    unittest.main()
