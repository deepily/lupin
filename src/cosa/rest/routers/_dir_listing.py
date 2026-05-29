"""
Shared directory-listing primitives for the doc/io file-serving endpoints.

Both `/api/docs/file` and `/api/io/file` now respond polymorphically:
- If path resolves to a file → existing PlainTextResponse / FileResponse
- If path resolves to a directory → JSONResponse with listing per §3.2

The per-extension `view_url` routing table (§3.4a) lives here so both
endpoints stay honest. Frontend consumes `view_url` as-is — no JS-side
extension sniffing.

Extended 2026-05-12 (multi-repo doc viewer): `scope` may now be any
registered external scope name (lupin, cosa-voice, claude-plans, etc.).
Updated 2026-05-16 for path-prefix routing per the 2026-05-15 unification
(Q-R2): `/app/docs` URLs now carry the project name as the first segment
of `path`; the legacy `?scope=` query param is retired server-side. The
/api/io/file and /app/audio endpoints continue to accept io-relative
paths without a project prefix.

Design docs:
- src/rnd/v0.1.7/2026.05.12-doc-viewer-directory-listing.md (original)
- src/rnd/v0.1.7/2026.05.12-multi-repo-doc-viewer.md (multi-repo extension)
- src/rnd/v0.1.7/2026.05.15-doc-viewer-scope-unification.md (path-prefix routing)
"""

import os
from typing import Callable
from urllib.parse import quote

from cosa.rest.routers._scope_registry import _is_secrets_path


def _build_view_url( rel_path: str, scope: str, kind: str, ext: str ) -> str:
    """
    Build the viewer/player/download URL for a directory entry.

    Single source of truth for the per-extension routing table. Per the
    2026-05-15 unification (Q-R2), `/app/docs?path=` URLs are now project-
    prefixed (path-prefix routing); the `?scope=` query param is retired
    server-side. The /api/io/file and /app/audio endpoints continue to
    accept io-relative paths without a project prefix.

    Routing table:
    - directory → /app/docs?path=<scope>/<rel> (project-prefixed)
    - .md/.txt/.json/.yaml/.yml → /app/docs?path=<scope>/<rel> (project-prefixed)
    - source-code extensions → /app/docs?path=<scope>/<rel> (plain <pre> in viewer)
    - .mp3/.wav (io only) → /app/audio?path=<rel> (io-relative; player page)
    - .pdf, images (io only) → /api/io/file?path=<rel> (io-relative; inline)
    - .pptx (io only) → /api/io/file?path=<rel>&download=true (io-relative)

    Requires:
        - rel_path is a non-empty path string relative to the scope root
        - scope is a non-empty scope name (built-in: "io"; project name otherwise:
          any registered in SCOPE_REGISTRY plus the built-in "lupin")
        - kind is "file" or "directory"
        - ext is a lowercase extension including the dot (e.g., ".md"), or "" for directories

    Ensures:
        - returns a non-empty URL string
        - rel_path is URL-encoded via quote(safe="")
        - /app/docs URLs include the project prefix as the first path segment
        - /api/io/file and /app/audio URLs stay io-relative (no prefix)
    """
    encoded = quote( rel_path, safe="" )

    # io-only direct-binary routing (player/download/inline render). Paths
    # are io-relative because the receiving endpoints expect that shape.
    if scope == "io" and kind == "file":
        if ext in ( ".mp3", ".wav" ):
            return f"/app/audio?path={encoded}"
        if ext == ".pdf":
            return f"/api/io/file?path={encoded}"
        if ext in ( ".png", ".jpg", ".jpeg", ".gif", ".webp" ):
            # Images render inline in the browser via direct URL (Option A
            # per 2026.05.12-doc-viewer-directory-listing.md decision).
            return f"/api/io/file?path={encoded}"
        if ext == ".pptx":
            return f"/api/io/file?path={encoded}&download=true"

    # Everything else routes through /app/docs with a project-prefixed path.
    # Directories AND text-renderable files in any scope share the same form.
    prefixed = quote( f"{scope}/{rel_path}", safe="" )
    return f"/app/docs?path={prefixed}"


def list_directory(
    abs_dir          : str,
    rel_dir          : str,
    scope            : str,
    allowed_exts     : set,
    parent_validator : Callable[ [ str ], bool ]
) -> dict:
    """
    Build a directory-listing JSON dict for a whitelisted directory.

    Requires:
        - abs_dir is an absolute filesystem path to an existing directory
        - rel_dir is the project-relative (scope=docs) or io-relative (scope=io)
          path string; may or may not have a trailing slash; may be empty string
          (scope=io root case)
        - scope is "docs" or "io"
        - allowed_exts is a set of lowercase extension strings (e.g., {".md", ".txt"})
        - parent_validator(parent_rel) returns True iff that parent path should be
          exposed as the `parent` field (lets caller plug in scope-specific
          whitelist logic)

    Ensures:
        - returns dict shaped per §3.2:
          {kind: "directory", scope, path, parent, entries: [...]}
        - hidden entries (names starting with ".") are excluded (Q5)
        - file entries are filtered to those whose extension is in allowed_exts
        - entries are sorted directories-first, then alphabetical case-insensitive (Q4)
        - each entry carries a `view_url` from _build_view_url
        - directory entries have size=None; file entries have size=int (bytes)
        - parent is None if rel_dir has no dirname OR parent_validator rejects it
    """
    rel_dir_norm = rel_dir.rstrip( "/" )

    entries = [ ]
    with os.scandir( abs_dir ) as it:
        for entry in it:
            # Q5: hidden files / directories always excluded
            if entry.name.startswith( "." ):
                continue

            # Secrets blocklist (2026-05-12) — drop entries whose basename
            # matches a SECRETS_BLOCKLIST_PATTERNS entry so they don't surface
            # in listings at all. The per-request file fetch also rejects these
            # (defense-in-depth).
            if _is_secrets_path( entry.name ):
                continue

            try:
                if entry.is_dir( follow_symlinks=False ):
                    child_rel = f"{rel_dir_norm}/{entry.name}" if rel_dir_norm else entry.name
                    entries.append( {
                        "name"     : entry.name,
                        "kind"     : "directory",
                        "size"     : None,
                        "rel_path" : child_rel,
                        "view_url" : _build_view_url( child_rel, scope, "directory", "" ),
                    } )
                elif entry.is_file( follow_symlinks=False ):
                    ext = os.path.splitext( entry.name )[ 1 ].lower()
                    if ext not in allowed_exts:
                        continue
                    stat = entry.stat()
                    child_rel = f"{rel_dir_norm}/{entry.name}" if rel_dir_norm else entry.name
                    entries.append( {
                        "name"     : entry.name,
                        "kind"     : "file",
                        "size"     : stat.st_size,
                        "rel_path" : child_rel,
                        "view_url" : _build_view_url( child_rel, scope, "file", ext ),
                    } )
            except OSError:
                # Permission errors etc. — silently skip the entry rather than
                # poisoning the whole listing
                continue

    # Q4: directories first, then files; alphabetical case-insensitive within group
    entries.sort( key=lambda e: ( e[ "kind" ] != "directory", e[ "name" ].lower() ) )

    # Parent calculation
    parent_rel = os.path.dirname( rel_dir_norm )
    if not parent_rel or not parent_validator( parent_rel ):
        parent_rel = None

    return {
        "kind"    : "directory",
        "scope"   : scope,
        "path"    : rel_dir_norm,
        "parent"  : parent_rel,
        "entries" : entries,
    }
