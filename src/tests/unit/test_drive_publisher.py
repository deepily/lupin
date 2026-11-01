"""
Unit tests for cosa.utils.drive_publisher.

No real Google call is made. A fake Drive service keeps folders in memory. It records every call
(names, parents, mime types), so the tests assert what was asked of Drive, not only what came back.
The token-building path is exercised through fake google modules placed in sys.modules.
"""

import json
import os
import re
import stat
import sys
import types

import pytest

from cosa.utils import drive_publisher as dp
from cosa.utils.drive_publisher import DrivePublisher, DrivePublishError


class _Request:
    def __init__( self, fn ): self.fn = fn
    def execute( self ): return self.fn()


class FakeFiles:
    """Fake `files()`: records calls in `service.calls`, keeps folders in `service.folders`."""

    def __init__( self, service ): self.service = service

    def list( self, q, fields, spaces ):
        self.service.calls.append( ( "list", q ) )
        def run():
            if self.service.fail_list: raise RuntimeError( "list exploded" )
            name   = re.search( r"name = '((?:[^'\\]|\\.)*)'", q ).group( 1 ).replace( "\\'", "'" ).replace( "\\\\", "\\" )
            parent = re.search( r"'([^']+)' in parents", q )
            hits   = [ { "id": i } for i, f in self.service.folders.items()
                       if f[ "name" ] == name and not f[ "trashed" ] and ( parent is None or f[ "parent" ] == parent.group( 1 ) ) ]
            return { "files": hits }
        return _Request( run )

    def get( self, fileId, fields ):
        self.service.calls.append( ( "get", fileId ) )
        def run():
            if fileId not in self.service.folders: raise RuntimeError( "404 not found" )
            return { "id": fileId, "trashed": self.service.folders[ fileId ][ "trashed" ] }
        return _Request( run )

    def create( self, body, fields, media_body=None ):
        mime = media_body.mimetype() if media_body is not None else body[ "mimeType" ]
        self.service.calls.append( ( "create", body[ "name" ], tuple( body.get( "parents", [] ) ), mime ) )
        def run():
            if media_body is not None and body[ "name" ] in self.service.fail_upload: raise RuntimeError( "quota exceeded" )
            if media_body is None and body[ "name" ] in self.service.fail_create: raise RuntimeError( "create exploded" )
            self.service.counter += 1
            new_id = f"id{self.service.counter}"
            if media_body is None:
                self.service.folders[ new_id ] = { "name": body[ "name" ], "parent": ( body.get( "parents" ) or [ None ] )[ 0 ], "trashed": False }
                return { "id": new_id }
            return { "id": new_id, "webViewLink": f"https://drive.example/file/{new_id}" }
        return _Request( run )


class FakeDriveService:
    def __init__( self, fail_upload=(), fail_create=(), fail_list=False ):
        self.calls       = []
        self.folders     = {}
        self.counter     = 0
        self.fail_upload = set( fail_upload )
        self.fail_create = set( fail_create )
        self.fail_list   = fail_list

    def files( self ): return FakeFiles( self )

    def names( self, verb ): return [ c[ 1 ] for c in self.calls if c[ 0 ] == verb ]


@pytest.fixture
def cache_path( tmp_path ): return str( tmp_path / "keys" / "folder-id.json" )


@pytest.fixture
def svc(): return FakeDriveService()


def _publisher( svc, cache_path, debug=False ):
    return DrivePublisher( "/unused/token.json", "Lupin Podcasts", service=svc, debug=debug, folder_cache_path=cache_path )


def _mp3( tmp_path, name="a.mp3" ):
    path = tmp_path / name
    path.write_bytes( b"ID3" )
    return str( path )


class TestConstruction:

    def test_injected_service_is_used_and_never_built( self, svc, cache_path, monkeypatch ):
        def boom( self ): raise AssertionError( "built a real service although one was injected" )
        monkeypatch.setattr( DrivePublisher, "_build_service", boom )
        assert _publisher( svc, cache_path ).service is svc

    def test_service_built_from_token_when_not_injected( self, monkeypatch ):
        sentinel = object()
        monkeypatch.setattr( DrivePublisher, "_build_service", lambda self: sentinel )
        pub = DrivePublisher( "/t.json", "Lupin Podcasts" )
        assert pub.service is sentinel

    def test_default_cache_path_is_under_project_root( self, svc, monkeypatch ):
        monkeypatch.setattr( dp.cu, "get_project_root", lambda: "/root" )
        pub = DrivePublisher( "/t.json", "X", service=svc )
        assert pub.folder_cache_path == "/root/src/conf/keys/google-drive-folder-id.json"


class TestEnsureFolder:

    def test_creates_when_absent_then_finds_it( self, svc, cache_path ):
        pub   = _publisher( svc, cache_path )
        first = pub.ensure_folder( "Job 1" )
        again = pub.ensure_folder( "Job 1" )
        assert first == again
        assert [ c for c in svc.calls if c[ 0 ] == "create" ] == [ ( "create", "Job 1", (), dp.FOLDER_MIME_TYPE ) ]

    def test_parent_goes_into_query_and_body( self, svc, cache_path ):
        pub = _publisher( svc, cache_path )
        child = pub.ensure_folder( "Sub", parent_id="PARENT" )
        assert ( "create", "Sub", ( "PARENT", ), dp.FOLDER_MIME_TYPE ) in svc.calls
        assert "'PARENT' in parents" in [ c for c in svc.calls if c[ 0 ] == "list" ][ 0 ][ 1 ]
        assert child in svc.folders

    def test_quote_in_name_is_escaped_in_the_query( self, svc, cache_path ):
        _publisher( svc, cache_path ).ensure_folder( "Rick's \\ show" )
        query = [ c for c in svc.calls if c[ 0 ] == "list" ][ 0 ][ 1 ]
        assert "name = 'Rick\\'s \\\\ show'" in query

    def test_trashed_folder_is_not_reused( self, svc, cache_path ):
        pub = _publisher( svc, cache_path )
        old = pub.ensure_folder( "Job" )
        svc.folders[ old ][ "trashed" ] = True
        assert pub.ensure_folder( "Job" ) != old

    def test_list_error_names_the_folder( self, cache_path ):
        svc = FakeDriveService( fail_list=True )
        with pytest.raises( DrivePublishError, match="find folder Job: list exploded" ):
            _publisher( svc, cache_path ).ensure_folder( "Job" )

    def test_create_error_names_the_folder( self, cache_path ):
        svc = FakeDriveService( fail_create=[ "Job" ] )
        with pytest.raises( DrivePublishError, match="create folder Job: create exploded" ):
            _publisher( svc, cache_path ).ensure_folder( "Job" )

    def test_debug_prints_creation( self, svc, cache_path, capsys ):
        _publisher( svc, cache_path, debug=True ).ensure_folder( "Job" )
        assert "created folder Job" in capsys.readouterr().out


class TestTopFolderCache:

    def test_first_run_writes_cache_with_mode_600( self, svc, cache_path ):
        top = _publisher( svc, cache_path ).ensure_folder( "Lupin Podcasts" )
        assert json.load( open( cache_path ) ) == { "folder_name": "Lupin Podcasts", "folder_id": top }
        assert stat.S_IMODE( os.stat( cache_path ).st_mode ) == 0o600

    def test_live_cached_id_is_reused_without_a_search( self, svc, cache_path, capsys ):
        top = _publisher( svc, cache_path ).ensure_folder( "Lupin Podcasts" )
        svc.calls.clear()
        assert _publisher( svc, cache_path, debug=True ).ensure_folder( "Lupin Podcasts" ) == top
        assert svc.calls == [ ( "get", top ) ]
        assert "reusing cached folder id" in capsys.readouterr().out

    def test_trashed_cached_id_makes_a_new_folder_and_rewrites_the_cache( self, svc, cache_path ):
        old = _publisher( svc, cache_path ).ensure_folder( "Lupin Podcasts" )
        svc.folders[ old ][ "trashed" ] = True
        new = _publisher( svc, cache_path ).ensure_folder( "Lupin Podcasts" )
        assert new != old
        assert json.load( open( cache_path ) )[ "folder_id" ] == new

    def test_deleted_cached_id_makes_a_new_folder_and_rewrites_the_cache( self, svc, cache_path ):
        old = _publisher( svc, cache_path ).ensure_folder( "Lupin Podcasts" )
        del svc.folders[ old ]
        new = _publisher( svc, cache_path ).ensure_folder( "Lupin Podcasts" )
        assert new != old
        assert json.load( open( cache_path ) )[ "folder_id" ] == new

    @pytest.mark.parametrize( "content", [ "not json", "[]", json.dumps( { "folder_name": "Other", "folder_id": "idX" } ) ] )
    def test_unusable_cache_is_ignored( self, svc, cache_path, content ):
        os.makedirs( os.path.dirname( cache_path ) )
        open( cache_path, "w" ).write( content )
        top = _publisher( svc, cache_path ).ensure_folder( "Lupin Podcasts" )
        assert top in svc.folders and "get" not in [ c[ 0 ] for c in svc.calls ]

    def test_subfolders_never_touch_the_cache( self, svc, cache_path ):
        _publisher( svc, cache_path ).ensure_folder( "Job", parent_id="P" )
        assert not os.path.exists( cache_path )


class TestUpload:

    def test_returns_ids_and_sends_name_parent_and_mime( self, svc, cache_path, tmp_path ):
        got = _publisher( svc, cache_path ).upload( _mp3( tmp_path ), "audio/mpeg", "PARENT" )
        assert svc.calls == [ ( "create", "a.mp3", ( "PARENT", ), "audio/mpeg" ) ]
        assert got == { "file_id": "id1", "web_view_link": "https://drive.example/file/id1" }

    def test_api_error_names_the_file( self, cache_path, tmp_path ):
        svc = FakeDriveService( fail_upload=[ "a.mp3" ] )
        with pytest.raises( DrivePublishError, match="upload a.mp3: quota exceeded" ):
            _publisher( svc, cache_path ).upload( _mp3( tmp_path ), "audio/mpeg", "P" )

    def test_missing_local_file_names_the_file( self, svc, cache_path, tmp_path ):
        with pytest.raises( DrivePublishError, match="upload gone.mp3" ):
            _publisher( svc, cache_path ).upload( str( tmp_path / "gone.mp3" ), "audio/mpeg", "P" )
        assert svc.calls == []


class TestPublishJob:

    def test_folders_then_files_in_order_under_the_job_folder( self, svc, cache_path, tmp_path ):
        files  = [ ( _mp3( tmp_path, "en.mp3" ), "audio/mpeg" ), ( _mp3( tmp_path, "src.md" ), "text/markdown" ) ]
        result = _publisher( svc, cache_path ).publish_job( "2026-job", files )
        top    = [ i for i, f in svc.folders.items() if f[ "name" ] == "Lupin Podcasts" ][ 0 ]
        job    = [ i for i, f in svc.folders.items() if f[ "name" ] == "2026-job" ][ 0 ]
        assert svc.folders[ job ][ "parent" ] == top
        assert [ c for c in svc.calls if c[ 0 ] == "create" and c[ 3 ] != dp.FOLDER_MIME_TYPE ] == [
            ( "create", "en.mp3", ( job, ), "audio/mpeg" ), ( "create", "src.md", ( job, ), "text/markdown" ) ]
        assert result[ "folder_id" ] == job
        assert result[ "folder_link" ] == f"https://drive.google.com/drive/folders/{job}"
        assert [ f[ "error" ] for f in result[ "files" ] ] == [ None, None ]
        assert result[ "files" ][ 0 ][ "web_view_link" ].startswith( "https://drive.example/file/" )

    def test_one_failed_file_does_not_stop_the_rest( self, cache_path, tmp_path ):
        svc    = FakeDriveService( fail_upload=[ "bad.mp3" ] )
        files  = [ ( _mp3( tmp_path, "bad.mp3" ), "audio/mpeg" ), ( _mp3( tmp_path, "good.mp3" ), "audio/mpeg" ) ]
        result = _publisher( svc, cache_path ).publish_job( "job", files )
        bad, good = result[ "files" ]
        assert bad[ "file_id" ] is None and "upload bad.mp3: quota exceeded" in bad[ "error" ]
        assert good[ "error" ] is None and good[ "file_id" ] is not None

    def test_folder_failure_is_raised( self, cache_path ):
        svc = FakeDriveService( fail_list=True )
        with pytest.raises( DrivePublishError, match="find folder Lupin Podcasts" ):
            _publisher( svc, cache_path ).publish_job( "job", [] )


# ── the real service-building path, through fake google modules ──────────────

class _FakeCreds:
    def __init__( self, valid, refresh_error=None ):
        self.valid, self.refresh_error, self.refreshed = valid, refresh_error, False
    def refresh( self, request ):
        if self.refresh_error: raise self.refresh_error
        self.refreshed = True
        self.valid     = True
    def to_json( self ): return '{"token": "refreshed"}'


@pytest.fixture
def google( monkeypatch ):
    """Install fake google modules; the returned state carries what the test wants and saw."""
    state = types.SimpleNamespace( creds=_FakeCreds( True ), load_error=None, built=None, scopes=None, path=None )

    class Credentials:
        @staticmethod
        def from_authorized_user_file( path, scopes ):
            state.path, state.scopes = path, scopes
            if state.load_error: raise state.load_error
            return state.creds

    def build( api, version, credentials, cache_discovery ):
        state.built = ( api, version, credentials, cache_discovery )
        return "REAL-SERVICE"

    for name, attrs in {
        "google.auth.transport.requests" : { "Request": lambda: "REQ" },
        "google.oauth2.credentials"      : { "Credentials": Credentials },
        "googleapiclient.discovery"      : { "build": build },
    }.items():
        module = types.ModuleType( name )
        for k, v in attrs.items(): setattr( module, k, v )
        monkeypatch.setitem( sys.modules, name, module )
    return state


class TestBuildService:

    def _token( self, tmp_path ):
        path = tmp_path / "token.json"
        path.write_text( '{"token": "old"}' )
        return str( path )

    def test_missing_token_says_to_run_the_authorize_script( self, tmp_path ):
        with pytest.raises( DrivePublishError, match="token file missing.*google-drive-authorize.py" ):
            DrivePublisher( str( tmp_path / "nope.json" ), "X" )

    def test_valid_token_builds_without_refreshing( self, google, tmp_path ):
        path = self._token( tmp_path )
        pub  = DrivePublisher( path, "X" )
        assert pub.service == "REAL-SERVICE"
        assert google.built == ( "drive", "v3", google.creds, False )
        assert google.scopes == [ "https://www.googleapis.com/auth/drive.file" ]
        assert not google.creds.refreshed and open( path ).read() == '{"token": "old"}'

    def test_expired_token_is_refreshed_and_saved_with_mode_600( self, google, tmp_path ):
        google.creds = _FakeCreds( False )
        path         = self._token( tmp_path )
        os.chmod( path, 0o644 )
        DrivePublisher( path, "X" )
        assert google.creds.refreshed
        assert open( path ).read() == '{"token": "refreshed"}'
        assert stat.S_IMODE( os.stat( path ).st_mode ) == 0o600  # a token that existed with a looser mode is tightened

    def test_refresh_failure_says_to_reauthorize( self, google, tmp_path ):
        google.creds = _FakeCreds( False, refresh_error=RuntimeError( "invalid_grant" ) )
        with pytest.raises( DrivePublishError, match="could not be refreshed \\(invalid_grant\\).*google-drive-authorize.py" ):
            DrivePublisher( self._token( tmp_path ), "X" )

    @pytest.mark.parametrize( "error", [ ValueError( "bad json" ), OSError( "denied" ) ] )
    def test_unreadable_token_is_named( self, google, tmp_path, error ):
        google.load_error = error
        path              = self._token( tmp_path )
        with pytest.raises( DrivePublishError, match=f"unreadable: {re.escape( path )}" ):
            DrivePublisher( path, "X" )


def _path_publisher( svc, cache_path, folder_name="Lupin AF/Explainers", debug=False ):
    return DrivePublisher( "/unused/token.json", folder_name, service=svc, debug=debug, folder_cache_path=cache_path )


class TestFolderPath:
    """A slash-separated folder name is a chain: each level is found or made under the one above."""

    def test_each_level_is_created_under_the_one_above( self, svc, cache_path ):
        leaf = _path_publisher( svc, cache_path ).ensure_folder( "Lupin AF/Explainers" )
        creates = [ c for c in svc.calls if c[ 0 ] == "create" ]
        assert [ ( c[ 1 ], c[ 2 ] ) for c in creates ] == [ ( "Lupin AF", () ), ( "Explainers", ( "id1", ) ) ]
        assert leaf == "id2"

    def test_an_existing_parent_is_found_not_duplicated( self, svc, cache_path ):
        _path_publisher( svc, cache_path, "Lupin AF" ).ensure_folder( "Lupin AF" )
        leaf = _path_publisher( svc, cache_path, "Lupin AF/Explainers" ).ensure_folder( "Lupin AF/Explainers" )
        assert svc.names( "create" ) == [ "Lupin AF", "Explainers" ]
        assert leaf == "id2" and svc.folders[ "id2" ][ "parent" ] == "id1"

    def test_a_same_named_folder_under_another_parent_is_not_reused( self, svc, cache_path ):
        pub = _path_publisher( svc, cache_path, "A/Same" )
        svc.folders[ "x" ] = { "name": "Same", "parent": "other", "trashed": False }
        leaf = pub.ensure_folder( "A/Same" )
        assert leaf != "x" and svc.folders[ leaf ][ "parent" ] != "other"

    def test_empty_levels_and_spaces_are_dropped( self, svc, cache_path ):
        pub = _path_publisher( svc, cache_path, " /Lupin AF// Explainers / " )
        assert pub.folder_levels == [ "Lupin AF", "Explainers" ] and pub.folder_path == "Lupin AF/Explainers"
        pub.ensure_folder( "Lupin AF/Explainers" )
        assert svc.names( "create" ) == [ "Lupin AF", "Explainers" ]

    @pytest.mark.parametrize( "bad", [ "", "/", " / // " ] )
    def test_a_path_with_no_level_is_refused( self, svc, cache_path, bad ):
        with pytest.raises( ValueError, match="no folder level" ):
            _path_publisher( svc, cache_path, bad )

    def test_ensure_folder_refuses_a_name_with_no_level( self, svc, cache_path ):
        with pytest.raises( ValueError, match="no folder level" ):
            _path_publisher( svc, cache_path ).ensure_folder( "//" )

    def test_a_path_under_a_given_parent_starts_there( self, svc, cache_path ):
        _path_publisher( svc, cache_path ).ensure_folder( "X/Y", parent_id="ROOT" )
        creates = [ c for c in svc.calls if c[ 0 ] == "create" ]
        assert creates[ 0 ][ 2 ] == ( "ROOT", ) and creates[ 1 ][ 2 ] == ( "id1", )
        assert not os.path.exists( cache_path ), "only the top folder is cached"


class TestFolderPathCache:

    def test_the_cache_records_the_full_path_and_the_last_level_id( self, svc, cache_path ):
        leaf = _path_publisher( svc, cache_path ).ensure_folder( "Lupin AF/Explainers" )
        assert json.load( open( cache_path ) ) == { "folder_name": "Lupin AF/Explainers", "folder_id": leaf }
        assert stat.S_IMODE( os.stat( cache_path ).st_mode ) == 0o600

    def test_a_live_cached_path_is_reused_with_no_search( self, svc, cache_path, capsys ):
        leaf = _path_publisher( svc, cache_path ).ensure_folder( "Lupin AF/Explainers" )
        svc.calls.clear()
        assert _path_publisher( svc, cache_path, debug=True ).ensure_folder( "Lupin AF/Explainers" ) == leaf
        assert svc.calls == [ ( "get", leaf ) ]
        assert "reusing cached folder id for Lupin AF/Explainers" in capsys.readouterr().out

    def test_a_cache_for_the_parent_alone_is_not_used_for_the_path( self, svc, cache_path ):
        parent = _path_publisher( svc, cache_path, "Lupin AF" ).ensure_folder( "Lupin AF" )
        svc.calls.clear()
        leaf = _path_publisher( svc, cache_path ).ensure_folder( "Lupin AF/Explainers" )
        assert leaf != parent and ( "get", parent ) not in svc.calls
        assert json.load( open( cache_path ) )[ "folder_name" ] == "Lupin AF/Explainers"

    def test_a_trashed_cached_leaf_is_replaced_and_the_cache_rewritten( self, svc, cache_path ):
        old = _path_publisher( svc, cache_path ).ensure_folder( "Lupin AF/Explainers" )
        svc.folders[ old ][ "trashed" ] = True
        new = _path_publisher( svc, cache_path ).ensure_folder( "Lupin AF/Explainers" )
        assert new != old and json.load( open( cache_path ) )[ "folder_id" ] == new
        assert svc.names( "create" ).count( "Lupin AF" ) == 1, "the live parent is reused"


class TestPublishJobUnderAPath:

    def test_the_job_folder_goes_inside_the_last_level( self, svc, cache_path, tmp_path ):
        result = _path_publisher( svc, cache_path ).publish_job( "2026-11-01 grading", [ ( _mp3( tmp_path ), "audio/mpeg" ) ] )
        assert svc.names( "create" )[ :3 ] == [ "Lupin AF", "Explainers", "2026-11-01 grading" ]
        assert svc.folders[ result[ "folder_id" ] ][ "parent" ] == "id2"

    def test_a_slash_in_the_job_folder_name_stays_one_folder( self, svc, cache_path, tmp_path ):
        result = _path_publisher( svc, cache_path ).publish_job( "a/b", [] )
        assert svc.folders[ result[ "folder_id" ] ][ "name" ] == "a/b"


class TestTheConfiguredPath:

    def test_the_ini_folder_name_makes_a_chain_not_one_folder_with_a_slash( self, svc, cache_path, tmp_path ):
        result = _path_publisher( svc, cache_path, "Lupin AF Mobile/Podcasts" ).publish_job( "2026-11-01 job", [ ( _mp3( tmp_path ), "audio/mpeg" ) ] )
        assert svc.names( "create" )[ :3 ] == [ "Lupin AF Mobile", "Podcasts", "2026-11-01 job" ]
        assert [ f[ "name" ] for f in svc.folders.values() if "/" in f[ "name" ] ] == [], "no folder carries a slash in its name"
        assert svc.folders[ "id1" ][ "parent" ] is None and svc.folders[ "id2" ][ "parent" ] == "id1"
        assert result[ "folder_link" ].endswith( result[ "folder_id" ] )
