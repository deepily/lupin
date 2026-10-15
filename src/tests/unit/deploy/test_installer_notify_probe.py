"""
The installer's test notification is classified, not swallowed.

Delivered exits 0, no listener exits 3 (skipped), anything else exits 1.
The installer must exit non-zero on a failure.
"""
import http.server
import os
import subprocess
import sys
import threading

import pytest

ROOT   = os.environ[ "LUPIN_ROOT" ] if "LUPIN_ROOT" in os.environ else os.getcwd()
PROBE  = os.path.join( ROOT, "src/scripts/lib/installer_notify_probe.py" )
SCRIPT = os.path.join( ROOT, "src/scripts/install-cosa-voice.sh" )


def _load():
    import importlib.util
    spec = importlib.util.spec_from_file_location( "installer_notify_probe", PROBE )
    mod  = importlib.util.module_from_spec( spec )
    spec.loader.exec_module( mod )
    return mod


class _Resp:
    def __init__( self, success, status, message="m" ):
        self.success, self.status, self.message = success, status, message


@pytest.mark.parametrize( "resp, rc, word", [
    ( _Resp( True,  "queued" ),               0, "ok" ),
    ( _Resp( True,  "user_not_available" ),   3, "skipped" ),      # the server's real no-listener reply
    ( _Resp( False, "user_not_available" ),   3, "skipped" ),
    ( _Resp( False, "connection_error" ),     1, "fail" ),
    ( _Resp( False, "error", "401 bad key" ), 1, "fail" ),
    ( _Resp( False, "timeout" ),              1, "fail" ),
    ( None,                                   1, "fail" ),
] )
def test_classify_separates_delivered_skipped_and_failed( resp, rc, word ):
    got_rc, line = _load().classify( resp )
    assert got_rc == rc
    assert line.split( ":" )[ 0 ] == word


def test_failure_line_carries_status_and_message():
    _, line = _load().classify( _Resp( False, "error", "HTTP 401 Invalid or inactive API key" ) )
    assert "error" in line and "HTTP 401 Invalid or inactive API key" in line


class _H( http.server.BaseHTTPRequestHandler ):
    code, body = 401, b"{}"

    def do_POST( self ):
        self.send_response( self.code ); self.send_header( "Content-Type", "application/json" )
        self.end_headers(); self.wfile.write( self.body )

    def log_message( self, *a ): pass


def _probe( code, body ):
    handler = type( "H", ( _H, ), { "code": code, "body": body } )
    srv = http.server.HTTPServer( ( "127.0.0.1", 0 ), handler )
    threading.Thread( target=srv.serve_forever, daemon=True ).start()
    try:
        url = f"http://127.0.0.1:{srv.server_port}"
        env = dict( os.environ, LUPIN_ROOT=ROOT, LUPIN_API_KEY="ck_live_" + "a" * 64, LUPIN_API_URL=url )
        return subprocess.run( [ sys.executable, PROBE, url ], env=env, capture_output=True, text=True, timeout=60 )
    finally:
        srv.shutdown()


def test_probe_process_exits_nonzero_when_the_server_rejects_the_post():
    r = _probe( 401, b"{}" )
    assert r.returncode == 1, r.stdout + r.stderr
    assert r.stdout.startswith( "fail:" )


def test_probe_process_reports_skipped_for_the_real_no_listener_reply():
    # HTTP 200, success=True, status user_not_available: read through the real notifier.
    r = _probe( 200, b'{"status": "user_not_available", "message": "no listener", "connection_count": 0}' )
    assert r.returncode == 3, r.stdout + r.stderr
    assert r.stdout.startswith( "skipped:" )


def test_probe_process_reports_ok_for_a_queued_reply():
    r = _probe( 200, b'{"status": "queued", "message": "sent", "connection_count": 1}' )
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.startswith( "ok:" )


# ── the installer's notify step, run for real with a stubbed probe ──────────────────────
STEP = os.path.join( ROOT, "src/scripts/lib/installer-notify-step.sh" )


def _step( tmp_path, probe_body, arg="reachable" ):
    stub = tmp_path / "probe.sh"
    stub.write_text( "#!/bin/sh\n" + probe_body + "\n" )
    harness = (
        'set -e\n'
        'pass_check() { echo "PASS|$1"; }\nwarn_check() { echo "WARN|$1"; }\nfail_check() { echo "FAIL|$1"; }\n'
        f'. "{STEP}"\nINSTALL_RC=0\nrun_test_notification {arg}\necho "RC|$INSTALL_RC"\n'
    )
    env = dict( os.environ, LUPIN_ROOT=ROOT, SERVER_URL="http://x", VENV_PYTHON="/bin/sh", NOTIFY_PROBE=str( stub ) )
    return subprocess.run( [ "bash", "-c", harness ], env=env, capture_output=True, text=True, timeout=30 ).stdout


def test_step_delivered_passes_and_leaves_rc_zero( tmp_path ):
    out = _step( tmp_path, 'echo "ok: queued"; exit 0' )
    assert "PASS|Test notification delivered" in out and "RC|0" in out and "FAIL|" not in out


def test_step_no_listener_is_skipped_and_leaves_rc_zero( tmp_path ):
    out = _step( tmp_path, 'echo "skipped: user_not_available: none"; exit 3' )
    assert "WARN|Test notification SKIPPED" in out and "RC|0" in out and "FAIL|" not in out


def test_step_failure_fails_the_check_sets_rc_one_and_shows_stderr( tmp_path ):
    out = _step( tmp_path, 'echo "fail: error: HTTP 401" ; echo "stderr-detail" >&2; exit 1' )
    assert "FAIL|Test notification failed" in out and "RC|1" in out
    assert "stderr-detail" in out                              # 2>&1 kept the probe's diagnostics


def test_step_any_other_exit_code_is_a_failure( tmp_path ):
    out = _step( tmp_path, "exit 2" )
    assert "FAIL|Test notification failed" in out and "RC|1" in out


def test_step_unreachable_server_is_skipped_and_never_runs_the_probe( tmp_path ):
    out = _step( tmp_path, 'echo PROBE-RAN; exit 1', arg="unreachable" )
    assert "WARN|Test notification SKIPPED: no server" in out and "RC|0" in out and "PROBE-RAN" not in out


def test_installer_sources_the_step_and_exits_with_its_code():
    text = open( SCRIPT, encoding="utf-8" ).read()
    tail = text[ text.index( "End-to-end test notification" ): ]
    assert "installer-notify-step.sh" in tail and "run_test_notification reachable" in tail
    assert 'exit "$INSTALL_RC"' in tail
