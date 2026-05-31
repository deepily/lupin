"""
Unit tests for cosa.agents.utils.sync_notify.notify.

Fire-and-forget REST notifier for sync proxy agents. All boundaries (requests.post,
config loaders, resolve_target_user) are mocked — no network.

Covers: target_user provided vs auto-resolved, API-key load success vs failure,
POST success (200→True) / non-200 (→False) / exception (→False), debug arms.

Created 2026-05-31 (CoSA coverage campaign, utils package — Tiffany 💍). New file.
"""

import unittest
from unittest.mock import Mock, patch

from cosa.agents.utils import sync_notify


class TestSyncNotify( unittest.TestCase ):
    """Comprehensive unit tests for sync_notify.notify()."""

    def _post_ok( self, status=200 ):
        resp = Mock()
        resp.status_code = status
        return resp

    def test_notify_success_with_explicit_target( self ):
        """Test a 200 response with an explicit target_user returns True + sets API key."""
        with patch( "cosa.agents.utils.sync_notify.get_api_config", return_value={ "api_key_file": "/k" } ), \
             patch( "cosa.agents.utils.sync_notify.load_api_key", return_value="KEY" ), \
             patch( "cosa.agents.utils.sync_notify.requests.post", return_value=self._post_ok() ) as mock_post:
            ok = sync_notify.notify( "hi", sender_id="x@y.deepily.ai", target_user="u@x.com", debug=True )

        self.assertTrue( ok )
        headers = mock_post.call_args.kwargs[ "headers" ]
        self.assertEqual( headers[ "X-API-Key" ], "KEY" )

    def test_notify_auto_resolves_target_user( self ):
        """Test a None target_user is resolved via resolve_target_user."""
        with patch( "lupin_cli.notifications.notification_models.resolve_target_user", return_value="auto@x.com" ) as mock_resolve, \
             patch( "cosa.agents.utils.sync_notify.get_api_config", return_value={ "api_key_file": "/k" } ), \
             patch( "cosa.agents.utils.sync_notify.load_api_key", return_value="KEY" ), \
             patch( "cosa.agents.utils.sync_notify.requests.post", return_value=self._post_ok() ) as mock_post:
            sync_notify.notify( "hi", sender_id="x@y.deepily.ai" )

        mock_resolve.assert_called_once()
        self.assertEqual( mock_post.call_args.kwargs[ "params" ][ "target_user" ], "auto@x.com" )

    def test_notify_api_key_load_failure_still_posts( self ):
        """Test an API-key load failure is swallowed; the POST still proceeds (debug on)."""
        with patch( "cosa.agents.utils.sync_notify.get_api_config", side_effect=Exception( "no config" ) ), \
             patch( "cosa.agents.utils.sync_notify.requests.post", return_value=self._post_ok() ) as mock_post:
            ok = sync_notify.notify( "hi", sender_id="x@y.deepily.ai", target_user="u@x.com", debug=True )

        self.assertTrue( ok )
        self.assertNotIn( "X-API-Key", mock_post.call_args.kwargs[ "headers" ] )

    def test_notify_non_200_returns_false( self ):
        """Test a non-200 response returns False."""
        with patch( "cosa.agents.utils.sync_notify.get_api_config", return_value={ "api_key_file": "/k" } ), \
             patch( "cosa.agents.utils.sync_notify.load_api_key", return_value="KEY" ), \
             patch( "cosa.agents.utils.sync_notify.requests.post", return_value=self._post_ok( status=500 ) ):
            self.assertFalse( sync_notify.notify( "hi", sender_id="x@y.deepily.ai", target_user="u@x.com" ) )

    def test_notify_post_exception_returns_false( self ):
        """Test a POST exception is swallowed and returns False (debug on)."""
        with patch( "cosa.agents.utils.sync_notify.get_api_config", return_value={ "api_key_file": "/k" } ), \
             patch( "cosa.agents.utils.sync_notify.load_api_key", return_value="KEY" ), \
             patch( "cosa.agents.utils.sync_notify.requests.post", side_effect=Exception( "conn refused" ) ):
            self.assertFalse( sync_notify.notify( "hi", sender_id="x@y.deepily.ai", target_user="u@x.com", debug=True ) )


if __name__ == "__main__":
    unittest.main()
