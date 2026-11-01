#!/usr/bin/env python3
"""
Publish finished files to the user's own Google Drive.

The Google libraries are imported only inside the methods that need them. A caller that never
builds a real service (a disabled feature, or a test that injects a fake) imposes no Google dependency. The scope is drive.file: the app sees only files it created.

Setup steps and settings: src/docs/agents/podcast-generator-google-drive.md
"""

import json
import os

import cosa.utils.util as cu

SCOPES                   = [ "https://www.googleapis.com/auth/drive.file" ]
FOLDER_MIME_TYPE         = "application/vnd.google-apps.folder"
FOLDER_LINK_TEMPLATE     = "https://drive.google.com/drive/folders/{folder_id}"
DRIVE_MEDIA_URL          = "https://www.googleapis.com/drive/v3/files/{file_id}"
FOLDER_CACHE_REL_PATH    = "/src/conf/keys/google-drive-folder-id.json"
UPLOAD_CHUNK_SIZE_BYTES  = 8 * 1024 * 1024


class DrivePublishError( Exception ):
    """
    A Drive publish step failed.

    Raised for a missing token, a token that cannot be refreshed, and API errors. The message names
    the file or folder involved.
    """


class DrivePublisher:
    """
    Find-or-create Drive folders and upload files into them.

    Requires:
        - token_path names an authorized-user token written by src/scripts/google-drive-authorize.py,
          unless service is injected
        - folder_name is a non-empty string naming the top folder in Drive, or a slash-separated path
          such as "Lupin AF/Explainers"; empty levels are dropped and each level is trimmed

    Ensures:
        - the Drive service is built from the token only when service is None
        - the top folder is the last level of the path; each level is found or created under the one above
        - the top folder's id is cached in the folder cache file, keyed to the full path, and re-checked on every run
    """

    def __init__( self, token_path, folder_name, service=None, debug=False, folder_cache_path=None ):
        """
        Hold the settings and, when no service is injected, build the real one.

        Requires:
            - token_path and folder_name as described on the class
            - folder_cache_path is a writable file path, or None for the default under the project root

        Ensures:
            - self.service is the injected service, or one built from the token
            - self.folder_levels lists the path's levels and self.folder_path joins them with "/"

        Raises:
            - ValueError if folder_name has no level left after empty ones are dropped
            - DrivePublishError if the token is missing, unreadable or cannot be refreshed
        """
        self.token_path        = token_path
        self.folder_name       = folder_name
        self.folder_levels     = self._split_levels( folder_name )
        if not self.folder_levels: raise ValueError( f"folder_name has no folder level in it: {folder_name!r}" )
        self.folder_path       = "/".join( self.folder_levels )
        self.debug             = debug
        self.folder_cache_path = folder_cache_path if folder_cache_path is not None else cu.get_project_root() + FOLDER_CACHE_REL_PATH
        self.creds             = None
        self.service           = service if service is not None else self._build_service()

    def _build_service( self ):
        """
        Build the real Drive v3 service from the token file, refreshing an expired token.

        Ensures:
            - a refreshed token is written back to token_path with mode 600

        Raises:
            - DrivePublishError if the token file is missing, unreadable or cannot be refreshed
        """
        if not os.path.exists( self.token_path ):
            raise DrivePublishError( f"Google Drive token file missing: {self.token_path} (run src/scripts/google-drive-authorize.py)" )

        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        try:
            creds = Credentials.from_authorized_user_file( self.token_path, SCOPES )
        except ( ValueError, OSError ) as e:
            raise DrivePublishError( f"Google Drive token file unreadable: {self.token_path} ({e})" ) from e

        if not creds.valid:
            try:
                creds.refresh( Request() )
            except Exception as e:
                raise DrivePublishError( f"Google Drive token could not be refreshed ({e}); re-run src/scripts/google-drive-authorize.py" ) from e
            fd = os.open( self.token_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600 )
            with os.fdopen( fd, "w" ) as token_file: token_file.write( creds.to_json() )
            os.chmod( self.token_path, 0o600 )

        self.creds = creds
        return build( "drive", "v3", credentials=creds, cache_discovery=False )

    def _call( self, what, request ):
        """
        Execute one Drive API request, turning any failure into a DrivePublishError naming `what`.

        Requires:
            - request has an execute() method

        Ensures:
            - returns the response dict

        Raises:
            - DrivePublishError naming `what` and the underlying error
        """
        try:
            return request.execute()
        except Exception as e:
            raise DrivePublishError( f"{what}: {e}" ) from e

    @staticmethod
    def _split_levels( path ):
        """
        Split a slash-separated folder path into its levels.

        Requires:
            - path is a string

        Ensures:
            - returns the trimmed, non-empty levels in order; "A//B/" gives [ "A", "B" ]
        """
        return [ level.strip() for level in path.split( "/" ) if level.strip() ]

    def _read_cached_folder_id( self ):
        """
        Return the cached top-folder id for self.folder_path, or None when there is none usable.

        Ensures:
            - a missing, unreadable or other-name cache returns None
        """
        try:
            with open( self.folder_cache_path ) as cache_file: cached = json.load( cache_file )
        except ( OSError, ValueError ):
            return None
        if not isinstance( cached, dict ) or cached.get( "folder_name" ) != self.folder_path: return None
        return cached.get( "folder_id" )

    def _write_cached_folder_id( self, folder_id ):
        """
        Record the top-folder id for self.folder_path in the cache file.

        Ensures:
            - the cache file exists with mode 600 and names this folder name and id
        """
        os.makedirs( os.path.dirname( self.folder_cache_path ), exist_ok=True )
        fd = os.open( self.folder_cache_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600 )
        with os.fdopen( fd, "w" ) as cache_file:
            json.dump( { "folder_name": self.folder_path, "folder_id": folder_id }, cache_file )

    def _cached_folder_is_live( self, folder_id ):
        """
        Ask Drive whether a cached folder id still names a folder that is not in the trash.

        Ensures:
            - returns False for a trashed folder or one Drive cannot find
        """
        try:
            found = self._call( f"check folder {folder_id}", self.service.files().get( fileId=folder_id, fields="id,trashed" ) )
        except DrivePublishError:
            return False
        return not found.get( "trashed" )

    def ensure_folder( self, name, parent_id=None ):
        """
        Find a folder the app created, by name or slash-separated path, or create it.

        Requires:
            - name is a non-empty string; "A/B" means folder B inside folder A
            - parent_id is a Drive folder id, or None for the Drive root

        Ensures:
            - returns the id of the last level; each level is found or created under the one above
            - for the top folder (no parent, same levels as self.folder_name) a cached id that is still live
              is reused with no search, and a stale one is replaced and the cache rewritten

        Raises:
            - ValueError if name has no level in it
            - DrivePublishError on an API error, naming the folder
        """
        levels = self._split_levels( name )
        if not levels: raise ValueError( f"folder name has no folder level in it: {name!r}" )

        is_top = parent_id is None and levels == self.folder_levels
        if is_top:
            cached_id = self._read_cached_folder_id()
            if cached_id is not None and self._cached_folder_is_live( cached_id ):
                if self.debug: print( f"[DrivePublisher] reusing cached folder id for {self.folder_path}" )
                return cached_id

        folder_id = parent_id
        for level in levels: folder_id = self._find_or_create( level, folder_id )

        if is_top: self._write_cached_folder_id( folder_id )
        return folder_id

    def _find_or_create( self, name, parent_id ):
        """
        Find one folder by exact name under a parent, or create it.

        Requires:
            - name is a non-empty string; a "/" in it is part of the name
            - parent_id is a Drive folder id, or None for the Drive root

        Ensures:
            - returns the folder id

        Raises:
            - DrivePublishError on an API error, naming the folder
        """
        found = self._find_only( name, parent_id )
        if found is not None: return found

        body = { "name": name, "mimeType": FOLDER_MIME_TYPE }
        if parent_id is not None: body[ "parents" ] = [ parent_id ]
        folder_id = self._call( f"create folder {name}", self.service.files().create( body=body, fields="id" ) )[ "id" ]
        if self.debug: print( f"[DrivePublisher] created folder {name}" )
        return folder_id

    def find_top_folder( self ):
        """
        Find the configured top folder without creating anything.

        Ensures:
            - returns the id of the last level of self.folder_path, or None when any level is absent
            - a cached id that is still live is returned with no search

        Raises:
            - DrivePublishError on an API error
        """
        cached_id = self._read_cached_folder_id()
        if cached_id is not None and self._cached_folder_is_live( cached_id ): return cached_id

        folder_id = None
        for level in self.folder_levels:
            folder_id = self._find_only( level, folder_id )
            if folder_id is None: return None
        return folder_id

    def _find_only( self, name, parent_id ):
        """
        Find one folder by exact name under a parent. Never creates.

        Requires:
            - name is a non-empty string
            - parent_id is a Drive folder id, or None for the Drive root

        Ensures:
            - returns the first matching folder id, or None

        Raises:
            - DrivePublishError on an API error
        """
        escaped = name.replace( "\\", "\\\\" ).replace( "'", "\\'" )
        query   = f"name = '{escaped}' and mimeType = '{FOLDER_MIME_TYPE}' and trashed = false"
        if parent_id is not None: query += f" and '{parent_id}' in parents"
        listing = self._call( f"find folder {name}", self.service.files().list( q=query, fields="files(id)", spaces="drive" ) )
        matches = listing.get( "files" ) or []
        return matches[ 0 ][ "id" ] if matches else None

    def list_job_folders( self, top_id, limit=50 ):
        """
        List the job subfolders of the top folder, newest first.

        Requires:
            - top_id is a Drive folder id
            - limit is a positive integer

        Ensures:
            - returns up to limit dicts { "id", "name", "createdTime" }, newest first

        Raises:
            - DrivePublishError on an API error
        """
        query   = f"'{top_id}' in parents and mimeType = '{FOLDER_MIME_TYPE}' and trashed = false"
        listing = self._call( "list job folders", self.service.files().list(
            q=query, fields="files(id,name,createdTime)", spaces="drive", orderBy="createdTime desc", pageSize=limit ) )
        return listing.get( "files" ) or []

    def list_folder_files( self, folder_id ):
        """
        List the files (not folders) inside one job folder.

        Requires:
            - folder_id is a Drive folder id

        Ensures:
            - returns dicts { "id", "name", "mimeType", "size" }; size is a string of bytes or absent

        Raises:
            - DrivePublishError on an API error
        """
        query   = f"'{folder_id}' in parents and mimeType != '{FOLDER_MIME_TYPE}' and trashed = false"
        listing = self._call( f"list files in {folder_id}", self.service.files().list(
            q=query, fields="files(id,name,mimeType,size)", spaces="drive", orderBy="name", pageSize=100 ) )
        return listing.get( "files" ) or []

    def file_inside_top_folder( self, file_id, top_id ):
        """
        Say whether a file sits in a job folder directly under the top folder.

        Requires:
            - file_id is any Drive file id, including one from a stranger
            - top_id is the top folder's id

        Ensures:
            - returns { "id", "name", "mimeType", "size" } when the file is not a folder, is not trashed,
              and its parent is a folder whose parent is top_id
            - returns None for anything else, including an id Drive cannot find

        Raises:
            - nothing
        """
        try:
            meta = self._call( f"check file {file_id}", self.service.files().get( fileId=file_id, fields="id,name,mimeType,size,parents,trashed" ) )
            if meta.get( "trashed" ) or meta.get( "mimeType" ) == FOLDER_MIME_TYPE: return None
            for parent_id in meta.get( "parents" ) or []:
                parent = self._call( f"check folder {parent_id}", self.service.files().get( fileId=parent_id, fields="id,mimeType,parents,trashed" ) )
                if parent.get( "mimeType" ) == FOLDER_MIME_TYPE and not parent.get( "trashed" ) and top_id in ( parent.get( "parents" ) or [] ):
                    return { key: meta[ key ] for key in ( "id", "name", "mimeType", "size" ) if key in meta }
        except DrivePublishError:
            return None
        return None

    def read_head( self, file_id, max_bytes=4096 ):
        """
        Read the first bytes of a file, for a title.

        Requires:
            - file_id is a Drive file id
            - max_bytes is a positive integer

        Ensures:
            - returns at most max_bytes of the file as bytes

        Raises:
            - DrivePublishError on an API error
        """
        request = self.service.files().get_media( fileId=file_id )
        request.headers[ "Range" ] = f"bytes=0-{max_bytes - 1}"
        return self._call( f"read file {file_id}", request )[ :max_bytes ]

    def _authorized_session( self ):
        """
        Build a requests session signed with the Drive token.

        Ensures:
            - returns a google.auth AuthorizedSession, which refreshes the token when it expires

        Raises:
            - DrivePublishError when the publisher was given a service and so holds no credentials
        """
        if self.creds is None: raise DrivePublishError( "no Drive credentials: the publisher was built with an injected service" )
        from google.auth.transport.requests import AuthorizedSession
        return AuthorizedSession( self.creds )

    def open_media( self, file_id, range_header=None ):
        """
        Open a file's bytes as a streamed HTTP response, passing a Range header through.

        Requires:
            - file_id is a Drive file id the caller has already checked with file_inside_top_folder
            - range_header is a "bytes=..." string, or None for the whole file

        Ensures:
            - returns the open streaming response (status 200, 206 or 416); the caller closes it

        Raises:
            - DrivePublishError if the request cannot be made
        """
        headers = { "Range": range_header } if range_header else {}
        try:
            return self._authorized_session().get( DRIVE_MEDIA_URL.format( file_id=file_id ), params={ "alt": "media" }, headers=headers, stream=True, timeout=30 )
        except DrivePublishError:
            raise
        except Exception as e:
            raise DrivePublishError( f"stream file {file_id}: {e}" ) from e

    def upload( self, local_path, mime_type, parent_id ):
        """
        Upload one file into a folder with a resumable upload.

        Requires:
            - local_path names an existing file
            - parent_id is a Drive folder id

        Ensures:
            - returns { "file_id", "web_view_link" }

        Raises:
            - DrivePublishError naming the file on any failure
        """
        from googleapiclient.http import MediaFileUpload

        name = os.path.basename( local_path )
        try:
            media = MediaFileUpload( local_path, mimetype=mime_type, chunksize=UPLOAD_CHUNK_SIZE_BYTES, resumable=True )
        except Exception as e:
            raise DrivePublishError( f"upload {name}: {e}" ) from e

        created = self._call(
            f"upload {name}",
            self.service.files().create( body={ "name": name, "parents": [ parent_id ] }, media_body=media, fields="id,webViewLink" )
        )
        return { "file_id": created[ "id" ], "web_view_link": created.get( "webViewLink" ) }

    def publish_job( self, job_folder_name, files ):
        """
        Make this job's subfolder under the top folder and upload each file into it.

        Requires:
            - job_folder_name is a non-empty string
            - files is a list of ( local_path, mime_type ) pairs

        Ensures:
            - returns { "folder_id", "folder_link", "files" } where each entry of "files" is
              { "path", "file_id", "web_view_link", "error" } with error None on success
            - one failed file does not stop the rest

        Raises:
            - DrivePublishError if a folder cannot be found or made
        """
        top_id    = self.ensure_folder( self.folder_name )
        folder_id = self._find_or_create( job_folder_name, top_id )
        results   = []
        for local_path, mime_type in files:
            try:
                uploaded = self.upload( local_path, mime_type, folder_id )
                results.append( { "path": local_path, "file_id": uploaded[ "file_id" ], "web_view_link": uploaded[ "web_view_link" ], "error": None } )
            except DrivePublishError as e:
                results.append( { "path": local_path, "file_id": None, "web_view_link": None, "error": str( e ) } )
        return { "folder_id": folder_id, "folder_link": FOLDER_LINK_TEMPLATE.format( folder_id=folder_id ), "files": results }
