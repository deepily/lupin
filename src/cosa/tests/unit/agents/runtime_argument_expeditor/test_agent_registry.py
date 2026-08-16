"""
Unit tests for runtime_argument_expeditor/agent_registry.py:
  - JOB_ARG_CONTRACTS         : the 10-entry routing registry (structure spot-checks)
  - get_cli_help           : subprocess --help capture + process-lifetime cache
  - get_user_visible_args  : subprocess --user-visible-args JSON capture + cache

subprocess.run is fully boundary-mocked — NO real subprocess spawn. The module-level
caches are cleared per-test to prevent cross-test pollution.

Created 2026-05-31 by Extra 1 🪨 (CoSA coverage campaign, runtime_argument_expeditor lane).
"""

import json
import subprocess
import unittest
from unittest.mock import MagicMock, patch

import cosa.agents.runtime_argument_expeditor.agent_registry as ar


class TestRegistryStructure( unittest.TestCase ):

    def test_every_agent_has_required_keys( self ):
        # count assert deleted 2026-08-15 (Rachel): len(JOB_ARG_CONTRACTS)==N reads its own
        # source and catches only stale-count churn; the drift guard's four-way set-equality
        # subsumes it. The per-entry required-field loop below is the real structural check.
        for key, entry in ar.JOB_ARG_CONTRACTS.items():
            for field in ( "cli_module", "required_user_args", "system_provided",
                           "arg_mapping", "fallback_questions", "fallback_defaults",
                           "display_name", "job_prefix" ):
                self.assertIn( field, entry, f"{key} missing {field}" )

    def test_known_entries( self ):
        self.assertEqual( ar.JOB_ARG_CONTRACTS[ "agent router go to deep research" ][ "required_user_args" ], [ "query" ] )
        self.assertIsNone( ar.JOB_ARG_CONTRACTS[ "agent router go to test suite" ][ "cli_module" ] )


class TestGetCliHelp( unittest.TestCase ):

    def setUp( self ):
        ar._help_cache.clear()

    def test_unknown_command_returns_none( self ):
        self.assertIsNone( ar.get_cli_help( "nonexistent" ) )

    def test_cli_module_none_caches_none( self ):
        out = ar.get_cli_help( "agent router go to test suite" )   # cli_module is None
        self.assertIsNone( out )
        self.assertIn( "agent router go to test suite", ar._help_cache )

    def test_subprocess_success_returns_stdout( self ):
        proc = MagicMock( stdout="usage: deep_research ...", stderr="", returncode=0 )
        with patch.object( ar.subprocess, "run", return_value=proc ) as run:
            out = ar.get_cli_help( "agent router go to deep research" )
        self.assertIn( "usage", out )
        run.assert_called_once()

    def test_subprocess_falls_back_to_stderr( self ):
        proc = MagicMock( stdout="", stderr="err help", returncode=0 )
        with patch.object( ar.subprocess, "run", return_value=proc ):
            out = ar.get_cli_help( "agent router go to deep research" )
        self.assertEqual( out, "err help" )

    def test_cache_hit_avoids_second_subprocess( self ):
        proc = MagicMock( stdout="help", stderr="", returncode=0 )
        with patch.object( ar.subprocess, "run", return_value=proc ) as run:
            ar.get_cli_help( "agent router go to deep research" )
            ar.get_cli_help( "agent router go to deep research" )   # cache hit
        run.assert_called_once()

    def test_subprocess_exception_returns_none_and_caches( self ):
        with patch.object( ar.subprocess, "run",
                           side_effect=subprocess.TimeoutExpired( cmd="x", timeout=10 ) ):
            out = ar.get_cli_help( "agent router go to deep research" )
        self.assertIsNone( out )
        self.assertIsNone( ar._help_cache[ "agent router go to deep research" ] )


class TestGetUserVisibleArgs( unittest.TestCase ):

    def setUp( self ):
        ar._user_visible_cache.clear()

    def test_unknown_command_returns_none( self ):
        self.assertIsNone( ar.get_user_visible_args( "nonexistent" ) )

    def test_cli_module_none_caches_none( self ):
        self.assertIsNone( ar.get_user_visible_args( "agent router go to test suite" ) )
        self.assertIn( "agent router go to test suite", ar._user_visible_cache )

    def test_success_parses_json_list( self ):
        proc = MagicMock( stdout='["query", "budget"]', returncode=0 )
        with patch.object( ar.subprocess, "run", return_value=proc ):
            out = ar.get_user_visible_args( "agent router go to deep research" )
        self.assertEqual( out, [ "query", "budget" ] )

    def test_cache_hit( self ):
        proc = MagicMock( stdout='["query"]', returncode=0 )
        with patch.object( ar.subprocess, "run", return_value=proc ) as run:
            ar.get_user_visible_args( "agent router go to deep research" )
            ar.get_user_visible_args( "agent router go to deep research" )
        run.assert_called_once()

    def test_nonzero_returncode_returns_none( self ):
        proc = MagicMock( stdout="", returncode=1 )
        with patch.object( ar.subprocess, "run", return_value=proc ):
            self.assertIsNone( ar.get_user_visible_args( "agent router go to deep research" ) )

    def test_malformed_json_returns_none( self ):
        proc = MagicMock( stdout="not json", returncode=0 )
        with patch.object( ar.subprocess, "run", return_value=proc ):
            self.assertIsNone( ar.get_user_visible_args( "agent router go to deep research" ) )

    def test_subprocess_exception_returns_none( self ):
        with patch.object( ar.subprocess, "run",
                           side_effect=subprocess.TimeoutExpired( cmd="x", timeout=10 ) ):
            self.assertIsNone( ar.get_user_visible_args( "agent router go to deep research" ) )


if __name__ == "__main__":
    unittest.main()
