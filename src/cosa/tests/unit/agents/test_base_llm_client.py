"""
Unit tests for cosa.agents.base_llm_client.

Two abstract base classes with concrete helper methods:

- LlmClientInterface: abstract run_async / run (bodies driven via super()) +
  concrete _format_duration and _print_metadata (tps + duration formatting arms)
- BaseLlmClient: __init__, abstract complete / validate_config /
  get_supported_parameters (super()-driven), concrete complete_sync
  (existing-loop + new-loop arms), __str__, __repr__

Abstract bodies are executed through minimal super()-delegating concrete
subclasses. asyncio.get_event_loop is mocked to exercise both complete_sync
arms deterministically. du.print_banner / print mocked at the boundary.

Created 2026-05-31 by Sam 🎙️ (CoSA coverage campaign, agents Tier-2).
"""

import asyncio
import unittest
from unittest.mock import Mock, patch

from cosa.agents.base_llm_client import LlmClientInterface, BaseLlmClient


class _ConcreteInterface( LlmClientInterface ):
    """Concrete LlmClientInterface delegating abstracts to super() for body coverage."""

    model_name = "test-model"

    async def run_async( self, prompt, stream=False, **kwargs ):
        return await super().run_async( prompt, stream, **kwargs )

    def run( self, prompt, stream=False, **kwargs ):
        return super().run( prompt, stream, **kwargs )


class _ConcreteBase( BaseLlmClient ):
    """Concrete BaseLlmClient delegating abstracts to super() for body coverage."""

    async def complete( self, request ):
        return await super().complete( request )

    async def validate_config( self ):
        return await super().validate_config()

    def get_supported_parameters( self ):
        return super().get_supported_parameters()


class TestLlmClientInterface( unittest.TestCase ):
    """Abstract-instantiation guard, abstract bodies, _format_duration, _print_metadata."""

    def test_cannot_instantiate_abstract( self ):
        with self.assertRaises( TypeError ):
            LlmClientInterface()

    def test_abstract_bodies_execute_via_super( self ):
        inst = _ConcreteInterface()
        self.assertIsNone( inst.run( "p" ) )
        self.assertIsNone( asyncio.run( inst.run_async( "p" ) ) )

    def test_format_duration( self ):
        inst = _ConcreteInterface()
        self.assertEqual( inst._format_duration( 1.5 ), "1500ms" )

    def test_print_metadata_with_duration( self ):
        """duration>0 → tokens/sec computed, duration formatted."""
        inst = _ConcreteInterface()
        with patch( "cosa.agents.base_llm_client.du.print_banner" ), patch( "builtins.print" ):
            inst._print_metadata( prompt_tokens=5, completion_tokens=10, duration=2.0, client_type="Chat" )
        # No exception == path executed; nothing returned

    def test_print_metadata_no_duration_uses_inf_and_na( self ):
        """duration=None → tps inf branch + 'N/A' duration string."""
        inst = _ConcreteInterface()
        with patch( "cosa.agents.base_llm_client.du.print_banner" ), patch( "builtins.print" ):
            inst._print_metadata( prompt_tokens=5, completion_tokens=10, duration=None )

    def test_print_metadata_zero_duration( self ):
        """duration=0 → tps inf (falsy first operand) but duration string still formatted."""
        inst = _ConcreteInterface()
        with patch( "cosa.agents.base_llm_client.du.print_banner" ), patch( "builtins.print" ):
            inst._print_metadata( prompt_tokens=1, completion_tokens=2, duration=0.0 )


class TestBaseLlmClient( unittest.TestCase ):
    """__init__, abstract bodies, complete_sync arms, __str__/__repr__."""

    def test_init_stores_fields( self ):
        client = _ConcreteBase( "gpt-x", debug=True, verbose=True )
        self.assertEqual( client.model, "gpt-x" )
        self.assertTrue( client.debug )
        self.assertTrue( client.verbose )
        self.assertFalse( client._initialized )

    def test_cannot_instantiate_abstract( self ):
        with self.assertRaises( TypeError ):
            BaseLlmClient( "m" )

    def test_abstract_bodies_execute_via_super( self ):
        client = _ConcreteBase( "m" )
        self.assertIsNone( asyncio.run( client.complete( Mock() ) ) )
        self.assertIsNone( asyncio.run( client.validate_config() ) )
        self.assertIsNone( client.get_supported_parameters() )

    def test_complete_sync_with_existing_loop( self ):
        """complete_sync uses the existing event loop when available."""
        client = _ConcreteBase( "m" )
        loop = asyncio.new_event_loop()
        try:
            with patch( "asyncio.get_event_loop", return_value=loop ):
                result = client.complete_sync( Mock() )
        finally:
            loop.close()
        self.assertIsNone( result )

    def test_complete_sync_creates_loop_when_none( self ):
        """get_event_loop raising RuntimeError → a new loop is created + set."""
        client = _ConcreteBase( "m" )
        new_loop = asyncio.new_event_loop()
        try:
            with patch( "asyncio.get_event_loop", side_effect=RuntimeError( "no loop" ) ), \
                 patch( "asyncio.new_event_loop", return_value=new_loop ) as mock_new, \
                 patch( "asyncio.set_event_loop" ) as mock_set:
                result = client.complete_sync( Mock() )
        finally:
            new_loop.close()
        self.assertIsNone( result )
        mock_new.assert_called_once()
        mock_set.assert_called_once_with( new_loop )

    def test_str_and_repr( self ):
        client = _ConcreteBase( "gpt-x", debug=True, verbose=False )
        self.assertEqual( str( client ), "_ConcreteBase(model=gpt-x)" )
        self.assertEqual(
            repr( client ),
            "_ConcreteBase(model='gpt-x', debug=True, verbose=False)"
        )


if __name__ == "__main__":
    unittest.main()
