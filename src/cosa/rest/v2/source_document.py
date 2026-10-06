#!/usr/bin/env python3
"""
Validation for the optional `source_document` argument on the v2 submit door.

A research run can take documents the caller already has as seed context, instead of starting
from a bare query. The documents come from the R&D Docs explainer or from IO-Trees.
`source_document` names them. This module is the only place that decides whether a named
document may be read.

Design choices, and why each one is here:

- Scope. The allowed scopes are the doc-viewer's registered scopes plus `io/`. This is not
  a second allowlist. Paths resolve through the same `ScopeConfig` registry that
  `/api/docs/file` and `/api/io/file` use. The same two per-scope guards apply: the secrets
  blocklist and the prefix or manifest whitelist. Sharing only the scope root is not enough.
  The browse door also refuses files inside a permitted root, such as
  `.claude/settings.local.json`, `CLAUDE.local.md` or anything outside a scope's
  `allowed_prefixes`. Disagreeing allowlists would let the agent read what the viewer refuses.
- A list, not one path. The argument is a list from the start, so its shape never has to
  change from `str` to `str | list`, which would touch every caller and test. A bare string
  is still accepted and becomes a one-element list.
- Refuse at the door, before the job is created. Every failure is returned as a message and
  never raised. The door turns it into a refusal the caller can read in the same response as
  the submit. A job that was accepted and then cannot read its own input would fail less
  visibly, after the caller was told the work had started.
- No size ceiling. There is no byte check in this module. Adding one changes
  agreed behaviour, so it needs a fresh decision rather than a tidy-up.
- Deep research only, for now. Nothing here is agent-specific, so extending it to other
  agents is a registry edit, not a second validator.

Resolution uses `os.path.realpath`, not `os.path.normpath`. This is the one place the module
differs from its neighbours. `_scope_registry.resolve_in_scope()` and the
read-side check in `deep_research.py` use `normpath`, which collapses `..` in the text and
does not follow symlinks. A symlink planted inside an allowed root passes a `normpath`
check while pointing anywhere on the filesystem. This module follows the symlink and then
re-checks containment on the real location. An input path is attacker-influenced in a way a
report path is not, so the module does not wait for the neighbours to change.

The `scopes` mapping is passed in, not imported from the router module. The registry is
built from the INI at FastAPI startup. Importing it here would make this module, and every
test of it, depend on a booted application. Injection lets a test use a two-line fake while
production passes the real registry.
"""

import os
from typing import Optional

# The doc-viewer's OWN per-scope guards, imported rather than reimplemented. If these two
# ever change — a new secret filename, a tightened manifest — this door changes with them,
# which is the whole reason the browse set and the read set can be said to agree.
from cosa.rest.routers._scope_registry import (
    _is_secrets_path_for_scope, _is_whitelisted_in_scope, landed_relative_path, landed_within_roots,
)


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
    Normalize whatever the caller put under `source_document` into a list of path strings.

    This checks the shape only and asks nothing about the filesystem. The shape check is kept
    apart from the scope check. A caller's typo, such as a dict, then comes back as its own
    message instead of a confusing path error later.

    Requires:
        - raw is whatever arrived in the args dict under SOURCE_DOCUMENT_ARG; any type

    Ensures:
        - returns ( paths, error ); exactly one of the two is meaningful
        - a single string returns a one-element list, so a caller naming one document need
          not know the argument is plural
        - a list or tuple of strings returns them stripped, in the caller's order
        - None or an empty or whitespace-only string returns ( [], None ). That means absent,
          not invalid, because the argument is optional and saying nothing is legal
        - any other type, an empty list, a non-string element, a blank element, or more
          than MAX_SOURCE_DOCUMENTS entries returns ( [], <message> )
        - never raises

    Raises:
        - None, because a caller-shaped mistake is a message, not an exception
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
    Split a `<scope>/<relative-path>` reference into its scope and its relative path.

    The form is the doc-viewer's. A link the user can already open reads
    `/app/docs?path=<scope>/<rel>`, so the string copied out of the viewer is the string this
    door accepts.

    Requires:
        - path is a non-empty, stripped string

    Ensures:
        - returns ( scope, relative_path, error ); error is None on success
        - a leading slash is tolerated and stripped, because pasted paths often carry one
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

    The path is resolved with `realpath` first and tested for containment afterwards. A
    `normpath` check judges the path the caller typed. This check judges the file the caller
    reaches, so a symlink under an allowed root that points at `/etc` is caught here.

    Requires:
        - root is an absolute filesystem path
        - relative_path is a scope-relative path string with no leading slash

    Ensures:
        - returns ( absolute_path, error ); error is None on success
        - the returned path is the real path, with symlinks already followed, and is under
          the real root
        - an absolute or traversing relative_path that lands outside the root returns an
          error naming the path, never the resolved location, which would leak the
          layout of a filesystem the caller cannot otherwise see
        - a link that lands outside the root gets the same answer whether or not its target
          exists, so whoever planted the link cannot probe which outside paths exist
        - containment is judged by directory identity, not by spelling, because the repo is
          mounted at two prefixes in the container. A prefix test would refuse live in-scope
          files reached through the other spelling. The doc-viewer door uses the same test
        - never raises

    Raises:
        - None
    """
    real_root = os.path.realpath( root )
    joined    = os.path.join( real_root, relative_path )
    candidate = os.path.realpath( joined )

    # Where it LANDS, by directory identity rather than spelling (rows cc39cee6, ae634018): the
    # repo is mounted at two prefixes in the container, so a prefix test refused live in-scope
    # files reached through the other spelling. Same predicate as the doc-viewer door.
    if not landed_within_roots( candidate, [ real_root ] ):
        # A link landing outside answers the same whether or not its target exists (row 9b80ef75):
        # a second answer would let whoever planted the link probe which outside paths exist.
        return ( None, f"'{relative_path}' resolves outside its scope." )

    return ( candidate, None )


def validate_source_documents( raw, scopes: dict ) -> tuple:
    """
    Turn the caller's `source_document` argument into real, readable, in-scope absolute paths.

    This function is the whole refusal surface for the argument. Everything the door can say no
    to about a source document is decided here and returned as a message. That gives one place
    to read to learn what is refused and one place to change it.

    Requires:
        - raw is the value found under SOURCE_DOCUMENT_ARG, or None
        - scopes maps scope name -> an object with a `root` attribute (the real
          ScopeConfig registry in production; anything with `.root` in a test)

    Ensures:
        - returns ( paths, error ); error is None on success and paths is the resolved,
          real, absolute path for each document, in the caller's order
        - an absent argument returns ( [], None ), because optional means optional
        - the first failure returns, naming the offending path. One refusal a caller can act
          on beats a list of derived complaints from the same mistake
        - refuses, each with its own message: a malformed shape, an unscoped reference,
          an unknown scope, a path escaping its scope, a path that does not exist, a
          directory where a file was named, an extension outside
          ALLOWED_SOURCE_EXTENSIONS, and a file that cannot be read
        - applies the doc-viewer's two per-scope guards, the secrets blocklist and the prefix
          whitelist, to both the typed relative path and the relative path re-derived from
          the resolved absolute path. A symlink inside an allowed root could otherwise point
          at a refused file. The typed path would look clean while the file actually opened
          is not. Checking both also refuses a path that is dirty as written even if it
          resolves somewhere clean
        - applies no size limit
        - never raises

    Raises:
        - None, because every failure is a message. This runs at the door, and the door
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
        if resolve_error is not None:
            return ( [ ], resolve_error )

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
        #
        # 🔴 CHECKED ON BOTH THE TYPED PATH AND THE RESOLVED ONE, AND THE SECOND IS THE
        # ONE THAT MATTERS. The first cut of this guard passed only `relative` — the
        # string the caller typed — while `absolute` is what actually gets opened. A
        # symlink INSIDE an allowed root defeats that completely: name it `sc/notes.json`
        # and point it at `.claude/settings.local.json` and the typed path is clean, the
        # extension is allowed, containment passes because the target is still under the
        # root, and the credentials file comes back. The guard was reading a different
        # string from the one the filesystem would act on.
        #
        # So the relative path is re-derived FROM THE RESOLVED ABSOLUTE and both are
        # tested. Keeping the typed check too costs nothing and refuses a path that is
        # dirty as written even if it resolves somewhere clean.
        resolved_relative = landed_relative_path( absolute, scope_cfg.root )   # identity-aware, never a `../..` form
        for candidate in ( relative, resolved_relative ):
            if _is_secrets_path_for_scope( scope_cfg, candidate ):
                return ( [ ], f"'{path}' is a credential-bearing path and is never readable." )
            if not _is_whitelisted_in_scope( scope_cfg, candidate ):
                return ( [ ], f"'{path}' is outside the readable prefixes for scope '{scope}'." )

        resolved.append( absolute )

    return ( resolved, None )
