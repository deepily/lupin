"""
Unit tests for cosa.rest.routers.peer.

Focus: pure helpers (host whitelist, request validation). Endpoint-level tests
with mocked aiohttp belong in src/tests/integration/.
"""

import pytest

from cosa.rest.routers import peer


class TestIsHostAllowed:
    """_is_host_allowed is a pure predicate, safe to unit-test in isolation."""

    def test_host_in_whitelist_returns_true( self ):
        assert peer._is_host_allowed( "localhost:8000", [ "localhost:8000", "localhost:7999" ] ) is True

    def test_host_not_in_whitelist_returns_false( self ):
        assert peer._is_host_allowed( "evil.example.com", [ "localhost:8000" ] ) is False

    def test_empty_whitelist_rejects_all( self ):
        assert peer._is_host_allowed( "localhost:8000", [] ) is False

    def test_case_sensitive_exact_match( self ):
        # Current impl is exact match; this pins that contract.
        assert peer._is_host_allowed( "LOCALHOST:8000", [ "localhost:8000" ] ) is False

    def test_port_must_match( self ):
        assert peer._is_host_allowed( "localhost:9999", [ "localhost:8000" ] ) is False

    def test_substring_does_not_match( self ):
        # "localhost" in "localhost:8000" must NOT match.
        assert peer._is_host_allowed( "localhost", [ "localhost:8000" ] ) is False


class TestValidateHostAndQueue:
    """_validate_host_and_queue raises HTTPException on invalid inputs."""

    def _patch_allowed( self, monkeypatch, hosts ):
        monkeypatch.setattr( peer, "_get_allowed_hosts", lambda: hosts )

    def test_valid_inputs_do_not_raise( self, monkeypatch ):
        self._patch_allowed( monkeypatch, [ "localhost:8000" ] )
        peer._validate_host_and_queue( "localhost:8000", "run" )  # no exception

    def test_invalid_queue_name_raises_400( self, monkeypatch ):
        self._patch_allowed( monkeypatch, [ "localhost:8000" ] )
        from fastapi import HTTPException
        with pytest.raises( HTTPException ) as exc:
            peer._validate_host_and_queue( "localhost:8000", "badqueue" )
        assert exc.value.status_code == 400
        assert "queue_name" in exc.value.detail

    def test_unlisted_host_raises_400( self, monkeypatch ):
        self._patch_allowed( monkeypatch, [ "localhost:8000" ] )
        from fastapi import HTTPException
        with pytest.raises( HTTPException ) as exc:
            peer._validate_host_and_queue( "evil.example.com", "run" )
        assert exc.value.status_code == 400
        assert "whitelist" in exc.value.detail

    def test_all_four_queue_names_accepted( self, monkeypatch ):
        self._patch_allowed( monkeypatch, [ "localhost:8000" ] )
        for q in ( "todo", "run", "done", "dead" ):
            peer._validate_host_and_queue( "localhost:8000", q )  # no exception


class TestWatcherStateIsolation:
    """Watcher state dicts must be per-user, not shared."""

    def test_watcher_state_is_module_level_dict( self ):
        assert isinstance( peer._watcher_state, dict )
        assert isinstance( peer._active_watchers, dict )

    def test_separate_users_get_separate_entries( self ):
        peer._watcher_state.clear()
        peer._watcher_state[ "user_a" ] = { "active": True, "host": "a" }
        peer._watcher_state[ "user_b" ] = { "active": True, "host": "b" }
        assert peer._watcher_state[ "user_a" ][ "host" ] == "a"
        assert peer._watcher_state[ "user_b" ][ "host" ] == "b"
        peer._watcher_state.clear()
