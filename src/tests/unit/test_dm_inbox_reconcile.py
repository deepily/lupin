#!/usr/bin/env python3
"""
Unit tests — store-backed DM inbox reconcile (bug 59f355e0, Option A).

Venue: :7999-eligible / local — no server, no network (fetch_fn injected;
HWM file under tmp_path). Covers the pure reconcile core + the IO shell
(read_hwm / write_hwm / surface_dm_inbox / _fetch_inbox / _load_settings /
_log_capped) to 100% lines/branches/functions.

Contract under test: the reconcile surfaces this-session DMs (job_id-filtered)
that are NOT yet surfaced (dedup by message_id), advances a durable per-session
high-water mark, and NEVER raises on the turn-start hot path (fail-open).
"""
import json
import os
import sys

import pytest

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from lupin_cli.claude_code.hooks.lib import dm_inbox_reconcile as dr


SESSION = "46ffe611-d6d2-480b-bc5e-914f2ce36882"
HASH8   = "46ffe611"


def _row( mid, job_id=HASH8, created="2026-07-02T11:00:00+00:00",
          body="hello", persona="mr radio", icon="🦉", thread="t1" ):
    return {
        "message_id"     : mid,
        "thread_id"      : thread,
        "reply_to"       : None,
        "sender_id"      : "s",
        "sender_persona" : persona,
        "sender_icon"    : icon,
        "body"           : body,
        "direction"      : "ai_to_ai",
        "state"          : "sent",
        "job_id"         : job_id,
        "created_at"     : created,
    }


# ── helpers ───────────────────────────────────────────────────────────────────

class TestMaxIso:

    def test_both_none( self ):
        assert dr._max_iso( None, None ) is None

    def test_a_none( self ):
        assert dr._max_iso( None, "2026-07-02T11:00:00+00:00" ) == "2026-07-02T11:00:00+00:00"

    def test_b_none( self ):
        assert dr._max_iso( "2026-07-02T11:00:00+00:00", None ) == "2026-07-02T11:00:00+00:00"

    def test_returns_later( self ):
        a = "2026-07-02T11:00:00+00:00"
        b = "2026-07-02T12:00:00+00:00"
        assert dr._max_iso( a, b ) == b
        assert dr._max_iso( b, a ) == b


class TestDedupTail:

    def test_preserves_order_first_occurrence( self ):
        assert dr._dedup_tail( [ "a", "b", "a", "c" ], 10 ) == [ "a", "b", "c" ]

    def test_caps_to_tail( self ):
        assert dr._dedup_tail( [ "a", "b", "c", "d" ], 2 ) == [ "c", "d" ]

    def test_no_cap_when_zero( self ):
        assert dr._dedup_tail( [ "a", "b", "c" ], 0 ) == [ "a", "b", "c" ]


# ── pure core: reconcile_context ────────────────────────────────────────────────

class TestReconcileContext:

    def _empty( self ):
        return { "cursor_ts": None, "surfaced_ids": [] }

    def test_empty_rows( self ):
        ctx, state = dr.reconcile_context( HASH8, [], self._empty() )
        assert ctx == ""
        assert state == { "cursor_ts": None, "surfaced_ids": [] }

    def test_row_other_session_ignored( self ):
        rows = [ _row( "m1", job_id="ffffffff" ) ]
        ctx, state = dr.reconcile_context( HASH8, rows, self._empty() )
        assert ctx == ""
        assert state[ "cursor_ts" ] is None            # cursor advances only by MY rows
        assert state[ "surfaced_ids" ] == []

    def test_fresh_dm_surfaced_and_recorded( self ):
        rows = [ _row( "m1", created="2026-07-02T11:05:00+00:00" ) ]
        ctx, state = dr.reconcile_context( HASH8, rows, self._empty() )
        assert "PEER DM from mr radio 🦉" in ctx
        assert "message_id m1" in ctx
        assert state[ "cursor_ts" ] == "2026-07-02T11:05:00+00:00"
        assert state[ "surfaced_ids" ] == [ "m1" ]

    def test_already_surfaced_deduped( self ):
        rows  = [ _row( "m1" ) ]
        state = { "cursor_ts": "2026-07-02T10:00:00+00:00", "surfaced_ids": [ "m1" ] }
        ctx, new_state = dr.reconcile_context( HASH8, rows, state )
        assert ctx == ""                                # dedup by message_id
        assert new_state[ "surfaced_ids" ] == [ "m1" ]
        assert new_state[ "cursor_ts" ] == "2026-07-02T11:00:00+00:00"   # still advances (seen)

    def test_extra_surfaced_excluded_and_recorded( self ):
        rows = [ _row( "m1" ) ]
        ctx, state = dr.reconcile_context( HASH8, rows, self._empty(), extra_surfaced_ids=[ "m1" ] )
        assert ctx == ""                                # buffer-drained this turn → not re-surfaced
        assert state[ "surfaced_ids" ] == [ "m1" ]      # but recorded so future turns skip it

    def test_multiple_fresh_sorted_ascending( self ):
        rows = [
            _row( "m2", created="2026-07-02T11:30:00+00:00", body="second" ),
            _row( "m1", created="2026-07-02T11:10:00+00:00", body="first" ),
        ]
        ctx, state = dr.reconcile_context( HASH8, rows, self._empty() )
        assert ctx.index( "first" ) < ctx.index( "second" )
        assert state[ "surfaced_ids" ] == [ "m1", "m2" ]
        assert state[ "cursor_ts" ] == "2026-07-02T11:30:00+00:00"

    def test_blank_body_recorded_but_not_surfaced( self ):
        rows = [ _row( "m1", body="   " ) ]
        ctx, state = dr.reconcile_context( HASH8, rows, self._empty() )
        assert ctx == ""
        assert state[ "surfaced_ids" ] == [ "m1" ]      # recorded → no infinite re-fetch loop

    def test_missing_message_id_not_recorded( self ):
        rows = [ _row( None, body="x" ) ]
        ctx, state = dr.reconcile_context( HASH8, rows, self._empty() )
        assert "PEER DM" in ctx                          # still surfaced
        assert state[ "surfaced_ids" ] == []             # no id to record

    def test_surfaced_ids_capped( self, monkeypatch ):
        monkeypatch.setattr( dr, "SURFACED_IDS_CAP", 2 )
        rows  = [ _row( "m3", created="2026-07-02T11:30:00+00:00" ) ]
        state = { "cursor_ts": "2026-07-02T10:00:00+00:00", "surfaced_ids": [ "m1", "m2" ] }
        _, new_state = dr.reconcile_context( HASH8, rows, state )
        assert new_state[ "surfaced_ids" ] == [ "m2", "m3" ]

    def test_cursor_keeps_max_when_existing_newer( self ):
        rows  = [ _row( "m1", created="2026-07-02T09:00:00+00:00" ) ]
        state = { "cursor_ts": "2026-07-02T20:00:00+00:00", "surfaced_ids": [] }
        _, new_state = dr.reconcile_context( HASH8, rows, state )
        assert new_state[ "cursor_ts" ] == "2026-07-02T20:00:00+00:00"


# ── HWM file IO ─────────────────────────────────────────────────────────────────

class TestHwmIo:

    def test_read_missing_returns_unseeded_default( self, tmp_path ):
        state = dr.read_hwm( SESSION, base_dir=tmp_path )
        assert state == { "cursor_ts": None, "surfaced_ids": [], "seeded": False }

    def test_write_then_read_roundtrip( self, tmp_path ):
        st = { "cursor_ts": "2026-07-02T11:00:00+00:00", "surfaced_ids": [ "m1", "m2" ], "seeded": True }
        assert dr.write_hwm( SESSION, st, base_dir=tmp_path ) is True
        assert dr.read_hwm( SESSION, base_dir=tmp_path ) == st

    def test_write_defaults_seeded_true( self, tmp_path ):
        # A state dict without an explicit seeded key persists seeded=True.
        dr.write_hwm( SESSION, { "cursor_ts": None, "surfaced_ids": [] }, base_dir=tmp_path )
        assert dr.read_hwm( SESSION, base_dir=tmp_path )[ "seeded" ] is True

    def test_read_malformed_json_returns_unseeded_default( self, tmp_path ):
        path = dr._hwm_path( SESSION, base_dir=tmp_path )
        path.parent.mkdir( parents=True, exist_ok=True )
        path.write_text( "{not json" )
        assert dr.read_hwm( SESSION, base_dir=tmp_path ) == { "cursor_ts": None, "surfaced_ids": [], "seeded": False }

    def test_read_non_dict_returns_unseeded_default( self, tmp_path ):
        path = dr._hwm_path( SESSION, base_dir=tmp_path )
        path.parent.mkdir( parents=True, exist_ok=True )
        path.write_text( "[1, 2, 3]" )
        assert dr.read_hwm( SESSION, base_dir=tmp_path ) == { "cursor_ts": None, "surfaced_ids": [], "seeded": False }

    def test_read_legacy_file_without_seeded_key_defaults_seeded( self, tmp_path ):
        # A pre-seed-era file (bad field types, no seeded key) → treated as SEEDED
        # so its existing dedup ledger stands and it does not re-seed/replay.
        path = dr._hwm_path( SESSION, base_dir=tmp_path )
        path.parent.mkdir( parents=True, exist_ok=True )
        path.write_text( json.dumps( { "cursor_ts": 123, "surfaced_ids": "nope" } ) )
        assert dr.read_hwm( SESSION, base_dir=tmp_path ) == { "cursor_ts": None, "surfaced_ids": [], "seeded": True }

    def test_write_failure_returns_false( self, monkeypatch, tmp_path ):
        def boom( *a, **k ):
            raise OSError( "disk full" )
        monkeypatch.setattr( "builtins.open", boom )
        assert dr.write_hwm( SESSION, { "cursor_ts": None, "surfaced_ids": [] }, base_dir=tmp_path ) is False


# ── IO shell: surface_dm_inbox ──────────────────────────────────────────────────

class TestSurfaceDmInbox:

    def test_empty_session_id( self, tmp_path ):
        assert dr.surface_dm_inbox( "", base_dir=tmp_path ) == ""

    def test_fetch_not_ok_does_not_advance( self, tmp_path ):
        def fetch( since=None, limit=None ):
            return False, [], False
        assert dr.surface_dm_inbox( SESSION, fetch_fn=fetch, base_dir=tmp_path ) == ""
        # hwm never written on a failed fetch
        assert not dr._hwm_path( SESSION, base_dir=tmp_path ).exists()

    def _seed( self, tmp_path ):
        """Mark this session as already-seeded so surfacing (not seeding) is tested."""
        dr.write_hwm( SESSION, { "cursor_ts": None, "surfaced_ids": [], "seeded": True }, base_dir=tmp_path )

    def test_first_run_seeds_without_replay( self, tmp_path ):
        # No HWM yet → SEED: record the inbox + advance cursor, but surface NOTHING
        # (constraint 4 — activation must not replay a live session's backlog).
        rows = [ _row( "m1", created="2026-07-02T11:05:00+00:00" ) ]
        def fetch( since=None, limit=None ):
            return True, rows, False
        ctx = dr.surface_dm_inbox( SESSION, fetch_fn=fetch, base_dir=tmp_path )
        assert ctx == ""                                 # NO replay on first run
        persisted = dr.read_hwm( SESSION, base_dir=tmp_path )
        assert persisted[ "seeded" ] is True
        assert persisted[ "surfaced_ids" ] == [ "m1" ]   # recorded → future turns skip it
        assert persisted[ "cursor_ts" ] == "2026-07-02T11:05:00+00:00"

    def test_seeded_session_surfaces_new_dm( self, tmp_path ):
        self._seed( tmp_path )
        rows = [ _row( "m1", created="2026-07-02T11:05:00+00:00" ) ]
        def fetch( since=None, limit=None ):
            return True, rows, False
        ctx = dr.surface_dm_inbox( SESSION, fetch_fn=fetch, base_dir=tmp_path )
        assert "message_id m1" in ctx                    # seeded → new DM IS surfaced
        persisted = dr.read_hwm( SESSION, base_dir=tmp_path )
        assert persisted[ "surfaced_ids" ] == [ "m1" ]
        assert persisted[ "cursor_ts" ] == "2026-07-02T11:05:00+00:00"

    def test_second_call_deduped_via_persisted_hwm( self, tmp_path ):
        self._seed( tmp_path )
        rows = [ _row( "m1" ) ]
        def fetch( since=None, limit=None ):
            return True, rows, False
        dr.surface_dm_inbox( SESSION, fetch_fn=fetch, base_dir=tmp_path )
        ctx2 = dr.surface_dm_inbox( SESSION, fetch_fn=fetch, base_dir=tmp_path )
        assert ctx2 == ""                                # durable dedup across turns

    def test_extra_surfaced_ids_threaded( self, tmp_path ):
        self._seed( tmp_path )
        rows = [ _row( "m1" ) ]
        def fetch( since=None, limit=None ):
            return True, rows, False
        ctx = dr.surface_dm_inbox( SESSION, extra_surfaced_ids=[ "m1" ], fetch_fn=fetch, base_dir=tmp_path )
        assert ctx == ""

    def test_since_cursor_passed_to_fetch( self, tmp_path ):
        dr.write_hwm( SESSION, { "cursor_ts": "2026-07-02T10:00:00+00:00", "surfaced_ids": [] }, base_dir=tmp_path )
        seen = {}
        def fetch( since=None, limit=None ):
            seen[ "since" ] = since
            seen[ "limit" ] = limit
            return True, [], False
        dr.surface_dm_inbox( SESSION, fetch_fn=fetch, base_dir=tmp_path )
        assert seen[ "since" ] == "2026-07-02T10:00:00+00:00"
        assert seen[ "limit" ] == dr.DEFAULT_LIMIT

    def test_page_full_logs( self, tmp_path, monkeypatch ):
        logged = {}
        monkeypatch.setattr( dr, "_log_capped", lambda sid, n: logged.update( sid=sid, n=n ) )
        rows = [ _row( f"m{i}", created="2026-07-02T11:05:00+00:00" ) for i in range( 3 ) ]
        def fetch( since=None, limit=None ):
            return True, rows, True                       # page_full
        dr.surface_dm_inbox( SESSION, fetch_fn=fetch, base_dir=tmp_path )
        assert logged[ "n" ] == 3

    def test_default_fetch_fn_used( self, tmp_path, monkeypatch ):
        monkeypatch.setattr( dr, "_fetch_inbox", lambda since=None, limit=None: ( True, [], False ) )
        assert dr.surface_dm_inbox( SESSION, base_dir=tmp_path ) == ""

    def test_never_raises_on_internal_error( self, tmp_path, monkeypatch ):
        def boom( *a, **k ):
            raise RuntimeError( "unexpected" )
        monkeypatch.setattr( dr, "read_hwm", boom )
        assert dr.surface_dm_inbox( SESSION, base_dir=tmp_path ) == ""


# ── _fetch_inbox + _load_settings + _log_capped ─────────────────────────────────

class TestFetchInbox:

    def test_ok_returns_messages( self, monkeypatch ):
        monkeypatch.setattr( dr, "_load_settings", lambda: { "api_base_url": "http://t:7999", "timeout_seconds": 1.0 } )
        import lupin_cli.claude_code.hooks.lib.task_store_client as tc
        monkeypatch.setattr( tc, "read_api_key", lambda: "ck_live_x" )
        captured = {}
        def fake_request( method, url, api_key, timeout, body=None ):
            captured[ "url" ] = url
            captured[ "method" ] = method
            return True, 200, { "messages": [ _row( "m1" ) ], "count": 1 }
        monkeypatch.setattr( tc, "_request", fake_request )
        ok, rows, full = dr._fetch_inbox( since="2026-07-02T10:00:00+00:00", limit=200 )
        assert ok is True and len( rows ) == 1 and full is False
        assert captured[ "method" ] == "GET"
        assert "/api/dm/list?" in captured[ "url" ] and "since=" in captured[ "url" ]

    def test_no_since_omits_param( self, monkeypatch ):
        monkeypatch.setattr( dr, "_load_settings", lambda: { "api_base_url": "http://t:7999", "timeout_seconds": 1.0 } )
        import lupin_cli.claude_code.hooks.lib.task_store_client as tc
        monkeypatch.setattr( tc, "read_api_key", lambda: "k" )
        captured = {}
        def fake_request( method, url, api_key, timeout, body=None ):
            captured[ "url" ] = url
            return True, 200, { "messages": [] }
        monkeypatch.setattr( tc, "_request", fake_request )
        ok, rows, full = dr._fetch_inbox( since=None, limit=5 )
        assert ok is True and rows == []
        assert "since=" not in captured[ "url" ]

    def test_page_full_when_limit_reached( self, monkeypatch ):
        monkeypatch.setattr( dr, "_load_settings", lambda: { "api_base_url": "http://t:7999", "timeout_seconds": 1.0 } )
        import lupin_cli.claude_code.hooks.lib.task_store_client as tc
        monkeypatch.setattr( tc, "read_api_key", lambda: "k" )
        monkeypatch.setattr( tc, "_request", lambda *a, **k: ( True, 200, { "messages": [ _row( "m1" ), _row( "m2" ) ] } ) )
        ok, rows, full = dr._fetch_inbox( since=None, limit=2 )
        assert ok is True and full is True

    def test_request_not_ok( self, monkeypatch ):
        monkeypatch.setattr( dr, "_load_settings", lambda: { "api_base_url": "http://t:7999", "timeout_seconds": 1.0 } )
        import lupin_cli.claude_code.hooks.lib.task_store_client as tc
        monkeypatch.setattr( tc, "read_api_key", lambda: "k" )
        monkeypatch.setattr( tc, "_request", lambda *a, **k: ( False, None, { "error": "boom" } ) )
        assert dr._fetch_inbox() == ( False, [], False )

    def test_body_not_dict( self, monkeypatch ):
        monkeypatch.setattr( dr, "_load_settings", lambda: { "api_base_url": "http://t:7999", "timeout_seconds": 1.0 } )
        import lupin_cli.claude_code.hooks.lib.task_store_client as tc
        monkeypatch.setattr( tc, "read_api_key", lambda: "k" )
        monkeypatch.setattr( tc, "_request", lambda *a, **k: ( True, 200, "not a dict" ) )
        assert dr._fetch_inbox() == ( False, [], False )

    def test_messages_not_list( self, monkeypatch ):
        monkeypatch.setattr( dr, "_load_settings", lambda: { "api_base_url": "http://t:7999", "timeout_seconds": 1.0 } )
        import lupin_cli.claude_code.hooks.lib.task_store_client as tc
        monkeypatch.setattr( tc, "read_api_key", lambda: "k" )
        monkeypatch.setattr( tc, "_request", lambda *a, **k: ( True, 200, { "messages": "nope" } ) )
        assert dr._fetch_inbox() == ( False, [], False )


class TestLoadSettings:

    def test_returns_loader_result( self, monkeypatch ):
        monkeypatch.setattr(
            "lupin_cli.claude_code.hooks.lib.task_store_settings.load_task_store_settings",
            lambda: { "api_base_url": "http://loaded:7999", "timeout_seconds": 2.0, "enabled": True, "spool_ttl_seconds": 1.0 },
        )
        s = dr._load_settings()
        assert s[ "api_base_url" ] == "http://loaded:7999"

    def test_malformed_settings_falls_back( self, monkeypatch ):
        def boom():
            raise ValueError( "bad config" )
        monkeypatch.setattr(
            "lupin_cli.claude_code.hooks.lib.task_store_settings.load_task_store_settings", boom
        )
        s = dr._load_settings()
        assert s[ "api_base_url" ] == "http://localhost:7999"
        assert s[ "timeout_seconds" ] == dr.DEFAULT_TIMEOUT_SECONDS


class TestLogCapped:

    def test_writes_line( self, tmp_path ):
        dr._log_capped( SESSION, 200, log_dir=tmp_path )
        content = ( tmp_path / "dm-inbox-reconcile.log" ).read_text()
        assert "CAPPED at 200" in content and HASH8 in content

    def test_never_raises_on_bad_dir( self, monkeypatch, tmp_path ):
        def boom( *a, **k ):
            raise OSError( "nope" )
        monkeypatch.setattr( "builtins.open", boom )
        dr._log_capped( SESSION, 200, log_dir=tmp_path )   # must not raise


class TestHwmPath:

    def test_uses_8char_suffix_and_base_dir( self, tmp_path ):
        p = dr._hwm_path( SESSION, base_dir=tmp_path )
        assert p.name == ".dm-inbox-hwm-46ffe611.json"
        assert p.parent == tmp_path

    def test_none_session_id_suffix( self, tmp_path ):
        p = dr._hwm_path( None, base_dir=tmp_path )
        assert p.name == ".dm-inbox-hwm-.json"


# ── 2a6759de — the sid8 key is a LOSSY truncation ─────────────────────────────

class TestPrefixCollisionBetweenTwoSessions:
    """
    ARMED GATE for row `2a6759de`. These tests describe a defect that is REAL and
    currently UNEXERCISED (0 duplicate suffixes measured across 435 live HWM files
    on 2026-07-26). They are xfail(strict) so they REPORT AS FAILURES the moment
    the defect is fixed — the same live-gate pattern the heartbeat-hold family
    used for its cargo and two-anchor guards.

    THE DEFECT: `_hwm_path` keys the durable HWM by `session_id[ :8 ]`, and
    `dm.py:329` sets a DM's `job_id` to `target_session_id[ :8 ]` by the same rule.
    So two sessions sharing a first-8 are indistinguishable BOTH in the ledger
    they write and in the DMs they claim.

    ⚠️ WHY xfail AND NOT A SKIP: a skip records an opinion; an xfail(strict)
    records a PREDICTION the suite re-tests on every run. If someone widens the
    key or adds a full-id check, these turn red and demand to be looked at,
    which is the only way this row's finding survives its author.
    """

    ALPHA = "46ffe611-aaaa-4000-8000-000000000001"
    BETA  = "46ffe611-bbbb-4000-8000-000000000002"      # same first-8 as ALPHA

    @pytest.mark.xfail( strict=True, reason="2a6759de arm 1 — _hwm_path keys on session_id[:8], so two "
                                            "sessions sharing a first-8 share one ledger. XPASS(strict) "
                                            "means the key was widened: come read the row before deleting me." )
    def test_two_sessions_sharing_a_prefix_do_not_share_one_hwm_file( self, tmp_path ):
        """The two sessions are distinct; their durable ledgers must be too."""
        a = dr._hwm_path( self.ALPHA, base_dir=tmp_path )
        b = dr._hwm_path( self.BETA,  base_dir=tmp_path )
        assert a.name != b.name, (
            f"COLLISION: both sessions key the same ledger {a.name!r} — "
            "arm 1, mutual suppression of each other's DMs"
        )

    @pytest.mark.xfail( strict=True, reason="2a6759de arm 2 — job_id IS target_session_id[:8] (dm.py:329), "
                                            "so a colliding session claims another's DMs. XPASS(strict) means "
                                            "DM addressing was widened: do NOT delete me, read the row." )
    def test_a_dm_addressed_to_one_session_is_not_claimed_by_the_other( self ):
        """
        Arm 2 — the worse one. `reconcile_context` selects rows whose `job_id`
        equals this session's hash8, and `job_id` IS the recipient's truncated id.
        A DM addressed to ALPHA is therefore indistinguishable from one addressed
        to BETA, so BETA surfaces ALPHA's private DM as its own.
        """
        hash8_alpha = self.ALPHA[ :8 ]
        hash8_beta  = self.BETA[ :8 ]
        dm_for_alpha = _row( "m-alpha", job_id=hash8_alpha, body="private to alpha" )

        ctx, _state = dr.reconcile_context(
            hash8_beta, [ dm_for_alpha ], { "cursor_ts": None, "surfaced_ids": [], "seeded": True }
        )
        assert "private to alpha" not in ctx, (
            "MISDELIVERY: session BETA surfaced a DM addressed to ALPHA — "
            "arm 2, upstream of the HWM entirely (dm.py:329)"
        )
