#!/usr/bin/env python3
"""
The one shared Google Drive hook for both podcast jobs.

PodcastGeneratorJob and DeepResearchToPodcastJob each call publish_podcast_to_drive() after their
audio is written and before the completion abstract is built. The publish flag is read before
cosa.utils.drive_publisher (and so any Google module) is imported.

Setup steps and settings: src/docs/agents/podcast-generator-google-drive.md
"""

import asyncio
import mimetypes
import os
import re
from datetime import datetime

import cosa.utils.util as cu

AUDIO_MIME_TYPE  = "audio/mpeg"
SCRIPT_MIME_TYPE = "text/markdown"


def make_job_folder_name( source_path ):
    """
    Build the per-job Drive subfolder name, <timestamp>-<topic>.

    Requires:
        - source_path is a non-empty path string

    Ensures:
        - returns a string with no path separators, topic taken from the file name without its extension
    """
    topic = re.sub( r"[^A-Za-z0-9._-]+", "-", os.path.splitext( os.path.basename( source_path ) )[ 0 ] ).strip( "-" )
    return f"{datetime.now().strftime( '%Y-%m-%d-%H%M%S' )}-{topic}"


def resolve_source_path( path ):
    """
    Resolve a job's source-document path against the project root when it is relative.

    Requires:
        - path is a string or None

    Ensures:
        - None or empty returns None; an absolute path is returned unchanged; a relative one is joined to the project root
    """
    if not path: return None
    return path if path.startswith( "/" ) else cu.get_project_root() + "/" + path


def _make_publisher( config ):
    """
    Build the real DrivePublisher from the config.

    Imports the Google-facing module, so it runs only when publishing is switched on.
    Tests replace this function with one that returns a fake.

    Requires:
        - config.drive_token_path is relative to the project root and starts with "/"
        - config.drive_folder_name is a non-empty string

    Ensures:
        - returns a DrivePublisher

    Raises:
        - DrivePublishError if the token is missing or unusable
    """
    from cosa.utils.drive_publisher import DrivePublisher
    return DrivePublisher( cu.get_project_root() + config.drive_token_path, config.drive_folder_name )


def _collect_files( audio_by_lang, script_by_lang, source_path, config ):
    """
    List the ( path, mime_type ) pairs to upload, mp3s first.

    Ensures:
        - one mp3 per language that has audio
        - one script per language only when config.drive_upload_script is on
        - the source document once, only when its flag is on and the file exists
    """
    files = [ ( path, AUDIO_MIME_TYPE ) for path in audio_by_lang.values() if path ]
    if config.drive_upload_script:
        files += [ ( path, SCRIPT_MIME_TYPE ) for path in script_by_lang.values() if path ]
    if config.drive_upload_source_document and source_path and os.path.exists( source_path ):
        files.append( ( source_path, mimetypes.guess_type( source_path )[ 0 ] or "application/octet-stream" ) )
    return files


def _publish_sync( audio_by_lang, script_by_lang, source_path, job_folder_name, config ):
    """
    Build the publisher and upload everything.

    Blocking; the caller runs it in a worker thread.

    Ensures:
        - returns the publisher's publish_job() result
    """
    publisher = _make_publisher( config )
    return publisher.publish_job( job_folder_name, _collect_files( audio_by_lang, script_by_lang, source_path, config ) )


async def publish_podcast_to_drive( audio_by_lang, script_by_lang, source_path, job_folder_name, config ):
    """
    Upload a finished podcast to Google Drive when publishing is on, and never fail the job.

    Requires:
        - audio_by_lang and script_by_lang map language to an absolute file path
        - source_path is the resolved absolute path of the source document, not a relative job argument
        - config carries the five drive_* fields and publish_to_google_drive

    Ensures:
        - flag off: returns the empty result and imports no Google module
        - success: "language_links" maps each language with an uploaded mp3 to its Drive link, and
          "extra_lines" carries one "**Drive folder**" line
        - any failure (including a non-Drive exception): "extra_lines" carries one
          "**Drive**: upload failed (<ExceptionType>: <reason>)" line and the caller still succeeds
        - "folder_link" is the job folder's link, or None
    """
    result = { "language_links": {}, "extra_lines": [], "folder_link": None }
    if not config.publish_to_google_drive: return result

    try:
        published = await asyncio.to_thread( _publish_sync, audio_by_lang, script_by_lang, source_path, job_folder_name, config )
    except Exception as e:  # noqa: BLE001 - the podcast is already made; any upload failure (Drive, network, disk, bad token file) must not fail the job
        result[ "extra_lines" ].append( f"**Drive**: upload failed ({type( e ).__name__}: {e})" )
        return result

    link_by_path = { f[ "path" ]: f[ "web_view_link" ] for f in published[ "files" ] if f[ "error" ] is None }
    result[ "language_links" ] = { lang: link_by_path[ path ] for lang, path in audio_by_lang.items() if link_by_path.get( path ) }
    result[ "folder_link" ]    = published[ "folder_link" ]
    result[ "extra_lines" ].append( f"**Drive folder**: [☁️ Open]({published[ 'folder_link' ]})" )
    failed = [ f"{os.path.basename( f[ 'path' ] )}: {f[ 'error' ]}" for f in published[ "files" ] if f[ "error" ] is not None ]
    if failed: result[ "extra_lines" ].append( f"**Drive**: upload failed ({'; '.join( failed )})" )
    return result
