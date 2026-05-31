"""
Unit tests for cosa.agents.bug_fix_expediter.dead_job_packager.

package_dead_job() pulls a row from the CJ Flow job_history table (via the
lazily-imported cosa.rest.job_persistence.get_job_by_id_hash) and converts it
to a DeadJobContext. Branch matrix covered:
  - empty dead_job_id            → ValueError
  - row is None                  → return None (debug-on prints, debug-off silent)
  - status not failed/interrupted→ ValueError
  - metadata_json present        → stack_trace extracted from it
  - metadata_json absent/falsy   → `or {}` fallback, stack_trace None
  - success                      → fully-populated DeadJobContext (debug-on prints)

The get_job_by_id_hash boundary is mocked via a fake cosa.rest.job_persistence
module injected into sys.modules — no Postgres, no real persistence import.
quick_smoke_test + __main__ excluded via pyproject coverage config.

Created 2026-05-31 by Mr. Radio 🦉 (CoSA coverage campaign, agents Tier-2, expediter lane).
"""

import io
import sys
import types
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from cosa.agents.bug_fix_expediter.dead_job_packager import package_dead_job
from cosa.agents.bug_fix_expediter.state import DeadJobContext


def _full_row( **over ):
    row = {
        "id_hash"          : "dr-test::u1",
        "job_type"         : "deep_research",
        "user_id"          : "u1",
        "user_email"       : "t@t.com",
        "session_id"       : "s1",
        "status"           : "failed",
        "question_text"    : "what is x",
        "error"            : "boom",
        "routing_command"  : "agent router go to deep research",
        "duration_seconds" : 3.5,
        "metadata_json"    : { "stack_trace": "Trace L42" },
        "created_at"       : "t0",
        "started_at"       : "t1",
        "completed_at"     : "t2",
    }
    row.update( over )
    return row


class _PatchedPersistence:
    """Context manager injecting a fake cosa.rest.job_persistence into sys.modules
    so the lazy `from cosa.rest.job_persistence import get_job_by_id_hash` resolves
    to our stub without importing the heavy real module."""

    def __init__( self, return_value ):
        self.return_value = return_value

    def __enter__( self ):
        self._fake = types.ModuleType( "cosa.rest.job_persistence" )
        self._fake.get_job_by_id_hash = lambda _id: self.return_value
        self._patcher = patch.dict( sys.modules, { "cosa.rest.job_persistence": self._fake } )
        self._patcher.start()
        return self

    def __exit__( self, *exc ):
        self._patcher.stop()
        return False


class TestPackageDeadJob( unittest.TestCase ):

    def test_empty_id_raises_valueerror( self ):
        with self.assertRaises( ValueError ) as cm:
            package_dead_job( "" )
        self.assertIn( "non-empty", str( cm.exception ) )

    def test_row_not_found_returns_none_debug_off( self ):
        with _PatchedPersistence( None ):
            buf = io.StringIO()
            with redirect_stdout( buf ):
                out = package_dead_job( "missing-id", debug=False )
        self.assertIsNone( out )
        self.assertEqual( buf.getvalue(), "" )          # silent when debug off

    def test_row_not_found_returns_none_debug_on_prints( self ):
        with _PatchedPersistence( None ):
            buf = io.StringIO()
            with redirect_stdout( buf ):
                out = package_dead_job( "missing-id", debug=True )
        self.assertIsNone( out )
        self.assertIn( "No job found for id_hash: missing-id", buf.getvalue() )

    def test_non_dead_status_raises_valueerror( self ):
        with _PatchedPersistence( _full_row( status="completed" ) ):
            with self.assertRaises( ValueError ) as cm:
                package_dead_job( "dr-test::u1" )
        self.assertIn( "status 'completed'", str( cm.exception ) )
        self.assertIn( "only 'failed' or 'interrupted'", str( cm.exception ) )

    def test_success_with_metadata_extracts_stack_trace_debug_on( self ):
        with _PatchedPersistence( _full_row() ):
            buf = io.StringIO()
            with redirect_stdout( buf ):
                ctx = package_dead_job( "dr-test::u1", debug=True )
        self.assertIsInstance( ctx, DeadJobContext )
        self.assertEqual( ctx.id_hash,          "dr-test::u1" )
        self.assertEqual( ctx.job_type,         "deep_research" )
        self.assertEqual( ctx.status,           "failed" )
        self.assertEqual( ctx.stack_trace,      "Trace L42" )      # from metadata_json
        self.assertEqual( ctx.error,            "boom" )
        self.assertEqual( ctx.routing_command,  "agent router go to deep research" )
        self.assertEqual( ctx.duration_seconds, 3.5 )
        self.assertEqual( ctx.metadata_json,    { "stack_trace": "Trace L42" } )
        self.assertIn( "Packaged dead job: dr-test::u1", buf.getvalue() )

    def test_success_with_none_metadata_uses_empty_dict_and_no_stack_trace( self ):
        # metadata_json None → `or {}` fallback → stack_trace None.
        row = _full_row( metadata_json=None, status="interrupted", error=None )
        with _PatchedPersistence( row ):
            buf = io.StringIO()
            with redirect_stdout( buf ):
                ctx = package_dead_job( "dr-test::u1", debug=False )
        self.assertEqual( ctx.status,        "interrupted" )
        self.assertIsNone( ctx.stack_trace )
        self.assertIsNone( ctx.error )
        self.assertEqual( ctx.metadata_json, {} )
        self.assertEqual( buf.getvalue(), "" )          # debug off → silent on success path


if __name__ == "__main__":
    unittest.main()
