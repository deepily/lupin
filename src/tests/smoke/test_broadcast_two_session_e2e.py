"""
Step 9 E2E smoke test for the user-broadcast surface.

Per src/rnd/v0.1.7/2026.05.09-inter-session-commons/03-phase2-user-broadcast-design.md AC12:

> "E2E test `src/tests/smoke/test_broadcast_two_session_e2e.py`: spawn 2 mock
>  listener subprocesses with distinct personas + a Maria-only directive +
>  a default body; assert Maria executes the directive (+ default) and
>  Tiberius executes only the default; assert UI receives 2 acks."

Venue: :7999 AI-discretionary — non-destructive (tempdir for storage),
fast (<10s), no shared external state.

Exercises the full Phase 2 backend integration end-to-end:
  execute_broadcast() pipeline → fanout posts to `broadcasts` topic +
  per-session `action:broadcast_received` notification → mock listener
  subprocesses run `broadcast_handler.handle_broadcast()` → directives parsed +
  injected via inject_fn + acks posted to `broadcast-acks` → parent runs
  `CommonsAckWatcher.tick()` → `commons_broadcast_ack` notifications fired.

Does NOT exercise FastAPI auth or router decorator plumbing — those paths are
covered by `test_commons_router.py` (55 tests) + `test_commons_ac14_registration.py`
(5 tests). This test exercises `execute_broadcast()` directly with DI'd deps
per the design doc's pure-logic-helpers split (AC12: "endpoint integration
tests, smoke tests, and Playwright E2E do NOT contribute to the coverage gate").
"""

import multiprocessing as mp
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import MagicMock

import pytest

from cosa.rest.commons_ack_watcher import CommonsAckWatcher
from cosa.rest.commons_rate_limiter import CommonsBroadcastRateLimiter
from cosa.rest.routers.commons import (
    BroadcastRequestBody,
    execute_broadcast,
)
from lupin_mcp.commons_store import CommonsStore


# ─── Mock listener subprocess (must be module-level for `spawn` context) ────


def _mock_listener_worker(
    commons_root    : str,
    session_id      : str,
    persona         : Dict[ str, Any ],
    inject_log_path : str,
    notification_q  : Any,
    done_q          : Any,
) -> None:
    """
    Spawn-safe mock CC-session listener.

    Each subprocess:
      1. Imports `broadcast_handler` + `CommonsStore` in a fresh interpreter.
      2. Blocks on `notification_q` until the parent pushes the broadcast notification.
      3. Calls `handle_broadcast()` with an `inject_fn` that appends the injected
         text to `inject_log_path` (so the parent can later assert what was
         injected into "tmux" for this persona).
      4. Reports the handler's return dict back via `done_q`.

    `handle_broadcast()` itself posts the per-session ack to the
    `broadcast-acks` reserved topic — no extra plumbing needed in this worker.
    """
    from lupin_mcp.broadcast_handler import handle_broadcast
    from lupin_mcp.commons_store     import CommonsStore

    store = CommonsStore( commons_root )

    def inject_fn( text: str ) -> None:
        with open( inject_log_path, "a", encoding="utf-8" ) as f:
            f.write( text )
            f.write( "\n---INJECT_END---\n" )

    try:
        notif = notification_q.get( timeout=15 )
    except Exception as e:
        done_q.put( { "status": "no-notification", "error": repr( e ) } )
        return

    try:
        result = handle_broadcast(
            notification      = notif,
            local_persona     = persona,
            inject_fn         = inject_fn,
            store             = store,
            sender_session_id = session_id,
        )
        done_q.put( result )
    except Exception as e:
        done_q.put( { "status": "handler-error", "error": repr( e ) } )


# ─── Test fixtures (parent-process helpers) ────────────────────────────────


def _make_bridge_dict( owner_user_id: str, age_seconds: float = 5.0 ) -> Dict[ str, Any ]:
    """
    Build a bridge dict that `filter_and_project_sessions` accepts (recent + same-owner).

    Per 2026-05-14 Option-C migration
    (`src/rnd/v0.1.7/2026.05.14-broadcast-listener-stamps-wrong-user-id.md`),
    scoping is now on `owner_user_id`, not the legacy `user_id` (which carries
    the listener service-account identity). The fixture's parameter name is
    `owner_user_id` to reflect what the filter actually reads.
    """
    now = time.time()
    return {
        "owner_user_id"            : owner_user_id,
        "last_activity_epoch"      : now - age_seconds,
        "conversation_mode_active" : False,
    }


def _make_persona( name: str, icon: str, color: str ) -> Dict[ str, Any ]:
    return { "name": name, "icon": icon, "color": color }


# ─── AC12 step 9 — 2-session E2E ───────────────────────────────────────────


@pytest.mark.timeout( 60 )
def test_step9_two_session_e2e_persona_targeted_broadcast():
    """
    End-to-end: 2 listener subprocesses with distinct personas + a body
    containing a default line + Maria-only directive. Assert:
      (a) execute_broadcast returns HTTP 200 with recipients=2
      (b) `broadcasts` topic has 2 entries with distinct target_session_ids
      (c) Maria's inject log contains default + matched directive
      (d) Tiberius's inject log contains default only (no @Maria line)
      (e) `broadcast-acks` topic has 2 completed acks correlated by broadcast_id
      (f) Maria's ack body_summary contains the directive; Tiberius's does not
      (g) `CommonsAckWatcher.tick()` dispatches 2 `commons_broadcast_ack` pushes
          to the originating user_id with correct payload shape
    """
    ctx     = mp.get_context( "spawn" )
    user_id = "test-user-step9@example.com"

    with tempfile.TemporaryDirectory() as tmp_commons, tempfile.TemporaryDirectory() as tmp_inject:
        # ─── Seed commons storage so reserved topic files exist ─────────────
        CommonsStore( tmp_commons )

        # ─── Spawn 2 mock listener subprocesses ─────────────────────────────
        maria_session_id    = "sess-maria-9aa12345"
        tiberius_session_id = "sess-tiberius-9bb67890"
        maria_persona       = _make_persona( "Maria",    "🌸", "#A040A0" )
        tiberius_persona    = _make_persona( "Tiberius", "🌑", "#3F51B5" )

        maria_inject_log    = os.path.join( tmp_inject, "maria_inject.log" )
        tiberius_inject_log = os.path.join( tmp_inject, "tiberius_inject.log" )

        maria_notif_q    = ctx.Queue()
        tiberius_notif_q = ctx.Queue()
        maria_done_q     = ctx.Queue()
        tiberius_done_q  = ctx.Queue()

        maria_proc = ctx.Process(
            target = _mock_listener_worker,
            args   = ( tmp_commons, maria_session_id, maria_persona, maria_inject_log, maria_notif_q, maria_done_q ),
        )
        tiberius_proc = ctx.Process(
            target = _mock_listener_worker,
            args   = ( tmp_commons, tiberius_session_id, tiberius_persona, tiberius_inject_log, tiberius_notif_q, tiberius_done_q ),
        )
        maria_proc.start()
        tiberius_proc.start()

        # ─── Build endpoint DI scaffolding in parent ────────────────────────
        store        = CommonsStore( tmp_commons )
        rate_limiter = CommonsBroadcastRateLimiter( window_seconds=30.0 )

        # Mock notification queue routes pushes by job_id (= target_sid[:8])
        # into each listener's mp.Queue, mimicking how the real listener daemon
        # is keyed to its session via its sender_id.
        notif_queue = MagicMock()

        def _push_notification( **kwargs ) -> None:
            job_id = kwargs.get( "job_id", "" )
            notif_dict = {
                "title"   : kwargs.get( "title" ),
                "payload" : kwargs.get( "payload", { } ),
            }
            if job_id == maria_session_id[ :8 ]:
                maria_notif_q.put( notif_dict )
            elif job_id == tiberius_session_id[ :8 ]:
                tiberius_notif_q.put( notif_dict )
            else:
                raise AssertionError( f"unexpected job_id during fanout: {job_id!r}" )

        notif_queue.push_notification = _push_notification

        # AckWatcher with capture-mock push_fn (no daemon thread — we drive tick() manually)
        ack_push_fn = MagicMock()
        ack_watcher = CommonsAckWatcher(
            store                  = store,
            push_notification_fn   = ack_push_fn,
            poll_interval_seconds  = 0.05,
            in_flight_ttl_seconds  = 60.0,
        )

        # Bridge fixtures for filter_and_project_sessions
        bridges: Dict[ str, Dict[ str, Any ] ] = {
            f"<bridge:{maria_session_id}>"    : _make_bridge_dict( user_id ),
            f"<bridge:{tiberius_session_id}>" : _make_bridge_dict( user_id ),
        }

        def raw_sessions_fn() -> List[ Tuple[ Any, str, Dict[ str, Any ] ] ]:
            return [
                ( f"<bridge:{maria_session_id}>",    maria_session_id,    maria_persona    ),
                ( f"<bridge:{tiberius_session_id}>", tiberius_session_id, tiberius_persona ),
            ]

        def bridge_loader( bridge_path: Any ) -> Optional[ Dict[ str, Any ] ]:
            return bridges.get( bridge_path )

        def build_sender_id( target_sid: str ) -> str:
            return f"cc:{target_sid}"

        # ─── POST the broadcast (in-process, no FastAPI) ────────────────────
        broadcast_body = (
            "Run the daily smoke check on master.\n"
            "@Maria: also re-baseline the visual snapshots."
        )
        request = BroadcastRequestBody(
            message            = broadcast_body,
            require_ack        = True,
            include_originator = True,
        )

        result = execute_broadcast(
            authenticated_user_id            = user_id,
            body                             = request,
            store                            = store,
            rate_limiter                     = rate_limiter,
            ack_watcher                      = ack_watcher,
            notification_queue               = notif_queue,
            active_session_threshold_seconds = 600.0,
            raw_sessions_fn                  = raw_sessions_fn,
            bridge_loader                    = bridge_loader,
            build_sender_id                  = build_sender_id,
        )

        # ─── (a) endpoint response ──────────────────────────────────────────
        assert result[ "http_status" ]        == 200, f"expected 200, got {result}"
        assert result[ "recipients" ]         == 2,   f"expected 2 recipients, got {result}"
        assert result[ "failed_recipients" ]  == [ ], f"unexpected failures: {result}"
        assert result[ "status" ]             == "queued"
        broadcast_id = result[ "broadcast_id" ]
        assert broadcast_id  # UUIDv4

        # ─── Wait for both listener subprocesses to finish processing ───────
        maria_proc.join( timeout=15 )
        tiberius_proc.join( timeout=15 )
        assert maria_proc.exitcode    == 0, f"maria listener exit code: {maria_proc.exitcode}"
        assert tiberius_proc.exitcode == 0, f"tiberius listener exit code: {tiberius_proc.exitcode}"

        maria_result    = maria_done_q.get( timeout=5 )
        tiberius_result = tiberius_done_q.get( timeout=5 )
        assert maria_result.get( "status" )    == "completed", f"maria handler: {maria_result}"
        assert tiberius_result.get( "status" ) == "completed", f"tiberius handler: {tiberius_result}"
        assert maria_result[ "broadcast_id" ]    == broadcast_id
        assert tiberius_result[ "broadcast_id" ] == broadcast_id

        # ─── (b) `broadcasts` topic — 2 entries, distinct target_session_ids ─
        broadcast_entries = store.read( "broadcasts", limit=100 )
        assert len( broadcast_entries ) == 2, f"expected 2 broadcast entries, got {len( broadcast_entries )}"
        target_sids = sorted( e[ "metadata" ][ "target_session_id" ] for e in broadcast_entries )
        assert target_sids == sorted( [ maria_session_id, tiberius_session_id ] )
        for e in broadcast_entries:
            assert e[ "metadata" ][ "broadcast_id" ]   == broadcast_id
            assert e[ "metadata" ][ "sender_user_id" ] == user_id
            assert e[ "body" ]                          == broadcast_body
            # AC4: pseudo-sid uses hyphen, no `@`
            assert e[ "sender_session_id" ].startswith( "broadcast-" )
            assert "@" not in e[ "sender_session_id" ]
            # AC4: per-recipient persona stamp is the System Broadcast identity
            assert e[ "persona_name" ] == "System Broadcast"
            assert e[ "persona_icon" ] == "📢"

        # ─── (c)(d) inject logs ─────────────────────────────────────────────
        maria_injected    = Path( maria_inject_log    ).read_text() if os.path.exists( maria_inject_log )    else ""
        tiberius_injected = Path( tiberius_inject_log ).read_text() if os.path.exists( tiberius_inject_log ) else ""

        # Both see the <system-reminder> wrapper + USER BROADCAST header + default line
        for name, injected in ( ( "maria", maria_injected ), ( "tiberius", tiberius_injected ) ):
            assert "<system-reminder>"  in injected,  f"{name} missing opening tag: {injected!r}"
            assert "</system-reminder>" in injected,  f"{name} missing closing tag: {injected!r}"
            assert "USER BROADCAST"     in injected,  f"{name} missing USER BROADCAST header"
            assert f"broadcast_id {broadcast_id}" in injected, f"{name} missing broadcast_id"
            assert "Run the daily smoke check on master." in injected, f"{name} missing default line"

        # Maria sees the @Maria directive
        assert "@Maria: also re-baseline the visual snapshots." in maria_injected, \
            f"Maria's inject log missing the directive: {maria_injected!r}"
        # Tiberius does NOT see the @Maria directive
        assert "@Maria" not in tiberius_injected, \
            f"Tiberius's inject log unexpectedly contains the @Maria directive: {tiberius_injected!r}"

        # ─── (e)(f) `broadcast-acks` topic — 2 completed acks with correlation ─
        ack_entries = store.read( "broadcast-acks", limit=100 )
        assert len( ack_entries ) == 2, f"expected 2 ack entries, got {len( ack_entries )}"
        ack_by_session = { e[ "sender_session_id" ]: e for e in ack_entries }
        assert maria_session_id    in ack_by_session
        assert tiberius_session_id in ack_by_session

        for sid, ack in ack_by_session.items():
            assert ack[ "metadata" ][ "broadcast_id" ] == broadcast_id, f"{sid} ack missing broadcast_id correlation"
            assert ack[ "metadata" ][ "status" ]       == "completed",  f"{sid} ack not completed: {ack}"

        # Body summaries differ — Maria's contains the directive, Tiberius's does not.
        maria_summary    = ack_by_session[ maria_session_id    ][ "metadata" ][ "body_summary" ]
        tiberius_summary = ack_by_session[ tiberius_session_id ][ "metadata" ][ "body_summary" ]
        assert "@Maria: also re-baseline the visual snapshots." in maria_summary,    f"maria summary: {maria_summary!r}"
        assert "@Maria"                                          not in tiberius_summary, f"tiberius summary: {tiberius_summary!r}"
        assert "Run the daily smoke check on master."            in tiberius_summary, f"tiberius summary: {tiberius_summary!r}"

        # Persona stamps on the acks reflect the LISTENER's persona, not System Broadcast.
        assert ack_by_session[ maria_session_id    ][ "persona_name" ] == "Maria"
        assert ack_by_session[ maria_session_id    ][ "persona_icon" ] == "🌸"
        assert ack_by_session[ tiberius_session_id ][ "persona_name" ] == "Tiberius"
        assert ack_by_session[ tiberius_session_id ][ "persona_icon" ] == "🌑"

        # ─── (g) AckWatcher.tick() dispatches 2 `commons_broadcast_ack` pushes ─
        # The broadcast is already registered in `ack_watcher` because
        # `execute_broadcast()` registered it (require_ack=True). One tick should
        # consume both acks since `_last_seen_ts` starts at None.
        dispatched = ack_watcher.tick()
        assert dispatched == 2, f"expected 2 acks dispatched, got {dispatched}"
        assert ack_push_fn.call_count == 2

        pushed_types    = [ call.kwargs[ "type" ]    for call in ack_push_fn.call_args_list ]
        pushed_user_ids = [ call.kwargs[ "user_id" ] for call in ack_push_fn.call_args_list ]
        pushed_payloads = [ call.kwargs[ "payload" ] for call in ack_push_fn.call_args_list ]

        assert all( t == "commons_broadcast_ack" for t in pushed_types ),     f"pushed types: {pushed_types}"
        assert all( uid == user_id              for uid in pushed_user_ids ), f"pushed user_ids: {pushed_user_ids}"

        pushed_session_ids = sorted( p[ "session_id" ] for p in pushed_payloads )
        assert pushed_session_ids == sorted( [ maria_session_id, tiberius_session_id ] )

        for p in pushed_payloads:
            assert p[ "broadcast_id" ] == broadcast_id
            assert p[ "status" ]       == "completed"
            assert p[ "persona_name" ] in ( "Maria", "Tiberius" )
            # body_summary travels through the payload so the UI can render per-session detail
            assert isinstance( p[ "body_summary" ], str )

        # ─── Suspenders: AckWatcher's _last_seen_ts is now past both entries; a
        # second tick() should dispatch 0 (no replay) ───────────────────────
        assert ack_watcher.tick() == 0, "second tick unexpectedly re-dispatched acks (last_seen_ts cursor failed)"


if __name__ == "__main__":
    # Standalone runner per the project's per-module quick_smoke_test convention.
    # Prints tabular pass/fail.
    print( "Running Phase 2 step 9 — 2-session E2E broadcast smoke test..." )
    tests = [
        ( "test_step9_two_session_e2e_persona_targeted_broadcast", test_step9_two_session_e2e_persona_targeted_broadcast ),
    ]
    rows = [ ]
    for name, fn in tests:
        try:
            fn()
            rows.append( ( name, "PASS" ) )
        except Exception as e:
            rows.append( ( name, f"FAIL ({type( e ).__name__}: {e})" ) )

    print( "\nResults:" )
    print( f"{'TEST':<70} {'STATUS'}" )
    print( "-" * 90 )
    for name, status in rows:
        print( f"{name:<70} {status}" )

    failed = [ r for r in rows if r[ 1 ] != "PASS" ]
    if failed:
        raise SystemExit( 1 )
