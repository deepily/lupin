"""
Coverage-completion unit tests for
src/lupin_cli/claude_code/hooks/lib/cc_notification_listener.py.

Drives the legacy listener module to 100% lines + branches under the Lupin-wide
100% coverage mandate. The pre-existing suites
(test_cc_notification_listener_injection_mutex / _owner_stamp /
test_cc_listener_broadcast_roster + the session-bridge / speakerphone-wrap
tests) already exercise _inject_via_tmux, _handle_broadcast_received, the
owner-stamp happy/no-creds/no-user-id paths, and the tmux-injection mutex; this
module fills the untested remainder:

    - logging plumbing  (_setup_logging / _write_central / _log / _log_central)
    - event routing      (_handle_event all branches)
    - peer-DM delivery   (_deliver_peer_dm / _recipient_is_injectable / _handle_peer_dm)
    - action routing     (_handle_action / _inject_exit_conversation_reminder /
                          _update_session_topic)
    - tmux resolution    (_resolve_tmux_session bridge-lookup + error branches)
    - gist auto-response (_send_gist_response)
    - buffering          (_buffer_message)
    - bridge stamping    (_stamp_user_id_on_bridge + owner-stamp error branches)
    - shutdown stats     (_print_stats)
    - restart loop       (run)
    - CLI surface        (parse_args / _resolve_credentials / main / signal handler)

Every collaborator is patched at its SOURCE module because the listener imports
most of them lazily inside method bodies. All tests are hermetic — no real
network, no real tmux, no state mutation outside tmp_path.
"""

import asyncio
import json

import pytest
from argparse import Namespace
from unittest.mock import AsyncMock, MagicMock, patch

import cosa.agents.utils.proxy_agents.base_listener as base_listener_module
import lupin_cli.claude_code.hooks.lib.cc_notification_listener as listener_module
from lupin_cli.claude_code.hooks.lib.cc_notification_listener import CCNotificationListener


# ═════════════════════════════════════════════════════════════════════════════
# Helpers / fixtures
# ═════════════════════════════════════════════════════════════════════════════

def _make_listener( session_id_hash="abc12345", tmux_session="test tmux",
                    debug=False, verbose=False, **kwargs ):
    """Listener with explicit tmux override — no bridge lookup, no WS connect."""
    return CCNotificationListener(
        email           = "service@lupin.deepily.ai",
        password        = "service-pass",
        session_id_hash = session_id_hash,
        tmux_session    = tmux_session,
        host            = "localhost",
        port            = 7999,
        debug           = debug,
        verbose         = verbose,
        **kwargs
    )


@pytest.fixture
def listener():
    return _make_listener()


def _login_cm( payload ):
    """A fake urlopen() context manager whose .read() returns json(payload)."""
    resp = MagicMock()
    resp.read.return_value = json.dumps( payload ).encode( "utf-8" )
    cm = MagicMock()
    cm.__enter__ = MagicMock( return_value=resp )
    cm.__exit__  = MagicMock( return_value=False )
    return cm


# ═════════════════════════════════════════════════════════════════════════════
# Logging plumbing
# ═════════════════════════════════════════════════════════════════════════════

class TestLoggingPlumbing:

    def test_setup_logging_opens_both_files( self, tmp_path ):
        l = _make_listener(
            log_file_path        = str( tmp_path / "session.log" ),
            centralized_log_path = str( tmp_path / "central.log" ),
        )
        l._setup_logging()
        assert l._log_file is not None
        assert l._centralized_log is not None
        l._log_file.close()
        l._centralized_log.close()

    def test_setup_logging_centralized_open_failure_is_swallowed( self, tmp_path ):
        # Point the centralized log under an existing FILE so mkdir(parents=True)
        # raises NotADirectoryError → _centralized_log stays None.
        blocker = tmp_path / "blocker"
        blocker.write_text( "x" )
        l = _make_listener( centralized_log_path = str( blocker / "sub" / "central.log" ) )
        l._setup_logging()
        assert l._centralized_log is None

    def test_write_central_writes_when_open( self, listener ):
        listener._centralized_log = MagicMock()
        listener._write_central( "hello" )
        listener._centralized_log.write.assert_called_once_with( "hello\n" )
        listener._centralized_log.flush.assert_called_once()

    def test_write_central_swallows_write_error( self, listener ):
        listener._centralized_log = MagicMock()
        listener._centralized_log.write.side_effect = OSError( "disk full" )
        # Must not raise
        listener._write_central( "hello" )

    def test_write_central_noop_when_closed( self, listener ):
        listener._centralized_log = None
        listener._write_central( "hello" )  # no-op, no raise

    def test_log_writes_to_logfile( self, listener, capsys ):
        listener._log_file       = MagicMock()
        listener._centralized_log = None
        listener._log( "a message" )
        listener._log_file.write.assert_called_once_with( "a message\n" )
        listener._log_file.flush.assert_called_once()

    def test_log_swallows_logfile_error( self, listener ):
        listener._log_file       = MagicMock()
        listener._log_file.write.side_effect = OSError( "io" )
        listener._centralized_log = None
        listener._log( "a message" )  # no raise

    def test_log_central_writes_marker( self, listener ):
        listener._centralized_log = MagicMock()
        listener._log_central( "=== MARKER ===" )
        assert listener._centralized_log.write.called


# ═════════════════════════════════════════════════════════════════════════════
# _handle_event routing
# ═════════════════════════════════════════════════════════════════════════════

class TestHandleEvent:

    def _run( self, listener, event_type, event_data ):
        asyncio.run( listener._handle_event( event_type, event_data ) )

    def test_ignores_non_matching_event_verbose( self, capsys ):
        l = _make_listener( verbose=True )
        l._log = MagicMock()
        self._run( l, "some_other_event", {} )
        assert any( "Ignoring event type" in str( c ) for c in l._log.call_args_list )

    def test_ignores_non_matching_event_quiet( self, listener ):
        listener._log = MagicMock()
        self._run( listener, "some_other_event", {} )
        # verbose False → no "Ignoring" log emitted
        assert not any( "Ignoring event type" in str( c ) for c in listener._log.call_args_list )

    def test_match_injects_and_sends_gist( self, listener ):
        listener.debug = True
        listener._inject_via_tmux  = MagicMock()
        listener._send_gist_response = MagicMock()
        notif = { "type": "user_initiated_message", "job_id": "abc12345", "message": "do the thing" }
        self._run( listener, "notification_queue_update", { "notification": notif } )
        listener._inject_via_tmux.assert_called_once_with( "do the thing" )
        listener._send_gist_response.assert_called_once_with( notif )

    def test_match_empty_message_skips_inject_still_gist( self, listener ):
        listener._inject_via_tmux  = MagicMock()
        listener._send_gist_response = MagicMock()
        notif = { "type": "user_initiated_message", "job_id": "abc12345", "message": "   " }
        self._run( listener, "notification_queue_update", { "notification": notif } )
        listener._inject_via_tmux.assert_not_called()
        listener._send_gist_response.assert_called_once()

    def test_action_title_routes_to_handle_action( self, listener ):
        listener._handle_action = MagicMock()
        notif = { "title": "action:set_session_topic", "job_id": "abc12345", "message": "Topic" }
        self._run( listener, "notification_queue_update", { "notification": notif } )
        listener._handle_action.assert_called_once_with( "set_session_topic", notif )

    def test_skips_non_user_initiated_type_debug( self, listener ):
        listener.debug = True
        listener._log = MagicMock()
        notif = { "type": "something_else", "job_id": "abc12345" }
        self._run( listener, "notification_queue_update", { "notification": notif } )
        assert any( "not user_initiated_message" in str( c ) for c in listener._log.call_args_list )

    def test_skips_non_user_initiated_type_quiet( self, listener ):
        # debug False → the 267->269 branch: no debug log, straight to return
        listener.debug = False
        listener._log = MagicMock()
        listener._inject_via_tmux = MagicMock()
        notif = { "type": "something_else", "job_id": "abc12345" }
        self._run( listener, "notification_queue_update", { "notification": notif } )
        listener._inject_via_tmux.assert_not_called()
        assert not any( "not user_initiated_message" in str( c ) for c in listener._log.call_args_list )

    def test_skips_unaccepted_job_id_debug( self, listener ):
        listener.debug = True
        listener._log = MagicMock()
        notif = { "type": "user_initiated_message", "job_id": "ZZZZZZZZ" }
        self._run( listener, "notification_queue_update", { "notification": notif } )
        assert any( "not in" in str( c ) for c in listener._log.call_args_list )

    def test_ai_to_ai_routes_to_deliver_peer_dm( self, listener ):
        listener._deliver_peer_dm = MagicMock()
        notif = {
            "type": "user_initiated_message", "job_id": "abc12345",
            "direction": "ai_to_ai", "message": "peer body",
        }
        self._run( listener, "notification_queue_update", { "notification": notif } )
        listener._deliver_peer_dm.assert_called_once_with( notif )


# ═════════════════════════════════════════════════════════════════════════════
# _deliver_peer_dm  +  _recipient_is_injectable
# ═════════════════════════════════════════════════════════════════════════════

class TestDeliverPeerDm:

    def test_idle_recipient_uses_tmux_wake( self, listener ):
        listener._recipient_is_injectable = MagicMock( return_value=True )
        listener._handle_peer_dm    = MagicMock()
        listener._buffer_message    = MagicMock()
        listener._deliver_peer_dm( { "message": "x" } )
        listener._handle_peer_dm.assert_called_once()
        listener._buffer_message.assert_not_called()

    def test_active_recipient_buffers( self, listener ):
        listener._recipient_is_injectable = MagicMock( return_value=False )
        listener._handle_peer_dm    = MagicMock()
        listener._buffer_message    = MagicMock()
        listener._deliver_peer_dm( { "message": "x" } )
        listener._buffer_message.assert_called_once()
        listener._handle_peer_dm.assert_not_called()


# ── pane-idle probe (bug d1bb1456) ──────────────────────────────────────────────
#
# The fix REPLACES the heartbeat-outcome heuristic with a bounded, fail-open tmux
# PANE-IDLE PROBE. The prior heuristic returned False (→ buffer) for a parked pane
# whose last outcome was None (only idle_prompt beacons) or "poked" — stranding the
# DM (the DM-wake gap). These are the repro cases from the triage doc:
#   A: parked, no qualifying outcome (None)   — pre-fix BUFFER, must now INJECT
#   B: parked, idle outcome                   — inject (unchanged)
#   C: last outcome "poked", re-parked        — pre-fix BUFFER, must now INJECT
#   D: honored hold                           — inject (unchanged)
# Post-fix ALL FOUR wake when the PANE is observably idle (the outcome log is no
# longer consulted); a genuinely BUSY / DIALOG pane never injects.

_DIVIDER = "─" * 128        # the real prompt divider is ~128 wide; IDLE_PROMPT_DIVIDER is 40

def _idle_capture( queued="" ):
    """A normal idle prompt: input-box divider chrome, no busy/dialog sentinels."""
    return ( f"{_DIVIDER}\n❯ {queued}\n{_DIVIDER}\n"
             "  ⏵⏵ auto mode on (shift+tab to cycle)\n" )

def _busy_capture():
    """A running turn: the status line carries the 'esc to interrupt' affordance."""
    return ( f"{_DIVIDER}\n❯ Press up to edit queued messages\n{_DIVIDER}\n"
             "  ⏵⏵ auto mode on (shift+tab to cycle) · esc to interrupt · ← for agents\n" )

def _dialog_capture():
    """A permission/AskUserQuestion modal — NO 'esc to interrupt', divider present,
    so it defeats naive absence-logic; only the dialog guard catches it."""
    return ( f"{_DIVIDER}\nDo you want to proceed?\n❯ 1. Yes\n"
             "  2. No, and tell Claude what to do differently\n" )


class TestClassifyCaptureIdle:
    """PURE classifier — the fail-closed-toward-buffer discriminator."""

    def test_idle_prompt_is_idle( self ):
        assert CCNotificationListener._classify_capture_idle( _idle_capture() ) is True

    def test_busy_sentinel_is_not_idle( self ):
        # Mr. Radio hardening: a running turn must NEVER be injected.
        assert CCNotificationListener._classify_capture_idle( _busy_capture() ) is False

    def test_dialog_sentinel_is_not_idle( self ):
        # Mr. Radio hardening #2: a permission/AskUserQuestion modal → buffer, even
        # though it shows no 'esc to interrupt' and DOES carry the divider chrome.
        assert CCNotificationListener._classify_capture_idle( _dialog_capture() ) is False

    def test_absence_of_busy_without_idle_chrome_is_not_idle( self ):
        # Mr. Radio hardening #1: ABSENCE ≠ IDLE — no busy/dialog sentinel but also
        # no positive idle-prompt divider (unknown/blank state) → NOT idle → buffer.
        assert CCNotificationListener._classify_capture_idle(
            "just scrollback, no structural prompt chrome here\n" ) is False

    def test_none_capture_is_not_idle( self ):
        assert CCNotificationListener._classify_capture_idle( None ) is False

    def test_empty_capture_is_not_idle( self ):
        assert CCNotificationListener._classify_capture_idle( "" ) is False


class TestCapturePane:
    """Bounded, total tmux capture-pane wrapper — all fail-open→None branches."""

    def test_clean_capture_returns_text( self, listener ):
        proc = MagicMock( returncode=0, stdout=_idle_capture() )
        with patch.object( listener_module.subprocess, "run", return_value=proc ):
            assert listener._capture_pane( "test tmux" ) == _idle_capture()

    def test_nonzero_rc_returns_none( self, listener ):
        listener._log = MagicMock()
        proc = MagicMock( returncode=1, stdout="" )
        with patch.object( listener_module.subprocess, "run", return_value=proc ):
            assert listener._capture_pane( "test tmux" ) is None

    def test_empty_stdout_returns_none( self, listener ):
        proc = MagicMock( returncode=0, stdout="   \n  " )
        with patch.object( listener_module.subprocess, "run", return_value=proc ):
            assert listener._capture_pane( "test tmux" ) is None

    def test_timeout_returns_none( self, listener ):
        listener._log = MagicMock()
        with patch.object( listener_module.subprocess, "run",
                           side_effect=listener_module.subprocess.TimeoutExpired( "tmux", 2 ) ):
            assert listener._capture_pane( "test tmux" ) is None
        assert any( "pane-idle probe capture failed" in str( c ) for c in listener._log.call_args_list )

    def test_oserror_returns_none( self, listener ):
        listener._log = MagicMock()
        with patch.object( listener_module.subprocess, "run", side_effect=OSError( "no tmux" ) ):
            assert listener._capture_pane( "test tmux" ) is None


class TestPaneIsIdleAtPrompt:
    """Probe orchestration — session resolution + the double-capture race guard."""

    def test_no_tmux_session_is_not_injectable( self, listener ):
        # Can't probe → fail-open to buffer.
        with patch.object( listener, "_resolve_tmux_session", return_value=None ):
            assert listener._pane_is_idle_at_prompt() is False

    def test_both_captures_idle_is_injectable( self, listener ):
        with patch.object( listener, "_resolve_tmux_session", return_value="t" ), \
             patch.object( listener, "_capture_pane", side_effect=[ _idle_capture(), _idle_capture() ] ), \
             patch.object( listener_module.time, "sleep" ) as sleep:
            assert listener._pane_is_idle_at_prompt() is True
        sleep.assert_called_once()          # the ~300ms recheck gap actually elapses

    def test_first_capture_busy_short_circuits_no_recheck( self, listener ):
        # Busy on the first read → False immediately, no second capture / sleep.
        cap = MagicMock( return_value=_busy_capture() )
        with patch.object( listener, "_resolve_tmux_session", return_value="t" ), \
             patch.object( listener, "_capture_pane", cap ), \
             patch.object( listener_module.time, "sleep" ) as sleep:
            assert listener._pane_is_idle_at_prompt() is False
        assert cap.call_count == 1
        sleep.assert_not_called()

    def test_transition_race_second_capture_busy_is_not_injectable( self, listener ):
        # Hardening #1: idle-then-busy across the ~300ms gap (a turn starting mid-
        # probe) → NOT injectable. The single-capture version would false-inject.
        with patch.object( listener, "_resolve_tmux_session", return_value="t" ), \
             patch.object( listener, "_capture_pane", side_effect=[ _idle_capture(), _busy_capture() ] ), \
             patch.object( listener_module.time, "sleep" ):
            assert listener._pane_is_idle_at_prompt() is False


class TestRecipientIsInjectableProbe:
    """_recipient_is_injectable delegates to the probe; the d1bb1456 regression anchor."""

    def test_delegates_to_probe( self, listener ):
        with patch.object( listener, "_pane_is_idle_at_prompt", return_value=True ) as p:
            assert listener._recipient_is_injectable() is True
        p.assert_called_once()

    def test_parked_pane_wakes_regardless_of_heartbeat_outcome( self, listener ):
        # THE d1bb1456 FIX (cases A + C flip buffer→inject): a parked pane whose
        # heartbeat last-outcome was None (case A) or "poked" (case C) — which the
        # OLD heuristic buffered — now WAKES, because the idle PANE state alone
        # decides. We assert the probe consults the PANE, not the outcome log:
        # last_emitted_outcome is patched to raise, proving it is never read.
        with patch.object( listener, "_resolve_tmux_session", return_value="t" ), \
             patch.object( listener, "_capture_pane", side_effect=[ _idle_capture(), _idle_capture() ] ), \
             patch.object( listener_module.time, "sleep" ), \
             patch( "lupin_cli.claude_code.hooks.lib.heartbeat_events.last_emitted_outcome",
                    side_effect=AssertionError( "outcome log must not be consulted post-fix" ) ):
            assert listener._recipient_is_injectable() is True

    def test_busy_pane_buffers_regardless_of_outcome( self, listener ):
        # The mid-turn guard: a busy pane never injects even if the old heuristic
        # would have (e.g. a stale 'idle'/'honored' outcome on record).
        with patch.object( listener, "_resolve_tmux_session", return_value="t" ), \
             patch.object( listener, "_capture_pane", return_value=_busy_capture() ), \
             patch.object( listener_module.time, "sleep" ):
            assert listener._recipient_is_injectable() is False


class TestPaneProbeSentinelsDocumented:
    """Version-coupling pin (Mr. Radio hardening #3): these sentinels are strings the
    Claude Code CLI paints. A CLI UI change that alters them will fail THIS test —
    the deliberate tripwire — and, at runtime, degrade safely to BUFFER (an
    unrecognised status line fails the positive-idle check → not-injectable)."""

    def test_busy_sentinel_pinned( self ):
        assert listener_module.BUSY_STATUS_SENTINELS == ( "esc to interrupt", )

    def test_idle_divider_is_a_long_horizontal_rule( self ):
        assert listener_module.IDLE_PROMPT_DIVIDER == "─" * 40

    def test_dialog_sentinels_cover_permission_and_question_modals( self ):
        for expected in ( "Do you want to proceed", "No, and tell Claude", "❯ 1." ):
            assert expected in listener_module.DIALOG_SENTINELS

    def test_recheck_gap_is_subsecond( self ):
        assert 0 < listener_module.PANE_PROBE_RECHECK_SECONDS < 1


# ═════════════════════════════════════════════════════════════════════════════
# _handle_peer_dm
# ═════════════════════════════════════════════════════════════════════════════

class TestHandlePeerDm:

    def test_empty_body_skips( self, listener ):
        listener._log = MagicMock()
        listener._inject_via_tmux = MagicMock()
        listener._handle_peer_dm( { "message": "  " } )
        listener._inject_via_tmux.assert_not_called()
        assert any( "peer DM missing body" in str( c ) for c in listener._log.call_args_list )

    def test_happy_injects_verbatim( self, listener ):
        listener._inject_via_tmux = MagicMock()
        with patch(
            "lupin_cli.claude_code.hooks.lib.hook_common.build_peer_dm_reminder",
            return_value="WRAPPED REMINDER",
        ):
            listener._handle_peer_dm( {
                "message": "hi there", "sender_persona": "tiberius",
                "sender_icon": "🦁", "id": "m1", "thread_id": "t1",
            } )
        listener._inject_via_tmux.assert_called_once_with( "WRAPPED REMINDER", wrap=False )

    def test_inject_failure_is_logged( self, listener ):
        listener._log = MagicMock()
        listener._inject_via_tmux = MagicMock( side_effect=OSError( "tmux gone" ) )
        with patch(
            "lupin_cli.claude_code.hooks.lib.hook_common.build_peer_dm_reminder",
            return_value="WRAPPED",
        ):
            listener._handle_peer_dm( { "message": "hi" } )
        assert any( "peer DM inject failed" in str( c ) for c in listener._log.call_args_list )


# ═════════════════════════════════════════════════════════════════════════════
# _handle_action  +  _inject_exit_conversation_reminder
# ═════════════════════════════════════════════════════════════════════════════

class TestHandleAction:

    def test_set_session_topic_with_topic( self, listener ):
        listener._update_session_topic = MagicMock()
        listener._handle_action( "set_session_topic", { "message": "  New Topic  " } )
        listener._update_session_topic.assert_called_once_with( "New Topic" )

    def test_set_session_topic_empty_skips( self, listener ):
        listener._update_session_topic = MagicMock()
        listener._handle_action( "set_session_topic", { "message": "   " } )
        listener._update_session_topic.assert_not_called()

    def test_disable_speakerphone_routes( self, listener ):
        listener._inject_exit_conversation_reminder = MagicMock()
        listener._handle_action( "disable_speakerphone", {} )
        listener._inject_exit_conversation_reminder.assert_called_once()

    def test_broadcast_received_routes( self, listener ):
        listener._handle_broadcast_received = MagicMock()
        notif = { "message": "hey all" }
        listener._handle_action( "broadcast_received", notif )
        listener._handle_broadcast_received.assert_called_once_with( notif )

    def test_unknown_action_logged( self, listener ):
        listener._log = MagicMock()
        listener._handle_action( "made_up_action", {} )
        assert any( "Unknown action" in str( c ) for c in listener._log.call_args_list )


class TestInjectExitConversationReminder:

    def test_happy_injects_verbatim( self, listener ):
        listener._inject_via_tmux = MagicMock()
        with patch(
            "lupin_cli.claude_code.hooks.lib.hook_common.speakerphone_exit_reminder",
            return_value="EXIT REMINDER",
        ), patch( "cosa.utils.util.get_tts_interaction_mode", return_value="chorus" ):
            listener._inject_exit_conversation_reminder()
        listener._inject_via_tmux.assert_called_once_with( "EXIT REMINDER", wrap=False )

    def test_build_failure_logged_no_inject( self, listener ):
        listener._log = MagicMock()
        listener._inject_via_tmux = MagicMock()
        with patch(
            "lupin_cli.claude_code.hooks.lib.hook_common.speakerphone_exit_reminder",
            side_effect=RuntimeError( "import boom" ),
        ):
            listener._inject_exit_conversation_reminder()
        listener._inject_via_tmux.assert_not_called()
        assert any( "speakerphone_exit_reminder" in str( c ) for c in listener._log.call_args_list )


# ═════════════════════════════════════════════════════════════════════════════
# _update_session_topic
# ═════════════════════════════════════════════════════════════════════════════

class TestUpdateSessionTopic:

    def test_no_bridge_path_logs( self, listener ):
        listener._log = MagicMock()
        with patch(
            "lupin_cli.claude_code.hooks.lib.session_bridge.get_session_metadata",
            return_value={},
        ):
            listener._update_session_topic( "Topic" )
        assert any( "No bridge path" in str( c ) for c in listener._log.call_args_list )

    def test_happy_writes_topic( self, listener, tmp_path ):
        bridge = tmp_path / "bridge.json"
        bridge.write_text( json.dumps( { "session_id": "abc12345" } ) )
        with patch(
            "lupin_cli.claude_code.hooks.lib.session_bridge.get_session_metadata",
            return_value={ "_bridge_path": str( bridge ) },
        ):
            listener._update_session_topic( "My New Topic" )
        data = json.loads( bridge.read_text() )
        assert data[ "session_topic" ] == "My New Topic"

    def test_write_error_logged( self, listener, tmp_path ):
        listener._log = MagicMock()
        missing = tmp_path / "does-not-exist.json"
        with patch(
            "lupin_cli.claude_code.hooks.lib.session_bridge.get_session_metadata",
            return_value={ "_bridge_path": str( missing ) },
        ):
            listener._update_session_topic( "Topic" )
        assert any( "Failed to set session topic" in str( c ) for c in listener._log.call_args_list )


# ═════════════════════════════════════════════════════════════════════════════
# _resolve_tmux_session  (bridge-lookup + error branches)
# ═════════════════════════════════════════════════════════════════════════════

class TestResolveTmuxSession:

    def test_bridge_lookup_success_and_cache( self ):
        l = _make_listener( tmux_session=None )  # force bridge lookup
        with patch(
            "lupin_cli.claude_code.hooks.lib.session_bridge.find_session_by_id",
            return_value={ "tmux_session": "resolved pane" },
        ) as mock_find:
            assert l._resolve_tmux_session() == "resolved pane"
            # cached → second call does NOT re-query the bridge
            assert l._resolve_tmux_session() == "resolved pane"
        mock_find.assert_called_once()

    def test_bridge_lookup_no_tmux_returns_none( self ):
        l = _make_listener( tmux_session=None )
        with patch(
            "lupin_cli.claude_code.hooks.lib.session_bridge.find_session_by_id",
            return_value={ "other": "x" },
        ):
            assert l._resolve_tmux_session() is None

    def test_bridge_lookup_error_logged_returns_none( self ):
        l = _make_listener( tmux_session=None )
        l._log = MagicMock()
        with patch(
            "lupin_cli.claude_code.hooks.lib.session_bridge.find_session_by_id",
            side_effect=RuntimeError( "bridge boom" ),
        ):
            assert l._resolve_tmux_session() is None
        assert any( "tmux session lookup failed" in str( c ) for c in l._log.call_args_list )


# ═════════════════════════════════════════════════════════════════════════════
# _send_gist_response
# ═════════════════════════════════════════════════════════════════════════════

class TestSendGistResponse:

    def test_empty_text_returns( self, listener ):
        listener._log = MagicMock()
        listener._send_gist_response( { "message": "   " } )
        # nothing logged beyond no-op (no gist sent)
        assert not any( "Gist response sent" in str( c ) for c in listener._log.call_args_list )

    def test_no_valid_email_returns( self, listener ):
        listener._log = MagicMock()
        listener._send_gist_response( { "message": "real text", "sender_id": "not-an-email" } )
        assert any( "No valid sender_id email" in str( c ) for c in listener._log.call_args_list )

    def _patch_notify( self, sender_id="claude.code@lupin.deepily.ai#abc12345" ):
        """Patch the notification-send collaborators; return the notify mock."""
        models = MagicMock()
        notify_mock = MagicMock()
        return patch.multiple(
            "lupin_cli.notifications.notification_models",
            AsyncNotificationRequest = MagicMock(),
            NotificationType         = MagicMock(),
            NotificationPriority     = MagicMock(),
        ), patch(
            "lupin_cli.notifications.notify_user_async.notify_user_async", notify_mock
        ), patch.object(
            listener_module, "build_sender_id_for_cc", return_value=sender_id
        ), notify_mock

    def test_gister_success_sends_notification( self, listener ):
        listener._log = MagicMock()
        gister_inst = MagicMock()
        gister_inst.get_gist.return_value = "short gist"
        models_patch, notify_patch, _sender_patch, notify_mock = self._patch_notify()
        with patch( "cosa.memory.gister.Gister", return_value=gister_inst ), \
             models_patch, notify_patch, _sender_patch:
            listener._send_gist_response( { "message": "the full message text", "sender_id": "user@x.com" } )
        notify_mock.assert_called_once()
        assert any( "Gist response sent" in str( c ) for c in listener._log.call_args_list )

    def test_gister_failure_falls_back_to_first_words( self, listener ):
        listener._log = MagicMock()
        models_patch, notify_patch, _sender_patch, notify_mock = self._patch_notify(
            sender_id=None  # exercises the `or f"..."` fallback branch
        )
        with patch( "cosa.memory.gister.Gister", side_effect=RuntimeError( "gister down" ) ), \
             models_patch, notify_patch, _sender_patch:
            listener._send_gist_response( {
                "message": "one two three four five six seven", "sender_id": "user@x.com",
            } )
        notify_mock.assert_called_once()
        assert any( "Gister failed" in str( c ) for c in listener._log.call_args_list )

    def test_notify_failure_is_logged( self, listener ):
        listener._log = MagicMock()
        gister_inst = MagicMock()
        gister_inst.get_gist.return_value = "gist"
        notify_mock = MagicMock( side_effect=RuntimeError( "notify boom" ) )
        with patch( "cosa.memory.gister.Gister", return_value=gister_inst ), patch.multiple(
            "lupin_cli.notifications.notification_models",
            AsyncNotificationRequest = MagicMock(),
            NotificationType         = MagicMock(),
            NotificationPriority     = MagicMock(),
        ), patch(
            "lupin_cli.notifications.notify_user_async.notify_user_async", notify_mock
        ), patch.object(
            listener_module, "build_sender_id_for_cc", return_value="sender#abc"
        ):
            listener._send_gist_response( { "message": "text here", "sender_id": "user@x.com" } )
        assert any( "Failed to send gist response" in str( c ) for c in listener._log.call_args_list )


# ═════════════════════════════════════════════════════════════════════════════
# _buffer_message
# ═════════════════════════════════════════════════════════════════════════════

class TestBufferMessage:

    def test_happy_appends_jsonl( self, tmp_path ):
        buf = tmp_path / "sub" / "cc-buffer.jsonl"
        l = _make_listener( buffer_path=str( buf ) )
        l._log = MagicMock()
        l._buffer_message( {
            "message": "hello world", "priority": "high", "job_id": "abc12345",
            "sender_id": "x@y.com", "id": "n1", "direction": "human_to_ai",
        } )
        lines = buf.read_text().strip().splitlines()
        assert len( lines ) == 1
        entry = json.loads( lines[0] )
        assert entry[ "message" ] == "hello world"
        assert entry[ "job_id" ]  == "abc12345"
        assert l._message_count == 1

    def test_buffer_error_is_logged( self, tmp_path ):
        # buffer_path parent is UNDER an existing file → mkdir(parents=True) raises.
        blocker = tmp_path / "file"
        blocker.write_text( "x" )
        l = _make_listener( buffer_path=str( blocker / "sub" / "buf.jsonl" ) )
        l._log = MagicMock()
        l._buffer_message( { "message": "x" } )
        assert any( "ERROR buffering message" in str( c ) for c in l._log.call_args_list )


# ═════════════════════════════════════════════════════════════════════════════
# _stamp_user_id_on_bridge  (self / service-account identity)
# ═════════════════════════════════════════════════════════════════════════════

class TestStampUserIdOnBridge:

    def test_happy_stamps( self, listener ):
        listener._log = MagicMock()
        with patch( "urllib.request.urlopen", return_value=_login_cm( { "user": { "id": "u-1" } } ) ), \
             patch( "lupin_cli.claude_code.hooks.lib.session_bridge.set_user_id", return_value=True ) as ms:
            listener._stamp_user_id_on_bridge()
        ms.assert_called_once_with( "abc12345", "u-1" )

    def test_no_user_id_skips( self, listener ):
        listener._log = MagicMock()
        with patch( "urllib.request.urlopen", return_value=_login_cm( {} ) ), \
             patch( "lupin_cli.claude_code.hooks.lib.session_bridge.set_user_id" ) as ms:
            listener._stamp_user_id_on_bridge()
        ms.assert_not_called()
        assert any( "no user.id" in str( c ) for c in listener._log.call_args_list )

    def test_set_user_id_false_logs_not_found( self, listener ):
        listener._log = MagicMock()
        with patch( "urllib.request.urlopen", return_value=_login_cm( { "user": { "id": "u-1" } } ) ), \
             patch( "lupin_cli.claude_code.hooks.lib.session_bridge.set_user_id", return_value=False ):
            listener._stamp_user_id_on_bridge()
        assert any( "bridge not found" in str( c ) for c in listener._log.call_args_list )

    def test_urlerror_silent_fallback( self, listener ):
        import urllib.error
        listener._log = MagicMock()
        with patch( "urllib.request.urlopen", side_effect=urllib.error.URLError( "down" ) ):
            listener._stamp_user_id_on_bridge()
        assert any( "user_id stamp failed" in str( c ) for c in listener._log.call_args_list )

    def test_unexpected_error_silent_fallback( self, listener ):
        listener._log = MagicMock()
        with patch( "urllib.request.urlopen", side_effect=RuntimeError( "weird" ) ):
            listener._stamp_user_id_on_bridge()
        assert any( "unexpected error" in str( c ) for c in listener._log.call_args_list )


# ═════════════════════════════════════════════════════════════════════════════
# _stamp_owner_user_id_on_bridge  (error branches not covered by owner_stamp tests)
# ═════════════════════════════════════════════════════════════════════════════

class TestStampOwnerUserIdErrorBranches:

    def test_set_owner_false_logs_not_found( self, listener ):
        listener._log = MagicMock()
        with patch(
            "lupin_cli.claude_code.hooks.lib.hook_credentials.get_owner_credentials",
            return_value=( "o@x.com", "pw" ),
        ), patch( "urllib.request.urlopen", return_value=_login_cm( { "user": { "id": "ou-1" } } ) ), \
           patch( "lupin_cli.claude_code.hooks.lib.session_bridge.set_owner_user_id", return_value=False ):
            listener._stamp_owner_user_id_on_bridge()
        assert any( "bridge not found" in str( c ) for c in listener._log.call_args_list )

    def test_urlerror_silent_fallback( self, listener ):
        import urllib.error
        listener._log = MagicMock()
        with patch(
            "lupin_cli.claude_code.hooks.lib.hook_credentials.get_owner_credentials",
            return_value=( "o@x.com", "pw" ),
        ), patch( "urllib.request.urlopen", side_effect=urllib.error.URLError( "down" ) ):
            listener._stamp_owner_user_id_on_bridge()
        assert any( "owner_user_id stamp failed" in str( c ) for c in listener._log.call_args_list )

    def test_unexpected_error_silent_fallback( self, listener ):
        listener._log = MagicMock()
        with patch(
            "lupin_cli.claude_code.hooks.lib.hook_credentials.get_owner_credentials",
            return_value=( "o@x.com", "pw" ),
        ), patch( "urllib.request.urlopen", side_effect=RuntimeError( "weird" ) ):
            listener._stamp_owner_user_id_on_bridge()
        assert any( "unexpected error" in str( c ) for c in listener._log.call_args_list )


# ═════════════════════════════════════════════════════════════════════════════
# _print_stats
# ═════════════════════════════════════════════════════════════════════════════

class TestPrintStats:

    def test_buffer_exists_counts_lines( self, tmp_path ):
        buf = tmp_path / "buf.jsonl"
        buf.write_text( "line1\nline2\nline3\n" )
        l = _make_listener( buffer_path=str( buf ) )
        l._log = MagicMock()
        l._print_stats()
        assert any( "Buffer lines  : 3" in str( c ) for c in l._log.call_args_list )

    def test_buffer_missing_reports_zero( self, tmp_path ):
        buf = tmp_path / "nope.jsonl"
        l = _make_listener( buffer_path=str( buf ) )
        l._log = MagicMock()
        l._print_stats()
        assert any( "file does not exist" in str( c ) for c in l._log.call_args_list )


# ═════════════════════════════════════════════════════════════════════════════
# run()  — restart loop + finally cleanup
# ═════════════════════════════════════════════════════════════════════════════

class TestRun:

    def _prep( self, listener ):
        listener._setup_logging              = MagicMock()
        listener._stamp_user_id_on_bridge    = MagicMock()
        listener._stamp_owner_user_id_on_bridge = MagicMock()
        listener._print_stats                = MagicMock()
        listener._log                        = MagicMock()
        listener._log_central                = MagicMock()

    def test_single_cycle_closes_log_handles( self, listener ):
        self._prep( listener )
        listener._centralized_log = MagicMock()
        listener._log_file        = MagicMock()

        async def fake_super_run( self ):
            self._running = False

        with patch.object( base_listener_module.BaseWebSocketListener, "run", fake_super_run ):
            asyncio.run( listener.run() )

        listener._centralized_log.close.assert_called_once()
        listener._log_file.close.assert_called_once()
        listener._print_stats.assert_called_once()

    def test_restart_after_reconnect_exhaustion( self, listener ):
        self._prep( listener )
        listener._centralized_log = None   # exercise the falsy close-branches
        listener._log_file        = None
        state = { "n": 0 }

        async def fake_super_run( self ):
            state[ "n" ] += 1
            if state[ "n" ] >= 2:
                self._running = False
            # first call: leave _running True → enters cooldown + restart

        with patch.object( base_listener_module.BaseWebSocketListener, "run", fake_super_run ), \
             patch.object( listener_module.asyncio, "sleep", new_callable=AsyncMock ):
            asyncio.run( listener.run() )

        assert state[ "n" ] == 2


# ═════════════════════════════════════════════════════════════════════════════
# CLI surface: parse_args / _resolve_credentials / main / signal handler
# ═════════════════════════════════════════════════════════════════════════════

class TestParseArgs:

    def test_parses_minimum( self ):
        with patch.object(
            listener_module.sys, "argv",
            [ "prog", "--session-id", "abc12345", "--debug", "--verbose" ],
        ):
            args = listener_module.parse_args()
        assert args.session_id == "abc12345"
        assert args.debug is True
        assert args.verbose is True


class TestResolveCredentials:

    def test_cli_args_take_priority( self ):
        args = Namespace( email="cli@x.com", password="cli-pw" )
        assert listener_module._resolve_credentials( args ) == ( "cli@x.com", "cli-pw" )

    def test_falls_back_to_ini( self ):
        args = Namespace( email=None, password=None )
        with patch(
            "lupin_cli.claude_code.hooks.lib.hook_credentials.get_hook_credentials",
            return_value=( "ini@x.com", "ini-pw" ),
        ):
            assert listener_module._resolve_credentials( args ) == ( "ini@x.com", "ini-pw" )

    def test_failure_exits( self, capsys ):
        args = Namespace( email=None, password=None )
        with patch(
            "lupin_cli.claude_code.hooks.lib.hook_credentials.get_hook_credentials",
            side_effect=FileNotFoundError( "no ini" ),
        ):
            with pytest.raises( SystemExit ):
                listener_module._resolve_credentials( args )


class TestMain:

    def _argv_ns( self, verbose, accepted_ids ):
        return Namespace(
            session_id="abc12345", accepted_ids=accepted_ids, buffer_path=None,
            tmux_session=None, host="localhost", port=7999, email=None, password=None,
            debug=False, verbose=verbose, log_file=None, centralized_log=None,
        )

    def _run_main( self ):
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete( listener_module.main() )
        finally:
            loop.close()

    def test_main_verbose_and_accepted_ids_plus_signal_handler( self ):
        ns = self._argv_ns( verbose=True, accepted_ids="aa,bb, " )
        fake_listener = MagicMock()
        fake_listener.run  = AsyncMock()
        # Plain MagicMock (not AsyncMock): the signal handler passes stop()'s
        # return into the MOCKED asyncio.ensure_future, which never awaits it —
        # an AsyncMock here would leak a "coroutine never awaited" warning.
        fake_listener.stop = MagicMock()
        fake_listener.LOG_PREFIX = "[CC-Listener]"
        captured = {}
        fake_loop = MagicMock()
        fake_loop.add_signal_handler = lambda sig, h: captured.setdefault( "h", h )

        with patch.object( listener_module, "parse_args", return_value=ns ), \
             patch.object( listener_module, "_resolve_credentials", return_value=( "e", "p" ) ), \
             patch.object( listener_module, "CCNotificationListener", return_value=fake_listener ) as mk, \
             patch.object( listener_module.asyncio, "get_event_loop", return_value=fake_loop ), \
             patch.object( listener_module.asyncio, "ensure_future" ) as mock_ef:
            self._run_main()
            # verbose=True coerced debug→True before constructing the listener
            assert mk.call_args.kwargs[ "debug" ] is True
            assert mk.call_args.kwargs[ "accepted_ids" ] == { "aa", "bb" }
            fake_listener.run.assert_awaited_once()
            # exercise the SIGTERM/SIGINT handler closure
            captured[ "h" ]()
            mock_ef.assert_called_once()

    def test_main_quiet_no_accepted_ids( self ):
        ns = self._argv_ns( verbose=False, accepted_ids=None )
        fake_listener = MagicMock()
        fake_listener.run = AsyncMock()
        fake_loop = MagicMock()

        with patch.object( listener_module, "parse_args", return_value=ns ), \
             patch.object( listener_module, "_resolve_credentials", return_value=( "e", "p" ) ), \
             patch.object( listener_module, "CCNotificationListener", return_value=fake_listener ) as mk, \
             patch.object( listener_module.asyncio, "get_event_loop", return_value=fake_loop ):
            self._run_main()
        assert mk.call_args.kwargs[ "accepted_ids" ] is None
        fake_listener.run.assert_awaited_once()
