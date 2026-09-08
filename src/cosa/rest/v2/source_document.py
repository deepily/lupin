#!/usr/bin/env python3
"""
Validation for the optional `source_document` argument on the v2 submit door.

WHAT THIS IS FOR. Rick's 2026-09-08 ask: a research run should be able to take a
document he already has — in the R&D Docs explainer or in IO-Trees — as seed context,
instead of starting from a bare query. `source_document` is how the caller names those
documents, and this module is the only thing that decides whether a named document may
be read.

FIVE THINGS HE RULED, AND WHY EACH ONE IS HERE RATHER THAN SOMEWHERE ELSE
-------------------------------------------------------------------------
· SCOPE — the doc-viewer's registered scopes PLUS `io/`. Not a second allowlist: this
  resolves through the SAME `ScopeConfig` registry `/api/docs/file` and `/api/io/file`
  answer with, AND applies the same two per-scope guards they apply — the secrets
  blocklist and the prefix/manifest whitelist. Two allowlists that disagree is the
  failure this avoids.

  ⚠️ THIS CLAIM WAS FALSE WHEN FIRST WRITTEN, AND THE CORRECTION IS THE POINT. The first
  cut shared only the scope ROOT and then checked an extension. Everything the browse
  door refuses INSIDE a permitted root — `.claude/settings.local.json`, `CLAUDE.local.md`,
  a secret-scan fixture, anything outside a scope's `allowed_prefixes` — this module
  happily returned, and `.json` is in its own extension list. So the docstring promised a
  guarantee the code did not implement, which is worse than not promising it: a reader
  audits the sentence and stops. Found by Krishna in review. Sharing a root is not
  sharing an allowlist.
· A LIST, not one path. He ruled it on day one precisely so the shape never has to
  change from `str` to `str | list` later, which would touch every caller and test.
  A bare string is still accepted and normalized to a one-element list — a caller
  handing over one document should not have to know it is a list.
· REFUSE AT THE DOOR, before the job is created. Every failure here is returned as a
  message, never raised: the door turns it into a refusal the caller can read, in the
  same breath as the submit. A job that was accepted and then cannot read its own input
  has to fail somewhere far less visible, after the caller was told the work started.
· NO SIZE CEILING. His call, recorded as his — the recommendation was to refuse over a
  limit and he declined it. There is deliberately no byte check in this module, and
  adding one is a decision to re-open with him, not a tidy-up.
· DEEP RESEARCH ONLY, for now. Nothing here is agent-specific, so extending it to the
  podcast and presentation siblings is a registry edit rather than a second validator
  (row 5726e3c5).

REALPATH, NOT NORMPATH — THE ONE PLACE THIS DELIBERATELY DIVERGES FROM ITS NEIGHBOURS
--------------------------------------------------------------------------------------
`_scope_registry.resolve_in_scope()` and `deep_research.py`'s read-side check both use
`os.path.normpath`, which collapses `..` TEXTUALLY and does not resolve symlinks. A
symlink planted inside an allowed root therefore passes a normpath check while pointing
anywhere on the filesystem. This module resolves with `os.path.realpath` and re-checks
containment AFTER resolution, so a symlink is followed and then judged on where it
actually lands. That gap is filed separately as row 0cd3811a; this module does not wait
for that fix, because an INPUT path is attacker-influenced in a way a report path is not.

WHY AN INJECTED RESOLVER RATHER THAN AN IMPORT
-----------------------------------------------
`scopes` is passed in rather than imported from the router module. The registry is built
at FastAPI startup from the INI, so importing it here would make this module — and every
test of it — depend on a booted application. Injection keeps the rule testable against a
two-line fake while production passes the real registry.
"""

import os
from typing import Optional

# The doc-viewer's OWN per-scope guards, imported rather than reimplemented. If these two
# ever change — a new secret filename, a tightened manifest — this door changes with them,
# which is the whole reason the browse set and the read set can be said to agree.
from cosa.rest.routers._scope_registry import _is_secrets_path_for_scope, _is_whitelisted_in_scope


# The argument's one spelling. Every reader imports this rather than typing the string,
# so a rename is one edit and a typo is an ImportError instead of a silently-missing
# argument — which is the whole failure mode described under UNRECOGNISED KEYS below.
SOURCE_DOCUMENT_ARG = "source_document"

# What a source document may be. Deliberately narrower than the doc-viewer's MEDIA_TYPES,
# which also serves images: an image cannot be seed context for a text prompt, and
# accepting one would mean the agent silently reads nothing useful out of it.
ALLOWED_SOURCE_EXTENSIONS = ( ".md", ".markdown", ".txt", ".yaml", ".yml", ".json", ".csv", ".rst" )

# The cap on how many documents one request may name. Not a size ceiling — Rick ruled
# there is none — but a bound on the LIST, which is a different thing: it stops a
# malformed caller from turning one submit into ten thousand stat() calls at the door.
MAX_SOURCE_DOCUMENTS = 16


def parse_source_documents( raw ) -> tuple:
    """
    Normalize whatever the caller put under `source_document` into a list of strings.

    SHAPE ONLY — this asks nothing about the filesystem. Splitting the shape check from
    the scope check is what lets a caller's typo ("a dict? really?") come back as its own
    message instead of a confusing path error thirty lines later.

    Requires:
        - raw is whatever arrived in the args dict under SOURCE_DOCUMENT_ARG; any type

    Ensures:
        - returns ( paths, error ); exactly one of the two is meaningful
        - a single string returns a one-element list — a caller naming one document need
          not know the argument is plural
        - a list or tuple of strings returns them stripped, in the caller's order
        - None or an empty/whitespace-only string returns ( [], None ) — ABSENT, not
          invalid. The argument is optional; saying nothing is a legal way to say nothing
        - any other type, an empty list, a non-string element, a blank element, or more
          than MAX_SOURCE_DOCUMENTS entries returns ( [], <message> )
        - never raises

    Raises:
        - None — a caller-shaped mistake is a message, not an exception
    """
    if raw is None: return ( [ ], None )

    if isinstance( raw, str ):
        stripped = raw.strip()
        if not stripped: return ( [ ], None )
        candidates = [ stripped ]
    elif isinstance( raw, ( list, tuple ) ):
        if len( raw ) == 0: return ( [ ], None )
        candidates = list( raw )
    else:
        return ( [ ], f"'{SOURCE_DOCUMENT_ARG}' must be a path or a list of paths, not {type( raw ).__name__}." )

    if len( candidates ) > MAX_SOURCE_DOCUMENTS:
        return ( [ ], f"'{SOURCE_DOCUMENT_ARG}' names {len( candidates )} documents; the limit is {MAX_SOURCE_DOCUMENTS}." )

    paths = [ ]
    for index, candidate in enumerate( candidates ):
        if not isinstance( candidate, str ):
            return ( [ ], f"'{SOURCE_DOCUMENT_ARG}' entry {index} must be a path string, not {type( candidate ).__name__}." )
        stripped = candidate.strip()
        if not stripped:
            return ( [ ], f"'{SOURCE_DOCUMENT_ARG}' entry {index} is blank." )
        paths.append( stripped )

    return ( paths, None )


def split_scope( path: str ) -> tuple:
    """
    Split a `<scope>/<relative-path>` reference into its two halves.

    THE FORM IS THE DOC-VIEWER'S, ON PURPOSE. A link the user can already open reads
    `/app/docs?path=<scope>/<rel>`, so the string he can copy out of the viewer is the
    string this door accepts. Inventing a second spelling would mean the path he can see
    is not the path he can paste.

    Requires:
        - path is a non-empty, stripped string

    Ensures:
        - returns ( scope, relative_path, error ); error is None on success
        - a leading slash is tolerated and stripped — pasted paths often carry one
        - a reference with no separator, or an empty half, returns an error naming the
          expected form rather than guessing a scope
        - never raises

    Raises:
        - None
    """
    cleaned = path.lstrip( "/" ).strip()
    if "/" not in cleaned:
        return ( None, None, f"'{path}' is not a scoped path — expected '<scope>/<path-within-scope>'." )

    scope, _, relative = cleaned.partition( "/" )
    if not scope or not relative.strip():
        return ( None, None, f"'{path}' is not a scoped path — expected '<scope>/<path-within-scope>'." )

    return ( scope, relative.strip(), None )


def resolve_within_root( root: str, relative_path: str ) -> tuple:
    """
    Resolve `relative_path` under `root`, following symlinks, and refuse any escape.

    THE SYMLINK IS THE POINT. Resolving with `realpath` and THEN testing containment is
    what separates this from its neighbours: a normpath check judges the path the caller
    typed, this one judges the file the caller actually reaches. A symlink under an
    allowed root that points at /etc is caught here and nowhere else in this codebase.

    Requires:
        - root is an absolute filesystem path
        - relative_path is a scope-relative path string with no leading slash

    Ensures:
        - returns ( absolute_path, error ); error is None on success
        - the returned path is the REAL path — symlinks already followed — and is under
          the real root
        - an absolute or traversing relative_path that lands outside the root returns an
          error naming the path, never the resolved location (which would leak the
          layout of a filesystem the caller cannot otherwise see)
        - never raises

    Raises:
        - None
    """
    real_root = os.path.realpath( root )
    candidate = os.path.realpath( os.path.join( real_root, relative_path ) )

    if candidate != real_root and not candidate.startswith( real_root + os.sep ):
        return ( None, f"'{relative_path}' resolves outside its scope." )

    return ( candidate, None )


def validate_source_documents( raw, scopes: dict ) -> tuple:
    """
    Turn the caller's `source_document` argument into real, readable, in-scope paths.

    THE WHOLE REFUSAL SURFACE FOR THIS ARGUMENT IS THIS FUNCTION. Everything the door
    can say no to about a source document is decided here and returned as a message, so
    there is one place to read to know what is refused and one place to change it.

    Requires:
        - raw is the value found under SOURCE_DOCUMENT_ARG, or None
        - scopes maps scope name -> an object with a `root` attribute (the real
          ScopeConfig registry in production; anything with `.root` in a test)

    Ensures:
        - returns ( paths, error ); error is None on success and paths is the resolved,
          real, absolute path for each document IN THE CALLER'S ORDER
        - an absent argument returns ( [], None ) — optional means optional
        - the FIRST failure returns, naming the offending path. Reporting one refusal a
          caller can act on beats a list of derived complaints from the same mistake
        - refuses, each with its own message: a malformed shape · an unscoped reference ·
          an unknown scope · a path escaping its scope · a path that does not exist · a
          directory where a file was named · an extension outside
          ALLOWED_SOURCE_EXTENSIONS · a file that cannot be read
        - applies NO size limit, by Rick's ruling of 2026-09-08
        - never raises

    Raises:
        - None — every failure is a message, because this runs at the door and the door
          answers with a refusal rather than a stack trace
    """
    paths, error = parse_source_documents( raw )
    if error is not None: return ( [ ], error )
    if not paths: return ( [ ], None )

    resolved = [ ]
    for path in paths:
        scope, relative, split_error = split_scope( path )
        if split_error is not None: return ( [ ], split_error )

        scope_cfg = scopes.get( scope )
        if scope_cfg is None:
            known = ", ".join( sorted( scopes.keys() ) ) or "none are registered"
            return ( [ ], f"'{path}' names scope '{scope}', which is not readable. Available scopes: {known}." )

        absolute, resolve_error = resolve_within_root( scope_cfg.root, relative )
        if resolve_error is not None: return ( [ ], resolve_error )

        if not os.path.exists( absolute ):
            return ( [ ], f"'{path}' does not exist." )
        if os.path.isdir( absolute ):
            return ( [ ], f"'{path}' is a directory; name a file." )

        extension = os.path.splitext( absolute )[ 1 ].lower()
        if extension not in ALLOWED_SOURCE_EXTENSIONS:
            allowed = ", ".join( ALLOWED_SOURCE_EXTENSIONS )
            return ( [ ], f"'{path}' has extension '{extension or "(none)"}', which is not a readable source document. Allowed: {allowed}." )
        if not os.access( absolute, os.R_OK ):
            return ( [ ], f"'{path}' exists but cannot be read." )

        # THE TWO GUARDS THE BROWSE DOOR APPLIES, applied here for the same reason it
        # applies them. Root containment says the file is in the right TREE; these say it
        # is a file a human is allowed to SEE inside that tree. Without them this door is
        # strictly more permissive than /api/docs/file on the very same scope, and the
        # research agent becomes a way to read what the viewer refuses.
        if _is_secrets_path_for_scope( scope_cfg, relative ):
            return ( [ ], f"'{path}' is a credential-bearing path and is never readable." )
        if not _is_whitelisted_in_scope( scope_cfg, relative ):
            return ( [ ], f"'{path}' is outside the readable prefixes for scope '{scope}'." )

        resolved.append( absolute )

    return ( resolved, None )
