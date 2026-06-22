#!/usr/bin/env python3
"""
Unit tests for fleet_render — the v2.1 direct-state fleet render + snapshot
(arbiter design `03` §10.2-§10.4). 100% line+branch+function coverage.
"""
import datetime
import os
import sys

import pytest

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.agents.heartbeat_arbiter import fleet_render as fr


NOW = datetime.datetime( 2026, 6, 6, 22, 41, 0, tzinfo=datetime.timezone.utc )


# ── _fmt_age ──────────────────────────────────────────────────────────────────

class TestFmtAge:
    def test_none( self ):       assert fr._fmt_age( None ) == "—"
    def test_negative( self ):   assert fr._fmt_age( -5 ) == "0s"
    def test_seconds( self ):    assert fr._fmt_age( 4 ) == "4s"
    def test_minutes( self ):    assert fr._fmt_age( 359 ) == "5m"
    def test_hours( self ):      assert fr._fmt_age( 7200 ) == "2h"
    def test_days( self ):       assert fr._fmt_age( 90000 ) == "1d"


# ── _bridge_age / _event_age ──────────────────────────────────────────────────

class TestSignalAges:
    def test_bridge_age_none( self ):
        assert fr._bridge_age( None, NOW ) is None

    def test_bridge_age_valid( self ):
        assert fr._bridge_age( NOW.timestamp() - 10, NOW ) == pytest.approx( 10, abs=1 )

    def test_bridge_age_bad_value_swallowed( self ):
        assert fr._bridge_age( "not-a-number", NOW ) is None

    def test_event_age_none( self ):
        assert fr._event_age( None, NOW ) is None

    def test_event_age_valid( self ):
        ts = NOW - datetime.timedelta( seconds=30 )
        assert fr._event_age( ts, NOW ) == pytest.approx( 30, abs=1 )

    def test_event_age_bad_type_swallowed( self ):
        assert fr._event_age( "not-a-datetime", NOW ) is None


# ── _verdict ──────────────────────────────────────────────────────────────────

class TestVerdict:
    def test_offline_when_no_signal( self ):
        assert fr._verdict( None, 60, 600, 3600 ) == "offline"

    def test_live( self ):
        assert fr._verdict( 30, 60, 600, 3600 ) == "LIVE"

    def test_quiet_carries_age( self ):
        assert fr._verdict( 360, 60, 600, 3600 ) == "quiet 6m"

    def test_stale_carries_age( self ):
        assert fr._verdict( 1800, 60, 600, 3600 ) == "stale 30m"

    def test_offline_beyond_stale( self ):
        assert fr._verdict( 7200, 60, 600, 3600 ) == "offline"


# ── compute_liveness ──────────────────────────────────────────────────────────

class TestComputeLiveness:
    def test_bridge_primary_overrides_old_event( self ):
        """Fresh bridge ⇒ LIVE even with a 35m-old event ts (bridge is PRIMARY)."""
        view = { "last_event_ts": NOW - datetime.timedelta( minutes=35 ) }
        out  = fr.compute_liveness( view, NOW.timestamp() - 4, NOW )
        assert out[ "verdict" ] == "LIVE"
        assert out[ "bridge_age_s" ] == 4
        assert out[ "event_age_s" ] == 35 * 60
        assert out[ "freshest_age_s" ] == 4

    def test_event_only_when_no_bridge( self ):
        view = { "last_event_ts": NOW - datetime.timedelta( seconds=120 ) }
        out  = fr.compute_liveness( view, None, NOW )
        assert out[ "bridge_age_s" ] is None
        assert out[ "freshest_age_s" ] == 120

    def test_no_signal_offline( self ):
        out = fr.compute_liveness( { "last_event_ts": None }, None, NOW )
        assert out[ "verdict" ] == "offline" and out[ "freshest_age_s" ] is None

    def test_view_not_dict( self ):
        out = fr.compute_liveness( "not-a-dict", None, NOW )
        assert out[ "event_age_s" ] is None and out[ "verdict" ] == "offline"


# ── build_snapshot ────────────────────────────────────────────────────────────

class TestBuildSnapshot:
    def test_rows_sorted_and_two_columns( self ):
        view = {
            "s2": { "session_id": "s2", "persona": "Bo", "state": "stuck",
                    "holding_on": "peer:Ann", "stuck": True, "last_event_ts": None },
            "s1": { "session_id": "s1", "persona": "Ann", "state": "working",
                    "holding_on": "none", "stuck": False,
                    "last_event_ts": NOW - datetime.timedelta( minutes=35 ) },
        }
        # include_offline=True so the offline, stuck s2 row is retained for the sort/column check.
        snap = fr.build_snapshot( view, { "s1": NOW.timestamp() - 4, "s2": None }, NOW, include_offline=True )
        assert snap[ "session_count" ] == 2
        assert [ r[ "session_id" ] for r in snap[ "sessions" ] ] == [ "s1", "s2" ]  # sorted
        r1 = snap[ "sessions" ][ 0 ]
        assert r1[ "state" ] == "working"          # state column
        assert "verdict" in r1[ "liveness" ]        # liveness column (orthogonal)
        assert snap[ "sessions" ][ 1 ][ "stuck" ] is True
        assert snap[ "generated_at" ] == NOW.isoformat()

    def test_non_dict_view_skipped( self ):
        # include_offline=True so the (signal-less → offline) "ok" row survives the prune,
        # keeping the focus on non-dict skipping.
        snap = fr.build_snapshot( { "bad": "not-a-dict", "ok": { "session_id": "ok" } }, { }, NOW, include_offline=True )
        assert snap[ "session_count" ] == 1 and snap[ "sessions" ][ 0 ][ "session_id" ] == "ok"

    def test_empty_fleet( self ):
        snap = fr.build_snapshot( { }, { }, NOW )
        assert snap[ "session_count" ] == 0 and snap[ "sessions" ] == [ ]

    def test_none_inputs( self ):
        snap = fr.build_snapshot( None, None, NOW )
        assert snap[ "session_count" ] == 0

    def test_default_no_seams_role_worker_manager_none( self ):
        # Neither seam injected → back-compatible flat snapshot, but the two new
        # keys are ALWAYS present (the frontend row shape depends on them).
        view = { "s1": { "session_id": "s1", "persona": "Ann", "state": "working",
                         "holding_on": "none", "stuck": False, "last_event_ts": NOW } }  # LIVE → survives prune
        row = fr.build_snapshot( view, { }, NOW )[ "sessions" ][ 0 ]
        assert row[ "role" ] == "worker" and row[ "manager" ] is None

    def _live_row( self, sid, persona ):
        """One LIVE fleet-view row (survives the offline prune)."""
        return { "session_id": sid, "persona": persona, "state": "working",
                 "holding_on": "none", "stuck": False, "last_event_ts": NOW }

    def test_declared_persona_badges_as_manager_without_manifest( self ):
        # COSA_VOICE_MANAGERS__<PROJECT> roster (Rick 2026-06-11): a declared
        # persona is role="manager" even before its first spawn (no manifest).
        view = { "s1": self._live_row( "s1", "Mr. Radio" ) }
        row  = fr.build_snapshot( view, { }, NOW, declared_managers=[ "Mr. Radio" ] )[ "sessions" ][ 0 ]
        assert row[ "role" ] == "manager"

    def test_declared_match_is_case_insensitive( self ):
        view = { "s1": self._live_row( "s1", "mr. radio" ) }
        row  = fr.build_snapshot( view, { }, NOW, declared_managers=[ "MR. RADIO" ] )[ "sessions" ][ 0 ]
        assert row[ "role" ] == "manager"

    def test_declared_match_is_punct_tolerant_JOURNAL_REGRESSION( self ):
        """F-B regression pin (2026-06-11 journal, 23:53:30Z): persona "mr radio"
        — the EVENT-sourced lowercase punct-stripped form a bridge-less session
        surfaces — read role=worker against declared "Mr. Radio", which ALSO
        config-deaded the F2 manager-staleness tier for him (stale_why_not:
        [not_manager]). Equivalence now rides the ONE canonical identity root
        (Phase 2 swap _normalize_for_match -> canonical_persona_key).

        FLIP (accent seam): the second case ("María"/"maria") is the bug-class
        this plan kills — the pre-Phase-1 accent-keeping normalizer KEPT accents
        ("María" -> "maría") and so MISSED a declared "María" against an
        event-sourced "maria"; canonical_persona_key accent-strips both to "maria" -> match.
        Reverting to the pre-Phase-1 accent-keeping normalizer makes the accent case fail.

        NOTE (intended keep-spaces tradeoff): the canonical key KEEPS internal
        spaces, so the realistic spaced journal form "mr radio" matches declared
        "Mr. Radio", but a contrived SPACELESS "MR.RADIO" -> "mrradio" would NOT
        (it no longer collapses onto "mr radio"). The space-dropping leniency was
        deliberately given up for store-key parity; the spaceless variant is not
        a real persona surface."""
        view = { "s1": self._live_row( "s1", "mr radio" ) }              # the journal shape (spaced)
        row  = fr.build_snapshot( view, { }, NOW, declared_managers=[ "Mr. Radio" ] )[ "sessions" ][ 0 ]
        assert row[ "role" ] == "manager"
        # accent bug-class flip: declared "María" matches event-sourced "maria"
        view = { "s1": self._live_row( "s1", "maria" ) }
        row  = fr.build_snapshot( view, { }, NOW, declared_managers=[ "María" ] )[ "sessions" ][ 0 ]
        assert row[ "role" ] == "manager" and row[ "persona" ] == "maria"

    def test_undeclared_persona_stays_worker( self ):
        view = { "s1": self._live_row( "s1", "Rio" ) }
        row  = fr.build_snapshot( view, { }, NOW, declared_managers=[ "Mr. Radio" ] )[ "sessions" ][ 0 ]
        assert row[ "role" ] == "worker"

    def test_declared_none_persona_row_stays_worker( self ):
        # A row with persona=None can never match the declared roster.
        view = { "s1": self._live_row( "s1", None ) }
        row  = fr.build_snapshot( view, { }, NOW, declared_managers=[ "Mr. Radio" ] )[ "sessions" ][ 0 ]
        assert row[ "role" ] == "worker"

    def test_declared_blank_entries_ignored( self ):
        view = { "s1": self._live_row( "s1", "Ann" ) }
        row  = fr.build_snapshot( view, { }, NOW, declared_managers=[ "  ", "" ] )[ "sessions" ][ 0 ]
        assert row[ "role" ] == "worker"

    def test_declared_unions_with_manifest_managers( self ):
        # One manager by manifest (list_managers_fn), another by declaration —
        # both badge as manager in the same snapshot.
        view = { "mgr-a": self._live_row( "mgr-a", "Tiberius" ),
                 "mgr-b": self._live_row( "mgr-b", "Mr. Radio" ) }
        snap  = fr.build_snapshot( view, { }, NOW,
                                   list_managers_fn  = lambda: { "mgr-a" },
                                   declared_managers = [ "Mr. Radio" ] )
        roles = { r[ "session_id" ]: r[ "role" ] for r in snap[ "sessions" ] }
        assert roles == { "mgr-a": "manager", "mgr-b": "manager" }


# ── _sid_matches (prefix-tolerant) ─────────────────────────────────────────────

class TestSidMatches:
    def test_exact( self ):            assert fr._sid_matches( "abc", "abc" ) is True
    def test_short_prefix_of_full( self ):
        assert fr._sid_matches( "d9e65cd8", "d9e65cd8-bb24-4656" ) is True
    def test_full_prefix_of_short( self ):
        assert fr._sid_matches( "d9e65cd8-bb24-4656", "d9e65cd8" ) is True
    def test_no_match( self ):         assert fr._sid_matches( "abc", "xyz" ) is False
    def test_falsy_a( self ):          assert fr._sid_matches( "", "x" ) is False
    def test_falsy_b( self ):          assert fr._sid_matches( "x", None ) is False


# ── _lookup_dead (prefix-tolerant dead-set membership) ──────────────────────────

class TestLookupDead:
    def test_none_or_empty_never_matches( self ):
        assert fr._lookup_dead( None, "s1" ) is False
        assert fr._lookup_dead( set(), "s1" ) is False
        assert fr._lookup_dead( [], "s1" ) is False

    def test_exact_match( self ):
        assert fr._lookup_dead( { "s1" }, "s1" ) is True

    def test_prefix_tolerant_match( self ):
        # 8-char fleet_view key vs full-uuid dead entry (and vice-versa)
        assert fr._lookup_dead( { "d9e65cd8-bb24-4656" }, "d9e65cd8" ) is True
        assert fr._lookup_dead( { "d9e65cd8" }, "d9e65cd8-bb24-4656" ) is True

    def test_no_match( self ):
        assert fr._lookup_dead( { "other" }, "s1" ) is False


# ── build_snapshot PID fast-death override (process_dead) ───────────────────────

class TestBuildSnapshotProcessDead:
    def _live_view( self ):
        # Fresh event → would be LIVE absent any override.
        return { "s1": { "session_id": "s1", "persona": "Ann", "state": "working",
                         "holding_on": "none", "stuck": False, "last_event_ts": NOW } }

    def test_confirmed_dead_forces_offline_despite_fresh_age( self ):
        # s1 is LIVE by age, but listed dead → forced offline (and pruned by default).
        snap = fr.build_snapshot( self._live_view(), { "s1": NOW.timestamp() }, NOW,
                                  process_dead = { "s1" } )
        assert snap[ "session_count" ] == 0   # offline → pruned from published snapshot

    def test_dead_row_carries_offline_verdict_and_flag_when_retained( self ):
        snap = fr.build_snapshot( self._live_view(), { "s1": NOW.timestamp() }, NOW,
                                  process_dead = { "s1" }, include_offline = True )
        row = snap[ "sessions" ][ 0 ]
        assert row[ "liveness" ][ "verdict" ] == "offline"
        assert row[ "liveness" ][ "process_dead" ] is True

    def test_non_dead_session_keeps_age_verdict( self ):
        snap = fr.build_snapshot( self._live_view(), { "s1": NOW.timestamp() }, NOW,
                                  process_dead = { "other" } )
        row = snap[ "sessions" ][ 0 ]
        assert row[ "liveness" ][ "verdict" ] == "LIVE"
        assert "process_dead" not in row[ "liveness" ]

    def test_none_process_dead_is_back_compat_noop( self ):
        # No process_dead → identical to today (LIVE row retained, no flag).
        row = fr.build_snapshot( self._live_view(), { "s1": NOW.timestamp() }, NOW )[ "sessions" ][ 0 ]
        assert row[ "liveness" ][ "verdict" ] == "LIVE"
        assert "process_dead" not in row[ "liveness" ]

    def test_prefix_tolerant_dead_key( self ):
        # dead-set carries the full uuid; the fleet_view key is the short form.
        snap = fr.build_snapshot( self._live_view(), { "s1": NOW.timestamp() }, NOW,
                                  process_dead = { "s1-full-uuid-form" }, include_offline = True )
        assert snap[ "sessions" ][ 0 ][ "liveness" ][ "verdict" ] == "offline"


# ── build_snapshot REAP TOMBSTONE override (reaped) ─────────────────────────────

class TestBuildSnapshotReaped:
    def _live_reaped_view( self ):
        # Fresh commons → would be LIVE absent the reaped tombstone override.
        return { "s1": { "session_id": "s1", "persona": "Ann", "state": "unknown",
                         "holding_on": "none", "stuck": False, "reaped": True,
                         "last_event_ts": None, "commons_ts": NOW } }

    def test_reaped_forces_offline_despite_fresh_signal( self ):
        # s1 is LIVE by commons, but reaped tombstone present → forced offline + pruned.
        snap = fr.build_snapshot( self._live_reaped_view(), { }, NOW )
        assert snap[ "session_count" ] == 0   # offline → pruned from published snapshot

    def test_reaped_row_carries_offline_verdict_and_flag_when_retained( self ):
        snap = fr.build_snapshot( self._live_reaped_view(), { }, NOW, include_offline = True )
        row = snap[ "sessions" ][ 0 ]
        assert row[ "liveness" ][ "verdict" ] == "offline"
        assert row[ "liveness" ][ "reaped" ] is True

    def test_non_reaped_session_keeps_age_verdict( self ):
        view = { "s1": { "session_id": "s1", "persona": "Ann", "state": "working",
                         "holding_on": "none", "stuck": False, "last_event_ts": NOW } }
        row = fr.build_snapshot( view, { "s1": NOW.timestamp() }, NOW )[ "sessions" ][ 0 ]
        assert row[ "liveness" ][ "verdict" ] == "LIVE"
        assert "reaped" not in row[ "liveness" ]

    def test_reaped_absent_key_is_noop( self ):
        # view without the reaped key → no override (back-compat with pre-fix views).
        view = { "s1": { "session_id": "s1", "persona": "Ann", "state": "working",
                         "holding_on": "none", "stuck": False, "last_event_ts": NOW } }
        row = fr.build_snapshot( view, { "s1": NOW.timestamp() }, NOW )[ "sessions" ][ 0 ]
        assert row[ "liveness" ][ "verdict" ] == "LIVE" and "reaped" not in row[ "liveness" ]


# ── build_snapshot hierarchy enrichment (Fleet-Status P1 §4) ────────────────────

class TestBuildSnapshotEnrichment:
    def _view( self ):
        # Fresh last_event_ts → LIVE, so the §5.2 default prune keeps these rows and
        # the hierarchy (role/manager) assertions below stay non-vacuous.
        return {
            "mgr0001": { "session_id": "mgr0001", "persona": "Tiberius", "state": "working",
                         "holding_on": "none", "stuck": False, "last_event_ts": NOW },
            "wkr0001": { "session_id": "wkr0001", "persona": "Rio", "state": "working",
                         "holding_on": "none", "stuck": False, "last_event_ts": NOW },
        }

    def test_role_manager_via_prefix_match( self ):
        # manager set carries the FULL slugified uuid; the row sid is the short form.
        snap = fr.build_snapshot(
            self._view(), { }, NOW,
            list_managers_fn = lambda: { "mgr0001-bb24-4656-8076-29f646b60a98" },
        )
        by_sid = { r[ "session_id" ]: r for r in snap[ "sessions" ] }
        assert by_sid[ "mgr0001" ][ "role" ] == "manager"
        assert by_sid[ "wkr0001" ][ "role" ] == "worker"

    def test_manager_persona_only_when_lineage( self ):
        def resolver( sid ):
            if sid == "wkr0001":
                return { "manager_persona": "Tiberius", "source": "lineage" }
            return { "manager_persona": "Bo", "source": "declared" }   # NOT lineage → ignored
        snap = fr.build_snapshot( self._view(), { }, NOW, resolve_manager_fn = resolver )
        by_sid = { r[ "session_id" ]: r for r in snap[ "sessions" ] }
        assert by_sid[ "wkr0001" ][ "manager" ] == "Tiberius"   # lineage surfaces
        assert by_sid[ "mgr0001" ][ "manager" ] is None         # declared → None (never guess)

    def test_manager_none_when_unresolved( self ):
        snap = fr.build_snapshot(
            self._view(), { }, NOW,
            resolve_manager_fn = lambda sid: { "manager_persona": None, "source": "unresolved" },
        )
        assert all( r[ "manager" ] is None for r in snap[ "sessions" ] )

    def test_manager_none_when_resolver_returns_non_dict( self ):
        snap = fr.build_snapshot(
            self._view(), { }, NOW,
            resolve_manager_fn = lambda sid: None,   # defensive: non-dict result
        )
        assert all( r[ "manager" ] is None for r in snap[ "sessions" ] )

    def test_resolver_throws_degrades_to_none( self ):
        def boom( sid ): raise RuntimeError( "brittle hop" )
        snap = fr.build_snapshot( self._view(), { }, NOW, resolve_manager_fn = boom )
        assert all( r[ "manager" ] is None for r in snap[ "sessions" ] )   # never raises

    def test_list_managers_throws_degrades_to_all_workers( self ):
        def boom(): raise RuntimeError( "no session dir" )
        snap = fr.build_snapshot( self._view(), { }, NOW, list_managers_fn = boom )
        assert all( r[ "role" ] == "worker" for r in snap[ "sessions" ] )   # never raises

    def test_list_managers_returns_none_treated_as_empty( self ):
        snap = fr.build_snapshot( self._view(), { }, NOW, list_managers_fn = lambda: None )
        assert all( r[ "role" ] == "worker" for r in snap[ "sessions" ] )

    def test_both_seams_full_hierarchy( self ):
        snap = fr.build_snapshot(
            self._view(), { }, NOW,
            list_managers_fn   = lambda: { "mgr0001" },
            resolve_manager_fn = lambda sid: (
                { "manager_persona": "Tiberius", "source": "lineage" } if sid == "wkr0001"
                else { "manager_persona": None, "source": "unresolved" }
            ),
        )
        by_sid = { r[ "session_id" ]: r for r in snap[ "sessions" ] }
        assert by_sid[ "mgr0001" ][ "role" ] == "manager" and by_sid[ "mgr0001" ][ "manager" ] is None
        assert by_sid[ "wkr0001" ][ "role" ] == "worker"  and by_sid[ "wkr0001" ][ "manager" ] == "Tiberius"


# ── frame_signature ───────────────────────────────────────────────────────────

class TestFrameSignature:
    def _view( self ):
        return { "s1": { "session_id": "s1", "persona": "Ann", "state": "working",
                         "holding_on": "none", "stuck": False,
                         "last_event_ts": NOW - datetime.timedelta( minutes=35 ) } }

    def test_ticking_ages_not_a_change( self ):
        snap_a = fr.build_snapshot( self._view(), { "s1": NOW.timestamp() - 4 }, NOW )
        later  = NOW + datetime.timedelta( seconds=10 )
        snap_b = fr.build_snapshot( self._view(), { "s1": later.timestamp() - 9 }, later )
        assert fr.frame_signature( snap_a ) == fr.frame_signature( snap_b )

    def test_state_change_is_a_change( self ):
        snap_a = fr.build_snapshot( self._view(), { "s1": NOW.timestamp() - 4 }, NOW )
        v2 = self._view(); v2[ "s1" ][ "state" ] = "stuck"
        snap_b = fr.build_snapshot( v2, { "s1": NOW.timestamp() - 4 }, NOW )
        assert fr.frame_signature( snap_a ) != fr.frame_signature( snap_b )

    def test_verdict_bucket_transition_is_a_change( self ):
        snap_live = fr.build_snapshot( self._view(), { "s1": NOW.timestamp() - 4 }, NOW )
        # include_offline=True keeps s1 present-but-offline so this exercises a verdict
        # BUCKET transition (LIVE→offline), not the §5.2 prune (which would drop the row).
        snap_off  = fr.build_snapshot( self._view(), { "s1": None }, NOW, include_offline=True )  # → offline
        assert fr.frame_signature( snap_live ) != fr.frame_signature( snap_off )

    def test_none_snapshot( self ):
        assert fr.frame_signature( None ) == tuple()

    def test_non_str_verdict_handled( self ):
        # A row whose liveness.verdict is None must not crash bucket-splitting.
        snap = { "sessions": [ { "session_id": "x", "liveness": { "verdict": None } } ] }
        sig  = fr.frame_signature( snap )
        assert sig[ 0 ][ -1 ] is None


# ── render_fleet_table / render_tick ──────────────────────────────────────────

class TestRender:
    def test_table_has_columns_and_stuck( self ):
        view = { "s1": { "session_id": "s1", "persona": "Ann", "state": "stuck",
                         "holding_on": "peer:Bo", "stuck": True, "last_event_ts": None } }
        snap  = fr.build_snapshot( view, { "s1": None }, NOW, include_offline=True )  # offline row retained for render
        table = fr.render_fleet_table( snap )
        assert "Fleet arbiter" in table and "verdict" in table
        assert "Ann" in table and "STUCK" in table

    def test_table_empty( self ):
        assert "(no sessions)" in fr.render_fleet_table( fr.build_snapshot( { }, { }, NOW ) )

    def test_table_none( self ):
        assert "(no sessions)" in fr.render_fleet_table( None )

    def test_table_row_falls_back_to_sid_when_no_persona( self ):
        view = { "s9": { "session_id": "s9", "persona": None, "state": "idle",
                         "holding_on": "none", "stuck": False, "last_event_ts": None } }
        table = fr.render_fleet_table( fr.build_snapshot( view, { "s9": None }, NOW, include_offline=True ) )
        assert "s9" in table

    def test_tick_with_change_shows_duration( self ):
        tick = fr.render_tick( NOW, NOW - datetime.timedelta( minutes=12 ), 5 )
        assert "no changes for 12m" in tick and "(since 22:29)" in tick and "5 session(s)" in tick

    def test_tick_never_changed( self ):
        assert "no changes yet" in fr.render_tick( NOW, None, 0 )


# ── D6 / §5.2 published-snapshot offline prune ────────────────────────────────

class TestPublishedOfflinePrune:
    def _view( self, *, last_event_ts=None, commons_ts=None ):
        v = { "s1": { "session_id": "s1", "persona": "Ann", "state": "idle",
                      "holding_on": "none", "stuck": False, "last_event_ts": last_event_ts } }
        if commons_ts is not None:
            v[ "s1" ][ "commons_ts" ] = commons_ts
        return v

    def test_default_omits_offline_session( self ):
        # No bridge + no recent signal → verdict "offline" → pruned from the published snapshot.
        snap = fr.build_snapshot( self._view(), { "s1": None }, NOW )
        assert snap[ "session_count" ] == 0
        assert snap[ "sessions" ] == [ ]

    def test_include_offline_true_retains_offline_session( self ):
        snap = fr.build_snapshot( self._view(), { "s1": None }, NOW, include_offline=True )
        assert snap[ "session_count" ] == 1
        assert snap[ "sessions" ][ 0 ][ "liveness" ][ "verdict" ] == "offline"

    def test_live_session_survives_default_prune( self ):
        # Fresh bridge → LIVE → kept even with the default (include_offline=False).
        snap = fr.build_snapshot( self._view(), { "s1": NOW.timestamp() - 4 }, NOW )
        assert snap[ "session_count" ] == 1
        assert snap[ "sessions" ][ 0 ][ "liveness" ][ "verdict" ] == "LIVE"

    def test_count_reflects_post_prune_rows_in_a_mixed_fleet( self ):
        view = {
            "live": { "session_id": "live", "persona": "L", "state": "working",
                      "holding_on": "none", "stuck": False, "last_event_ts": None,
                      "commons_ts": NOW - datetime.timedelta( seconds=5 ) },   # LIVE by commons
            "dead": { "session_id": "dead", "persona": "D", "state": "idle",
                      "holding_on": "none", "stuck": False, "last_event_ts": None },  # offline
        }
        snap = fr.build_snapshot( view, { }, NOW )
        assert { r[ "session_id" ] for r in snap[ "sessions" ] } == { "live" }
        assert snap[ "session_count" ] == 1


# ── carry_forward_lineage (offline-lineage retention, 2026-06-10) ──────────────

def _snap( *rows ):
    """Minimal build_snapshot-shaped result for carry tests."""
    return { "generated_at": NOW.isoformat(), "session_count": len( rows ), "sessions": list( rows ) }


def _row( sid, manager=None ):
    return { "session_id": sid, "persona": sid.upper(), "manager": manager }


class TestCarryForwardLineage:

    def test_fresh_manager_refreshes_carry( self ):
        snap = _snap( _row( "w1", manager="Tiberius" ) )
        out, nxt = fr.carry_forward_lineage( snap, { } )
        # fresh lineage left untouched (no retained flag) and recorded for next poll
        assert out[ "sessions" ][ 0 ][ "manager" ] == "Tiberius"
        assert "manager_retained" not in out[ "sessions" ][ 0 ]
        assert nxt == { "w1": "Tiberius" }

    def test_none_with_prior_is_filled_and_flagged( self ):
        snap = _snap( _row( "w1", manager=None ) )                 # resolver missed (reaped)
        out, nxt = fr.carry_forward_lineage( snap, { "w1": "Tiberius" } )
        row = out[ "sessions" ][ 0 ]
        assert row[ "manager" ] == "Tiberius"                      # replayed last-known
        assert row[ "manager_retained" ] is True                  # honest transparency flag
        assert nxt == { "w1": "Tiberius" }                        # keeps carrying

    def test_none_without_prior_stays_unmanaged( self ):
        snap = _snap( _row( "w1", manager=None ) )
        out, nxt = fr.carry_forward_lineage( snap, { } )
        assert out[ "sessions" ][ 0 ][ "manager" ] is None
        assert "manager_retained" not in out[ "sessions" ][ 0 ]
        assert nxt == { }                                         # never invents lineage

    def test_eviction_prunes_carry_to_current_sids( self ):
        # w2 was carried last poll but is gone from THIS snapshot → forgotten.
        snap = _snap( _row( "w1", manager="Tiberius" ) )
        _, nxt = fr.carry_forward_lineage( snap, { "w1": "Tiberius", "w2": "Tiberius" } )
        assert nxt == { "w1": "Tiberius" }                        # w2 evicted

    def test_non_dict_prior_treated_as_empty( self ):
        snap = _snap( _row( "w1", manager=None ) )
        out, nxt = fr.carry_forward_lineage( snap, None )         # prior None → {}
        assert out[ "sessions" ][ 0 ][ "manager" ] is None
        assert nxt == { }

    def test_falsy_or_non_dict_snapshot_degrades( self ):
        assert fr.carry_forward_lineage( None, { "w1": "T" } ) == ( None, { } )
        assert fr.carry_forward_lineage( "nope", { } ) == ( "nope", { } )

    def test_malformed_rows_are_skipped( self ):
        snap = _snap( "not-a-dict", { }, _row( "w1", manager=None ) )  # non-dict row + sid-less row
        out, nxt = fr.carry_forward_lineage( snap, { "w1": "Tiberius" } )
        # only the well-formed sid'd row is processed (filled from prior)
        assert out[ "sessions" ][ 2 ][ "manager" ] == "Tiberius"
        assert nxt == { "w1": "Tiberius" }


class TestPruneOfflineRows:
    """Post-game 2026-06-11: the D6/§5.2 offline-prune extracted as a pure helper
    so the arbiter can detect on the FULL snapshot and publish the live-only view."""

    def _live_row( self, sid, verdict="LIVE" ):
        return { "session_id": sid, "liveness": { "verdict": verdict } }

    def test_prunes_offline_and_recounts( self ):
        snap = _snap( self._live_row( "a" ), self._live_row( "b", "offline" ),
                      self._live_row( "c", "stale 45m" ) )
        out = fr.prune_offline_rows( snap )
        assert [ r[ "session_id" ] for r in out[ "sessions" ] ] == [ "a", "c" ]
        assert out[ "session_count" ] == 2
        assert out[ "generated_at" ] == snap[ "generated_at" ]
        # the INPUT snapshot is untouched (new top-level dict; rows shared)
        assert snap[ "session_count" ] == 3 and len( snap[ "sessions" ] ) == 3
        assert out[ "sessions" ][ 0 ] is snap[ "sessions" ][ 0 ]       # rows SHARED, not copied

    def test_non_dict_rows_dropped_and_malformed_liveness_kept( self ):
        snap = _snap( "not-a-dict",
                      { "session_id": "x", "liveness": "bad" },        # malformed liveness → kept (verdict None)
                      { "session_id": "y" } )                          # no liveness at all → kept
        out = fr.prune_offline_rows( snap )
        assert [ r[ "session_id" ] for r in out[ "sessions" ] ] == [ "x", "y" ]
        assert out[ "session_count" ] == 2

    def test_falsy_or_non_dict_snapshot_degrades_to_empty( self ):
        for bad in ( None, "nope", 7 ):
            out = fr.prune_offline_rows( bad )
            assert out == { "generated_at": None, "session_count": 0, "sessions": [ ] }

    def test_all_live_passthrough_and_all_offline_empty( self ):
        live = _snap( self._live_row( "a" ), self._live_row( "b", "quiet 6m" ) )
        assert fr.prune_offline_rows( live )[ "session_count" ] == 2
        dark = _snap( self._live_row( "a", "offline" ) )
        out  = fr.prune_offline_rows( dark )
        assert out[ "sessions" ] == [ ] and out[ "session_count" ] == 0


def test_quick_smoke_test():
    assert fr.quick_smoke_test() is True


if __name__ == "__main__":
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
