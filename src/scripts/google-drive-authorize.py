#!/usr/bin/env python3
"""
One-time Google Drive authorization for podcast publishing.

Runs the installed-app OAuth flow (scope drive.file) in a browser and saves the refresh token with mode 600.
Then it makes one call that lists the app's own files and prints the account email.

Usage:
    LUPIN_ROOT="$PWD" PYTHONPATH="$PWD/src" .venv/bin/python src/scripts/google-drive-authorize.py

Reads:  src/conf/keys/google-drive-oauth-client.json  (the Desktop-app OAuth client ID)
Writes: src/conf/keys/google-drive-oauth-token.json

Setup steps: src/docs/agents/podcast-generator-google-drive.md
"""

# Bootstrap: this runs before cosa is importable, so it puts src/ on sys.path itself.
import os
import sys

lupin_root = os.environ.get( "LUPIN_ROOT" )
if lupin_root is None:
    raise RuntimeError( "LUPIN_ROOT not set — export LUPIN_ROOT=/path/to/project" )
src_path = os.path.join( lupin_root, "src" )
if src_path not in sys.path: sys.path.insert( 0, src_path )

import cosa.utils.util as cu

SCOPES              = [ "https://www.googleapis.com/auth/drive.file" ]
CLIENT_REL_PATH     = "/src/conf/keys/google-drive-oauth-client.json"
TOKEN_REL_PATH      = "/src/conf/keys/google-drive-oauth-token.json"


def run_flow( client_path ):
    """
    Open the browser consent page and return the credentials the user grants.

    Requires:
        - client_path names the Desktop-app OAuth client JSON

    Ensures:
        - returns google credentials carrying a refresh token
    """
    from google_auth_oauthlib.flow import InstalledAppFlow
    return InstalledAppFlow.from_client_secrets_file( client_path, SCOPES ).run_local_server( port=0 )


def write_token( creds, token_path ):
    """
    Save the credentials as JSON with mode 600.

    Requires:
        - creds has to_json()
        - the folder of token_path exists

    Ensures:
        - the file holds creds.to_json() and its mode is 600, even if it existed with another mode
    """
    fd = os.open( token_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600 )
    with os.fdopen( fd, "w" ) as token_file: token_file.write( creds.to_json() )
    os.chmod( token_path, 0o600 )


def verify( creds ):
    """
    Make one real call: list the app's own files and read the account email.

    Requires:
        - creds are valid Drive credentials

    Ensures:
        - returns ( email, file_names ) where file_names are the app's own files, at most ten
    """
    from googleapiclient.discovery import build
    service = build( "drive", "v3", credentials=creds, cache_discovery=False )
    email   = service.about().get( fields="user(emailAddress)" ).execute()[ "user" ][ "emailAddress" ]
    files   = service.files().list( pageSize=10, fields="files(name)" ).execute().get( "files", [] )
    return email, [ f[ "name" ] for f in files ]


def main():
    """
    Authorize, save the token and verify it.

    Ensures:
        - returns 0 after printing the account email and the app's own file names
        - returns 2, writing nothing, when the OAuth client file is missing
    """
    root        = cu.get_project_root()
    client_path = root + CLIENT_REL_PATH
    token_path  = root + TOKEN_REL_PATH

    if not os.path.exists( client_path ):
        print( f"OAuth client file missing: {client_path}\nCreate a Desktop-app OAuth client ID in Google Cloud Console and save it there." )
        return 2

    creds = run_flow( client_path )
    write_token( creds, token_path )
    email, names = verify( creds )
    print( f"Authorized as {email}. Token saved to {token_path}." )
    print( f"App's own files in Drive: {', '.join( names ) if names else '(none yet)'}" )
    return 0


if __name__ == "__main__":  # pragma: no cover - runs only when the file is executed as a script, never on import
    sys.exit( main() )
