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
# One leading date (YYYY-MM-DD or YYYY.MM.DD), a 6 or 8 digit time or run number, or an 8 hex serial with a digit in it.
_LEADING_STAMP_RE  = re.compile( r"^(?:\d{4}[-.]\d{2}[-.]\d{2}|\d{8}|\d{6}|(?=[0-9a-f]*\d)[0-9a-f]{8})(?:[-_ .]+|$)" )
_TRAILING_SERIAL_RE = re.compile( r"[-_ ]+(?=[0-9a-f]*\d)[0-9a-f]{8}$" )


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


def title_from_script_text( text ):
    """
    Read the plain title from the first "# " heading in a script's text.

    Requires:
        - text is a string

    Ensures:
        - returns the cleaned title, or None when there is no heading

    Raises:
        - nothing
    """
    match = _H1_RE.search( text )
    return clean_title( match.group( 1 ) ) if match else None


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
    return title_from_script_text( text )


def title_from_folder_name( folder_name ):
    """
    Make a plain title from a Drive job folder name, with no dates, times or serials.

    Requires:
        - folder_name is a string

    Ensures:
        - every leading run of date, time and serial is removed, however many there are, and so is a trailing 8-hex serial
        - dashes and underscores become spaces and each word is capitalised
        - returns the folder name unchanged when nothing is left after that

    Raises:
        - nothing
    """
    rest = folder_name
    while True:
        stripped = _LEADING_STAMP_RE.sub( "", rest )
        if stripped == rest: break
        rest = stripped
    rest  = _TRAILING_SERIAL_RE.sub( "", rest )
    words = rest.replace( "-", " " ).replace( "_", " " ).split()
    return " ".join( word[ :1 ].upper() + word[ 1: ] for word in words ) or folder_name


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


def script_link( script_rel ):
    """
    Build the Script link for one language on a finished podcast card.

    The link opens the script in the doc viewer. The viewer serves io/podcasts/<email>/ only to the person it
    belongs to, so the same link is safe on any card.

    Requires:
        - script_rel is a path relative to io/ ( "podcasts/<email>/<file>" ), or None

    Ensures:
        - returns None when there is no script
        - otherwise returns a markdown link to /app/docs?path=lupin/io/<script_rel>

    Raises:
        - nothing
    """
    if not script_rel: return None
    return f"[📝 Script](/app/docs?path={urllib.parse.quote( 'lupin/io/' + script_rel )})"


def io_relative( path, io_base ):
    """
    Turn an artifact path into the form the io viewer endpoints take, relative to io/.

    Matches the receiving logic in get_io_file ( cosa/rest/routers/io_files.py ), which accepts absolute,
    "io/" and slash-led forms.

    Requires:
        - path is a string or None
        - io_base is the absolute io directory with a trailing slash

    Ensures:
        - returns None for an empty path
        - strips the io_base prefix, else a leading "io/", else any leading slashes

    Raises:
        - nothing
    """
    if not path: return None
    if path.startswith( io_base ): return path[ len( io_base ): ]
    if path.startswith( "io/" ):   return path[ 3: ]
    return path.lstrip( "/" )


def ordered_languages( languages, audio_by_lang, script_by_lang ):
    """
    List the languages that produced an artifact: requested order first, then any extras.

    Requires:
        - languages is a list of language codes
        - audio_by_lang and script_by_lang are dicts keyed by language code

    Ensures:
        - returns each language once
        - requested languages come first, in request order, and only when they produced an artifact
        - extra languages that produced an artifact follow

    Raises:
        - nothing
    """
    ordered = [ l for l in languages if l in audio_by_lang or l in script_by_lang ]
    for l in list( audio_by_lang ) + list( script_by_lang ):
        if l not in ordered:
            ordered.append( l )
    return ordered


def language_card_lines( ordered_langs, names, audio_by_lang, script_by_lang, source_rel, io_base, drive_links ):
    """
    Build the per-language link lines of a finished podcast card.

    Each line reads "**Label**: 📝 Script | ▶️ Play Here | 🎧 Listen | ⬇️ Download | ☁️ Drive".

    Requires:
        - ordered_langs is a list of language codes
        - names maps a language code to its label
        - audio_by_lang and script_by_lang map a language code to an artifact path
        - source_rel is the player's source reference, or None
        - io_base is the absolute io directory with a trailing slash
        - drive_links maps a language code to its Drive link

    Ensures:
        - one line per language that has at least one link, in ordered_langs order
        - the label falls back to the language code

    Raises:
        - nothing
    """
    lines = []
    for lang in ordered_langs:
        label  = names.get( lang, lang )
        a_rel  = io_relative( audio_by_lang.get( lang ), io_base )
        s_rel  = io_relative( script_by_lang.get( lang ), io_base )
        parts  = []
        s_link = script_link( s_rel )
        if s_link: parts.append( s_link )
        if a_rel:
            title = read_script_title( io_base + s_rel ) if s_rel else None
            parts.append( audio_triplet( a_rel, s_rel, source_rel, title ) )
        if lang in drive_links: parts.append( f"[☁️ Drive]({drive_links[ lang ]})" )
        if parts:
            lines.append( f"**{label}**: " + " | ".join( parts ) )
    return lines
