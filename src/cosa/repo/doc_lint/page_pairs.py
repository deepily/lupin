"""
Page pairs: whole-page before and after texts, cut into chunks the claim harness can read.

The claim harness takes one old text and one new text per pair. A page is far longer than a docstring.
One reply listing every claim of an eighteen thousand word page is the untested case.
So the old page is cut at its section headings into chunks of about a fixed word count.
Each chunk is paired with the whole new text, an index plus its parts for a split page.
Nothing here calls a model.
"""

import argparse
import json
import re
import subprocess
import sys

DEFAULT_TARGET_WORDS = 600

SECTION_START = re.compile( r"^#{2,3}\s+\S" )
FENCE         = re.compile( r"^\s*(```|~~~)" )


def split_sections( text ):
    """
    Cut a page at its second and third level headings.

    Requires:
        - text is a str

    Ensures:
        - "".join( result ) == text
        - a section starts at a line beginning with ## or ###, never at one inside a fenced block
        - the text before the first heading is the first section
        - a page with no heading is one section; an empty text gives an empty list
    """
    sections = []
    current  = []
    fence    = None
    for line in text.splitlines( keepends=True ):
        match = FENCE.match( line )
        if match:
            if fence is None: fence = match.group( 1 )
            elif match.group( 1 ) == fence: fence = None
        if fence is None and not match and SECTION_START.match( line ) and current:
            sections.append( "".join( current ) )
            current = []
        current.append( line )
    if current: sections.append( "".join( current ) )
    return sections


def chunk_text( text, target_words=DEFAULT_TARGET_WORDS ):
    """
    Group consecutive sections into chunks of about target_words words.

    Requires:
        - text is a str
        - target_words is a positive int

    Ensures:
        - "".join( result ) == text, except that a text of only whitespace gives an empty list
        - a section is never cut: one longer than the target is a chunk of its own
        - a chunk is closed before the section that would take it past the target
        - no chunk is blank; a blank leading section is folded into the chunk after it
    """
    chunks = []
    held   = ""
    for section in split_sections( text ):
        if held.strip() and len( held.split() ) + len( section.split() ) > target_words:
            chunks.append( held )
            held = ""
        held += section
    if held.strip(): chunks.append( held )
    return chunks


def page_pairs( page_id, old_text, new_text, target_words=DEFAULT_TARGET_WORDS ):
    """
    Build the harness pairs of one page.

    Requires:
        - page_id is a non-empty str, unique among the pages of a run

    Ensures:
        - returns one { id, old, new } per chunk of old_text, ids page_id plus "#" and a three digit counter
        - every pair carries new_text whole
    """
    return [ { "id": f"{page_id}#{n:03d}", "old": chunk, "new": new_text }
             for n, chunk in enumerate( chunk_text( old_text, target_words ) ) ]


def join_new_text( parts ):
    """
    Join the files of a new page into one text.

    Requires:
        - parts is a list of ( path, text ) in reading order, the index first

    Ensures:
        - each file's text follows a header line naming its path, so a judge can tell the parts apart
        - an empty list gives an empty text
    """
    return "".join( f"<!-- file: {path} -->\n\n{text.rstrip()}\n\n" for path, text in parts )


def read_at( root, ref, path ):
    """
    Read a file as it was at a git revision.

    Requires:
        - root is a git working tree, ref a revision it knows

    Ensures:
        - returns the text, decoded as UTF-8 with replacement
        - returns None when the path does not exist at that revision
    """
    res = subprocess.run( [ "git", "-C", root, "show", f"{ref}:{path}" ], capture_output=True )
    if res.returncode != 0: return None
    return res.stdout.decode( "utf-8", "replace" )


def build_pairs( root, manifest, target_words=DEFAULT_TARGET_WORDS ):
    """
    Build the harness pairs of every page in a manifest.

    Requires:
        - manifest is a list of { page, old_ref, old_path, new_ref, new_paths }
        - new_paths lists the index first, then its parts

    Ensures:
        - old text is read at old_ref and new text at new_ref, so a rerun after a later rewrite
          changes only the pairs whose text changed
        - pairs come in manifest order, chunks in page order

    Raises:
        - ValueError naming the page and the path when an old or a new path is missing at its revision
    """
    pairs = []
    for entry in manifest:
        old_text = read_at( root, entry[ "old_ref" ], entry[ "old_path" ] )
        if old_text is None:
            raise ValueError( f"{entry[ 'page' ]}: {entry[ 'old_path' ]} is missing at {entry[ 'old_ref' ]}" )
        parts = []
        for path in entry[ "new_paths" ]:
            text = read_at( root, entry[ "new_ref" ], path )
            if text is None:
                raise ValueError( f"{entry[ 'page' ]}: {path} is missing at {entry[ 'new_ref' ]}" )
            parts.append( ( path, text ) )
        pairs.extend( page_pairs( entry[ "page" ], old_text, join_new_text( parts ), target_words ) )
    return pairs


def main( argv=None ):
    """
    Command line: read a manifest, write the pairs file the harness reads.

    Requires:
        - --root names a git working tree, --manifest a JSON list as build_pairs reads it

    Ensures:
        - writes --out as a JSON list of pairs and prints the page and pair counts
        - returns 0
    """
    parser = argparse.ArgumentParser( description="Cut whole pages into claim harness pairs." )
    parser.add_argument( "--root", required=True )
    parser.add_argument( "--manifest", required=True )
    parser.add_argument( "--out", required=True )
    parser.add_argument( "--target-words", type=int, default=DEFAULT_TARGET_WORDS )
    args = parser.parse_args( argv )
    with open( args.manifest, encoding="utf-8" ) as f: manifest = json.load( f )
    pairs = build_pairs( args.root, manifest, args.target_words )
    with open( args.out, "w", encoding="utf-8" ) as f: json.dump( pairs, f, indent=1 )
    print( f"{len( manifest )} pages, {len( pairs )} pairs, written to {args.out}" )
    return 0


if __name__ == "__main__":
    sys.exit( main() )
