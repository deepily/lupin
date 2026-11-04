"""
Unit tests for the phone's door to Drive.

They cover the DrivePublisher listing and streaming methods and the /api/podcast-drive router.
The Drive service is a fake that parses the query strings the real code sends. The router tests drive a real
DrivePublisher over that fake.
"""

import re

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import cosa.rest.routers.podcast_drive as router_mod
from cosa.rest.auth import get_current_user
from cosa.rest.dependencies.config import get_config_manager
from cosa.utils.drive_publisher import DriveNotFound, DrivePublishError, DrivePublisher

FOLDER = "application/vnd.google-apps.folder"
OWNER  = "owner@example.com"


class _HttpError( Exception ):
    """What googleapiclient raises: the HTTP answer rides on .resp."""

    def __init__( self, status, text ):
        super().__init__( text )
        self.resp = type( "Resp", ( object, ), { "status": status } )()


class _Request:
    def __init__( self, fn ):
        self.fn      = fn
        self.headers = {}

    def execute( self ): return self.fn( self.headers )


class FakeFiles:

    def __init__( self, service ): self.service = service

    def list( self, q, fields, spaces, orderBy=None, pageSize=None ):
        self.service.calls.append( ( "list", q, orderBy, pageSize ) )
        def run( _headers ):
            if self.service.fail: raise RuntimeError( "drive down" )
            rows = list( self.service.items.items() )
            parent = re.search( r"'([^']+)' in parents", q )
            if parent: rows = [ ( i, f ) for i, f in rows if parent.group( 1 ) in f.get( "parents", [] ) ]
            name = re.search( r"name = '((?:[^'\\]|\\.)*)'", q )
            if name: rows = [ ( i, f ) for i, f in rows if f[ "name" ] == name.group( 1 ).replace( "\\'", "'" ).replace( "\\\\", "\\" ) ]
            if "mimeType != " in q:   rows = [ ( i, f ) for i, f in rows if f[ "mimeType" ] != FOLDER ]
            elif "mimeType = " in q:  rows = [ ( i, f ) for i, f in rows if f[ "mimeType" ] == FOLDER ]
            rows = [ ( i, f ) for i, f in rows if not f.get( "trashed" ) ]
            if orderBy == "createdTime desc": rows.sort( key=lambda r: r[ 1 ].get( "createdTime", "" ), reverse=True )
            if orderBy == "name":             rows.sort( key=lambda r: r[ 1 ][ "name" ] )
            if pageSize is not None:          rows = rows[ :pageSize ]
            asked = set( re.search( r"files\((.*)\)", fields ).group( 1 ).split( "," ) )   # only the fields the code asks for come back
            return { "files": [ dict( id=i, **{ k: v for k, v in f.items() if k in asked } ) for i, f in rows ] }
        return _Request( run )

    def get( self, fileId, fields ):
        self.service.calls.append( ( "get", fileId ) )
        def run( _headers ):
            if fileId in self.service.get_fails: raise _HttpError( self.service.get_fails[ fileId ], "drive error" )
            if fileId not in self.service.items: raise _HttpError( 404, "File not found" )
            f = self.service.items[ fileId ]
            return { "id": fileId, **{ k: v for k, v in f.items() if k != "content" } }
        return _Request( run )

    def get_media( self, fileId ):
        self.service.calls.append( ( "get_media", fileId ) )
        def run( headers ):
            if self.service.fail: raise RuntimeError( "drive down" )
            data  = self.service.items[ fileId ][ "content" ]
            match = re.match( r"bytes=(\d+)-(\d+)", headers.get( "Range", "" ) )
            return data[ int( match.group( 1 ) ): int( match.group( 2 ) ) + 1 ] if match else data
        return _Request( run )


class FakeService:
    def __init__( self ):
        self.calls = []
        self.fail  = False
        self.items = {}
        self.get_fails = {}

    def files( self ): return FakeFiles( self )

    def add( self, id, name, mime="audio/mpeg", parents=(), **extra ):
        self.items[ id ] = { "name": name, "mimeType": mime, "parents": list( parents ), "trashed": False, **extra }


def _drive_with_two_jobs():
    svc = FakeService()
    svc.add( "ROOT", "Lupin AF Mobile", FOLDER )
    svc.add( "TOP", "Podcasts", FOLDER, [ "ROOT" ] )
    svc.add( "J1", "2026-11-01-014849-grading-your-own-exam", FOLDER, [ "TOP" ], createdTime="2026-11-01T01:48:49Z" )
    svc.add( "J2", "2026-11-01-184006-the-empty-net", FOLDER, [ "TOP" ], createdTime="2026-11-01T18:40:06Z" )
    svc.add( "A1", "grading.mp3", "audio/mpeg", [ "J1" ], size="1000", content=b"0123456789" * 100 )
    svc.add( "A2", "empty.mp3", "audio/mpeg", [ "J2" ], size="500", content=b"abcdefghij" * 50 )
    svc.add( "S2", "empty-script.md", "text/markdown", [ "J2" ], size="60", content=b"# Podcast: The Empty Net: A Failed Pilot\n\nbody" )
    svc.add( "STRANGER", "private.mp3", "audio/mpeg", [ "ELSEWHERE" ], size="1", content=b"x" )
    svc.add( "ELSEWHERE", "Other Folder", FOLDER, [ "ROOT" ] )
    return svc


def _publisher( svc, tmp_path, name="Lupin AF Mobile/Podcasts" ):
    return DrivePublisher( "/unused/token.json", name, service=svc, folder_cache_path=str( tmp_path / "keys" / "cache.json" ) )


class TestPublisherListing:

    def test_find_top_folder_walks_the_path_and_never_creates( self, tmp_path ):
        svc = _drive_with_two_jobs()
        assert _publisher( svc, tmp_path ).find_top_folder() == "TOP"
        assert not [ c for c in svc.calls if c[ 0 ] == "create" ]

    def test_find_top_folder_is_none_when_any_level_is_absent( self, tmp_path ):
        svc = _drive_with_two_jobs()
        assert _publisher( svc, tmp_path, "Lupin AF Mobile/Nope" ).find_top_folder() is None
        assert _publisher( svc, tmp_path, "Nowhere/Podcasts" ).find_top_folder() is None

    def test_find_top_folder_uses_a_live_cache( self, tmp_path ):
        svc = _drive_with_two_jobs()
        pub = _publisher( svc, tmp_path )
        pub._write_cached_folder_id( "TOP" )
        svc.calls.clear()
        assert pub.find_top_folder() == "TOP" and svc.calls == [ ( "get", "TOP" ) ]

    def test_job_folders_come_newest_first_and_are_limited( self, tmp_path ):
        svc = _drive_with_two_jobs()
        pub = _publisher( svc, tmp_path )
        assert [ f[ "id" ] for f in pub.list_job_folders( "TOP" ) ] == [ "J2", "J1" ]
        assert [ f[ "id" ] for f in pub.list_job_folders( "TOP", limit=1 ) ] == [ "J2" ]

    def test_folder_files_exclude_subfolders_and_trash( self, tmp_path ):
        svc = _drive_with_two_jobs()
        svc.add( "SUB", "inner", FOLDER, [ "J2" ] )
        svc.add( "OLD", "old.mp3", "audio/mpeg", [ "J2" ], trashed=True )
        assert [ f[ "id" ] for f in _publisher( svc, tmp_path ).list_folder_files( "J2" ) ] == [ "S2", "A2" ]

    def test_a_listing_error_is_a_drive_error( self, tmp_path ):
        svc = _drive_with_two_jobs()
        svc.fail = True
        with pytest.raises( DrivePublishError, match="list job folders" ):
            _publisher( svc, tmp_path ).list_job_folders( "TOP" )

    def test_read_head_returns_only_the_first_bytes( self, tmp_path ):
        assert _publisher( _drive_with_two_jobs(), tmp_path ).read_head( "A1", max_bytes=4 ) == b"0123"


class TestNotFoundIsNotOutage:
    """Only a Drive 404 reads as "not there"; other failures must not."""

    def test_a_404_is_drive_not_found_and_still_a_publish_error( self, tmp_path ):
        svc = _drive_with_two_jobs()
        with pytest.raises( DriveNotFound, match="check file NOPE" ) as caught:
            _publisher( svc, tmp_path )._call( "check file NOPE", svc.files().get( fileId="NOPE", fields="id" ) )
        assert isinstance( caught.value, DrivePublishError )

    def test_a_500_is_a_plain_publish_error( self, tmp_path ):
        svc = _drive_with_two_jobs()
        svc.get_fails[ "A1" ] = 500
        with pytest.raises( DrivePublishError ) as caught:
            _publisher( svc, tmp_path )._call( "check file A1", svc.files().get( fileId="A1", fields="id" ) )
        assert not isinstance( caught.value, DriveNotFound )

    def test_an_error_with_no_http_answer_is_a_plain_publish_error( self, tmp_path ):
        svc = _drive_with_two_jobs()
        svc.fail = True
        with pytest.raises( DrivePublishError ) as caught:
            _publisher( svc, tmp_path )._call( "list", svc.files().list( q="", fields="", spaces="drive" ) )
        assert not isinstance( caught.value, DriveNotFound )

    def test_a_500_on_the_file_lookup_is_raised_not_hidden( self, tmp_path ):
        svc = _drive_with_two_jobs()
        svc.get_fails[ "A2" ] = 500
        with pytest.raises( DrivePublishError, match="check file A2" ) as caught:
            _publisher( svc, tmp_path ).file_inside_top_folder( "A2", "TOP" )
        assert not isinstance( caught.value, DriveNotFound )

    def test_a_500_on_the_parent_lookup_is_raised_not_hidden( self, tmp_path ):
        svc = _drive_with_two_jobs()
        svc.get_fails[ "J2" ] = 503
        with pytest.raises( DrivePublishError, match="check folder J2" ):
            _publisher( svc, tmp_path ).file_inside_top_folder( "A2", "TOP" )


class TestFileInsideTopFolder:

    def test_a_file_in_a_job_folder_is_allowed( self, tmp_path ):
        got = _publisher( _drive_with_two_jobs(), tmp_path ).file_inside_top_folder( "A2", "TOP" )
        assert got == { "id": "A2", "name": "empty.mp3", "mimeType": "audio/mpeg", "size": "500" }

    @pytest.mark.parametrize( "file_id", [ "STRANGER", "J1", "TOP", "ROOT", "NOPE" ] )
    def test_everything_else_is_refused( self, tmp_path, file_id ):
        assert _publisher( _drive_with_two_jobs(), tmp_path ).file_inside_top_folder( file_id, "TOP" ) is None

    def test_a_trashed_file_and_a_file_in_a_trashed_job_folder_are_refused( self, tmp_path ):
        svc = _drive_with_two_jobs()
        pub = _publisher( svc, tmp_path )
        svc.items[ "A1" ][ "trashed" ] = True
        assert pub.file_inside_top_folder( "A1", "TOP" ) is None
        svc.items[ "J2" ][ "trashed" ] = True
        assert pub.file_inside_top_folder( "A2", "TOP" ) is None

    def test_a_file_directly_in_the_top_folder_is_refused( self, tmp_path ):
        svc = _drive_with_two_jobs()
        svc.add( "LOOSE", "loose.mp3", "audio/mpeg", [ "TOP" ], size="1", content=b"x" )
        assert _publisher( svc, tmp_path ).file_inside_top_folder( "LOOSE", "TOP" ) is None

    def test_a_file_whose_parent_cannot_be_read_is_refused( self, tmp_path ):
        svc = _drive_with_two_jobs()
        svc.add( "ORPHAN", "o.mp3", "audio/mpeg", [ "GONE" ], size="1" )
        assert _publisher( svc, tmp_path ).file_inside_top_folder( "ORPHAN", "TOP" ) is None

    def test_a_file_with_no_parents_is_refused( self, tmp_path ):
        svc = _drive_with_two_jobs()
        svc.add( "ROOTFILE", "r.mp3" )
        assert _publisher( svc, tmp_path ).file_inside_top_folder( "ROOTFILE", "TOP" ) is None


class _Upstream:
    """A streamed HTTP response, as requests gives one."""

    def __init__( self, status, body, headers ):
        self.status_code = status
        self.body        = body
        self.headers     = headers
        self.closed      = False
        self.chunk_size  = None
        self.yielded     = 0

    def iter_content( self, chunk_size ):
        self.chunk_size = chunk_size
        for i in range( 0, len( self.body ), 4 ):
            self.yielded += 1
            yield self.body[ i: i + 4 ]

    def close( self ): self.closed = True


class _Session:
    def __init__( self, responder ):
        self.responder = responder
        self.requests  = []

    def get( self, url, params, headers, stream, timeout ):
        self.requests.append( { "url": url, "params": params, "headers": headers, "stream": stream } )
        return self.responder( headers )


class TestOpenMedia:

    def test_the_range_header_goes_to_drive_with_alt_media( self, tmp_path, monkeypatch ):
        pub     = _publisher( _drive_with_two_jobs(), tmp_path )
        session = _Session( lambda h: _Upstream( 206, b"x", {} ) )
        monkeypatch.setattr( pub, "_authorized_session", lambda: session )
        pub.open_media( "A1", "bytes=10-19" )
        sent = session.requests[ 0 ]
        assert sent[ "url" ] == "https://www.googleapis.com/drive/v3/files/A1" and sent[ "params" ] == { "alt": "media" }
        assert sent[ "headers" ] == { "Range": "bytes=10-19" } and sent[ "stream" ] is True

    def test_no_range_sends_no_range_header( self, tmp_path, monkeypatch ):
        pub     = _publisher( _drive_with_two_jobs(), tmp_path )
        session = _Session( lambda h: _Upstream( 200, b"x", {} ) )
        monkeypatch.setattr( pub, "_authorized_session", lambda: session )
        pub.open_media( "A1" )
        assert session.requests[ 0 ][ "headers" ] == {}

    def test_a_transport_failure_is_a_drive_error( self, tmp_path, monkeypatch ):
        pub = _publisher( _drive_with_two_jobs(), tmp_path )
        def boom( _h ): raise OSError( "connection reset" )
        monkeypatch.setattr( pub, "_authorized_session", lambda: _Session( boom ) )
        with pytest.raises( DrivePublishError, match="stream file A1: connection reset" ):
            pub.open_media( "A1" )

    def test_the_file_id_is_quoted_in_the_url( self, tmp_path, monkeypatch ):
        pub     = _publisher( _drive_with_two_jobs(), tmp_path )
        session = _Session( lambda h: _Upstream( 200, b"x", {} ) )
        monkeypatch.setattr( pub, "_authorized_session", lambda: session )
        pub.open_media( "a/b?c=d#e" )
        assert session.requests[ 0 ][ "url" ] == "https://www.googleapis.com/drive/v3/files/a%2Fb%3Fc%3Dd%23e"

    def test_a_publisher_with_an_injected_service_has_no_session( self, tmp_path ):
        with pytest.raises( DrivePublishError, match="no Drive credentials" ):
            _publisher( _drive_with_two_jobs(), tmp_path ).open_media( "A1" )

    def test_the_session_signs_with_the_publishers_credentials( self, tmp_path, monkeypatch ):
        import google.auth.transport.requests as gtr
        seen = []
        monkeypatch.setattr( gtr, "AuthorizedSession", lambda creds: seen.append( creds ) or "SESSION" )
        pub       = _publisher( _drive_with_two_jobs(), tmp_path )
        pub.creds = "CREDS"
        assert pub._authorized_session() == "SESSION" and seen == [ "CREDS" ]


# ── the router ───────────────────────────────────────────────────────────────

class _Config:
    def __init__( self, owner=OWNER, folder="Lupin AF Mobile/Podcasts" ):
        self.values = { "podcast drive owner email": owner, "podcast drive folder name": folder, "podcast drive token path": "/tok.json" }

    def get( self, key, default=None, return_type=None, silent=False ):
        return self.values.get( key, default )


@pytest.fixture
def world( tmp_path, monkeypatch ):
    """A TestClient over the real router, with a real publisher on a fake Drive."""
    svc     = _drive_with_two_jobs()
    pub     = _publisher( svc, tmp_path )
    made    = []
    state   = { "user": { "email": OWNER }, "config": _Config(), "upstream": None, "session": None }
    session = _Session( lambda headers: state[ "upstream" ]( headers ) )
    monkeypatch.setattr( pub, "_authorized_session", lambda: session )
    monkeypatch.setattr( router_mod, "_make_publisher", lambda ini: made.append( ini ) or pub )
    app = FastAPI()
    app.include_router( router_mod.router )
    app.dependency_overrides[ get_current_user ]   = lambda: state[ "user" ]
    app.dependency_overrides[ get_config_manager ] = lambda: state[ "config" ]
    state.update( client=TestClient( app ), made=made, svc=svc, pub=pub, session=session )
    return state


class TestList:

    def test_a_folder_description_is_the_title_ahead_of_the_script( self, world ):
        world[ "svc" ].items[ "J2" ][ "description" ] = "  The Clean Title Rick Wants "
        assert world[ "client" ].get( "/api/podcast-drive/list" ).json()[ 0 ][ "title" ] == "The Clean Title Rick Wants"

    def test_a_blank_description_is_ignored( self, world ):
        world[ "svc" ].items[ "J2" ][ "description" ] = "   "
        assert world[ "client" ].get( "/api/podcast-drive/list" ).json()[ 0 ][ "title" ] == "The Empty Net: A Failed Pilot"

    def test_the_live_folder_with_a_dated_source_name_gets_a_date_free_title( self, world ):
        world[ "svc" ].add( "J3", "2026-11-01-190015-2026.10.31-google-drive-sign-in-explainer", FOLDER, [ "TOP" ], createdTime="2026-11-01T19:00:15Z" )
        world[ "svc" ].add( "A3", "explainer.mp3", "audio/mpeg", [ "J3" ], size="9", content=b"x" )
        newest = world[ "client" ].get( "/api/podcast-drive/list" ).json()[ 0 ]
        assert newest[ "job_folder" ].endswith( "google-drive-sign-in-explainer" )
        assert newest[ "title" ] == "Google Drive Sign In Explainer"

    def test_lists_newest_first_with_the_contract_fields( self, world ):
        body = world[ "client" ].get( "/api/podcast-drive/list" ).json()
        assert [ j[ "job_folder" ] for j in body ] == [ "2026-11-01-184006-the-empty-net", "2026-11-01-014849-grading-your-own-exam" ]
        newest = body[ 0 ]
        assert newest[ "created_ts" ] == "2026-11-01T18:40:06Z"
        assert newest[ "files" ] == [
            { "name": "empty-script.md", "mime": "text/markdown", "size": 60,  "drive_file_id": "S2", "stream_url": "/api/podcast-drive/stream/S2" },
            { "name": "empty.mp3",       "mime": "audio/mpeg",    "size": 500, "drive_file_id": "A2", "stream_url": "/api/podcast-drive/stream/A2" },
        ]

    def test_the_title_comes_from_the_script_when_there_is_one_else_the_folder_name( self, world ):
        titles = { j[ "job_folder" ][ -13: ]: j[ "title" ] for j in world[ "client" ].get( "/api/podcast-drive/list" ).json() }
        assert titles == { "the-empty-net": "The Empty Net: A Failed Pilot", "your-own-exam": "Grading Your Own Exam" }

    def test_an_unreadable_script_falls_back_to_the_folder_name( self, world ):
        world[ "svc" ].items[ "S2" ][ "content" ] = b"no heading at all"
        assert world[ "client" ].get( "/api/podcast-drive/list" ).json()[ 0 ][ "title" ] == "The Empty Net"

    def test_a_script_that_cannot_be_read_from_drive_falls_back( self, world, monkeypatch ):
        def boom( file_id, max_bytes ): raise DrivePublishError( "read failed" )
        monkeypatch.setattr( world[ "pub" ], "read_head", boom )
        assert world[ "client" ].get( "/api/podcast-drive/list" ).json()[ 0 ][ "title" ] == "The Empty Net"

    def test_a_file_with_no_size_reports_none( self, world ):
        del world[ "svc" ].items[ "A2" ][ "size" ]
        sizes = { f[ "name" ]: f[ "size" ] for f in world[ "client" ].get( "/api/podcast-drive/list" ).json()[ 0 ][ "files" ] }
        assert sizes[ "empty.mp3" ] is None

    def test_a_missing_drive_folder_is_an_empty_list( self, world ):
        world[ "pub" ].folder_levels = [ "Nowhere" ]
        world[ "pub" ].folder_path   = "Nowhere"
        assert world[ "client" ].get( "/api/podcast-drive/list" ).json() == []

    def test_a_drive_failure_is_503( self, world ):
        world[ "svc" ].fail = True
        resp = world[ "client" ].get( "/api/podcast-drive/list" )
        assert resp.status_code == 503 and "Drive unavailable" in resp.json()[ "detail" ]


class TestOwnerOnly:

    @pytest.mark.parametrize( "url", [ "/api/podcast-drive/list", "/api/podcast-drive/stream/A1" ] )
    def test_another_user_gets_403_before_any_drive_call( self, world, url ):
        world[ "user" ] = { "email": "someone.else@example.com" }
        assert world[ "client" ].get( url ).status_code == 403
        assert world[ "svc" ].calls == [], "no Drive call is made for a stranger"

    def test_the_publisher_is_built_from_the_ini_folder_and_token_path( self, world ):
        world[ "client" ].get( "/api/podcast-drive/list" )
        assert [ ( m.drive_folder_name, m.drive_token_path ) for m in world[ "made" ] ] == [ ( "Lupin AF Mobile/Podcasts", "/tok.json" ) ]

    def test_missing_folder_and_token_keys_use_the_defaults( self, world ):
        world[ "config" ].values = { "podcast drive owner email": OWNER }
        world[ "client" ].get( "/api/podcast-drive/list" )
        assert [ ( m.drive_folder_name, m.drive_token_path ) for m in world[ "made" ] ] == [ ( "Lupin Podcasts", "/src/conf/keys/google-drive-oauth-token.json" ) ]

    def test_the_owner_match_ignores_case_and_spaces( self, world ):
        world[ "user" ] = { "email": f"  {OWNER.upper()} " }
        assert world[ "client" ].get( "/api/podcast-drive/list" ).status_code == 200

    def test_an_unset_owner_means_nobody( self, world ):
        world[ "config" ] = _Config( owner="" )
        assert world[ "client" ].get( "/api/podcast-drive/list" ).status_code == 403
        world[ "user" ] = { "email": "" }
        assert world[ "client" ].get( "/api/podcast-drive/list" ).status_code == 403

    def test_a_user_with_no_email_is_refused( self, world ):
        world[ "user" ] = {}
        assert world[ "client" ].get( "/api/podcast-drive/list" ).status_code == 403

    def test_a_missing_token_is_503( self, world, monkeypatch ):
        def no_token( config ): raise DrivePublishError( "Google Drive token file missing" )
        monkeypatch.setattr( router_mod, "_make_publisher", no_token )
        resp = world[ "client" ].get( "/api/podcast-drive/list" )
        assert resp.status_code == 503 and "token file missing" in resp.json()[ "detail" ]

    def test_without_a_login_the_route_is_refused_by_the_auth_dependency( self ):
        app = FastAPI()
        app.include_router( router_mod.router )
        app.dependency_overrides[ get_config_manager ] = lambda: _Config()
        assert TestClient( app ).get( "/api/podcast-drive/list" ).status_code in ( 401, 403 )


class TestStream:

    def _upstream( self, status=206, body=b"23456789", headers=None ):
        return lambda request_headers: _Upstream( status, body, headers or { "Content-Range": "bytes 2-9/1000", "Content-Length": "8" } )

    def test_a_range_request_comes_back_206_with_the_range_headers( self, world ):
        world[ "upstream" ] = self._upstream()
        resp = world[ "client" ].get( "/api/podcast-drive/stream/A1", headers={ "Range": "bytes=2-9" } )
        assert resp.status_code == 206 and resp.content == b"23456789"
        assert resp.headers[ "content-range" ] == "bytes 2-9/1000" and resp.headers[ "accept-ranges" ] == "bytes"
        assert resp.headers[ "content-type" ] == "audio/mpeg"
        assert world[ "session" ].requests[ 0 ][ "headers" ] == { "Range": "bytes=2-9" }, "the browser's Range reaches Drive"

    def test_no_range_streams_the_whole_file_as_200( self, world ):
        world[ "upstream" ] = self._upstream( 200, b"0123456789", { "Content-Length": "10" } )
        resp = world[ "client" ].get( "/api/podcast-drive/stream/A1" )
        assert resp.status_code == 200 and resp.content == b"0123456789" and resp.headers[ "accept-ranges" ] == "bytes"
        assert world[ "session" ].requests[ 0 ][ "headers" ] == {}

    def test_an_unsatisfiable_range_is_passed_through_as_416( self, world ):
        world[ "upstream" ] = self._upstream( 416, b"", { "Content-Range": "bytes */1000" } )
        resp = world[ "client" ].get( "/api/podcast-drive/stream/A1", headers={ "Range": "bytes=5000-" } )
        assert resp.status_code == 416 and resp.headers[ "content-range" ] == "bytes */1000"

    def test_the_body_is_streamed_in_chunks_and_the_upstream_is_closed( self, world ):
        holder = {}
        def respond( headers ):
            holder[ "up" ] = _Upstream( 200, b"0123456789", {} )
            return holder[ "up" ]
        world[ "upstream" ] = respond
        world[ "client" ].get( "/api/podcast-drive/stream/A1" )
        assert holder[ "up" ].chunk_size == router_mod.STREAM_CHUNK_BYTES and holder[ "up" ].closed is True

    @pytest.mark.asyncio
    async def test_the_first_chunk_is_sent_before_the_rest_is_read( self, world ):
        holder = {}
        def respond( headers ):
            holder[ "up" ] = _Upstream( 200, b"0123456789abcdefghij", {} )
            return holder[ "up" ]
        world[ "upstream" ] = respond
        request  = type( "Req", ( object, ), { "headers": {} } )()
        response = router_mod.stream_podcast_file( "A1", request, { "email": OWNER }, world[ "config" ] )
        first    = await response.body_iterator.__anext__()
        assert first == b"0123" and holder[ "up" ].yielded == 1, "one chunk read for the first send, not the whole file"
        assert holder[ "up" ].yielded < len( holder[ "up" ].body ) // 4, "the rest is still unread"
        rest = [ chunk async for chunk in response.body_iterator ]
        assert b"".join( [ first ] + rest ) == b"0123456789abcdefghij" and holder[ "up" ].yielded == 5

    @pytest.mark.parametrize( "file_id", [ "STRANGER", "J1", "TOP", "NOPE" ] )
    def test_a_file_outside_the_folder_is_404_and_never_opened( self, world, file_id ):
        world[ "upstream" ] = lambda headers: pytest.fail( "an outside file must never be requested from Drive" )
        assert world[ "client" ].get( f"/api/podcast-drive/stream/{file_id}" ).status_code == 404
        assert world[ "session" ].requests == []

    def test_a_missing_top_folder_is_404( self, world ):
        world[ "pub" ].folder_levels = [ "Nowhere" ]
        world[ "pub" ].folder_path   = "Nowhere"
        assert world[ "client" ].get( "/api/podcast-drive/stream/A1" ).status_code == 404

    def test_an_id_drive_calls_not_found_is_404( self, world ):
        assert world[ "client" ].get( "/api/podcast-drive/stream/NOPE" ).status_code == 404

    @pytest.mark.parametrize( "failing", [ "A1", "J1" ] )
    def test_any_other_drive_error_on_the_lookup_is_503_not_404( self, world, failing ):
        world[ "svc" ].get_fails[ failing ] = 500
        resp = world[ "client" ].get( "/api/podcast-drive/stream/A1" )
        assert resp.status_code == 503 and "Drive unavailable" in resp.json()[ "detail" ]
        assert world[ "session" ].requests == []

    def test_a_drive_failure_while_opening_is_503( self, world ):
        def boom( headers ): raise OSError( "connection reset" )
        world[ "upstream" ] = boom
        assert world[ "client" ].get( "/api/podcast-drive/stream/A1" ).status_code == 503


class TestRegistration:

    def test_main_imports_and_includes_the_router( self ):
        import os
        import cosa.utils.util as cu
        source = open( os.path.join( cu.get_project_root(), "src/lupin_app/main.py" ), encoding="utf-8" ).read()
        assert "podcast_drive" in source.split( "from cosa.rest.routers import", 1 )[ 1 ].split( "\n", 1 )[ 0 ]
        assert "app.include_router(podcast_drive.router)" in source

    def test_the_routes_are_under_the_documented_prefix( self ):
        assert sorted( ( r.path, tuple( sorted( r.methods ) ) ) for r in router_mod.router.routes ) == [
            ( "/api/podcast-drive/list", ( "GET", ) ), ( "/api/podcast-drive/stream/{drive_file_id}", ( "GET", ) ),
        ]
