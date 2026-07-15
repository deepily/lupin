#!/usr/bin/env python3
"""
Notification Utility Functions.

Shared formatting utilities for notification messages across COSA agents
and the MCP server. Handles TTS message formatting, API format conversion,
and qualifier extraction/formatting for yes/no responses.
"""

import re


# ── Known Project Registry ───────────────────────────────────────────────────

KNOWN_PROJECTS = {
    "/cosa"                  : "cosa",
    "/planning-is-prompting" : "plan",
    "/lupin"                 : "lupin",
    "/lupin-mobile"          : "lupin-mobile",
    "/lupin-plugin-firefox"  : "lupin-plugin-firefox",
    "/scratchpad"            : "scratchpad",
}


def is_known_project( project: str ) -> bool:
    """
    Check whether a project name is in the known project registry.

    Requires:
        - project is a string

    Ensures:
        - Returns True if project is a recognized project name
        - Returns False otherwise (including empty string)

    Args:
        project: Project name to check (e.g., "lupin", "cosa", "plan")

    Returns:
        bool: True if known, False otherwise
    """
    return project in KNOWN_PROJECTS.values()


def normalize_abstract( abstract ) -> str:
    """
    Convert literal \\n to actual newlines in abstract text.

    Requires:
        - abstract is None or a string

    Ensures:
        - Returns None if input is None
        - Returns string with literal \\\\n converted to newlines

    Args:
        abstract: Abstract text from MCP tool call (may contain escaped newlines)

    Returns:
        str or None: Normalized abstract text
    """
    if abstract is None:
        return None
    return abstract.replace( '\\n', '\n' )


def format_questions_for_tts( questions: list ) -> str:
    """
    Format questions for TTS playback.

    Returns ONLY the question text. Options are displayed in the UI
    and should NOT be included in the spoken TTS message.

    Requires:
        - questions is a list of question dicts
        - Each dict should have 'question' key
        - Optional 'multiSelect' key (camelCase, from Claude Code format)

    Ensures:
        - Returns TTS-friendly string with question text only
        - Multi-question: "Question N of X: ..."
        - Single question: Just the question text
        - Adds multi-select hint when multiSelect is True

    Args:
        questions: List of question objects (Claude Code format)

    Returns:
        str: TTS-friendly message (question text only, no options)
    """
    total = len( questions )
    parts = []

    for i, q in enumerate( questions, 1 ):
        question_text = q.get( "question", "Please select an option" )
        multi_select = q.get( "multiSelect", False )

        # Build question intro (question text ONLY)
        if total > 1:
            part = f"Question {i} of {total}: {question_text}"
        else:
            part = question_text

        # Add multi-select hint if needed
        if multi_select:
            part += " You can select multiple options."

        # NOTE: Options are displayed in UI, not spoken in TTS
        parts.append( part )

    return " ".join( parts )


def convert_questions_for_api( questions: list ) -> dict:
    """
    Convert Claude Code's camelCase format to API's snake_case format.

    Claude Code uses: multiSelect (camelCase)
    API/Database expects: multi_select (snake_case)

    Frontend rendering depends on multi_select:
        - multi_select: true -> renders as checkboxes
        - multi_select: false -> renders as radio buttons

    Requires:
        - questions is a list of question dicts

    Ensures:
        - Returns dict with 'questions' array
        - multiSelect converted to multi_select
        - Other fields preserved (question, header, options)

    Args:
        questions: List of question dicts in Claude Code format

    Returns:
        dict: API-compatible response_options structure
    """
    converted = []
    for q in questions:
        converted_q = {
            "question"     : q.get( 'question', '' ),
            "header"       : q.get( 'header', 'Selection' ),
            "multi_select" : q.get( 'multiSelect', False ),
            "options"      : q.get( 'options', [] )
        }
        converted.append( converted_q )
    return { "questions": converted }


def format_open_ended_batch_for_tts( questions: list ) -> str:
    """
    Format open-ended batch questions for TTS playback.

    For a single question, speaks the question text directly.
    For multiple questions, speaks only the count preamble — individual
    questions are already displayed in the UI batch form and should NOT
    be read aloud (too verbose for voice UX).

    Requires:
        - questions is a non-empty list of question dicts
        - Each dict should have 'question' key

    Ensures:
        - Single question: just the question text (no preamble)
        - Multiple questions: count-only preamble ("I have N questions for you.")

    Args:
        questions: List of question objects with 'question' and 'header' keys

    Returns:
        str: TTS-friendly message
    """
    total = len( questions )
    if total == 0:
        return ""
    if total == 1:
        return questions[ 0 ].get( "question", "Please provide a value" )
    return f"I have {total} questions for you."


def convert_open_ended_batch_for_api( questions: list ) -> dict:
    """
    Convert open-ended batch questions to API response_options format.

    Marks each question with input_type: "text" so the frontend knows
    to render text inputs instead of radio/checkbox options.

    Requires:
        - questions is a list of question dicts

    Ensures:
        - Returns dict with 'questions' array
        - Each question has input_type: "text"
        - Preserves question and header fields

    Args:
        questions: List of question dicts with 'question' and 'header' keys

    Returns:
        dict: API-compatible response_options structure
    """
    converted = []
    for q in questions:
        converted_q = {
            "question"   : q.get( "question", "" ),
            "header"     : q.get( "header", f"Question {len( converted ) + 1}" ),
            "input_type" : "text"
        }
        if "default_value" in q:
            converted_q[ "default_value" ] = q[ "default_value" ]
        converted.append( converted_q )
    return { "questions": converted }


def extract_qualifier_comment( response_value ):
    """
    Extract qualifier comment from a yes/no/neither response value.

    Requires:
        - response_value is a string or None

    Ensures:
        - Returns ( answer, qualifier ) tuple
        - answer is "yes", "no", or "neither" (lowercase), or None if empty
        - qualifier is the comment text or None

    Examples:
        "yes [comment: fix the tests]"         -> ( "yes", "fix the tests" )
        "no [comment: not ready]"              -> ( "no", "not ready" )
        "neither [comment: re-frame please]"   -> ( "neither", "re-frame please" )
        "yes"                                  -> ( "yes", None )
        "no"                                   -> ( "no", None )
        "neither"                              -> ( "neither", None )
    """
    if not response_value:
        return ( None, None )

    match = re.match( r'^(yes|no|neither)\s*(?:\[comment:\s*(.+)\])?$', response_value.strip(), re.IGNORECASE )
    if match:
        return ( match.group( 1 ).lower(), match.group( 2 ) )

    # Fallback: treat the whole string as the answer
    return ( response_value.strip().lower(), None )


def format_qualified_response( answer, qualifier ):
    """
    Format a yes/no/neither answer with qualifier into an enriched string that Claude will act on.

    Requires:
        - answer is "yes", "no", or "neither"
        - qualifier is a non-empty string

    Ensures:
        - Returns a multi-line string with explicit instructions for Claude
        - "neither" answers get re-framed copy signaling the question needs revision
    """
    if answer == "neither":
        return (
            f"{answer}\n\n"
            f"IMPORTANT — The user signaled the question itself needs re-framing and attached a comment:\n"
            f'"{qualifier}"\n\n'
            "You MUST treat this as a direct instruction to re-frame the question, not as a soft yes or no. "
            "Read the comment, then ask a clearer follow-up that addresses what they actually want to decide."
        )

    return (
        f"{answer}\n\n"
        f"IMPORTANT — The user attached a comment to their {answer} response:\n"
        f'"{qualifier}"\n\n'
        "You MUST act on this comment. It is a direct instruction or question from the user. "
        "Do NOT ignore it. If it is a question, answer it. If it is an instruction, carry it out."
    )


def quick_smoke_test():
    """Quick smoke test for notification_utils module."""
    import cosa.utils.util as cu

    cu.print_banner( "Notification Utils Smoke Test", prepend_nl=True )

    try:
        # Test 1: Single question, single select
        print( "Testing format_questions_for_tts (single question, single select)..." )
        questions = [ {
            "question"    : "Which database?",
            "multiSelect" : False,
            "options"     : [ { "label": "PostgreSQL" }, { "label": "MySQL" } ]
        } ]
        tts = format_questions_for_tts( questions )
        assert tts == "Which database?"
        assert "Option" not in tts  # Options NOT in TTS
        print( f"✓ Result: '{tts}'" )

        # Test 2: Single question, multi-select
        print( "Testing format_questions_for_tts (single question, multi-select)..." )
        questions = [ {
            "question"    : "Which features?",
            "multiSelect" : True,
            "options"     : [ { "label": "Auth" }, { "label": "Cache" } ]
        } ]
        tts = format_questions_for_tts( questions )
        assert "Which features?" in tts
        assert "You can select multiple options" in tts
        print( f"✓ Result: '{tts}'" )

        # Test 3: Multiple questions
        print( "Testing format_questions_for_tts (multiple questions)..." )
        questions = [
            { "question": "First?", "multiSelect": False },
            { "question": "Second?", "multiSelect": True }
        ]
        tts = format_questions_for_tts( questions )
        assert "Question 1 of 2" in tts
        assert "Question 2 of 2" in tts
        assert "You can select multiple options" in tts
        print( f"✓ Result: '{tts}'" )

        # Test 4: convert_questions_for_api
        print( "Testing convert_questions_for_api..." )
        questions = [ {
            "question"    : "Which auth?",
            "header"      : "Auth",
            "multiSelect" : True,
            "options"     : [ { "label": "OAuth" }, { "label": "JWT" } ]
        } ]
        converted = convert_questions_for_api( questions )
        assert "questions" in converted
        assert converted[ "questions" ][ 0 ][ "multi_select" ] is True
        assert "multiSelect" not in converted[ "questions" ][ 0 ]
        print( "✓ multiSelect -> multi_select conversion correct" )

        # Test 5: format_open_ended_batch_for_tts (single question)
        print( "Testing format_open_ended_batch_for_tts (single question)..." )
        questions = [ { "question": "What topic?", "header": "Topic" } ]
        tts = format_open_ended_batch_for_tts( questions )
        assert tts == "What topic?"
        assert "I have" not in tts
        print( f"✓ Result: '{tts}'" )

        # Test 6: format_open_ended_batch_for_tts (multiple questions — count-only preamble)
        print( "Testing format_open_ended_batch_for_tts (multiple questions)..." )
        questions = [
            { "question": "What topic?", "header": "Topic" },
            { "question": "What budget?", "header": "Budget" },
            { "question": "Who is the audience?", "header": "Audience" }
        ]
        tts = format_open_ended_batch_for_tts( questions )
        assert tts == "I have 3 questions for you."
        assert "Question 1 of 3" not in tts  # Individual questions NOT spoken
        print( f"✓ Result: '{tts}'" )

        # Test 7: convert_open_ended_batch_for_api
        print( "Testing convert_open_ended_batch_for_api..." )
        questions = [
            { "question": "What topic?", "header": "Topic" },
            { "question": "What budget?", "header": "Budget" }
        ]
        converted = convert_open_ended_batch_for_api( questions )
        assert "questions" in converted
        assert len( converted[ "questions" ] ) == 2
        assert converted[ "questions" ][ 0 ][ "input_type" ] == "text"
        assert converted[ "questions" ][ 0 ][ "header" ] == "Topic"
        assert converted[ "questions" ][ 1 ][ "header" ] == "Budget"
        print( "✓ Batch questions converted with input_type='text'" )

        # Test 8: convert_open_ended_batch_for_api with default_value
        print( "Testing convert_open_ended_batch_for_api (with default_value)..." )
        questions = [
            { "question": "What budget?", "header": "Budget", "default_value": "no limit" },
            { "question": "What audience?", "header": "Audience" }
        ]
        converted = convert_open_ended_batch_for_api( questions )
        assert converted[ "questions" ][ 0 ][ "default_value" ] == "no limit"
        assert "default_value" not in converted[ "questions" ][ 1 ]
        print( "✓ default_value passed through when present, omitted when absent" )

        # Test 9: extract_qualifier_comment
        print( "Testing extract_qualifier_comment..." )
        answer, qualifier = extract_qualifier_comment( "yes [comment: fix the tests]" )
        assert answer == "yes"
        assert qualifier == "fix the tests"
        answer, qualifier = extract_qualifier_comment( "no" )
        assert answer == "no"
        assert qualifier is None
        answer, qualifier = extract_qualifier_comment( None )
        assert answer is None
        assert qualifier is None
        # Neither parse cases
        answer, qualifier = extract_qualifier_comment( "neither" )
        assert answer == "neither"
        assert qualifier is None
        answer, qualifier = extract_qualifier_comment( "neither [comment: re-frame please]" )
        assert answer == "neither"
        assert qualifier == "re-frame please"
        answer, qualifier = extract_qualifier_comment( "NEITHER" )
        assert answer == "neither"
        assert qualifier is None
        print( "✓ extract_qualifier_comment works correctly" )

        # Test 10: format_qualified_response
        print( "Testing format_qualified_response..." )
        result = format_qualified_response( "yes", "fix the import" )
        assert result.startswith( "yes\n" )
        assert "MUST act" in result
        assert "fix the import" in result
        assert "Do NOT ignore" in result
        # Neither format case — uses re-framed copy
        result = format_qualified_response( "neither", "the question is malformed" )
        assert result.startswith( "neither\n" )
        assert "re-framing" in result
        assert "the question is malformed" in result
        assert "soft yes or no" in result
        print( "✓ format_qualified_response works correctly" )

        # Test 11: is_known_project (known projects)
        print( "Testing is_known_project (known)..." )
        assert is_known_project( "lupin" ) is True
        assert is_known_project( "cosa" ) is True
        assert is_known_project( "plan" ) is True
        assert is_known_project( "lupin-mobile" ) is True
        assert is_known_project( "lupin-plugin-firefox" ) is True
        print( "✓ Known projects return True" )

        # Test 12: is_known_project (unknown projects)
        print( "Testing is_known_project (unknown)..." )
        assert is_known_project( "newrepo" ) is False
        assert is_known_project( "unknown" ) is False
        assert is_known_project( "" ) is False
        print( "✓ Unknown projects return False" )

        # Test 13: KNOWN_PROJECTS dict structure
        print( "Testing KNOWN_PROJECTS structure..." )
        assert "/lupin" in KNOWN_PROJECTS
        assert KNOWN_PROJECTS[ "/lupin" ] == "lupin"
        assert KNOWN_PROJECTS[ "/cosa" ] == "cosa"
        assert KNOWN_PROJECTS[ "/planning-is-prompting" ] == "plan"
        assert KNOWN_PROJECTS[ "/lupin-mobile" ] == "lupin-mobile"
        assert KNOWN_PROJECTS[ "/lupin-plugin-firefox" ] == "lupin-plugin-firefox"
        assert KNOWN_PROJECTS[ "/scratchpad" ] == "scratchpad"
        print( "✓ KNOWN_PROJECTS has correct mappings" )

        print( "\n✓ Notification utils smoke test completed successfully" )

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
