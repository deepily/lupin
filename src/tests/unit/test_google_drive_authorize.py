"""
Unit tests for src/scripts/google-drive-authorize.py.

The script's name has dashes, so it is loaded by path. No browser opens and no Google call is made:
the OAuth flow and the Drive service are fake modules placed in sys.modules.
"""

import importlib.util
import json
import os
import stat
import sys
import types

import pytest

SCRIPT = os.environ[ "LUPIN_ROOT" ] + "/src/scripts/google-drive-authorize.py"


def _load():
    spec   = importlib.util.spec_from_file_location( "google_drive_authorize_under_test", SCRIPT )
    module = importlib.util.module_from_spec( spec )
    spec.loader.exec_module( module )
    return module


@pytest.fixture
def script(): return _load()


class _Creds:
    def to_json( self ): return '{"refresh_token": "r"}'


def _install_fake( monkeypatch, name, **attrs ):
    module = types.ModuleType( name )
    for k, v in attrs.items(): setattr( module, k, v )
    monkeypatch.setitem( sys.modules, name, module )


class TestBootstrap:

    def test_refuses_to_load_without_lupin_root( self, monkeypatch ):
        monkeypatch.delenv( "LUPIN_ROOT" )
        with pytest.raises( RuntimeError, match="LUPIN_ROOT not set" ):
            _load()

    def test_puts_src_first_on_sys_path_when_absent( self, monkeypatch ):
        src = os.environ[ "LUPIN_ROOT" ] + "/src"
        monkeypatch.setattr( sys, "path", [ p for p in sys.path if p != src ] )
        _load()
        assert sys.path[ 0 ] == src

    def test_leaves_sys_path_alone_when_src_is_already_there( self, monkeypatch ):
        src = os.environ[ "LUPIN_ROOT" ] + "/src"
        monkeypatch.setattr( sys, "path", [ "/first", src ] )
        _load()
        assert sys.path == [ "/first", src ]


class TestRunFlow:

    def test_runs_the_installed_app_flow_with_drive_file_scope_on_a_free_port( self, script, monkeypatch ):
        seen = {}
        class Flow:
            def run_local_server( self, port ): seen[ "port" ] = port; return "CREDS"
        class InstalledAppFlow:
            @staticmethod
            def from_client_secrets_file( path, scopes ): seen[ "path" ], seen[ "scopes" ] = path, scopes; return Flow()
        _install_fake( monkeypatch, "google_auth_oauthlib.flow", InstalledAppFlow=InstalledAppFlow )
        assert script.run_flow( "/c.json" ) == "CREDS"
        assert seen == { "path": "/c.json", "scopes": [ "https://www.googleapis.com/auth/drive.file" ], "port": 0 }


class TestWriteToken:

    def test_new_file_is_mode_600_and_holds_the_json( self, script, tmp_path ):
        path = str( tmp_path / "token.json" )
        script.write_token( _Creds(), path )
        assert json.load( open( path ) ) == { "refresh_token": "r" }
        assert stat.S_IMODE( os.stat( path ).st_mode ) == 0o600

    def test_a_looser_existing_file_is_tightened_to_600( self, script, tmp_path ):
        path = tmp_path / "token.json"
        path.write_text( "old" )
        os.chmod( path, 0o644 )
        script.write_token( _Creds(), str( path ) )
        assert stat.S_IMODE( os.stat( path ).st_mode ) == 0o600 and path.read_text() == '{"refresh_token": "r"}'


class TestVerify:

    def test_lists_the_apps_own_files_and_reads_the_email( self, script, monkeypatch ):
        calls = []
        class Req:
            def __init__( self, out ): self.out = out
            def execute( self ): return self.out
        class About:
            def get( self, fields ): calls.append( ( "about", fields ) ); return Req( { "user": { "emailAddress": "rick@example.com" } } )
        class Files:
            def list( self, pageSize, fields ): calls.append( ( "list", pageSize, fields ) ); return Req( { "files": [ { "name": "a.mp3" } ] } )
        class Service:
            def about( self ): return About()
            def files( self ): return Files()
        _install_fake( monkeypatch, "googleapiclient.discovery", build=lambda api, version, credentials, cache_discovery: Service() )
        assert script.verify( "CREDS" ) == ( "rick@example.com", [ "a.mp3" ] )
        assert calls == [ ( "about", "user(emailAddress)" ), ( "list", 10, "files(name)" ) ]


class TestMain:

    def _root( self, script, monkeypatch, tmp_path ):
        ( tmp_path / "src" / "conf" / "keys" ).mkdir( parents=True )
        monkeypatch.setattr( script.cu, "get_project_root", lambda: str( tmp_path ) )
        return tmp_path / "src" / "conf" / "keys"

    def test_missing_client_file_returns_2_and_writes_nothing( self, script, monkeypatch, tmp_path, capsys ):
        keys = self._root( script, monkeypatch, tmp_path )
        monkeypatch.setattr( script, "run_flow", lambda p: pytest.fail( "opened the browser without a client file" ) )
        assert script.main() == 2
        assert "OAuth client file missing" in capsys.readouterr().out
        assert list( keys.iterdir() ) == []

    @pytest.mark.parametrize( "names, shown", [ ( [ "a.mp3", "b.mp3" ], "a.mp3, b.mp3" ), ( [], "(none yet)" ) ] )
    def test_success_saves_the_token_and_prints_email_and_files( self, script, monkeypatch, tmp_path, capsys, names, shown ):
        keys = self._root( script, monkeypatch, tmp_path )
        ( keys / "google-drive-oauth-client.json" ).write_text( "{}" )
        monkeypatch.setattr( script, "run_flow", lambda p: _Creds() if p.endswith( "google-drive-oauth-client.json" ) else None )
        monkeypatch.setattr( script, "verify", lambda creds: ( "rick@example.com", names ) )
        assert script.main() == 0
        out = capsys.readouterr().out
        assert "Authorized as rick@example.com" in out and shown in out
        token = keys / "google-drive-oauth-token.json"
        assert json.load( open( token ) ) == { "refresh_token": "r" } and stat.S_IMODE( os.stat( token ).st_mode ) == 0o600
