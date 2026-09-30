#!/usr/bin/env python3
"""
The one place a `source_document` becomes seed context for a research run.

WHY THIS IS A MODULE AND NOT THREE COPIES. Slice 1 (row 14c54c10) built this as two
private methods on `DeepResearchJob`, which was right when exactly one command took the
argument. Row 5726e3c5 extends `source_document` to `research to podcast` and
`research to presentation`, and those two reach the research leg by a DIFFERENT route --
they construct their own agent, which calls `run_research` itself rather than going
through `DeepResearchJob` at all (measured 2026-09-08, Sam 🎙️). So three call sites now
need the same enrichment.

Three copies of a prompt-assembly rule drift, and the drift is invisible: each copy keeps
working, they simply stop agreeing about what a seed document looks like to the model.
Row 14c54c10 Q1 made the same call for the scope validator -- one allowlist, not three.
This applies that decision to the enrichment, for the same reason.

⚠️ THE PATHS ARRIVING HERE ARE ALREADY VALIDATED. The v2 door
(`cosa/rest/v2/source_document.py`) resolves and stat's every path before any job exists
-- Rick's 2026-09-08 ruling that a bad document is refused at the door. Nothing in this
module re-decides whether a file may be read, and adding such a check here would create a
second opinion that can disagree with the one that was actually enforced.
"""

from typing import Optional


def normalize_source_document( source_document ) -> list:
    """
    Turn whatever a caller supplied into a list of paths.

    NORMALIZED AT THE BOUNDARY so nothing downstream has to ask whether it got a string,
    a list or None. The v2 door hands over a list; a direct in-process caller might hand
    over a bare string, and one spelling here beats three checks later.

    Requires:
        - source_document is None, a string, or an iterable of strings

    Ensures:
        - returns [] for None
        - returns [ source_document ] for a single string
        - returns a NEW list for any other iterable, so the caller's object is not aliased

    Raises:
        - TypeError if source_document is not None, a string, or iterable
    """
    if source_document is None:      return [ ]
    if isinstance( source_document, str ): return [ source_document ]
    return list( source_document )


def read_seed_documents( source_document ) -> list:
    """
    Read every source document, returning ( path, text ) pairs.

    WHY THIS RAISES INSTEAD OF SKIPPING A BAD FILE. By the time a job exists, the v2 door
    has already resolved and stat'd these paths -- Rick ruled the refusal happens there,
    before anything is built. So a file that cannot be read HERE means the world changed
    under a validated path, and continuing would produce a report that silently rests on
    less than the caller asked for. That is the exact indistinguishable-from-success
    failure this feature was careful to avoid at the door; swallowing it one layer down
    would reintroduce it.

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
    The query as the RESEARCH sees it -- seed documents first, then the question.

    🔴 THIS IS DELIBERATELY NOT THE BARE QUERY, AND THE DIFFERENCE MATTERS IN FOUR PLACES.
    The caller's `query` is also used for the session-name gist, the "Starting deep
    research on..." notification, the saved report's frontmatter, and the job's display
    title. Folding a document into it would put a whole file into all four -- a session
    named after the first eighty characters of somebody's notes, and frontmatter nobody
    can read. So the enrichment lives here, on the one path that feeds the model, and the
    caller's `query` stays the question the user actually asked.

    Rick ruled NO SIZE CEILING on 2026-09-08, so this does not truncate. A large document
    reaches the model whole, and the cost of that is a research run with less room to
    think -- visible in the report rather than hidden by a silent trim.

    Requires:
        - query is the user's question
        - source_document is None, a path string, or a list of validated paths

    Ensures:
        - with no source document, returns `query` UNCHANGED -- the whole "works as it did
          before" requirement rests on this line
        - otherwise returns the documents, each fenced and labelled with its path,
          followed by the user's question under its own heading

    Raises:
        - OSError / UnicodeDecodeError when a validated path can no longer be read
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
