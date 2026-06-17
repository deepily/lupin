#!/usr/bin/env python3
"""
Unit tests for the DM-as-liveness toggle (2026-06-17) — the 5th `dm_age` liveness
signal, flag-gated by `arbiter count dm as liveness` (default TRUE).

Design: src/rnd/v0.1.8/2026.06.17-dm-as-liveness-toggle-plan.md.

Covers the full changed surface with injected fakes (no real IO):
  - compute_liveness          — dm_age as a 5th freshest-of candidate, gated by
                                count_dm; dm_age_s ALWAYS present (auditable);
                                flag-OFF byte-identical to the 4-signal verdict;
                                dm_age freshest vs not-freshest; non-dict view
  - build_snapshot            — count_dm_as_liveness passthrough (default + False)
  - _dm_ts_for_session        — max selection (newer-wins + not-newer skip),
                                non-matching skip, None-ts skip, empty/None map
  - build_fleet_view          — dm_activity confers membership (DM-only session),
                                dm_ts set + off the activity axis + NOT phantom-
                                guarded; prefix-tolerant id match; absent → None
  - ArbiterConsumerJob seams  — count_dm_as_liveness_fn None→lambda True default +
                                provided; dm_activity_fn stored; _poll_once gating
                                (flag ON calls the reader + dm_age flows; flag OFF
                                SKIPS the reader; reader None → inert)
  - factory wiring            — build_fleet_arbiter_job_factory defaults
                                dm_activity_fn to the real reader + threads both
                                seams to the job
"""
import datetime

from cosa.agents.heartbeat_arbiter.fleet_render import compute_liveness, build_snapshot
from cosa.agents.heartbeat_arbiter.fleet_data_model import build_fleet_view, _dm_ts_for_session
from cosa.agents.heartbeat_arbiter.arbiter_job import ArbiterConsumerJob, _default_dm_activity_fn


UTC = datetime.timezone.utc
NOW = datetime.datetime( 2026, 6, 17, 12, 0, 0, tzinfo=UTC )


def _ago( seconds ):
    return NOW - datetime.timedelta( seconds=seconds )


# ── compute_liveness — the 5th dm_age signal ─────────────────────────────────
class TestComputeLivenessDmAge:

    def test_dm_age_always_present_even_without_dm_ts( self ):
        live = compute_liveness( { "session_id": "s" }, None, NOW )
        assert "dm_age_s" in live and live[ "dm_age_s" ] is None

    def test_flag_on_dm_only_drives_live_verdict( self ):
        # ONLY signal is a fresh SENT-DM → flag ON ⇒ dm_age is the freshest ⇒ LIVE
        view = { "dm_ts": _ago( 7 ) }
        live = compute_liveness( view, None, NOW, count_dm=True )
        assert live[ "verdict" ] == "LIVE"
        assert live[ "dm_age_s" ] == 7 and live[ "freshest_age_s" ] == 7

    def test_flag_off_dm_only_excluded_byte_identical_offline( self ):
        # flag OFF ⇒ dm_age computed (auditable) but EXCLUDED ⇒ no counted signal
        # ⇒ offline (byte-identical to the prior 4-signal verdict)
        view = { "dm_ts": _ago( 7 ) }
        off  = compute_liveness( view, None, NOW, count_dm=False )
        assert off[ "dm_age_s" ] == 7                     # still computed for audit
        assert off[ "freshest_age_s" ] is None and off[ "verdict" ] == "offline"
        # and it equals the verdict block with NO dm_ts at all (the 4-signal truth)
        none_dm = compute_liveness( { }, None, NOW, count_dm=True )
        assert off[ "freshest_age_s" ] == none_dm[ "freshest_age_s" ]
        assert off[ "verdict" ] == none_dm[ "verdict" ]

    def test_flag_on_dm_present_but_not_freshest_another_signal_wins( self ):
        # bridge 3s (freshest) beats dm 40s; dm_age_s still surfaced for audit
        view = { "dm_ts": _ago( 40 ) }
        live = compute_liveness( view, NOW.timestamp() - 3, NOW, count_dm=True )
        assert live[ "verdict" ] == "LIVE"
        assert live[ "freshest_age_s" ] == 3 and live[ "dm_age_s" ] == 40

    def test_flag_on_dm_age_freshest_among_several( self ):
        # dm 2s is fresher than commons 30s ⇒ dm drives the freshest age
        view = { "dm_ts": _ago( 2 ), "commons_ts": _ago( 30 ) }
        live = compute_liveness( view, NOW.timestamp() - 50, NOW, count_dm=True )
        assert live[ "freshest_age_s" ] == 2 and live[ "verdict" ] == "LIVE"

    def test_non_dict_view_dm_age_none( self ):
        live = compute_liveness( None, None, NOW, count_dm=True )
        assert live[ "dm_age_s" ] is None and live[ "verdict" ] == "offline"


# ── build_snapshot — count_dm_as_liveness passthrough ────────────────────────
class TestBuildSnapshotPassthrough:

    def _dm_only_view( self ):
        return { "s": { "session_id": "s", "persona": "Dee", "state": "working",
                        "holding_on": "none", "stuck": False,
                        "last_event_ts": None, "dm_ts": _ago( 5 ) } }

    def test_default_true_dm_drives_live( self ):
        snap = build_snapshot( self._dm_only_view(), { }, NOW, include_offline=True )
        live = snap[ "sessions" ][ 0 ][ "liveness" ]
        assert live[ "verdict" ] == "LIVE" and live[ "dm_age_s" ] == 5

    def test_explicit_false_excludes_dm( self ):
        snap = build_snapshot( self._dm_only_view(), { }, NOW,
                               include_offline=True, count_dm_as_liveness=False )
        live = snap[ "sessions" ][ 0 ][ "liveness" ]
        assert live[ "dm_age_s" ] == 5 and live[ "verdict" ] == "offline"


# ── _dm_ts_for_session — the prefix-matched MAX helper ───────────────────────
class TestDmTsForSession:

    def test_none_and_empty_map( self ):
        assert _dm_ts_for_session( None, "s" ) is None
        assert _dm_ts_for_session( { }, "s" ) is None

    def test_single_match( self ):
        assert _dm_ts_for_session( { "s": NOW }, "s" ) == NOW

    def test_prefix_tolerant_match( self ):
        full = "abcd1234-aaaa-bbbb"
        assert _dm_ts_for_session( { "abcd1234": NOW }, full ) == NOW
        assert _dm_ts_for_session( { full: NOW }, "abcd1234" ) == NOW

    def test_max_newer_wins_and_older_skipped( self ):
        # two entries that BOTH prefix-match sid: the older one exercises the
        # `ts > best` FALSE arc (best stays the newer) — closes the 144->141 branch
        older, newer = _ago( 90 ), _ago( 5 )
        assert _dm_ts_for_session( { "s": older, "sxx": newer }, "s" ) == newer
        # reverse insertion order so the FIRST seen is the newer, second is older
        assert _dm_ts_for_session( { "s": newer, "sxx": older }, "s" ) == newer

    def test_non_matching_skipped( self ):
        assert _dm_ts_for_session( { "other": NOW }, "s" ) is None

    def test_none_ts_skipped( self ):
        assert _dm_ts_for_session( { "s": None }, "s" ) is None


# ── build_fleet_view — dm_activity as membership + liveness source (e) ────────
class TestBuildFleetViewDmActivity:

    def test_no_dm_activity_all_dm_ts_none( self ):
        events = { "s1": [ { "session_id": "s1", "persona": "Ann", "outcome": "poked",
                             "ts": _ago( 30 ).isoformat() } ] }
        view = build_fleet_view( events, [ ], NOW, 3600 )
        assert view[ "s1" ][ "dm_ts" ] is None

    def test_dm_only_session_enters_roster_off_activity_axis( self ):
        # a session whose ONLY signal is a SENT-DM enters the roster (source e),
        # dm_ts set, but stays OFF the activity axis (state unknown, no event ts,
        # alive False — the verdict seam, not this leaf, turns dm into LIVE) and is
        # NOT phantom-guarded (no bridge yet still carries dm_ts — the coverage hole)
        dm_ts = _ago( 9 )
        view  = build_fleet_view( { }, [ ], NOW, 3600, dm_activity={ "dm1": dm_ts } )
        assert "dm1" in view
        v = view[ "dm1" ]
        assert v[ "dm_ts" ] == dm_ts
        assert v[ "last_event_ts" ] is None and v[ "commons_ts" ] is None
        assert v[ "last_activity_ts" ] is None and v[ "alive" ] is False
        assert v[ "state" ] == "unknown"

    def test_dm_ts_folds_into_existing_member_without_changing_state( self ):
        events = { "s1": [ { "session_id": "s1", "persona": "Ann", "outcome": "poked",
                             "ts": _ago( 30 ).isoformat(), "awaiting": None } ] }
        dm_ts  = _ago( 4 )
        view   = build_fleet_view( events, [ ], NOW, 3600, dm_activity={ "s1": dm_ts } )
        assert view[ "s1" ][ "dm_ts" ] == dm_ts
        # state / last_event_ts are activity-axis → unchanged by dm (liveness ≠ activity)
        assert view[ "s1" ][ "state" ] == "working" and view[ "s1" ][ "last_event_ts" ] is not None


# ── ArbiterConsumerJob seams — construction + _poll_once gating ───────────────
class _Gateway:
    def who( self, retention_hours=24 ): return [ ]
    def send_to( self, recipient, body, metadata=None ): pass
    def post( self, topic, body ): pass
    def read( self, topic, since=None, limit=50 ): return [ ]


class _FakeClock:
    def __init__( self, t ): self.t = t
    def now_iso( self ): return self.t.isoformat()
    def monotonic( self ): return 0.0
    async def sleep( self, s ): return None


def _poll_job( tmp_path, *, count_dm_as_liveness_fn=None, dm_activity_fn=None,
               bridges=None, mtimes=None, sink=None ):
    bridges = bridges or { }
    mtimes  = mtimes or { }
    return ArbiterConsumerJob(
        commons                    = _Gateway(),
        poll_seconds               = 60,
        manager_recipient          = "manager-on-duty",
        events_dir                 = str( tmp_path ),
        clock                      = _FakeClock( NOW ),
        count_dm_as_liveness_fn    = count_dm_as_liveness_fn,
        dm_activity_fn             = dm_activity_fn,
        notify_fn                  = lambda *a, **k: None,
        log_fn                     = lambda event, **f: None,
        bridge_discovery_fn        = lambda: dict( bridges ),
        bridge_mtime_fn            = lambda sid: mtimes.get( sid ),
        list_managers_fn           = lambda: set(),
        resolve_manager_fn         = lambda sid, declared_manager=None: {
                                         "manager_persona": None, "source": "unresolved" },
        resolve_active_managers_fn = lambda who, bridge_sessions: [ ],
        render_sink                = lambda s: None,
        snapshot_sink              = sink or ( lambda s: None ),
    )


class TestArbiterSeamConstruction:

    def test_count_dm_fn_defaults_to_lambda_true( self, tmp_path ):
        job = _poll_job( tmp_path )                               # None → lambda: True
        assert job._count_dm_as_liveness_fn() is True
        assert job._dm_activity_fn is None                        # None seam → inert

    def test_count_dm_fn_provided_is_used( self, tmp_path ):
        job = _poll_job( tmp_path, count_dm_as_liveness_fn=lambda: False )
        assert job._count_dm_as_liveness_fn() is False


class TestPollOnceGating:

    def test_flag_on_reader_called_and_dm_age_flows( self, tmp_path ):
        calls = [ ]
        snaps = [ ]
        dm_fn = lambda: ( calls.append( 1 ) or { "dmsess": _ago( 6 ) } )
        job = _poll_job(
            tmp_path,
            count_dm_as_liveness_fn = lambda: True,
            dm_activity_fn          = dm_fn,
            bridges                 = { "dmsess": "Dee" },        # roster membership
            mtimes                  = { "dmsess": None },         # no bridge mtime → dm is the live signal
            sink                    = snaps.append,
        )
        job._poll_once()
        assert calls == [ 1 ]                                     # reader CALLED when flag ON
        rows = { r[ "session_id" ]: r for r in snaps[ -1 ][ "sessions" ] }
        assert "dmsess" in rows                                   # published (LIVE, not pruned)
        assert rows[ "dmsess" ][ "liveness" ][ "dm_age_s" ] == 6
        assert rows[ "dmsess" ][ "liveness" ][ "verdict" ] == "LIVE"

    def test_flag_off_skips_reader_entirely( self, tmp_path ):
        calls = [ ]
        job = _poll_job(
            tmp_path,
            count_dm_as_liveness_fn = lambda: False,
            dm_activity_fn          = lambda: ( calls.append( 1 ) or { "x": NOW } ),
        )
        job._poll_once()
        assert calls == [ ]                                       # query SKIPPED when flag OFF

    def test_reader_none_is_inert_when_flag_on( self, tmp_path ):
        # flag ON but no reader wired → no crash, no dm signal (the inert seam)
        job = _poll_job( tmp_path, count_dm_as_liveness_fn=lambda: True, dm_activity_fn=None )
        summary = job._poll_once()                                # must not raise
        assert isinstance( summary, dict )

    def test_reader_raises_is_swallowed_poll_still_publishes( self, tmp_path ):
        # observer invariant (Krishna fresh-critical finding): a RAISING reader
        # (e.g. DB timeout) must NOT propagate out of _poll_once — it degrades to
        # NO dm signal (the other 4 carry liveness), so the poll still completes &
        # publishes. Without the call-site try/except this would abort the poll and
        # surface as a false "arbiter down" loop-level escalation.
        snaps = [ ]
        def _boom():
            raise RuntimeError( "dm store timeout" )
        job = _poll_job(
            tmp_path,
            count_dm_as_liveness_fn = lambda: True,
            dm_activity_fn          = _boom,
            bridges                 = { "s": "Ann" },            # a roster member so a snapshot is built
            mtimes                  = { "s": NOW.timestamp() - 3 },
            sink                    = snaps.append,
        )
        summary = job._poll_once()                               # must NOT raise
        assert isinstance( summary, dict )
        assert snaps and isinstance( snaps[ -1 ], dict )         # the poll still published


# ── factory wiring (:8001) ───────────────────────────────────────────────────
class _FakeStore:
    def __init__( self ): self.sections = { }
    def set_section( self, name, value ): self.sections[ name ] = value


class _FakeGatewayFactory:
    def who( self, retention_hours=24 ): return [ ]
    def send_to( self, recipient, body, metadata=None ): pass
    def post( self, topic, body ): pass
    def read( self, topic, since=None, limit=50 ): return [ ]


class TestFactoryWiring:

    def test_factory_defaults_dm_reader_and_threads_seams( self ):
        from lupin_arbiter_app.fleet_arbiter_loop import build_fleet_arbiter_job_factory
        factory = build_fleet_arbiter_job_factory(
            _FakeGatewayFactory(), _FakeStore(), log_fn=lambda *a, **k: None,
        )
        job = factory()
        # dm_activity_fn defaults to the real reader (like owed_work_fn)
        assert job._dm_activity_fn is _default_dm_activity_fn
        # count_dm_as_liveness_fn not wired by the factory → job defaults to lambda True
        assert job._count_dm_as_liveness_fn() is True

    def test_factory_threads_injected_seams( self ):
        from lupin_arbiter_app.fleet_arbiter_loop import build_fleet_arbiter_job_factory
        flag_fn = lambda: False
        dm_fn   = lambda: { "s": NOW }
        factory = build_fleet_arbiter_job_factory(
            _FakeGatewayFactory(), _FakeStore(), log_fn=lambda *a, **k: None,
            count_dm_as_liveness_fn=flag_fn, dm_activity_fn=dm_fn,
        )
        job = factory()
        assert job._count_dm_as_liveness_fn is flag_fn
        assert job._dm_activity_fn is dm_fn
