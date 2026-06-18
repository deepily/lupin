#!/usr/bin/env python3
"""
Unit tests for cosa.agents.presentation_generator.prompts.json_recovery.

Pure functions — no IO, no LLM. Covers extract_json_object brace-matching
(clean / embedded / nested / no-close / dangling) and recover_json_object
(direct / fenced / prose / unrecoverable / extracted-but-invalid).
"""

from cosa.agents.presentation_generator.prompts.json_recovery import (
    extract_json_object,
    recover_json_object,
)


class TestExtractJsonObject:
    def test_clean( self ):
        assert extract_json_object( '{"a": 1}' ) == '{"a": 1}'

    def test_embedded_in_prose( self ):
        assert extract_json_object( 'go: {"a": 1} ok' ) == '{"a": 1}'

    def test_nested_returns_outermost( self ):
        assert extract_json_object( 'x {"a": {"b": 2}} y' ) == '{"a": {"b": 2}}'

    def test_no_closing_brace( self ):
        assert extract_json_object( "no braces" ) is None

    def test_dangling_close_no_open( self ):
        assert extract_json_object( "dangling } brace" ) is None


class TestRecoverJsonObject:
    def test_direct( self ):
        assert recover_json_object( '{"a": 1}' ) == { "a": 1 }

    def test_json_fence( self ):
        assert recover_json_object( '```json\n{"a": 1}\n```' ) == { "a": 1 }

    def test_bare_fence( self ):
        assert recover_json_object( '```\n{"b": 2}\n```' ) == { "b": 2 }

    def test_prose_recovery( self ):
        assert recover_json_object( 'Sure! {"c": 3} done.' ) == { "c": 3 }

    def test_list_value( self ):
        assert recover_json_object( '[1, 2, 3]' ) == [ 1, 2, 3 ]

    def test_unrecoverable_none( self ):
        assert recover_json_object( "no json here" ) is None

    def test_extracted_but_invalid_none( self ):
        # direct parse fails; extract returns "{not valid}" which is still
        # not valid JSON → second json.loads fails → None.
        assert recover_json_object( "prefix {not valid json} suffix" ) is None
