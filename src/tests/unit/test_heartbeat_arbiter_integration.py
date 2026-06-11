#!/usr/bin/env python3
"""
Heartbeat Arbiter — PRODUCER→CONSUMER whole-chain integration suite.

**Author:** Mr. Radio 🦉 (integration tester, idx 3). Implementers: Rachel 🕊️
(arbiter wiring), Tiffany 💍 (pure leaves). Design: María 🌸
(`src/rnd/v0.1.8/2026.06.04-heartbeat-hook/03-arbiter-design.md`). Manager: Tiberius 👑.

## Why this suite exists (the gap vs the unit suites)

The arbiter's own unit tests (`test_heartbeat_arbiter_job.py` + the leaf suites)
drive the real leaves, but with TWO substitutions that hide whole-chain seams:
  1. **hand-built `_event()` dicts** — never the REAL Hook emit. If the
     producer's on-disk record shape ever drifts from the unit test's helper,
     the unit test still passes while production silently breaks.
  2. **a FIXED clock** — so they can only prove "a 2nd ping at the SAME `now`
     is blocked", never "a ping fires AGAIN after the backoff window expires".

This suite closes both: the REAL Hook write path (`heartbeat_events.emit_outcome`
— the exact call `stop._run_heartbeat` makes — plus one full
transcript→`_run_heartbeat`→emit chain) produces on-disk JSONL that the REAL
arbiter (`tail_fleet_events` → `build_fleet_view` → `build_graph` →
`build_roster` → `_auto_ping` / `_escalate_deadlocks` / `_surface_to_manager`)
consumes, driven by a STEPPABLE clock so multi-poll backoff/cap/quiet trajectories
are exercised against real time advance.

## Hermetic mandate

Every test passes `events_dir=<tmp>` to the arbiter and emits with `base_dir=<tmp>`
(or, for the one full-chain test, relies on the autouse `conftest.py`
`FLEET_EVENTS_DIR`→tmp redirect) + a `FakeGateway` — so NO real `~/.claude` file
is read/written and NO real peer is ever DM'd. Plain pytest, :7999-free.

## Coverage map (the consumer seams the unit suites don't reach)

  PC  producer→consumer loop closure (real emit → real tail/view/act)
  T   incremental byte-offset tail across polls (real appends / partial line)
  TH  multi-poll backoff trajectory with an ADVANCING clock
  INFER  inferred-roster path (requires quiet_threshold < alive_threshold — see finding F3)
  ISO  arbiter is read-only on the event plane; all I/O via the injected gateway

## Adversarial findings — found by this integration tier, RESOLVED by the owners, LOCKED here

  F1  RESOLVED (Rachel): `_auto_ping` keyed `edges` by PERSONA but looked up
      `fleet_view.get(holder)` (SESSION_ID) → the reason collapsed to "none".
      Fix dropped the unsourceable reason → per-(holder, awaited) throttle +
      a holder-only ping message. PC4 locks recipient + ping-fired (the message
      no longer carries a reason).
  F2  RESOLVED (Tiffany adjudicated, Rachel wired): backoff off-by-one — `attempt`
      pre-incremented so `schedule[0]`=60 never gated (first gap was 300, not 60).
      Fix gates with `backoff_for_attempt(attempt-1)`. TH1 LOCKS the corrected
      60→300→900 ladder (the negative-clamp keeps attempt=0 safe).
  F3  RESOLVED (Rachel): inferred-roster was config-dead with the old defaults
      (idle=900 > alive=600). Fix renamed idle_threshold→quiet_threshold, defaulted
      it to 300 (< alive 600), AND added a constructor invariant (quiet < alive →
      else ValueError) so the dead config is now UN-CONSTRUCTABLE. INFER1 exercises
      the path; INFER2 LOCKS that the SHIPPED defaults keep inference reachable;
      INFER3 LOCKS that quiet ≥ alive raises at construction.

Venue: :7999-eligible / local — hermetic, sub-second.
"""
import datetime
import json
import os
import sys

import pytest

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:   # pragma: no cover - src is always already on sys.path under pytest collection
    sys.path.insert( 0, _src_path )

import lupin_cli.claude_code.hooks.stop as stop
from lupin_cli.claude_code.hooks.lib import heartbeat_events, heartbeat_poke_cap
from lupin_cli.claude_code.hooks.lib.heartbeat_events import emit_outcome, EVENT_IDLE
from cosa.agents.heartbeat_arbiter.arbiter_job import ArbiterConsumerJob, ROSTER_TOPIC
from cosa.agents.heartbeat_arbiter.fleet_data_model import build_fleet_view
from cosa.agents.heartbeat_arbiter.idle_roster import build_roster

UTC      = datetime.timezone.utc
BASE_NOW = datetime.datetime( 2026, 6, 5, 12, 0, 0, tzinfo=UTC )


# ═════════════════════════════════════════════════════════════════════════════
# Test doubles — a STEPPABLE clock (the unit suite's FakeClock is fixed) + a
# recording gateway. Both kept minimal + fully exercised (100% test-support cov).
# ═════════════════════════════════════════════════════════════════════════════

class SteppableClock:
    """
    Clock whose wall-time (`now_iso`) advances ON DEMAND between polls — the
    capability the arbiter unit suite's fixed FakeClock lacks, and the reason the
    multi-poll backoff/cap/quiet trajectories are testable here.
    """
    def __init__( self, start, monotonic_seq=None ):
        self._now  = start
        self._seq  = list( monotonic_seq ) if monotonic_seq is not None else None
        self.sleeps = [ ]

    def now_iso( self ):
        return self._now.isoformat()

    def set_now( self, dt ):
        """Advance (or set) wall-clock now to an aware datetime."""
        self._now = dt

    def monotonic( self ):
        """Pop a scripted monotonic value (drives the hard-cap loop), else 0.0."""
        if self._seq:
            return self._seq.pop( 0 )
        return 0.0

    async def sleep( self, seconds ):
        self.sleeps.append( seconds )


class FakeGateway:
    """Records who/send_to/post; who() returns a scripted roster. No real I/O."""
    def __init__( self, who_rows=None ):
        self._who  = list( who_rows ) if who_rows else [ ]
        self.sent  = [ ]    # (recipient, body)
        self.posts = [ ]    # (topic, body)

    def who( self, retention_hours=24 ):
        return list( self._who )

    def send_to( self, recipient, body, metadata=None ):
        self.sent.append( ( recipient, body ) )

    def post( self, topic, body ):
        self.posts.append( ( topic, body ) )

    def read( self, topic, since=None, limit=50 ):
        return [ ]   # v2.2 B3: no decision-needed posts in this suite (hermetic)


def _pings( arb ):
    """
    Auto-ping sends ONLY — excludes the v2.2 B2 manager-tap advisory DMs.

    Since v2.2, `_poll_once` fires BOTH `_auto_ping` (to the blocked peer) AND
    `_tap_managers` (an advisory DM to the manager), so `_commons.sent` carries
    two outbound surfaces. The 2b-2 #4-rewritten auto-ping body uniquely contains
    "blocking worker"; the tap body never does — so these backoff-trajectory tests
    (which count AUTO-PINGS) filter on that signature to keep their intent explicit.
    """
    return [ s for s in arb._commons.sent if "blocking worker" in s[ 1 ] ]


def _roster( arb ):
    """
    Rebuild the trust-labeled idle-roster the way _poll_once does — the sensing
    leaf (build_roster) is unchanged by 2b-2; only its old surface (the dropped
    #6 roster broadcast) is gone, so these tests assert the leaf output directly.
    """
    now = datetime.datetime.fromisoformat( arb._clock.now_iso() )
    fv  = build_fleet_view( arb._acc.snapshot(), arb._commons.who(), now,
                            arb.alive_threshold_seconds,
                            bridge_sessions=arb._bridge_discovery_fn() )
    return build_roster( fv, now, arb.quiet_threshold_seconds )


def _snapshot_row( arb, sid ):
    """The latest published /state snapshot row for `sid` (the pull-state surface
    that REPLACED the #6 roster broadcast), or None."""
    if not arb.captured_snapshots:
        return None
    for row in arb.captured_snapshots[ -1 ][ "sessions" ]:
        if row[ "session_id" ] == sid:
            return row
    return None


# ═════════════════════════════════════════════════════════════════════════════
# Helpers — the REAL producer write path + arbiter factory
# ═════════════════════════════════════════════════════════════════════════════

def _emit( events_dir, sid, outcome, *, ts=BASE_NOW, persona="Mr. Radio 🦉",
           awaiting=None, work_owed=False, poke_count=1, cap=3, reason=None ):
    """
    Append one record via the REAL producer write path (`emit_outcome`) — the
    exact call `stop._run_heartbeat` makes — with a controlled `ts`.
    """
    ok = emit_outcome(
        sid, persona, outcome, poke_count, cap,
        work_owed=work_owed, awaiting=awaiting, reason=reason,
        ts=ts.isoformat(), base_dir=str( events_dir ),
    )
    assert ok is True, f"real emit failed for {sid}/{outcome}"


def _make_arbiter( events_dir, *, gateway=None, clock=None, notify_fn=None, **overrides ):
    """Construct the REAL ArbiterConsumerJob over an isolated events dir + fakes."""
    cfg = dict(
        poll_seconds            = 5,
        manager_recipient       = "Tiberius",
        alive_threshold_seconds = 600,
        quiet_threshold_seconds = 300,
        ping_global_cap         = 10,
        events_dir              = str( events_dir ),
        clock                   = clock if clock is not None else SteppableClock( BASE_NOW ),
        notify_fn               = notify_fn if notify_fn is not None else ( lambda *a, **k: None ),
        # v2.2: a DETERMINISTIC, hermetic manager resolver — the production default
        # would do a real ~/.claude bridge lookup (violating this suite's hermetic
        # mandate). Resolving every worker to "Tiberius" means the B2 tap fires to
        # a fixed manager (its DMs are filtered out by _pings; backoff-trajectory
        # tests count auto-pings only).
        resolve_manager_fn      = lambda sid, declared_manager=None: {
            "manager_session_id": "mgr", "manager_persona": "Tiberius", "source": "lineage" },
        # v1.4: hermetic bridge discovery — the production default does a real
        # ~/.claude bridge scan (non-deterministic here). Default to an EMPTY
        # union source (a) so these event/commons-driven tests stay isolated;
        # the dedicated union test overrides it.
        bridge_discovery_fn     = lambda: { },
    )
    cfg.update( overrides )
    # Capture the /state snapshots (the pull-state surface that replaced the #6
    # roster broadcast) so the sensing tests can assert against them.
    captured = [ ]
    cfg.setdefault( "snapshot_sink", captured.append )
    arb = ArbiterConsumerJob( commons=gateway if gateway is not None else FakeGateway(), **cfg )
    arb.captured_snapshots = captured
    return arb


@pytest.fixture
def fleet( tmp_path ):
    """An isolated fleet events dir the arbiter reads + the producer writes."""
    d = tmp_path / "fleet"
    d.mkdir()
    return d


# ═════════════════════════════════════════════════════════════════════════════
# GROUP PC — producer→consumer loop closure (real emit → real tail/view/act)
# ═════════════════════════════════════════════════════════════════════════════

class TestGroupPCLoopClosure:

    def test_pc1_full_chain_real_hook_emit_feeds_arbiter( self, tmp_path, monkeypatch ):
        """THE loop closure: transcript → real _run_heartbeat → emit → fleet dir → arbiter consumes it.

        Proves the two independently-built halves interoperate on disk — the one
        thing neither side's unit tests can show (each mocks the other half).
        """
        # producer harness (real leaves, isolated roots)
        monkeypatch.setattr( stop, "load_heartbeat_settings", lambda: { "enabled": True, "poke_cap": 3 } )
        monkeypatch.setattr( stop, "get_voice_persona", lambda _s: { "name": "Mr. Radio 🦉" } )
        import cosa.utils.util as cu
        proj = tmp_path / "proj"; proj.mkdir()
        monkeypatch.setattr( cu, "get_project_root", lambda: str( proj ) )
        counter = tmp_path / "counter"; counter.mkdir()
        monkeypatch.setattr( heartbeat_poke_cap, "COUNTER_DIR", counter )

        # an owed transcript (one created→pending task) → the real Hook pokes
        tp   = tmp_path / "t.jsonl"
        line = json.dumps( { "type": "assistant", "message": { "role": "assistant", "content": [
            { "type": "tool_use", "name": "TaskCreate", "input": { "subject": "x" }, "id": "c1" },
        ] } } )
        tp.write_text( line + "\n" )

        out = stop._run_heartbeat( "ha-sid-1", str( tp ) )
        assert out[ "decision" ] == "block"                       # producer poked (sanity)

        # the REAL emitted file lands in the conftest-redirected fleet dir
        fleet_dir = heartbeat_events.FLEET_EVENTS_DIR
        # Deterministic `now`: derive it from the emitted record's OWN ts (the
        # record is alive at its own ts) — NEVER real wall-clock, which would
        # flake under parallel load. Keeps PC1 a true full-chain test, hermetic.
        emitted  = heartbeat_events.read_events( "ha-sid-1" )
        rec_ts   = datetime.datetime.fromisoformat( emitted[ -1 ][ "ts" ] )
        arb      = _make_arbiter( fleet_dir, clock=SteppableClock( rec_ts ) )
        summary  = arb._poll_once()

        assert summary[ "sessions" ] == 1
        rec = arb._acc.snapshot()[ "ha-sid-1" ][ -1 ]            # consumer state == producer's real write
        assert rec[ "outcome" ]   == "poked"
        assert rec[ "work_owed" ] is True                         # v2 real bool flowed end-to-end
        assert rec[ "persona" ]   == "Mr. Radio 🦉"
        # surfaced via the /state snapshot (the pull-state surface that replaced the
        # #6 roster broadcast) — NOT a per-tick commons post (Part-6 #6 DROP)
        assert _snapshot_row( arb, "ha-sid-1" ) is not None
        assert arb._commons.posts == [ ]                          # #6: no roster broadcast

    def test_pc2_real_idle_beacon_to_declared_roster( self, fleet ):
        """Real idle beacon → roster entry trust-labeled declared-available."""
        _emit( fleet, "s-idle", EVENT_IDLE, work_owed=False, persona="Alice" )
        arb     = _make_arbiter( fleet )
        summary = arb._poll_once()
        assert summary[ "roster" ] == 1
        # the trust label the manager weighs — asserted on the (unchanged) build_roster
        # leaf directly, now that the #6 roster broadcast that carried it is dropped
        assert any( r[ "persona" ] == "Alice" and r[ "trust_label" ] == "declared-available"
                    for r in _roster( arb ) )

    def test_pc3_real_poke_to_cap_surfaces_stuck( self, fleet ):
        """Real ≥2 cap_reached+work_owed=True (the stuck signal) → surfaced as Stuck."""
        _emit( fleet, "s-stuck", "cap_reached", work_owed=True, persona="Bob", poke_count=3 )
        _emit( fleet, "s-stuck", "cap_reached", work_owed=True, persona="Bob", poke_count=3 )
        arb = _make_arbiter( fleet )
        arb._poll_once()
        row = _snapshot_row( arb, "s-stuck" )                     # pull-state surface (#6 broadcast dropped)
        assert row is not None and row[ "stuck" ] is True

    def test_pc4_real_awaiting_edge_auto_pings_blocker( self, fleet ):
        """Real honored+awaiting:peer:Bob → edge → auto-ping to Bob (F1-resolved: holder-only message)."""
        _emit( fleet, "s-hold", "honored", awaiting="peer:Bob", persona="Alice" )
        arb     = _make_arbiter( fleet )
        summary = arb._poll_once()
        assert summary[ "edges" ] == 1 and summary[ "pings_fired" ] == 1
        recipient, body = arb._commons.sent[ 0 ]
        assert recipient == "Bob"                                 # pings the awaited peer (the blocker)
        # Part-6 #4 rewrite: names the blocked worker + the ask (not "where are we?")
        assert "Alice" in body and "blocking worker" in body

    def test_pc5_mutual_await_is_deadlock_escalated_not_broken( self, fleet ):
        """Two real sessions awaiting each other → deadlock cycle → ESCALATE (never auto-broken)."""
        _emit( fleet, "s1", "honored", awaiting="peer:Bob",   persona="Alice" )
        _emit( fleet, "s2", "honored", awaiting="peer:Alice", persona="Bob" )
        escalations = [ ]
        arb     = _make_arbiter( fleet, notify_fn=lambda m: escalations.append( m ) )
        summary = arb._poll_once()
        assert summary[ "cycles" ] == 1
        # Part-6 #5: surfaced to Rick (notify_fn) + active managers — not posted to a
        # roster topic (#6 dropped), and NEVER autonomously broken
        assert escalations and "DEADLOCK" in escalations[ 0 ]
        assert arb._commons.posts == [ ]                          # #6: no roster broadcast


# ═════════════════════════════════════════════════════════════════════════════
# GROUP T — incremental byte-offset tail across polls (real appends)
# ═════════════════════════════════════════════════════════════════════════════

class TestGroupTIncrementalTail:

    def test_t1_second_poll_consumes_only_new_record( self, fleet ):
        """poll2 consumes ONLY the appended record (byte-offset advance; no re-consume)."""
        _emit( fleet, "s1", "honored", awaiting="none", persona="A" )
        arb = _make_arbiter( fleet )
        arb._poll_once()
        assert len( arb._acc.snapshot()[ "s1" ] ) == 1
        off1 = arb._offsets[ "s1" ]

        _emit( fleet, "s1", "poked", awaiting="none", persona="A", poke_count=2 )   # a later turn
        arb._poll_once()
        snap = arb._acc.snapshot()[ "s1" ]
        assert len( snap ) == 2                                   # grew by exactly one
        assert snap[ -1 ][ "outcome" ] == "poked"                  # the new record
        assert arb._offsets[ "s1" ] > off1                        # offset advanced past the old bytes

    def test_t2_partial_trailing_line_not_consumed_until_complete( self, fleet ):
        """A mid-write partial last line is NOT consumed; the completed record is read next poll."""
        path = fleet / "s1.jsonl"
        rec1 = json.dumps( { "schema_version": 1, "session_id": "s1", "persona": "A",
                             "ts": BASE_NOW.isoformat(), "outcome": "honored", "poke_count": 1,
                             "cap": 3, "work_owed": False, "awaiting": "none" } )
        path.write_text( rec1 + "\n" + '{"schema_version": 1, "outcome": "po' )      # partial, no newline
        arb = _make_arbiter( fleet )
        arb._poll_once()
        assert len( arb._acc.snapshot()[ "s1" ] ) == 1            # partial line skipped

        rec2 = json.dumps( { "schema_version": 1, "session_id": "s1", "persona": "A",
                             "ts": BASE_NOW.isoformat(), "outcome": "poked", "poke_count": 2,
                             "cap": 3, "work_owed": False, "awaiting": "none" } )
        path.write_text( rec1 + "\n" + rec2 + "\n" )              # the line is now complete
        arb._poll_once()
        snap = arb._acc.snapshot()[ "s1" ]
        assert len( snap ) == 2 and snap[ -1 ][ "outcome" ] == "poked"

    def test_t3_stuck_accumulates_across_polls( self, fleet ):
        """Stuck needs ≥2 cap_reached in the BOUNDED deque — they arrive in separate polls."""
        _emit( fleet, "s1", "cap_reached", work_owed=True, persona="A", poke_count=3 )
        arb = _make_arbiter( fleet )
        arb._poll_once()
        assert _snapshot_row( arb, "s1" )[ "stuck" ] is False     # one episode → not yet stuck

        _emit( fleet, "s1", "cap_reached", work_owed=True, persona="A", poke_count=3 )
        arb._poll_once()
        assert _snapshot_row( arb, "s1" )[ "stuck" ] is True      # the deque retained both → stuck


# ═════════════════════════════════════════════════════════════════════════════
# GROUP TH — multi-poll backoff trajectory with an ADVANCING clock
# (the seam the fixed-clock unit suite structurally cannot reach)
# ═════════════════════════════════════════════════════════════════════════════

class TestGroupTHBackoffTrajectory:

    def test_th1_per_edge_backoff_escalates_across_real_time( self, fleet ):
        """LOCKS the F2 fix: first ping immediate; the FIRST gated gap is schedule[0]=60s,
        then 300s — the corrected 60→300→900→3600 ladder (Rachel's backoff_for_attempt(attempt-1))."""
        _emit( fleet, "s1", "honored", awaiting="peer:Bob", persona="Alice" )
        clk = SteppableClock( BASE_NOW )
        arb = _make_arbiter( fleet, clock=clk )

        arb._poll_once()                                          # T0   → ping #1 (last_ping was None)
        assert len( _pings( arb ) ) == 1

        clk.set_now( BASE_NOW + datetime.timedelta( seconds=59 ) )
        arb._poll_once()                                          # +59  → within the 60s first gap → no ping
        assert len( _pings( arb ) ) == 1

        clk.set_now( BASE_NOW + datetime.timedelta( seconds=60 ) )
        arb._poll_once()                                          # +60  → schedule[0]=60 elapsed → ping #2
        assert len( _pings( arb ) ) == 2

        clk.set_now( BASE_NOW + datetime.timedelta( seconds=60 + 299 ) )
        arb._poll_once()                                          # next gap is 300 → not yet
        assert len( _pings( arb ) ) == 2

        clk.set_now( BASE_NOW + datetime.timedelta( seconds=60 + 300 ) )
        arb._poll_once()                                          # 300 elapsed → ping #3
        assert len( _pings( arb ) ) == 3

    def test_th2_global_cap_rolling_window_reopens( self, fleet ):
        """Global cap halts excess; once the cap window passes, _prune reopens capacity."""
        _emit( fleet, "s1", "honored", awaiting="peer:Bob",  persona="Alice" )
        _emit( fleet, "s2", "honored", awaiting="peer:Cara", persona="Beth" )
        clk = SteppableClock( BASE_NOW )
        arb = _make_arbiter( fleet, clock=clk, ping_global_cap=1, ping_cap_window_seconds=100 )

        s1 = arb._poll_once()                                     # T0 → cap=1 → exactly one of the two fires
        assert s1[ "pings_fired" ] == 1
        assert len( _pings( arb ) ) == 1

        clk.set_now( BASE_NOW + datetime.timedelta( seconds=50 ) )
        arb._poll_once()                                          # within window → still capped → no new ping
        assert len( _pings( arb ) ) == 1

        clk.set_now( BASE_NOW + datetime.timedelta( seconds=150 ) )
        s3 = arb._poll_once()                                     # window passed → prune → capacity reopens
        assert s3[ "pings_fired" ] == 1
        assert len( _pings( arb ) ) == 2                      # the other blocker finally pinged

    def test_th3_clear_on_resume_resets_backoff( self, fleet ):
        """An edge that resumes then re-blocks resets its attempt → the next ping fires IMMEDIATELY."""
        path = fleet / "s1.jsonl"
        _emit( fleet, "s1", "honored", awaiting="peer:Bob", persona="Alice" )
        clk = SteppableClock( BASE_NOW )
        arb = _make_arbiter( fleet, clock=clk )

        arb._poll_once()                                          # ping #1
        assert len( _pings( arb ) ) == 1

        clk.set_now( BASE_NOW + datetime.timedelta( seconds=10 ) )
        arb._poll_once()                                          # within 300 → no ping; edge still tracked
        assert len( _pings( arb ) ) == 1
        assert arb._ledger.tracked_edges()                        # the Bob edge is tracked

        _emit( fleet, "s1", "poked", awaiting="none", persona="Alice", poke_count=2 )   # RESUMED
        clk.set_now( BASE_NOW + datetime.timedelta( seconds=20 ) )
        arb._poll_once()                                          # edge gone → cleared
        assert arb._ledger.tracked_edges() == set()
        assert arb._ping_attempts == { }

        _emit( fleet, "s1", "honored", awaiting="peer:Bob", persona="Alice" )           # RE-BLOCKED
        clk.set_now( BASE_NOW + datetime.timedelta( seconds=30 ) )
        arb._poll_once()                                          # attempt reset → last_ping None → fires now
        assert len( _pings( arb ) ) == 2                      # immediate re-ping after the resume/re-block


# ═════════════════════════════════════════════════════════════════════════════
# GROUP INFER — inferred (heuristic) idle-roster path
# ═════════════════════════════════════════════════════════════════════════════

class TestGroupInferRoster:

    def test_infer1_alive_and_quiet_session_is_inferred_idle( self, fleet ):
        """A session ALIVE but QUIET past the quiet threshold → roster entry 'quiet (inferred)'.

        The window is non-empty because quiet_threshold < alive_threshold (the F3
        invariant Rachel now enforces at construction).
        """
        # last activity 300s ago: quiet ≥ quiet(120) AND alive ≤ alive(600) → inferred
        quiet_ts = BASE_NOW - datetime.timedelta( seconds=300 )
        _emit( fleet, "s-quiet", "poked", work_owed=False, persona="Cara", ts=quiet_ts, poke_count=1 )
        arb = _make_arbiter( fleet, quiet_threshold_seconds=120, alive_threshold_seconds=600 )
        summary = arb._poll_once()
        assert summary[ "roster" ] == 1
        assert any( r[ "persona" ] == "Cara" and r[ "trust_label" ] == "quiet (inferred)"
                    for r in _roster( arb ) )

    def test_infer2_shipped_defaults_keep_inference_reachable( self, fleet ):
        """F3 DEFAULTS-LOCK: with the SHIPPED defaults (no override), an alive+quiet
        session still lands on the roster as inferred — the inference half can never
        again silently go config-dead. Construct WITHOUT threshold args so the real
        defaults (quiet=300 < alive=600) are exercised."""
        # quiet 450s ago: within the shipped window 300 ≤ age < 600 → inferred
        quiet_ts = BASE_NOW - datetime.timedelta( seconds=450 )
        _emit( fleet, "s-def", "poked", work_owed=False, persona="Dee", ts=quiet_ts, poke_count=1 )
        arb = ArbiterConsumerJob(
            commons           = FakeGateway(),
            poll_seconds      = 5,
            manager_recipient = "Tiberius",
            events_dir        = str( fleet ),
            clock             = SteppableClock( BASE_NOW ),
            notify_fn         = lambda *a, **k: None,
        )
        assert arb.quiet_threshold_seconds < arb.alive_threshold_seconds   # F3 invariant holds for defaults
        summary = arb._poll_once()
        # inference reachable under shipped defaults — the alive+quiet session lands on
        # the idle-roster (the #6 roster broadcast that formerly carried the label is
        # dropped; roster==1 is the surviving proof the inference half is alive)
        assert summary[ "roster" ] == 1

    def test_infer3_construction_rejects_config_dead_thresholds( self ):
        """F3 INVARIANT-LOCK: quiet_threshold ≥ alive_threshold is now UN-CONSTRUCTABLE
        (the old config-dead state raises at init instead of silently disabling inference)."""
        with pytest.raises( ValueError ):
            ArbiterConsumerJob(
                commons                 = FakeGateway(),
                poll_seconds            = 5,
                manager_recipient       = "Tiberius",
                alive_threshold_seconds = 600,
                quiet_threshold_seconds = 900,                   # ≥ alive → the dead config
            )


# ═════════════════════════════════════════════════════════════════════════════
# GROUP ISO — the arbiter is READ-ONLY on the event plane; all I/O via the seam
# ═════════════════════════════════════════════════════════════════════════════

class TestGroupISOReadOnly:

    def test_iso1_arbiter_never_mutates_event_files_and_uses_only_the_gateway( self, fleet ):
        """María §7 invariant: the arbiter only READS event files + posts via the gateway —
        it never writes the event plane and never touches a real peer/dir."""
        _emit( fleet, "s1", "honored", awaiting="peer:Bob", persona="Alice" )
        path   = fleet / "s1.jsonl"
        before = path.read_bytes()

        gw  = FakeGateway()
        arb = _make_arbiter( fleet, gateway=gw )
        arb._poll_once()

        assert path.read_bytes() == before                       # event file untouched (read-only plane)
        files_after = sorted( p.name for p in fleet.iterdir() )
        assert files_after == [ "s1.jsonl" ]                     # arbiter wrote NO new file to the fleet dir
        # outbound I/O is now directed DMs only (auto-ping + tap); the #6 roster
        # broadcast is dropped, so NO commons post — all push, no blackboard spam
        assert gw.sent and gw.posts == [ ]

    def test_iso2_full_execute_loop_over_real_events( self, fleet ):
        """The REAL poll LOOP (do_all → _execute) over a real event file — one poll then hard-cap.

        Complements the unit suite's lifecycle tests (which use synthetic events):
        here the loop tails a real emitted file, pings the real blocker, sleeps one
        cadence, and exits cleanly on the hard cap.
        """
        _emit( fleet, "s1", "honored", awaiting="peer:Bob", persona="Alice" )
        # monotonic: start=0, check1=0 (<cap → poll), check2=100 (>=cap → exit)
        clk     = SteppableClock( BASE_NOW, monotonic_seq=[ 0, 0, 100 ] )
        arb     = _make_arbiter( fleet, clock=clk, max_duration_seconds=100 )
        summary = arb.do_all()
        assert "hard-cap" in summary
        assert arb._poll_count == 1
        assert clk.sleeps == [ 5 ]                                # slept one cadence (poll_seconds)
        assert arb._commons.sent[ 0 ][ 0 ] == "Bob"              # the real loop pinged the real blocker
        assert arb.started_at is not None and arb.completed_at is not None

    def test_iso3_cancel_exits_before_any_poll( self, fleet ):
        """Cancellation exits the loop immediately — no poll, no real-peer I/O."""
        gw  = FakeGateway()
        arb = _make_arbiter( fleet, gateway=gw )                  # default clock (unscripted monotonic)
        arb._cancel_requested = True
        summary = arb.do_all()
        assert "cancelled" in summary
        assert arb._poll_count == 0                               # never polled
        assert gw.sent == [ ] and gw.posts == [ ]                # no outbound I/O at all
