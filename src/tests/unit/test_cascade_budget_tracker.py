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


class TestDmTopicForSlug( unittest.TestCase ):
    """Phase 4: the daemon's `dm_topic_for` now routes through the shared
    `persona_slug` root, byte-identical to the two heartbeat gateways + the MCP
    DM layer. Guards accent-proofing + the PG-6 space→"_" contract."""

    def setUp( self ):
        self.module = _load_module()

    def test_ascii_personas( self ):
        self.assertEqual( self.module.dm_topic_for( "Mr Radio" ), "dm-mr_radio" )
        self.assertEqual( self.module.dm_topic_for( "mr radio" ), "dm-mr_radio" )
        self.assertEqual( self.module.dm_topic_for( "tiberius" ), "dm-tiberius" )

    def test_accented_persona_FLIP( self ):
        # FLIP guard: the retired accent-leaky re.sub(re.UNICODE) kept accents →
        # "dm-maría" (the split-topic live bug). The persona_slug root strips the
        # accent → the canonical "dm-maria". Revert → "dm-maría" → this fails.
        self.assertEqual( self.module.dm_topic_for( "María" ),     "dm-maria" )
        self.assertEqual( self.module.dm_topic_for( "Mr. Radio" ), "dm-mr_radio" )


class _FakeResp:
    """Minimal requests.Response double for the dm/send push."""
    def __init__( self, status_code=201, json_body=None, text="" ):
        self.status_code = status_code
        self._json       = json_body if json_body is not None else { "dispatched": True }
        self.text        = text
    def json( self ):
        return self._json


class TestFireHeartbeatDmSend( unittest.TestCase ):
    """fire_heartbeat()/fire_budget_warning() were migrated off the deleted
    /api/commons/register-question route onto the notification-native
    /api/dm/send push (body INLINE). These guard the repointed endpoint +
    payload shape so the dead-route regression cannot return."""

    def setUp( self ):
        self.module = _load_module()
        # Patch the module-global requests with a recording double — no real HTTP.
        self.posts          = []
        self._orig_requests = self.module.requests
        fake_requests       = MagicMock()
        def _post( url, json=None, headers=None, timeout=None ):
            self.posts.append( { "url": url, "json": json, "headers": headers, "timeout": timeout } )
            return _FakeResp()
        fake_requests.post  = _post
        self.module.requests = fake_requests

    def tearDown( self ):
        self.module.requests = self._orig_requests

    def test_fire_heartbeat_posts_to_dm_send( self ):
        result = self.module.fire_heartbeat(
            api_base_url = "http://localhost:7999",
            api_key      = "stub-key",
            manager      = "tiberius",
            store        = MagicMock(),
            tick_num     = 7,
        )
        self.assertEqual( len( self.posts ), 1 )
        call = self.posts[ 0 ]
        self.assertEqual( call[ "url" ], "http://localhost:7999/api/dm/send" )
        self.assertEqual( call[ "headers" ][ "X-API-Key" ], "stub-key" )
        payload = call[ "json" ]
        self.assertEqual( set( payload.keys() ),
                          { "sender_session_id", "recipient_persona", "body", "thread_id" } )
        self.assertEqual( payload[ "recipient_persona" ], "tiberius" )
        self.assertEqual( payload[ "sender_session_id" ], self.module.SCHEDULER_SESSION_ID )
        self.assertIn( "heartbeat-7", payload[ "body" ] )
        # retired register-question fields are GONE
        self.assertNotIn( "topic",        payload )
        self.assertNotIn( "expect_reply", payload )
        self.assertNotIn( "ttl_seconds",  payload )
        # success body surfaces dm/send's `dispatched`
        self.assertEqual( result[ "register_status" ], 201 )
        self.assertTrue( result[ "dispatched" ] )

    def test_fire_heartbeat_thread_id_equals_disk_question_id( self ):
        store = MagicMock()
        self.module.fire_heartbeat(
            api_base_url = "http://h", api_key = "k", manager = "tiberius",
            store = store, tick_num = 1,
        )
        # disk post metadata.question_id and the push thread_id are the same qid
        disk_qid = store.post.call_args.kwargs[ "metadata" ][ "question_id" ]
        self.assertEqual( self.posts[ 0 ][ "json" ][ "thread_id" ], disk_qid )

    def test_fire_heartbeat_store_error_skips_push( self ):
        store = MagicMock()
        store.post.side_effect = RuntimeError( "disk down" )
        result = self.module.fire_heartbeat(
            api_base_url = "http://h", api_key = "k", manager = "tiberius",
            store = store, tick_num = 3,
        )
        self.assertEqual( len( self.posts ), 0, "store failure short-circuits before the push" )
        self.assertIn( "store_error", result )

    def test_fire_heartbeat_non_2xx_surfaces_register_body( self ):
        self.module.requests.post = lambda url, json=None, headers=None, timeout=None: \
            _FakeResp( status_code=404, text="not found" )
        result = self.module.fire_heartbeat(
            api_base_url = "http://h", api_key = "k", manager = "tiberius",
            store = MagicMock(), tick_num = 4,
        )
        self.assertEqual( result[ "register_status" ], 404 )
        self.assertEqual( result[ "register_body" ], "not found" )
        self.assertNotIn( "dispatched", result )

    def test_fire_heartbeat_2xx_unparseable_body_is_swallowed( self ):
        def _bad_json():
            raise ValueError( "no body" )
        resp = _FakeResp( status_code=201 )
        resp.json = _bad_json
        self.module.requests.post = lambda url, json=None, headers=None, timeout=None: resp
        result = self.module.fire_heartbeat(
            api_base_url = "http://h", api_key = "k", manager = "tiberius",
            store = MagicMock(), tick_num = 5,
        )
        self.assertEqual( result[ "register_status" ], 201 )
        self.assertNotIn( "dispatched", result )   # parse failure swallowed, no crash

    def test_fire_heartbeat_push_exception_returns_register_error( self ):
        def _boom( url, json=None, headers=None, timeout=None ):
            raise RuntimeError( "network down" )
        self.module.requests.post = _boom
        result = self.module.fire_heartbeat(
            api_base_url = "http://h", api_key = "k", manager = "tiberius",
            store = MagicMock(), tick_num = 6,
        )
        self.assertIn( "register_error", result )

    def test_fire_budget_warning_store_error_skips_push( self ):
        store = MagicMock()
        store.post.side_effect = RuntimeError( "disk down" )
        result = self.module.fire_budget_warning(
            api_base_url = "http://h", api_key = "k", manager = "tiberius",
            store = store, section = "sec-A", count = 30, threshold = 25,
        )
        self.assertEqual( len( self.posts ), 0 )
        self.assertIn( "store_error", result )

    def test_fire_budget_warning_push_exception_returns_register_error( self ):
        def _boom( url, json=None, headers=None, timeout=None ):
            raise RuntimeError( "network down" )
        self.module.requests.post = _boom
        result = self.module.fire_budget_warning(
            api_base_url = "http://h", api_key = "k", manager = "tiberius",
            store = MagicMock(), section = "sec-A", count = 30, threshold = 25,
        )
        self.assertIn( "register_error", result )

    def test_fire_budget_warning_posts_to_dm_send( self ):
        result = self.module.fire_budget_warning(
            api_base_url = "http://localhost:7999",
            api_key      = "stub-key",
            manager      = "mr radio",
            store        = MagicMock(),
            section      = "cascaded-prototype-section-A",
            count        = 30,
            threshold    = 25,
        )
        self.assertEqual( len( self.posts ), 1 )
        call = self.posts[ 0 ]
        self.assertEqual( call[ "url" ], "http://localhost:7999/api/dm/send" )
        payload = call[ "json" ]
        self.assertEqual( set( payload.keys() ),
                          { "sender_session_id", "recipient_persona", "body", "thread_id" } )
        self.assertEqual( payload[ "recipient_persona" ], "mr radio" )
        self.assertIn( "30/25", payload[ "body" ] )
        self.assertEqual( result[ "register_status" ], 201 )


if __name__ == "__main__":
    unittest.main()
