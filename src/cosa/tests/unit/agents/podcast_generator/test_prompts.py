"""
Unit tests for podcast_generator prompt builders/parsers
(`cosa.agents.podcast_generator.prompts.personality` +
`...prompts.script_generation`).

These two modules are pure string-builders and JSON parsers — no LLM calls, no
IO. The tests harvest the modules' `quick_smoke_test` assertions into real
pytest and add the branch coverage the smoke blocks miss (audience/language/
truncation arcs, markdown-fence stripping, JSON-decode fallbacks, every
keyword branch of `create_personality_from_description`).

Run via `run-sdk-cov.sh` (podcast_generator is in the SDK-adjacent set).
"""

import unittest

from cosa.agents.podcast_generator.config import (
    HostPersonality,
    DEFAULT_CURIOUS_HOST,
    DEFAULT_EXPERT_HOST,
)
from cosa.agents.podcast_generator.prompts.personality import (
    CURIOUS_HOST_PROMPT_SECTION,
    EXPERT_HOST_PROMPT_SECTION,
    get_personality_prompt_section,
    get_dynamic_duo_description,
    create_personality_from_description,
    get_prosody_guidelines,
)
from cosa.agents.podcast_generator.prompts.script_generation import (
    get_content_analysis_prompt,
    get_script_generation_prompt,
    get_script_revision_prompt,
    parse_analysis_response,
    parse_script_response,
    extract_prosody_from_text,
)


# ── personality.py ──────────────────────────────────────────────────────────────


class TestGetPersonalityPromptSection( unittest.TestCase ):

    def test_curious_role_with_phrases( self ):
        p = HostPersonality(
            name="Nora", role="Curious Questioner",
            typical_phrases=[ "Wait, so...", "Help me understand..." ],
        )
        out = get_personality_prompt_section( p, is_curious_role=True )
        self.assertIn( "CURIOUS HOST - Nora", out )
        self.assertIn( "Example phrases:", out )
        self.assertIn( "Wait, so...", out )

    def test_expert_role_without_phrases( self ):
        p = HostPersonality( name="Quentin", role="Expert", typical_phrases=[] )
        out = get_personality_prompt_section( p, is_curious_role=False )
        self.assertIn( "KNOWLEDGEABLE HOST - Quentin", out )
        self.assertNotIn( "Example phrases:", out )


class TestGetDynamicDuoDescription( unittest.TestCase ):

    def test_includes_both_hosts_and_dynamics( self ):
        out = get_dynamic_duo_description( DEFAULT_CURIOUS_HOST, DEFAULT_EXPERT_HOST )
        self.assertIn( DEFAULT_CURIOUS_HOST.name, out )
        self.assertIn( DEFAULT_EXPERT_HOST.name, out )
        self.assertIn( "INTERACTION DYNAMICS", out )
        self.assertIn( "COMPLEMENTARY ENERGY", out )


class TestCreatePersonalityFromDescription( unittest.TestCase ):

    def test_enthusiastic_professor_not_curious( self ):
        p = create_personality_from_description( "Dr. Chen", "an enthusiastic professor", is_curious=False )
        self.assertEqual( p.tone, "enthusiastic and energetic" )
        self.assertEqual( p.expertise_level, "expert" )
        self.assertEqual( p.curiosity_level, "moderate" )  # not curious, not "focused"
        self.assertEqual( p.role, "Knowledgeable Explainer" )

    def test_calm_student_very_curious( self ):
        p = create_personality_from_description( "Sam", "a calm student, very curious", is_curious=True )
        self.assertEqual( p.tone, "calm and measured" )
        self.assertEqual( p.expertise_level, "learning" )
        self.assertEqual( p.curiosity_level, "high" )  # "very curious"

    def test_humorous_focused_not_curious( self ):
        p = create_personality_from_description( "Jo", "humorous and focused", is_curious=False )
        self.assertEqual( p.tone, "humorous and witty" )
        self.assertEqual( p.expertise_level, "knowledgeable" )  # no prof/student, not curious
        self.assertEqual( p.curiosity_level, "low" )  # not curious + "focused"

    def test_scholarly_curious_layperson( self ):
        p = create_personality_from_description( "Lee", "scholarly tone", is_curious=True )
        self.assertEqual( p.tone, "scholarly and precise" )
        self.assertEqual( p.expertise_level, "educated layperson" )  # else + is_curious
        self.assertEqual( p.curiosity_level, "moderate" )  # curious, not "very curious"
        self.assertEqual( p.role, "Curious Questioner" )

    def test_plain_description_defaults( self ):
        p = create_personality_from_description( "Pat", "an ordinary person", is_curious=False )
        self.assertEqual( p.tone, "conversational" )  # no keyword
        self.assertEqual( p.expertise_level, "knowledgeable" )
        self.assertEqual( p.curiosity_level, "moderate" )


class TestGetProsodyGuidelines( unittest.TestCase ):

    def test_contains_markers( self ):
        out = get_prosody_guidelines()
        self.assertIn( "*[pause]*", out )
        self.assertIn( "EMOTIONAL MARKERS", out )


class TestPersonalityModuleConstants( unittest.TestCase ):

    def test_default_sections_have_content( self ):
        self.assertIn( "questions", CURIOUS_HOST_PROMPT_SECTION.lower() )
        self.assertIn( "analogies", EXPERT_HOST_PROMPT_SECTION.lower() )


# ── script_generation.py ────────────────────────────────────────────────────────


class TestGetContentAnalysisPrompt( unittest.TestCase ):

    def test_short_content_no_audience( self ):
        out = get_content_analysis_prompt( "short research", max_topics=3 )
        self.assertIn( "short research", out )
        self.assertIn( "up to 3", out )
        self.assertNotIn( "Target Audience", out )

    def test_long_content_truncates_with_audience_and_context( self ):
        long = "x" * 60000
        out = get_content_analysis_prompt(
            long, max_topics=5, audience="beginner", audience_context="busy commuters",
        )
        self.assertIn( "Target Audience: Beginner", out )
        self.assertIn( "busy commuters", out )
        # Content was truncated to 50000 chars (plus the surrounding template).
        self.assertNotIn( "x" * 50001, out )

    def test_unknown_audience_adds_no_guidelines( self ):
        out = get_content_analysis_prompt( "r", audience="martian" )
        self.assertNotIn( "Target Audience", out )


class TestGetScriptGenerationPrompt( unittest.TestCase ):

    def test_english_no_language_instruction( self ):
        out = get_script_generation_prompt(
            content_analysis={ "main_topic": "T", "key_subtopics": [] },
            research_content="r", host_a_personality=DEFAULT_CURIOUS_HOST,
            host_b_personality=DEFAULT_EXPERT_HOST, target_language="en",
        )
        self.assertNotIn( "LANGUAGE REQUIREMENT", out )
        self.assertIn( DEFAULT_CURIOUS_HOST.name, out )

    def test_spanish_truncates_with_language_audience_context( self ):
        out = get_script_generation_prompt(
            content_analysis={ "main_topic": "Quantum", "key_subtopics": [ "qubits" ] },
            research_content="y" * 40000, host_a_personality=DEFAULT_CURIOUS_HOST,
            host_b_personality=DEFAULT_EXPERT_HOST, target_language="es-MX",
            audience="expert", audience_context="grad students",
        )
        self.assertIn( "LANGUAGE REQUIREMENT", out )
        self.assertIn( "Mexican Spanish", out )
        self.assertIn( "Target Audience: Expert", out )
        self.assertIn( "grad students", out )
        self.assertNotIn( "y" * 30001, out )

    def test_unknown_audience_no_guidelines( self ):
        out = get_script_generation_prompt(
            content_analysis={ "main_topic": "T", "key_subtopics": [] },
            research_content="r", host_a_personality=DEFAULT_CURIOUS_HOST,
            host_b_personality=DEFAULT_EXPERT_HOST, audience="martian",
        )
        self.assertNotIn( "Target Audience", out )


class TestGetScriptRevisionPrompt( unittest.TestCase ):

    def test_revision_prompt( self ):
        out = get_script_revision_prompt( "**[Nora]**: Hi", "make it punchier", revision_number=2 )
        self.assertIn( "revision #2", out )
        self.assertIn( "make it punchier", out )


class TestParseAnalysisResponse( unittest.TestCase ):

    def test_plain_json( self ):
        parsed = parse_analysis_response( '{"main_topic": "AI", "key_subtopics": ["ML"]}' )
        self.assertEqual( parsed[ "main_topic" ], "AI" )

    def test_json_fenced( self ):
        parsed = parse_analysis_response( '```json\n{"main_topic": "T"}\n```' )
        self.assertEqual( parsed[ "main_topic" ], "T" )

    def test_bare_fenced( self ):
        parsed = parse_analysis_response( '```\n{"main_topic": "B"}\n```' )
        self.assertEqual( parsed[ "main_topic" ], "B" )

    def test_invalid_returns_default( self ):
        parsed = parse_analysis_response( "not json at all" )
        self.assertEqual( parsed[ "main_topic" ], "Unknown Topic" )
        self.assertEqual( parsed[ "complexity_level" ], "intermediate" )


class TestParseScriptResponse( unittest.TestCase ):

    def test_full_valid( self ):
        parsed = parse_script_response( '{"title": "Ep", "segments": [{"speaker": "A"}]}' )
        self.assertEqual( parsed[ "title" ], "Ep" )
        self.assertEqual( len( parsed[ "segments" ] ), 1 )

    def test_missing_segments_and_title_get_defaults( self ):
        parsed = parse_script_response( '{"key_topics": ["x"]}' )
        self.assertEqual( parsed[ "segments" ], [] )
        self.assertEqual( parsed[ "title" ], "Untitled Podcast" )

    def test_fenced_json( self ):
        parsed = parse_script_response( '```json\n{"title": "F", "segments": []}\n```' )
        self.assertEqual( parsed[ "title" ], "F" )

    def test_bare_fenced_json( self ):
        parsed = parse_script_response( '```\n{"title": "Bare", "segments": []}\n```' )
        self.assertEqual( parsed[ "title" ], "Bare" )

    def test_invalid_returns_default( self ):
        parsed = parse_script_response( "garbage" )
        self.assertEqual( parsed[ "title" ], "Untitled Podcast" )
        self.assertEqual( parsed[ "estimated_duration_minutes" ], 0 )


class TestExtractProsodyFromText( unittest.TestCase ):

    def test_extracts_and_cleans( self ):
        clean, annotations = extract_prosody_from_text(
            "So *[pause]* what you're saying is *[Excited]* amazing!"
        )
        self.assertIn( "pause", annotations )
        self.assertIn( "excited", annotations )  # normalized lowercase
        self.assertNotIn( "*[", clean )

    def test_no_annotations( self ):
        clean, annotations = extract_prosody_from_text( "plain dialogue with no markers" )
        self.assertEqual( annotations, [] )
        self.assertEqual( clean, "plain dialogue with no markers" )


if __name__ == "__main__":
    unittest.main()
