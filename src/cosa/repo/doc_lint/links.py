"""
Link and Design-path resolution for the docstring and markdown linters (rule 6).

A relative markdown link and a `Design:` path must point at a file that exists. The search
covers tracked and untracked files alike, because the question is whether a reader can open it.
"""

import os
import re

from .text_rules import Finding, line_of_offset

MD_LINK_REGEX = re.compile( r"\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)" )
DESIGN_REGEX  = re.compile( r"Design:\s*`?([\w./\-]+\.\w+)" )
EXTERNAL      = ( "http://", "https://", "mailto:", "#", "/app/", "tel:" )


def markdown_link_findings( text, path, root ):
    """
    Report relative markdown links whose target file does not exist.

    Requires:
        - text is markdown source
        - path is the repo-relative path of the page
        - root is the repo working tree

    Ensures:
        - external links, anchors-only links and doc-viewer links are skipped
        - a fragment or query is removed before the existence check
        - one Finding per dead link, at its line

    Raises:
        - nothing
    """
    findings = []
    base = os.path.dirname( path )
    for m in MD_LINK_REGEX.finditer( text ):
        target = m.group( 1 )
        if target.startswith( EXTERNAL ): continue
        target = re.split( r"[#?]", target, maxsplit=1 )[ 0 ]
        if not target: continue
        full = os.path.join( root, target.lstrip( "/" ) if target.startswith( "/" ) else os.path.join( base, target ) )
        if not os.path.exists( full ):
            findings.append( Finding( path, 1 + line_of_offset( text, m.start() ), "dead-link", f"link target {m.group( 1 )!r} does not exist" ) )
    return findings


def is_outside_root( design_path ):
    """
    Say whether a Design path cannot be judged from inside the repo tree.

    Requires:
        - design_path is a path string as written in a docstring

    Ensures:
        - True for any absolute path, even one that sits under this machine's root
        - True for a relative path that leaves the root once normalised
        - decided by the path's shape alone, never by comparing it to the root string

    Raises:
        - nothing
    """
    if os.path.isabs( design_path ): return True
    flat = os.path.normpath( design_path )
    return flat == ".." or flat.startswith( "../" )


def design_path_findings( text, path, first_line, root, not_checked=None ):
    """
    Report `Design:` paths that do not exist.

    Requires:
        - text is a docstring or page
        - first_line is the 1-based file line of the first line of text
        - root is the repo working tree
        - not_checked is a list or None

    Ensures:
        - paths are resolved from the repo root
        - a path outside the root is never judged, so the verdict does not depend on where the tree sits
        - with not_checked given, each such path is appended to it as ( path, line, design_path )
        - a line that carries a removal note with its recovery command is skipped
        - one Finding per dead path inside the root, at its line

    Raises:
        - nothing
    """
    findings = []
    lines = text.split( "\n" )
    for m in DESIGN_REGEX.finditer( text ):
        i = line_of_offset( text, m.start() )
        if "REMOVED" in lines[ i ]: continue
        if is_outside_root( m.group( 1 ) ):
            if not_checked is not None: not_checked.append( ( path, first_line + i, m.group( 1 ) ) )
            continue
        if not os.path.exists( os.path.join( root, m.group( 1 ) ) ):
            findings.append( Finding( path, first_line + i, "dead-design", f"Design path {m.group( 1 )!r} does not exist" ) )
    return findings
