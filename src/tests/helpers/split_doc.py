"""
Read a reference page that has been split into an index and parts.

A split page keeps its old path as a short index. Its content is in a folder named after the page.
A test that asserts on the page's text reads the index and every part through this helper.
It then fails loudly when the parts are missing, instead of reading an index and finding nothing.
"""

import os


def read_split_page( root, relative_path ):
    """
    Return the text of a page and of every part in the folder named after it.

    Requires:
        - root is the project root as a str or Path
        - relative_path is the page's path from root, ending in ".md"
        - the page's parts sit in the folder named after the page, with the same stem

    Ensures:
        - returns the index text followed by each part's text, in file-name order, joined by newlines
        - at least one part was read

    Raises:
        - FileNotFoundError if the index is missing
        - AssertionError if the folder holds no parts
    """
    index  = os.path.join( str( root ), relative_path )
    folder = index[ : -len( ".md" ) ]
    parts  = sorted( os.path.join( folder, name ) for name in os.listdir( folder ) if name.endswith( ".md" ) ) if os.path.isdir( folder ) else []
    assert len( parts ) > 0, f"no parts found in {folder}: the page is an index and its content is in its parts"
    texts  = []
    for path in [ index ] + parts:
        with open( path, encoding="utf-8" ) as handle:
            texts.append( handle.read() )
    return "\n".join( texts )
