"""
Unit tests for `lupin_mcp.outbound_api_key`.

Regression origin: on `lupin-host-test` (2026-07-25) the outbound key file was
present but mode 600 owned by uid 1001 while the MCP server ran as a different
uid. The loader's bare `except Exception: return None` erased the
`PermissionError`, and `dm_send` / `dm_list` reported `missing_auth_header`
with a `detail` that named neither the path, the mode, nor the errno.

The contract under test is therefore two-sided:
    - the RETURN value stays exactly as before (key string, or None) so the 13
      call sites are unchanged, and
    - the REASON survives in a parallel channel that callers render into
      `detail`.

Every test drives a real key file on disk through a real `LUPIN_ROOT` — the
defect lived in the gap between `os.path.exists()` and `open()`, so mocking the
filesystem would mock away the thing that broke.
"""

import os

import pytest

import lupin_mcp.outbound_api_key as oak


KEY_REL_PATH = "src/conf/keys/notification-api-claude-code-dev"


@pytest.fixture
def key_root( tmp_path, monkeypatch ):
    """
    A throwaway LUPIN_ROOT with the keys directory made but no key file yet.

    Ensures:
        - `LUPIN_ROOT` points at the temp tree for the duration of the test
        - the recorded failure state is reset, so no test inherits another's
        - yields (root_path, key_path)
    """
    ( tmp_path / "src" / "conf" / "keys" ).mkdir( parents=True )
    monkeypatch.setenv( "LUPIN_ROOT", str( tmp_path ) )
    monkeypatch.setattr( oak, "_last_failure", None )
    return tmp_path, tmp_path / KEY_REL_PATH


def test_loads_key_and_strips_whitespace( key_root ):
    """A readable, non-empty key file yields the stripped key and records no failure."""
    _, key_path = key_root
    key_path.write_text( "ck_live_abc123\n" )

    assert oak.load_outbound_api_key() == "ck_live_abc123"
    assert oak._last_failure is None


def test_absent_key_file_names_the_path( key_root ):
    """An absent key file returns None and the detail names the exact path attempted."""
    _, key_path = key_root

    assert oak.load_outbound_api_key() is None

    detail = oak.outbound_key_failure_detail( "/api/dm/send" )
    assert "/api/dm/send" in detail
    assert "not found" in detail
    assert str( key_path ) in detail


@pytest.mark.skipif( os.getuid() == 0, reason="root bypasses file permission bits" )
def test_unreadable_key_file_reports_mode_and_owner( key_root ):
    """
    The lupin-host-test shape: the file EXISTS but this process cannot read it.

    This is the case an existence check passes and a readability check catches.
    The detail must carry the two facts that make the remedy a one-liner — the
    mode and the owning uid — not a blank "unavailable".
    """
    _, key_path = key_root
    key_path.write_text( "ck_live_abc123\n" )
    key_path.chmod( 0o000 )

    assert oak.load_outbound_api_key() is None

    detail = oak.outbound_key_failure_detail( "/api/dm/list" )
    assert "/api/dm/list" in detail
    assert "not readable" in detail
    assert "mode 0" in detail
    assert f"owner uid {os.getuid()}" in detail


def test_empty_key_file_is_distinguished_from_absent( key_root ):
    """A whitespace-only key file reports 'empty', not 'not found'."""
    _, key_path = key_root
    key_path.write_text( "   \n" )

    assert oak.load_outbound_api_key() is None

    detail = oak.outbound_key_failure_detail( "/api/dm/get" )
    assert "empty" in detail
    assert "not found" not in detail


def test_successful_load_clears_a_prior_failure( key_root ):
    """
    A stale diagnosis must never be reported against a later working load.

    Without the clear-on-success, a key that was fixed mid-process would keep
    reporting the permission error that no longer applies.
    """
    _, key_path = key_root

    assert oak.load_outbound_api_key() is None            # absent -> failure recorded
    assert oak._last_failure is not None

    key_path.write_text( "ck_live_abc123\n" )
    assert oak.load_outbound_api_key() == "ck_live_abc123"
    assert oak._last_failure is None


def test_detail_without_recorded_failure_does_not_invent_one( key_root ):
    """
    A caller that passes a None key it never loaded here gets an honest answer.

    The fallback diagnosis must NOT claim the file is empty or missing when it
    is neither — a false lead is the failure mode this module exists to stop.
    """
    _, key_path = key_root
    key_path.write_text( "ck_live_abc123\n" )

    detail = oak.outbound_key_failure_detail( "/api/tasks/create" )
    assert "present and readable" in detail
    assert "did not originate from this loader" in detail


def test_loader_exception_is_reported_not_swallowed( key_root, monkeypatch ):
    """
    An exception raised by the underlying helper surfaces its type and message.

    This is the bare-`except` regression stated directly: the loader still
    returns None (callers unchanged), but the reason is no longer erased.
    """
    _, key_path = key_root
    key_path.write_text( "ck_live_abc123\n" )

    import cosa.utils.util as du
    def _boom( *args, **kwargs ):
        raise RuntimeError( "config subsystem exploded" )
    monkeypatch.setattr( du, "get_api_key", _boom )

    assert oak.load_outbound_api_key() is None

    detail = oak.outbound_key_failure_detail( "/api/dm/respond" )
    assert "RuntimeError" in detail
    assert "config subsystem exploded" in detail


def test_unresolvable_project_root_does_not_raise( monkeypatch ):
    """
    A broken project root degrades to a sentinel path, never an exception.

    The diagnosis path runs while something is already wrong; it must not be
    the thing that throws.
    """
    import cosa.utils.util as du
    def _boom():
        raise RuntimeError( "no LUPIN_ROOT" )
    monkeypatch.setattr( du, "get_project_root", _boom )

    path = oak._key_path()
    assert "unresolvable project root" in path
    assert "RuntimeError" in path


def test_unstatable_unreadable_path_is_handled( key_root, monkeypatch ):
    """A file that reports unreadable but then fails to stat still yields a detail."""
    _, key_path = key_root
    key_path.write_text( "ck_live_abc123\n" )

    # `os.path.exists` is itself implemented on `os.stat`, so the exists probe
    # must be pinned True independently — otherwise a raising stat short-circuits
    # the branch under test into the not-found branch.
    monkeypatch.setattr( oak.os.path, "exists", lambda *a, **k: True )
    monkeypatch.setattr( oak.os, "access", lambda *a, **k: False )
    def _stat_boom( *args, **kwargs ):
        raise OSError( "stat failed" )
    monkeypatch.setattr( oak.os, "stat", _stat_boom )

    detail = oak._diagnose( str( key_path ), None )
    assert "cannot be stat'ed" in detail
    assert "stat failed" in detail


def test_diagnosis_survives_a_failure_inside_itself( monkeypatch ):
    """The last-resort guard returns a string rather than propagating."""
    def _exists_boom( *args, **kwargs ):
        raise RuntimeError( "exists exploded" )
    monkeypatch.setattr( oak.os.path, "exists", _exists_boom )

    detail = oak._diagnose( "/some/path", None )
    assert "diagnosis itself failed" in detail
    assert "RuntimeError" in detail
