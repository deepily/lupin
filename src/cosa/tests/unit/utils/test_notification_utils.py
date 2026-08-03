"""
Unit tests for cosa.utils.notification_utils.

All functions are pure (string/dict transforms), so no mocking is required.
Covers TTS formatting, camelCase->snake_case API conversion, open-ended batch
formatting, yes/no/neither qualifier extraction, and qualified-response copy.

Assertions harvested and strengthened from the module's quick_smoke_test()
(now superseded), with added coverage of default-key fallbacks and the
non-matching qualifier fallback branch the smoke test did not reach.
"""

import unittest

from cosa.utils.notification_utils import (
    KNOWN_PROJECTS,
    is_known_project,
    normalize_abstract,
    format_questions_for_tts,
    convert_questions_for_api,
    format_open_ended_batch_for_tts,
    convert_open_ended_batch_for_api,
    extract_qualifier_comment,
    format_qualified_response,
)


class TestIsKnownProject( unittest.TestCase ):
    """Registry membership test against KNOWN_PROJECTS values."""

    def test_known_projects_true( self ):
        for name in ( "lupin", "cosa", "plan", "lupin-mobile", "lupin-plugin-firefox", "scratchpad" ):
            self.assertTrue( is_known_project( name ), name )

    def test_unknown_projects_false( self ):
        for name in ( "newrepo", "unknown", "" ):
            self.assertFalse( is_known_project( name ), name )

    def test_known_projects_mapping( self ):
        self.assertEqual( KNOWN_PROJECTS[ "/lupin" ], "lupin" )
        self.assertEqual( KNOWN_PROJECTS[ "/planning-is-prompting" ], "plan" )
        self.assertEqual( KNOWN_PROJECTS[ "/scratchpad" ], "scratchpad" )


class TestNormalizeAbstract( unittest.TestCase ):
    """
    normalize_abstract() literal-escape conversion.

    Ensures:
        - None passes through as None
        - literal backslash-n becomes a real newline
        - text without escapes is returned unchanged
    """

    def test_none_returns_none( self ):
        self.assertIsNone( normalize_abstract( None ) )

    def test_literal_newline_converted( self ):
        self.assertEqual( normalize_abstract( "a\\nb" ), "a\nb" )

    def test_plain_text_unchanged( self ):
        self.assertEqual( normalize_abstract( "no escapes here" ), "no escapes here" )


class TestFormatQuestionsForTts( unittest.TestCase ):
    """
    format_questions_for_tts() — question-only spoken text.

    Ensures:
        - a single question is spoken verbatim (no numbering, no options)
        - multiSelect adds the multi-select hint
        - multiple questions get 'Question N of X' numbering
        - a missing 'question' key falls back to the default prompt
    """

    def test_single_question_verbatim( self ):
        out = format_questions_for_tts( [ { "question": "Which database?" } ] )
        self.assertEqual( out, "Which database?" )
        self.assertNotIn( "Option", out )

    def test_single_multiselect_adds_hint( self ):
        out = format_questions_for_tts(
            [ { "question": "Which features?", "multiSelect": True } ]
        )
        self.assertIn( "Which features?", out )
        self.assertIn( "You can select multiple options.", out )

    def test_multiple_questions_numbered( self ):
        out = format_questions_for_tts(
            [ { "question": "First?" }, { "question": "Second?", "multiSelect": True } ]
        )
        self.assertIn( "Question 1 of 2: First?", out )
        self.assertIn( "Question 2 of 2: Second?", out )
        self.assertIn( "You can select multiple options.", out )

    def test_missing_question_key_uses_default( self ):
        out = format_questions_for_tts( [ {} ] )
        self.assertEqual( out, "Please select an option" )


class TestConvertQuestionsForApi( unittest.TestCase ):
    """
    convert_questions_for_api() — camelCase -> snake_case + defaults.

    Ensures:
        - multiSelect maps to multi_select and the camelCase key is dropped
        - missing optional keys get their documented defaults
    """

    def test_multiselect_converted( self ):
        out = convert_questions_for_api(
            [ { "question": "Q", "header": "H", "multiSelect": True, "options": [ 1 ] } ]
        )
        q0 = out[ "questions" ][ 0 ]
        self.assertTrue( q0[ "multi_select" ] )
        self.assertNotIn( "multiSelect", q0 )
        self.assertEqual( q0[ "options" ], [ 1 ] )

    def test_defaults_applied_for_missing_keys( self ):
        out = convert_questions_for_api( [ {} ] )
        q0 = out[ "questions" ][ 0 ]
        self.assertEqual( q0[ "question" ], "" )
        self.assertEqual( q0[ "header" ], "Selection" )
        self.assertFalse( q0[ "multi_select" ] )
        self.assertEqual( q0[ "options" ], [] )


class TestFormatOpenEndedBatchForTts( unittest.TestCase ):
    """
    format_open_ended_batch_for_tts() — count-aware spoken text.

    Ensures:
        - empty list -> empty string
        - single question -> its text (default when 'question' absent)
        - multiple questions -> count-only preamble (no individual text)
    """

    def test_empty_returns_empty_string( self ):
        self.assertEqual( format_open_ended_batch_for_tts( [] ), "" )

    def test_single_question_text( self ):
        self.assertEqual(
            format_open_ended_batch_for_tts( [ { "question": "What topic?" } ] ),
            "What topic?",
        )

    def test_single_missing_question_uses_default( self ):
        self.assertEqual(
            format_open_ended_batch_for_tts( [ {} ] ), "Please provide a value"
        )

    def test_multiple_questions_count_preamble( self ):
        out = format_open_ended_batch_for_tts(
            [ { "question": "a" }, { "question": "b" }, { "question": "c" } ]
        )
        self.assertEqual( out, "I have 3 questions for you." )
        self.assertNotIn( "Question 1 of 3", out )


class TestConvertOpenEndedBatchForApi( unittest.TestCase ):
    """
    convert_open_ended_batch_for_api() — text inputs + optional default_value.

    Ensures:
        - every question is marked input_type 'text'
        - header defaults to 'Question N' (1-based) when absent
        - default_value is passed through only when present
    """

    def test_text_input_and_header_default( self ):
        out = convert_open_ended_batch_for_api( [ { "question": "a" }, { "question": "b" } ] )
        qs = out[ "questions" ]
        self.assertEqual( qs[ 0 ][ "input_type" ], "text" )
        self.assertEqual( qs[ 0 ][ "header" ], "Question 1" )
        self.assertEqual( qs[ 1 ][ "header" ], "Question 2" )

    def test_default_value_passthrough_and_omission( self ):
        out = convert_open_ended_batch_for_api(
            [ { "question": "a", "default_value": "x" }, { "question": "b" } ]
        )
        qs = out[ "questions" ]
        self.assertEqual( qs[ 0 ][ "default_value" ], "x" )
        self.assertNotIn( "default_value", qs[ 1 ] )


class TestExtractQualifierComment( unittest.TestCase ):
    """
    extract_qualifier_comment() — (answer, qualifier) parsing.

    Ensures:
        - falsy input -> (None, None)
        - 'yes/no/neither [comment: ...]' splits answer + qualifier
        - bare answers yield a None qualifier
        - case is normalized to lowercase
        - a non-matching string falls back to (whole-lowered, None)
    """

    def test_empty_returns_none_pair( self ):
        self.assertEqual( extract_qualifier_comment( None ), ( None, None ) )
        self.assertEqual( extract_qualifier_comment( "" ), ( None, None ) )

    def test_answer_with_comment( self ):
        self.assertEqual(
            extract_qualifier_comment( "yes [comment: fix the tests]" ),
            ( "yes", "fix the tests" ),
        )
        self.assertEqual(
            extract_qualifier_comment( "neither [comment: re-frame please]" ),
            ( "neither", "re-frame please" ),
        )

    def test_bare_answers_have_none_qualifier( self ):
        self.assertEqual( extract_qualifier_comment( "no" ), ( "no", None ) )
        self.assertEqual( extract_qualifier_comment( "neither" ), ( "neither", None ) )

    def test_case_normalized( self ):
        self.assertEqual( extract_qualifier_comment( "NEITHER" ), ( "neither", None ) )

    def test_non_matching_falls_back_to_whole_string( self ):
        self.assertEqual(
            extract_qualifier_comment( "  Maybe later  " ), ( "maybe later", None )
        )


class TestFormatQualifiedResponse( unittest.TestCase ):
    """
    format_qualified_response() — enriched instruction copy.

    Ensures:
        - 'neither' produces the re-framing variant
        - 'yes'/'no' produce the act-on-comment variant
        - the answer and qualifier are embedded in the output
    """

    def test_neither_uses_reframing_copy( self ):
        out = format_qualified_response( "neither", "the question is malformed" )
        self.assertTrue( out.startswith( "neither\n" ) )
        self.assertIn( "re-framing", out )
        self.assertIn( "soft yes or no", out )
        self.assertIn( "the question is malformed", out )

    def test_yes_uses_act_on_comment_copy( self ):
        out = format_qualified_response( "yes", "fix the import" )
        self.assertTrue( out.startswith( "yes\n" ) )
        self.assertIn( "MUST act", out )
        self.assertIn( "Do NOT ignore", out )
        self.assertIn( "fix the import", out )


if __name__ == "__main__":
    unittest.main()
