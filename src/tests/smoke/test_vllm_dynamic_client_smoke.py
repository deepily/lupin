#!/usr/bin/env python3
"""
Smoke test for dynamic vLLM client creation via LlmClientFactory.

Verifies that:
1. LlmClient.get_model() produces a valid model string from a filesystem path
2. LlmClientFactory().get_client() creates a CompletionClient for dynamic vLLM models
   (instead of raising NotImplementedError)
3. The returned client has correct base_url and model_name attributes

Does NOT require:
- A running vLLM server
- A running Lupin server
- GPU resources or training data

Created: 2026-02-04
"""

import os
import sys
import traceback

# Bootstrap path setup
lupin_root = os.environ.get( "LUPIN_ROOT" )
if lupin_root:
    sys.path.insert( 0, os.path.join( lupin_root, "src" ) )

import cosa.utils.util as cu

# Hardcoded merged adapter path from last successful training run (2026-02-04)
MERGED_ADAPTER_DIR = "/mnt/DATA01/include/www.deepily.ai/projects/models/Ministral-8B-Instruct-2410.lora/merged-on-2026-02-04-at-17-31"


def quick_smoke_test():
    """
    Smoke test for dynamic vLLM CompletionClient creation.

    Requires:
        - LUPIN_ROOT environment variable set
        - cosa package importable

    Ensures:
        - LlmClient.get_model() produces 'deepily//mnt/...' format string
        - LlmClientFactory().get_client() returns a CompletionClient (no NotImplementedError)
        - Returned client has base_url pointing to localhost:3000
        - Returned client has model_name matching the filesystem path
    """

    from cosa.agents.llm_client import LlmClient
    from cosa.agents.llm_client_factory import LlmClientFactory
    from cosa.agents.completion_client import CompletionClient

    results = []

    # Test 1: LlmClient.get_model() produces correct format
    cu.print_banner( "Test 1: LlmClient.get_model() format", prepend_nl=True )
    try:
        model = LlmClient.get_model( MERGED_ADAPTER_DIR )
        expected_prefix = "deepily/"
        assert model.startswith( expected_prefix ), f"Expected prefix '{expected_prefix}', got '{model[:20]}...'"
        assert "//" in model, f"Expected '//' in model string, got '{model}'"
        assert MERGED_ADAPTER_DIR in model, f"Expected adapter dir in model string"
        print( f"  Model string: {model}" )
        print( f"  ✓ Format correct" )
        results.append( ( "get_model format", True, "" ) )
    except Exception as e:
        print( f"  ✗ {e}" )
        traceback.print_exc()
        results.append( ( "get_model format", False, str( e ) ) )

    # Test 2: LlmClientFactory creates CompletionClient (no NotImplementedError)
    cu.print_banner( "Test 2: Factory creates CompletionClient", prepend_nl=True )
    try:
        model = LlmClient.get_model( MERGED_ADAPTER_DIR )
        factory = LlmClientFactory()
        client = factory.get_client( model, debug=True, verbose=True )
        assert isinstance( client, CompletionClient ), f"Expected CompletionClient, got {type( client ).__name__}"
        print( f"  Client type: {type( client ).__name__}" )
        print( f"  ✓ CompletionClient created successfully" )
        results.append( ( "factory creates client", True, "" ) )
    except NotImplementedError as e:
        print( f"  ✗ NotImplementedError: {e}" )
        print( f"  This is the bug — factory guard was not replaced" )
        results.append( ( "factory creates client", False, f"NotImplementedError: {e}" ) )
    except Exception as e:
        print( f"  ✗ {e}" )
        traceback.print_exc()
        results.append( ( "factory creates client", False, str( e ) ) )

    # Test 3: Client attributes are correct
    cu.print_banner( "Test 3: Client attributes", prepend_nl=True )
    try:
        model = LlmClient.get_model( MERGED_ADAPTER_DIR )
        factory = LlmClientFactory()
        client = factory.get_client( model, debug=False, verbose=False )

        assert client.base_url == "http://localhost:3000/v1/completions", f"Expected localhost:3000, got {client.base_url}"
        assert client.model_name == MERGED_ADAPTER_DIR, f"Expected '{MERGED_ADAPTER_DIR}', got '{client.model_name}'"
        assert client.prompt_format == "instruction_completion", f"Expected 'instruction_completion', got '{client.prompt_format}'"
        print( f"  base_url: {client.base_url}" )
        print( f"  model_name: {client.model_name}" )
        print( f"  prompt_format: {client.prompt_format}" )
        print( f"  ✓ All attributes correct" )
        results.append( ( "client attributes", True, "" ) )
    except NotImplementedError:
        print( f"  ✗ Skipped (factory creation failed)" )
        results.append( ( "client attributes", False, "Skipped — factory failed" ) )
    except Exception as e:
        print( f"  ✗ {e}" )
        traceback.print_exc()
        results.append( ( "client attributes", False, str( e ) ) )

    # Summary
    cu.print_banner( "Results Summary", prepend_nl=True )
    passed = sum( 1 for _, ok, _ in results if ok )
    total  = len( results )
    for name, ok, err in results:
        status = "✓ PASS" if ok else "✗ FAIL"
        suffix = f" — {err}" if err else ""
        print( f"  {status} | {name}{suffix}" )
    print( f"\n  {passed}/{total} tests passed" )

    return passed == total


def test_vllm_dynamic_client():
    """Pytest entry point."""
    assert quick_smoke_test()


if __name__ == "__main__":
    success = quick_smoke_test()
    sys.exit( 0 if success else 1 )
