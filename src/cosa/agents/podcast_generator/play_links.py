#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Shared builder for the audio links on a finished podcast card.

Both podcast jobs ( podcast_generator and deep_research_to_podcast ) put the same three links on a card:
Play Here, Listen and Download. Play Here and Listen open the player page. That page needs the script, the
original document and a plain-words title. The script and the mp3 carry different time stamps in their
file names. So the player cannot pair them by name, and the job passes the paths instead.
"""

import re
import urllib.parse

_PODCAST_PREFIX_RE = re.compile( r"^\s*podcast\s*:\s*", re.IGNORECASE )
_H1_RE             = re.compile( r"^#[ \t]+(.+?)[ \t]*$", re.MULTILINE )


def clean_title( heading ):
    """
    Turn a script's first heading into the title a person would say.

    Requires:
        - heading is a string or None

    Ensures:
        - returns the heading without a leading "Podcast:" label and without surrounding spaces
        - returns None when nothing is left

    Raises:
        - nothing
    """
    if heading is None: return None
    title = _PODCAST_PREFIX_RE.sub( "", heading ).strip()
    return title if title else None


def read_script_title( script_abs_path ):
    """
    Read the plain title from a script file's first "# " heading.

    Requires:
        - script_abs_path is a path string or None

    Ensures:
        - returns the cleaned title, or None when the path is empty, the file is unreadable, or it has no heading

    Raises:
        - nothing
    """
    if not script_abs_path: return None
    try:
        with open( script_abs_path, "r", encoding="utf-8" ) as handle:
            text = handle.read()
    except OSError:
        return None
    match = _H1_RE.search( text )
    return clean_title( match.group( 1 ) ) if match else None


def source_ref( path, project_root ):
    """
    Name the original document the way the player page expects.

    Requires:
        - path is a string or None
        - project_root is the absolute project directory without a trailing slash

    Ensures:
        - a file under io/ comes back as "io/<rel>", which the player fetches with the user's token
        - any other file in the project comes back as "lupin/<rel>", which the doc viewer opens
        - an empty path, or an absolute path outside the project, comes back as None

    Raises:
        - nothing
    """
    if not path: return None
    if path.startswith( project_root + "/" ): path = path[ len( project_root ) + 1: ]
    elif path.startswith( "/" ):              return None
    return path if path.startswith( "io/" ) else "lupin/" + path


def player_query( audio_rel, script_rel=None, source_rel=None, title=None ):
    """
    Build the query string the player page reads.

    Requires:
        - audio_rel is a non-empty path relative to io/
        - script_rel, source_rel and title are strings or None

    Ensures:
        - starts with path=<audio_rel>
        - adds script=, source= and title= only when given; an absent value is left out, never written empty

    Raises:
        - nothing
    """
    query = "path=" + urllib.parse.quote( audio_rel )
    if script_rel: query += "&script=" + urllib.parse.quote( script_rel )
    if source_rel: query += "&source=" + urllib.parse.quote( source_rel )
    if title:      query += "&title=" + urllib.parse.quote( title, safe="" )
    return query


def audio_triplet( audio_rel, script_rel=None, source_rel=None, title=None ):
    """
    Build the Play Here | Listen | Download markdown for one audio file.

    Requires:
        - audio_rel is a non-empty path relative to io/

    Ensures:
        - Play Here is the player URL with embed=1; Listen is the same URL without it
        - both carry the script, source and title values when given
        - Download is the raw file link, unchanged

    Raises:
        - nothing
    """
    query = player_query( audio_rel, script_rel, source_rel, title )
    enc   = urllib.parse.quote( audio_rel )
    return (
        f"[▶️ Play Here](/app/audio?{query}&embed=1) | "
        f"[🎧 Listen](/app/audio?{query}) | "
        f"[⬇️ Download](/api/io/file?path={enc}&download=true)"
    )


def script_link( audio_rel, script_rel=None, source_rel=None, title=None ):
    """
    Build the Script link for one language on a finished podcast card.

    The doc viewer cannot open io/podcasts files, which are per user. So the link opens the player page
    with open=script, and that page reads the script with the user's login and shows it on the page.

    Requires:
        - audio_rel is a path relative to io/, or None
        - script_rel, source_rel and title are strings or None

    Ensures:
        - returns None when there is no audio or no script, because there is then no player page to open
        - otherwise returns the markdown link to the player URL with open=script, carrying the same query as Listen

    Raises:
        - nothing
    """
    if not audio_rel or not script_rel: return None
    return f"[📝 Script](/app/audio?{player_query( audio_rel, script_rel, source_rel, title )}&open=script)"
