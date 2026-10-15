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
    def do_POST( self ):
        self.send_response( 401 ); self.end_headers(); self.wfile.write( b"{}" )
    def log_message( self, *a ): pass


def test_probe_process_exits_nonzero_when_the_server_rejects_the_post( tmp_path ):
    srv = http.server.HTTPServer( ( "127.0.0.1", 0 ), _H )
    threading.Thread( target=srv.serve_forever, daemon=True ).start()
    try:
        env = dict( os.environ, LUPIN_ROOT=ROOT, LUPIN_API_KEY="ck_live_" + "a" * 64,
                    LUPIN_API_URL=f"http://127.0.0.1:{srv.server_port}" )
        r = subprocess.run( [ sys.executable, PROBE, f"http://127.0.0.1:{srv.server_port}" ],
                            env=env, capture_output=True, text=True, timeout=60 )
    finally:
        srv.shutdown()
    assert r.returncode == 1, r.stdout + r.stderr
    assert r.stdout.startswith( "fail:" )


def test_installer_exits_nonzero_on_a_failed_test_notification_and_names_it_skipped_otherwise():
    text = open( SCRIPT, encoding="utf-8" ).read()
    tail = text[ text.index( "End-to-end test notification" ): ]
    assert "installer_notify_probe.py" in tail
    assert 'warn_check "Test notification failed' not in tail      # the old warn-and-exit-0 branch
    assert "fail_check \"Test notification failed" in tail
    assert "Test notification SKIPPED" in tail
    assert text.rstrip().endswith( 'exit "$INSTALL_RC"' ) or "exit $INSTALL_RC" in tail or 'exit "$INSTALL_RC"' in tail
