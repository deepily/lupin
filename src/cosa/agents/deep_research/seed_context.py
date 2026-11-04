#!/usr/bin/env python3
"""
The one place a `source_document` becomes seed context for a research run.

This is a module, not three copies, because three call sites need the same enrichment.
The research, podcast and presentation commands all take a source document.
The last two build their own agent that calls `run_research` directly.

Copies of a prompt-assembly rule drift invisibly: each keeps working, but they stop
agreeing about what a seed document looks like to the model.
The scope validator has one allowlist for the same reason.

Paths arriving here are already validated. The v2 door (`cosa/rest/v2/source_document.py`)
resolves and stats every path before any job exists, so a bad document is refused there.
Nothing here re-decides whether a file may be read, because a second check could
disagree with the one that was enforced.
"""

from typing import Optional


def normalize_source_document( source_document ) -> list:
    """
    Turn whatever a caller supplied into a list of paths.

    Normalized at the boundary so nothing downstream asks what type it got.
    The v2 door hands over a list, a direct caller may hand over a bare string.

    Requires:
        - source_document is None, a string, or an iterable of strings

    Ensures:
        - returns [] for None
        - returns [ source_document ] for a single string
        - returns a new list for any other iterable, so the caller's object is not aliased

    Raises:
        - TypeError if source_document is not None, a string, or iterable
    """
    if source_document is None:      return [ ]
    if isinstance( source_document, str ): return [ source_document ]
    return list( source_document )


def read_seed_documents( source_document ) -> list:
    """
    Read every source document, returning ( path, text ) pairs.

    This raises instead of skipping a bad file: the door already validated these paths,
    so an unreadable file means the world changed. Skipping it would give a report
    resting on less than the caller asked for, hidden behind a success.

    Requires:
        - source_document holds absolute paths already validated by the door

    Ensures:
        - returns a list of ( path, text ) in the caller's order
        - returns [] when no source document was named

    Raises:
        - OSError / UnicodeDecodeError, unwrapped, when a validated path can no longer be
          read -- the caller's own error path then reports it by name
    """
    documents = [ ]
    for path in normalize_source_document( source_document ):
        with open( path, encoding="utf-8" ) as handle:
            documents.append( ( path, handle.read() ) )
    return documents


def query_with_seed_context( query: str, source_document ) -> str:
    """
    The query as the research sees it: seed documents first, then the question.

    This is not the bare query: the caller's `query` stays the question the user asked.
    There is no size ceiling, so nothing is truncated.

    Requires:
        - query is the user's question
        - source_document is None, a path string, or a list of validated paths

    Ensures:
        - with no source document, returns `query` unchanged -- the whole "works as it did
          before" requirement rests on this line
        - otherwise returns the documents, each fenced and labelled with its path,
          followed by the user's question under its own heading

    Raises:
        - OSError / UnicodeDecodeError when a validated path can no longer be read

    Notes:
        The caller's `query` also feeds the session-name gist, the "Starting deep
        research on..." notification, the report frontmatter and the job's display
        title. Folding a document into it would put a whole file into all four, so the
        enrichment lives only on the path that feeds the model.
        A large document reaches the model whole, costing room to think, which shows
        in the report rather than hiding in a silent trim.
    """
    documents = read_seed_documents( source_document )
    if not documents: return query

    blocks = [ ]
    for path, text in documents:
        blocks.append( f"<source_document path=\"{path}\">\n{text}\n</source_document>" )
    joined = "\n\n".join( blocks )
    return (
        "The following document(s) were supplied as background for this research. "
        "Read them first and use them as context.\n\n"
        f"{joined}\n\n"
        f"RESEARCH QUESTION:\n{query}"
    )
