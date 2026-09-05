"""
Scan the repo for `src/rnd/…` citations that no longer resolve, and REPORT ITS OWN CORPUS.

Row 88f4dfdb. This module exists because the same population exclusion was made TWICE by the
same author, in two sessions, and the correction in between was recorded as PROSE in a task-store
row rather than as code. A defect recorded in a document is not a control; only the code is.

🔴 THE EXCLUSION THAT BIT TWICE, AND WHY IT IS SPLIT HERE.
The obvious rule is `if path.startswith( "src/rnd/" ): skip` — a research doc citing a sibling
research doc is a RECORD, not an instruction, so skipping the tree is right for the DOCUMENTS.
It is WRONG for `src/rnd/README.md`, which is the one file in that tree whose entire job is to
send readers somewhere. Both sweeps skipped the index along with the documents and both hid the
same 52 dead links.

⇒ `INDEX_FILES` is carved out of the exclusion by name, and
`src/tests/unit/test_dead_rnd_citation_corpus_includes_the_index.py` fails if it stops being.

⚠️ THIS SCANNER DOES NOT ASSERT A COUNT AND MUST NOT BE MADE TO. A guard written today against
the live dead-citation total would ship RED on 133 sites, and a guard that ships red is one
somebody deletes. It guards the CORPUS — that the search can see what it claims to search.
"""

import os
import re
import subprocess

# a citation is a repo-relative path into src/rnd with a recognised extension
CITATION_PAT   = re.compile( r"src/rnd/[A-Za-z0-9_.\-/]*[A-Za-z0-9_\-]\.(?:md|py|sh|json|txt)" )

# a markdown link, used for the index, whose targets are relative to src/rnd/
MD_LINK_PAT    = re.compile( r"\]\(([^)]+\.md)\)" )

# 🔴 the carve-out. Inside src/rnd/ but an INDEX, so it is scanned like any instructing doc.
INDEX_FILES    = ( "src/rnd/README.md", )

# an ARCHIVE is a frozen record of what was true then; a dead citation there is not a defect
ARCHIVE_PREFIX = ( "todo-history/", "history/", "src/cosa/history/", "src/cosa/rnd/" )

# the fix form embeds the dead path inside its own recovery command, so a naive re-scan re-flags
# exactly what it just fixed. These two markers are how an already-annotated site is recognised.
#
# 🔴 THESE WERE HARDCODED TO `c752ab9e` AND THAT WAS WRONG. The row this module serves names THREE
# deletion shas; deriving the set from `git log --diff-filter=D` rather than from that written list
# turns up FIVE — c752ab9e, 172cb57f, 8bf71a64, a4a27b0c, 942fe0b8. A marker keyed on one sha
# recognises one sha's cleanup and re-flags the other four's, so the scanner reports its own fix as
# the disease for 80% of the population. Measured: 40 sites annotated, only 15 stopped being
# reported. Matching ANY sha is not a generalisation for its own sake — it is the only form that
# cannot go stale the next time a doc is deleted.
ANNOTATED_NEAR = re.compile( r"\b[0-9a-f]{7,40}\^:$" )
ANNOTATED_LINE = re.compile( r"REMOVED by `?[0-9a-f]{7,40}`?" )


def tracked_files( repo_root ):
    """
    List every file git tracks, relative to the repo root.

    Requires:
        - repo_root is a directory inside a git working tree

    Ensures:
        - returns a list of repo-relative path strings
        - the list is empty only if git tracks nothing, never because the call failed silently

    Raises:
        - subprocess.CalledProcessError if git cannot answer
    """
    out = subprocess.run(
        [ "git", "-C", repo_root, "ls-files" ], capture_output=True, text=True, check=True
    ).stdout
    return out.split()


def is_archive( path ):
    """
    Ensures: True iff `path` is a frozen historical record rather than an instructing document.
    """
    return path.startswith( ARCHIVE_PREFIX ) or ".backup-" in path


def in_corpus( path ):
    """
    Decide whether a tracked file belongs in the scanned corpus.

    🔴 THE INDEX CARVE-OUT LIVES HERE. `src/rnd/` is skipped because a research doc citing a
    sibling is a record — but `INDEX_FILES` is scanned, because an index instructs.

    Requires:
        - path is a repo-relative path string

    Ensures:
        - returns True for every tracked file except src/rnd documents that are not an index
        - returns True for every member of INDEX_FILES
    """
    if path in INDEX_FILES:            return True
    if path.startswith( "src/rnd/" ):  return False
    return True


# 🔴 A `src/rnd/…` MATCH CAN BELONG TO ANOTHER REPO, AND THEN IT IS NOT OURS TO RESOLVE.
# Sibling repos use the same `src/rnd/` layout, so a correctly-written cross-repo citation reads
# `planning-is-prompting/src/rnd/<doc>.md`. CITATION_PAT matches the `src/rnd/…` TAIL of that path
# and the prefix sits outside the match, so the resolver looks for the doc in LUPIN, does not find
# it, and reports a correct citation as dead. Measured: 15 of 52 cross-repo sites were already
# prefixed properly and every one was being flagged.
#
# This is the mirror of the annotation defect above: there the scanner failed to recognise its own
# FIX, here it fails to recognise a citation that was never broken.
CROSS_REPO_PREFIX = ( "planning-is-prompting/", "lupin-mobile/", "cosa-voice/", "lupin-plugin-firefox/" )


def is_cross_repo( line, col ):
    """
    Decide whether the `src/rnd/…` match at `col` is the tail of ANOTHER repo's path.

    Requires:
        - line is the full source line, col is the match start offset within it

    Ensures:
        - returns True iff the text immediately before the match names a sibling repo
        - returns False for a bare lupin-relative citation, so those are still resolved here
    """
    return line[ : col ].endswith( CROSS_REPO_PREFIX )


def is_annotated( line, col ):
    """
    Ensures: True iff the match at `col` is already-fixed text rather than a live dead citation —
             either it sits inside a recovery command, or its line carries the REMOVED marker.
    """
    return bool( ANNOTATED_NEAR.search( line[ max( 0, col - 45 ) : col ] ) ) \
        or bool( ANNOTATED_LINE.search( line ) )


def scan( repo_root ):
    """
    Scan the corpus and report BOTH the findings and the corpus they came from.

    Requires:
        - repo_root is a directory inside a git working tree

    Ensures:
        - returns a dict with keys: scanned, skipped, live, dead, index_scanned
        - `scanned` counts files actually read, so a caller can tell an empty result from an
          empty search — an absence is the one finding that looks identical either way
        - `index_scanned` names every INDEX_FILES member that was reached, so the exclusion
          that bit twice is visible in the OUTPUT rather than only in the source
        - already-annotated sites are not reported as dead
    """
    scanned, skipped   = [], 0
    live, dead         = set(), []

    for rel in tracked_files( repo_root ):
        if not in_corpus( rel ):
            skipped += 1
            continue
        try:
            with open( os.path.join( repo_root, rel ), "r", encoding="utf-8" ) as fh:
                lines = fh.readlines()
        except ( UnicodeDecodeError, OSError ):
            skipped += 1
            continue
        scanned.append( rel )
        for n, line in enumerate( lines, 1 ):
            for m in CITATION_PAT.finditer( line ):
                path = m.group( 0 )
                if is_cross_repo( line, m.start() ):
                    continue
                if os.path.exists( os.path.join( repo_root, path ) ):
                    live.add( path )
                elif not is_annotated( line, m.start() ):
                    dead.append( { "path": path, "file": rel, "line": n,
                                   "archive": is_archive( rel ) } )

    return {
        "scanned"       : scanned,
        "skipped"       : skipped,
        "live"          : sorted( live ),
        "dead"          : dead,
        "index_scanned" : [ f for f in INDEX_FILES if f in scanned ],
    }


def scan_index_links( repo_root, index_rel="src/rnd/README.md" ):
    """
    Resolve the markdown links in the rnd index, whose targets are relative to `src/rnd/`.

    Kept separate from `scan` on purpose: these are a DIFFERENT POPULATION with a different fix
    shape — a list of links in one file, versus per-citation prose surgery across the tree. They
    must not be merged into one headline number.

    Requires:
        - index_rel names a markdown file inside the repo

    Ensures:
        - returns ( live_count, dead_targets ) with dead_targets a list of link targets
        - live_count > 0 is the caller's positive control that the resolver works

    Raises:
        - FileNotFoundError if the index is missing
    """
    live, dead = 0, []
    with open( os.path.join( repo_root, index_rel ), "r", encoding="utf-8" ) as fh:
        text = fh.read()
    base = os.path.dirname( index_rel )
    for m in MD_LINK_PAT.finditer( text ):
        target  = m.group( 1 )
        resolved = target if target.startswith( "src/" ) else os.path.normpath(
            os.path.join( base, target ) )
        if os.path.exists( os.path.join( repo_root, resolved ) ): live += 1
        else:                                                     dead.append( target )
    return live, dead
