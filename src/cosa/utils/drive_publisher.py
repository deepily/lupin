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
        - folder_name is a non-empty string, the top-level folder in Drive

    Ensures:
        - the Drive service is built from the token only when service is None
        - the top folder's id is cached in the folder cache file and re-checked on every run
    """

    def __init__( self, token_path, folder_name, service=None, debug=False, folder_cache_path=None ):
        """
        Hold the settings and, when no service is injected, build the real one.

        Requires:
            - token_path and folder_name as described on the class
            - folder_cache_path is a writable file path, or None for the default under the project root

        Ensures:
            - self.service is the injected service, or one built from the token

        Raises:
            - DrivePublishError if the token is missing, unreadable or cannot be refreshed
        """
        self.token_path        = token_path
        self.folder_name       = folder_name
        self.debug             = debug
        self.folder_cache_path = folder_cache_path if folder_cache_path is not None else cu.get_project_root() + FOLDER_CACHE_REL_PATH
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

    def _read_cached_folder_id( self ):
        """
        Return the cached top-folder id for self.folder_name, or None when there is none usable.

        Ensures:
            - a missing, unreadable or other-name cache returns None
        """
        try:
            with open( self.folder_cache_path ) as cache_file: cached = json.load( cache_file )
        except ( OSError, ValueError ):
            return None
        if not isinstance( cached, dict ) or cached.get( "folder_name" ) != self.folder_name: return None
        return cached.get( "folder_id" )

    def _write_cached_folder_id( self, folder_id ):
        """
        Record the top-folder id for self.folder_name in the cache file.

        Ensures:
            - the cache file exists with mode 600 and names this folder name and id
        """
        os.makedirs( os.path.dirname( self.folder_cache_path ), exist_ok=True )
        fd = os.open( self.folder_cache_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600 )
        with os.fdopen( fd, "w" ) as cache_file:
            json.dump( { "folder_name": self.folder_name, "folder_id": folder_id }, cache_file )

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
        Find a folder the app created, by name, or create it.

        Requires:
            - name is a non-empty string
            - parent_id is a Drive folder id, or None for the Drive root

        Ensures:
            - returns the folder id
            - for the top folder (no parent, name == self.folder_name) a cached id that is still live is
              reused with no search, and a stale one is replaced and the cache rewritten

        Raises:
            - DrivePublishError on an API error, naming the folder
        """
        is_top = parent_id is None and name == self.folder_name
        if is_top:
            cached_id = self._read_cached_folder_id()
            if cached_id is not None and self._cached_folder_is_live( cached_id ):
                if self.debug: print( f"[DrivePublisher] reusing cached folder id for {name}" )
                return cached_id

        escaped = name.replace( "\\", "\\\\" ).replace( "'", "\\'" )
        query   = f"name = '{escaped}' and mimeType = '{FOLDER_MIME_TYPE}' and trashed = false"
        if parent_id is not None: query += f" and '{parent_id}' in parents"

        listing = self._call( f"find folder {name}", self.service.files().list( q=query, fields="files(id)", spaces="drive" ) )
        matches = listing.get( "files" ) or []
        if matches:
            folder_id = matches[ 0 ][ "id" ]
        else:
            body = { "name": name, "mimeType": FOLDER_MIME_TYPE }
            if parent_id is not None: body[ "parents" ] = [ parent_id ]
            folder_id = self._call( f"create folder {name}", self.service.files().create( body=body, fields="id" ) )[ "id" ]
            if self.debug: print( f"[DrivePublisher] created folder {name}" )

        if is_top: self._write_cached_folder_id( folder_id )
        return folder_id

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
        folder_id = self.ensure_folder( job_folder_name, parent_id=top_id )
        results   = []
        for local_path, mime_type in files:
            try:
                uploaded = self.upload( local_path, mime_type, folder_id )
                results.append( { "path": local_path, "file_id": uploaded[ "file_id" ], "web_view_link": uploaded[ "web_view_link" ], "error": None } )
            except DrivePublishError as e:
                results.append( { "path": local_path, "file_id": None, "web_view_link": None, "error": str( e ) } )
        return { "folder_id": folder_id, "folder_link": FOLDER_LINK_TEMPLATE.format( folder_id=folder_id ), "files": results }
