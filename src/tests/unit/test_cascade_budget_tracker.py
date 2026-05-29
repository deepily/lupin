"""
Unit smoke test for the per-section budget tracker added to
src/scripts/cascade_heartbeat_scheduler.py (v2 Item #3).

Tests check_section_budgets() in isolation by:
  - patching COMMONS_TOPICS_DIR to a tmp directory
  - patching fire_budget_warning to capture calls (no real HTTP / DM)
  - exercising 3 scenarios: unit smoke, idempotence, multi-section

Run:
  pytest src/tests/unit/test_cascade_budget_tracker.py -v
"""

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock


LUPIN_ROOT = os.environ.get( "LUPIN_ROOT" )
if LUPIN_ROOT is None:
    raise RuntimeError( "LUPIN_ROOT must be set to run this test" )

SCRIPT_PATH = Path( LUPIN_ROOT ) / "src" / "scripts" / "cascade_heartbeat_scheduler.py"


def _load_module():
    """Load the daemon script as a module via importlib (bypasses __main__ block)."""
    spec   = importlib.util.spec_from_file_location( "cascade_heartbeat_scheduler", SCRIPT_PATH )
    module = importlib.util.module_from_spec( spec )
    spec.loader.exec_module( module )
    return module


class TestCheckSectionBudgets( unittest.TestCase ):

    def setUp( self ):
        self.module   = _load_module()
        self.tmp      = tempfile.TemporaryDirectory()
        self.tmp_path = Path( self.tmp.name )
        self.marker   = "<<<__lupin_commons_entry_boundary__>>>"

        # Redirect COMMONS_TOPICS_DIR on the module to our tmp dir
        self._original_dir              = self.module.COMMONS_TOPICS_DIR
        self.module.COMMONS_TOPICS_DIR  = self.tmp_path

        # Capture fire_budget_warning calls without making real HTTP
        self.warning_calls = []
        def _fake_fire( api_base_url, api_key, manager, store, section, count, threshold ):
            self.warning_calls.append( {
                "section"   : section,
                "count"     : count,
                "threshold" : threshold,
                "manager"   : manager,
            } )
            return { "section": section, "register_status": 200 }
        self._original_fire             = self.module.fire_budget_warning
        self.module.fire_budget_warning = _fake_fire

    def tearDown( self ):
        self.module.COMMONS_TOPICS_DIR  = self._original_dir
        self.module.fire_budget_warning = self._original_fire
        self.tmp.cleanup()

    def _make_section_file( self, name, entry_count ):
        """Create a fake section file with N boundary markers."""
        path     = self.tmp_path / f"{name}.md"
        content  = f"---\ntopic: {name}\n---\n"
        content += ( self.marker + "\n## fake entry\nfake body\n\n" ) * entry_count
        path.write_text( content, encoding="utf-8" )
        return path

    def _invoke( self, warned_sections, threshold=25 ):
        """Run check_section_budgets with stock test args."""
        self.module.check_section_budgets(
            section_glob    = "cascaded-prototype-section-*.md",
            threshold       = threshold,
            api_base_url    = "http://localhost:7999",
            api_key         = "stub",
            manager         = "tiberius",
            store           = MagicMock(),
            warned_sections = warned_sections,
        )

    # -- Scenario 1: unit smoke (single section at threshold) --
    def test_scenario_1_unit_smoke_at_threshold( self ):
        self._make_section_file( "cascaded-prototype-section-test", entry_count=25 )
        warned_sections = {}

        self._invoke( warned_sections )

        self.assertEqual( len( self.warning_calls ), 1, "exactly one warn expected" )
        self.assertEqual( self.warning_calls[ 0 ][ "section" ],   "cascaded-prototype-section-test" )
        self.assertEqual( self.warning_calls[ 0 ][ "count" ],     25 )
        self.assertEqual( self.warning_calls[ 0 ][ "threshold" ], 25 )
        self.assertEqual( self.warning_calls[ 0 ][ "manager" ],   "tiberius" )
        self.assertTrue( warned_sections.get( "cascaded-prototype-section-test" ) )

    # -- Scenario 2: idempotence (second tick doesn't re-warn) --
    def test_scenario_2_idempotence( self ):
        path = self._make_section_file( "cascaded-prototype-section-test", entry_count=25 )
        warned_sections = {}

        # First tick — should warn
        self._invoke( warned_sections )
        self.assertEqual( len( self.warning_calls ), 1, "first tick should warn" )

        # Add a 26th entry (file grows past threshold)
        with path.open( "a", encoding="utf-8" ) as f:
            f.write( self.marker + "\n## entry 26\nbody\n\n" )

        # Second tick — should NOT warn again
        self._invoke( warned_sections )
        self.assertEqual( len( self.warning_calls ), 1, "no second warn for same section" )

    # -- Scenario 3: multi-section (only one over threshold) --
    def test_scenario_3_multi_section_only_one_over( self ):
        self._make_section_file( "cascaded-prototype-section-A", entry_count=10 )  # below
        self._make_section_file( "cascaded-prototype-section-B", entry_count=30 )  # over
        warned_sections = {}

        self._invoke( warned_sections )

        self.assertEqual( len( self.warning_calls ), 1, "exactly one section over threshold" )
        self.assertEqual( self.warning_calls[ 0 ][ "section" ], "cascaded-prototype-section-B" )
        self.assertEqual( self.warning_calls[ 0 ][ "count" ],   30 )
        self.assertFalse( warned_sections.get( "cascaded-prototype-section-A" ) )
        self.assertTrue(  warned_sections.get( "cascaded-prototype-section-B" ) )

    # -- Bonus: below-threshold section never warns --
    def test_scenario_4_below_threshold_no_warn( self ):
        self._make_section_file( "cascaded-prototype-section-X", entry_count=24 )
        warned_sections = {}

        self._invoke( warned_sections )

        self.assertEqual( len( self.warning_calls ), 0, "below-threshold should not warn" )
        self.assertFalse( warned_sections.get( "cascaded-prototype-section-X" ) )

    # -- Bonus: glob ignores non-matching files --
    def test_scenario_5_glob_ignores_unrelated_topics( self ):
        # Section file (matches glob)
        self._make_section_file( "cascaded-prototype-section-A", entry_count=30 )
        # Non-section file (doesn't match glob)
        unrelated = self.tmp_path / "dm-tiberius.md"
        unrelated.write_text( "---\n---\n" + ( self.marker + "\nbody\n\n" ) * 30, encoding="utf-8" )

        warned_sections = {}
        self._invoke( warned_sections )

        self.assertEqual( len( self.warning_calls ), 1, "exactly one match (section file only)" )
        self.assertEqual( self.warning_calls[ 0 ][ "section" ], "cascaded-prototype-section-A" )


if __name__ == "__main__":
    unittest.main()
