"""
Unit tests for cosa.agents.llm_data_types.

Pure value-object module (dataclasses + an enum) with __post_init__ validation
on each type. Tests exercise every validation branch:

- MessageRole enum values
- LlmMessage: valid construction, empty-content guard, metadata default
- LlmRequest: prompt/messages XOR guard, temperature / max_tokens / top_p /
  frequency_penalty / presence_penalty range guards (both bounds)
- LlmResponse: negative-token / negative-duration guards, total_tokens
  derivation, tokens_per_second derivation
- LlmStreamChunk: negative chunk_index guard

No external dependencies — these are in-memory value objects.

Created 2026-05-31 by Sam 🎙️ (CoSA coverage campaign, agents Tier-2, greenfield).
"""

import unittest

from cosa.agents.llm_data_types import (
    MessageRole,
    LlmMessage,
    LlmRequest,
    LlmResponse,
    LlmStreamChunk,
)


class TestMessageRole( unittest.TestCase ):
    def test_enum_values( self ):
        self.assertEqual( MessageRole.SYSTEM.value, "system" )
        self.assertEqual( MessageRole.USER.value, "user" )
        self.assertEqual( MessageRole.ASSISTANT.value, "assistant" )


class TestLlmMessage( unittest.TestCase ):
    def test_valid_message_defaults_metadata( self ):
        """A non-empty message is accepted; metadata defaults to an empty dict."""
        msg = LlmMessage( role=MessageRole.USER, content="hello" )
        self.assertEqual( msg.role, MessageRole.USER )
        self.assertEqual( msg.content, "hello" )
        self.assertEqual( msg.metadata, {} )

    def test_empty_content_raises( self ):
        """Whitespace-only content trips the empty-content guard."""
        with self.assertRaises( ValueError ):
            LlmMessage( role=MessageRole.USER, content="   " )


class TestLlmRequest( unittest.TestCase ):
    def test_prompt_only_valid( self ):
        req = LlmRequest( prompt="hi" )
        self.assertEqual( req.prompt, "hi" )
        self.assertEqual( req.metadata, {} )

    def test_messages_only_valid( self ):
        req = LlmRequest( messages=[ LlmMessage( role=MessageRole.USER, content="hi" ) ] )
        self.assertEqual( len( req.messages ), 1 )

    def test_neither_prompt_nor_messages_raises( self ):
        with self.assertRaises( ValueError ):
            LlmRequest()

    def test_both_prompt_and_messages_raises( self ):
        with self.assertRaises( ValueError ):
            LlmRequest( prompt="hi", messages=[ LlmMessage( role=MessageRole.USER, content="hi" ) ] )

    def test_temperature_too_low_and_high( self ):
        with self.assertRaises( ValueError ):
            LlmRequest( prompt="hi", temperature=-0.1 )
        with self.assertRaises( ValueError ):
            LlmRequest( prompt="hi", temperature=2.1 )

    def test_temperature_boundaries_valid( self ):
        self.assertEqual( LlmRequest( prompt="hi", temperature=0.0 ).temperature, 0.0 )
        self.assertEqual( LlmRequest( prompt="hi", temperature=2.0 ).temperature, 2.0 )

    def test_max_tokens_non_positive_raises( self ):
        with self.assertRaises( ValueError ):
            LlmRequest( prompt="hi", max_tokens=0 )

    def test_max_tokens_none_or_positive_valid( self ):
        self.assertIsNone( LlmRequest( prompt="hi", max_tokens=None ).max_tokens )
        self.assertEqual( LlmRequest( prompt="hi", max_tokens=10 ).max_tokens, 10 )

    def test_top_p_out_of_range_raises( self ):
        with self.assertRaises( ValueError ):
            LlmRequest( prompt="hi", top_p=-0.1 )
        with self.assertRaises( ValueError ):
            LlmRequest( prompt="hi", top_p=1.1 )

    def test_frequency_penalty_out_of_range_raises( self ):
        with self.assertRaises( ValueError ):
            LlmRequest( prompt="hi", frequency_penalty=2.5 )
        with self.assertRaises( ValueError ):
            LlmRequest( prompt="hi", frequency_penalty=-2.5 )

    def test_presence_penalty_out_of_range_raises( self ):
        with self.assertRaises( ValueError ):
            LlmRequest( prompt="hi", presence_penalty=3.0 )

    def test_penalties_in_range_valid( self ):
        req = LlmRequest( prompt="hi", frequency_penalty=-2.0, presence_penalty=2.0 )
        self.assertEqual( req.frequency_penalty, -2.0 )
        self.assertEqual( req.presence_penalty, 2.0 )


class TestLlmResponse( unittest.TestCase ):
    def test_minimal_valid( self ):
        resp = LlmResponse( text="answer" )
        self.assertEqual( resp.text, "answer" )
        self.assertEqual( resp.total_tokens, 0 )
        self.assertEqual( resp.tokens_per_second, 0.0 )

    def test_negative_prompt_tokens_raises( self ):
        with self.assertRaises( ValueError ):
            LlmResponse( text="x", prompt_tokens=-1 )

    def test_negative_completion_tokens_raises( self ):
        with self.assertRaises( ValueError ):
            LlmResponse( text="x", completion_tokens=-1 )

    def test_negative_duration_raises( self ):
        with self.assertRaises( ValueError ):
            LlmResponse( text="x", duration_ms=-5.0 )

    def test_total_tokens_derived_from_prompt( self ):
        """total_tokens==0 with prompt_tokens>0 → total derived."""
        resp = LlmResponse( text="x", prompt_tokens=10 )
        self.assertEqual( resp.total_tokens, 10 )

    def test_total_tokens_derived_from_completion( self ):
        """total_tokens==0 with completion_tokens>0 → total derived (inner-or arm)."""
        resp = LlmResponse( text="x", completion_tokens=7 )
        self.assertEqual( resp.total_tokens, 7 )

    def test_total_tokens_not_overwritten_when_provided( self ):
        """A non-zero total_tokens is left untouched."""
        resp = LlmResponse( text="x", prompt_tokens=2, completion_tokens=3, total_tokens=99 )
        self.assertEqual( resp.total_tokens, 99 )

    def test_tokens_per_second_derived( self ):
        """duration>0 and completion>0 → tokens_per_second computed."""
        resp = LlmResponse( text="x", completion_tokens=100, duration_ms=1000.0 )
        self.assertAlmostEqual( resp.tokens_per_second, 100.0 )   # 100 / 1000ms * 1000

    def test_tokens_per_second_zero_when_no_duration( self ):
        """duration==0 → tokens_per_second stays 0 (False arm)."""
        resp = LlmResponse( text="x", completion_tokens=100, duration_ms=0.0 )
        self.assertEqual( resp.tokens_per_second, 0.0 )


class TestLlmStreamChunk( unittest.TestCase ):
    def test_valid_chunk( self ):
        chunk = LlmStreamChunk( text="partial", is_final=False, chunk_index=3 )
        self.assertEqual( chunk.text, "partial" )
        self.assertEqual( chunk.chunk_index, 3 )
        self.assertEqual( chunk.metadata, {} )

    def test_negative_chunk_index_raises( self ):
        with self.assertRaises( ValueError ):
            LlmStreamChunk( text="x", chunk_index=-1 )


if __name__ == "__main__":
    unittest.main()
