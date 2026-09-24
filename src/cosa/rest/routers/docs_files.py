"""
Whitelisted documentation file serving endpoint.

Sibling to io_files.py — serves project source-tree docs and (per the
multi-repo extension on 2026-05-12) external-repo files via `?scope=<name>`.

Built-in `scope=docs` preserves backwards compatibility: the legacy narrow
whitelist (src/docs/, src/rnd/, src/workflow/, root *.md) under the project
root. Every other `scope` value is resolved through SCOPE_REGISTRY built at
startup from `[Lupin: Baseline]` INI keys (see _scope_registry.py).

Security model:
- JWT auth required on all requests (Depends(get_current_user)).
- Path normalized to block `..` traversal; resolved path must stay within
  scope root.
- Secrets blocklist (filename pattern match) applied to ALL scopes after
  per-scope whitelist (defense-in-depth).
- Only text-document and source-code extensions are allowed (MEDIA_TYPES).

Generated on: 2026-05-04, extended 2026-05-12.
"""

import errno
import os
import uuid
from urllib.parse import quote, unquote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse

import cosa.utils.util as cu
from cosa.config.cache_registry import register_invalidator
from cosa.config.configuration_manager import ConfigurationManager
from cosa.rest.auth import get_current_user
from cosa.rest.auth_middleware import require_admin
from cosa.rest.routers._dir_listing import list_directory
from cosa.rest.routers._scope_registry import ScopeConfig
from cosa.rest.routers._scope_registry import (
    SECRETS_BLOCKLIST_PATTERNS,
    ScopeConfig,
    _is_secrets_path,
    _is_whitelisted_in_scope,
    build_scope_registry,
    resolve_in_scope,
)

router = APIRouter( tags=[ "docs-files" ] )


# Allowed extensions:
#   - Markdown / text-renderable docs (handled as text/markdown in the viewer)
#   - Source code (handled as plain <pre> in the viewer; syntax highlighting
#     is a Phase 2.5 follow-on per design §8)
MEDIA_TYPES = {
    # Existing — markdown-renderable text
    ".md"   : "text/markdown; charset=utf-8",
    ".txt"  : "text/plain; charset=utf-8",
    ".json" : "application/json",
    ".yaml" : "text/yaml; charset=utf-8",
    ".yml"  : "text/yaml; charset=utf-8",

    # NEW (2026-05-12) — source code, rendered as plain <pre> in the frontend
    ".py"   : "text/x-python; charset=utf-8",
    ".ts"   : "text/typescript; charset=utf-8",
    ".tsx"  : "text/typescript; charset=utf-8",
    ".js"   : "text/javascript; charset=utf-8",
    ".jsx"  : "text/javascript; charset=utf-8",
    ".css"  : "text/css; charset=utf-8",
    ".html" : "text/html; charset=utf-8",
    ".sh"   : "text/x-shellscript; charset=utf-8",
    ".sql"  : "text/x-sql; charset=utf-8",
    ".toml" : "text/x-toml; charset=utf-8",
    ".ini"  : "text/plain; charset=utf-8",
    ".cfg"  : "text/plain; charset=utf-8",
    ".xml"  : "text/xml; charset=utf-8",

    # NEW (2026-05-21) — image MIMEs, served via FileResponse (binary).
    # The Lupin SPA dispatches on media_type.startswith("image/") to render
    # via <img> tag instead of the text/markdown/code component.
    ".png"  : "image/png",
    ".jpg"  : "image/jpeg",
    ".jpeg" : "image/jpeg",
    ".gif"  : "image/gif",
    ".svg"  : "image/svg+xml",
    ".webp" : "image/webp",

    # NEW (2026-09-24, ticket 668aa0a3, Rick's ruling) — audio, video and PDF, served
    # via FileResponse like images. The viewer plays/shows them inline and offers the
    # raw bytes through its ⬇ Download button. The whitelist, the name blocklist and
    # .docview.yml still gate every path; only the credential CONTENT check is text-only,
    # because it cannot read binary — which is why these join the binary branch below.
    ".mp3"  : "audio/mpeg",
    ".wav"  : "audio/wav",
    ".mp4"  : "video/mp4",
    ".webm" : "video/webm",
    ".pdf"  : "application/pdf",
}

# The media families served as raw bytes, never decoded as utf-8.
BINARY_MEDIA_PREFIXES = ( "image/", "audio/", "video/", "application/pdf" )


# Process-lifetime scope registry. Lazy-init on first access; subsequent
# calls hit the cached dict (no per-request rebuild).
_SCOPE_REGISTRY: dict = None  # sentinel — None means "not built yet"


def _get_scope_registry() -> dict:
    """
    Return the process-wide name→ScopeConfig dict, building it on first access.

    Ensures:
        - Returns a dict (possibly empty if no external repos configured)
        - Built exactly once per process via build_scope_registry(config_mgr)
        - Cleared by _invalidate_scope_registry(); next call rebuilds
    """
    global _SCOPE_REGISTRY
    if _SCOPE_REGISTRY is None:
        config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
        _SCOPE_REGISTRY = build_scope_registry( config_mgr )
    return _SCOPE_REGISTRY


def _invalidate_scope_registry() -> None:
    """
    Drop the cached registry so the next `_get_scope_registry()` call rebuilds.

    Registered with `cosa.config.cache_registry` at import time. Called by
    `/api/init` (via `invalidate_all()`) after `config_mgr.init()` so any
    INI changes to `external repo *` keys take effect without a restart.
    Resolves Mr. Radio's `/api/init` invalidation bug (filed 2026-05-15).
    """
    global _SCOPE_REGISTRY
    _SCOPE_REGISTRY = None


register_invalidator( "scope_registry", _invalidate_scope_registry )


def _resolve_scoped( path: str, registry: dict ) -> tuple:
    """
    Resolve a `<project>/<rel>` doc path through EVERY guard the viewer applies.

    Extracted 2026-09-24 (ticket 416d4b00) so the upload endpoint asks the SAME gate
    the read path does rather than restating it: two copies of a path rule agree until
    they do not, and the day they disagree is the day upload writes where read refuses.

    Requires:
        - path is the raw `<project>/<rel>` string (URL-decoding happens here)
        - registry maps scope name -> ScopeConfig (the caller may add built-ins)

    Ensures:
        - returns ( project_name, scope_cfg, rel_path, full_path ), full_path REAL
          (symlinks followed) and inside the scope root
        - the path was judged both as TYPED and where it LANDS: floor blocklist,
          per-scope blocklist and whitelist

    Raises:
        - HTTPException 400 on an empty path, missing/unknown project, a whitelist or
          blocklist refusal, or a traversal escape
    """
    decoded_path = unquote( path ).lstrip( "/" )

    # Empty path early-fail (must come before split-at-first-slash).
    if not decoded_path:
        raise HTTPException( status_code=400, detail="Empty path" )

    # Universal floor blocklist applies BEFORE project resolution — if the
    # path itself names a secret, never even attempt to look up the project.
    if _is_secrets_path( decoded_path ):
        raise HTTPException(
            status_code = 400,
            detail      = "Path matches secrets blocklist"
        )

    # ---------------------------------------------------------------------
    # Phase 4b — path-prefix routing. Legacy `?scope=` is 400'd above before
    # we ever reach this point (aggressive-deprecation policy, 2026-05-21).
    # ---------------------------------------------------------------------
    if "/" not in decoded_path:
        # Bare registered-project name (`?path=claude-plans`) lists that
        # project's root — parity with the trailing-slash form
        # (`?path=claude-plans/`) and with the built-in `io` scope, which both
        # list at the bare name. Unregistered bare names keep the 400.
        if decoded_path not in registry:
            raise HTTPException(
                status_code = 400,
                detail      = "Missing project prefix; URL format: `?path=<project>/<rel>`"
            )
        project_name, rel_path = decoded_path, ""
    else:
        project_name, rel_path = decoded_path.split( "/", 1 )

    if not project_name:  # pragma: no cover - unreachable: decoded_path is lstrip('/')'d (L192) and guarded non-empty (L195); the bare branch assigns it whole, and in the split branch its first char is non-slash → split('/',1)[0] is a non-empty pre-slash segment → project_name is always truthy
        raise HTTPException(
            status_code = 400,
            detail      = "Empty project prefix"
        )

    scope_cfg = registry.get( project_name )

    if scope_cfg is None:
        raise HTTPException(
            status_code = 400,
            detail      = f"Unknown project: {project_name!r}"
        )

    if not _is_whitelisted_in_scope( scope_cfg, rel_path ):
        raise HTTPException(
            status_code = 400,
            detail      = f"Path not in scope whitelist: {rel_path}"
        )

    # Phase 3 — per-scope extra_blocklist from .docview.yml (additive to floor)
    if scope_cfg.extra_blocklist_patterns:
        from cosa.rest.routers._scope_registry import _is_secrets_path_for_scope
        if _is_secrets_path_for_scope( scope_cfg, rel_path ):
            raise HTTPException(
                status_code = 400,
                detail      = "Path matches secrets blocklist (per-scope)"
            )

    try:
        full_path = resolve_in_scope( scope_cfg, rel_path )
    except ValueError as e:
        raise HTTPException( status_code=400, detail=str( e ) )

    # The guards above judged the path as TYPED. A symlink inside the root can land
    # somewhere they would refuse (row 9ab0bddb: `sc/notes.json` -> `.claude/settings.local.json`),
    # so re-judge the path where it actually LANDS — the same double check
    # `cosa.rest.v2.source_document.validate_source_documents` applies.
    landed_rel = os.path.relpath( full_path, os.path.realpath( scope_cfg.root ) )
    if landed_rel == ".": landed_rel = ""
    from cosa.rest.routers._scope_registry import _is_secrets_path_for_scope
    if _is_secrets_path_for_scope( scope_cfg, landed_rel ):   # floor + per-scope patterns
        raise HTTPException( status_code=400, detail="Path matches secrets blocklist" )
    if not _is_whitelisted_in_scope( scope_cfg, landed_rel ):
        raise HTTPException( status_code=400, detail=f"Path not in scope whitelist: {rel_path}" )

    return project_name, scope_cfg, rel_path, full_path


@router.get(
    "/api/docs/file",
    summary     = "Serve a project documentation file or directory listing via the unified scope registry",
    description = "Polymorphic file/directory endpoint. The `path` query parameter MUST be `<project>/<rel>` — the first segment names a registered project (see /api/docs/scopes); the remainder is resolved under that project's root, subject to the project's `.docview.yml` whitelist (if present) plus the universal secrets blocklist floor. The legacy `?scope=` query parameter is RETIRED — its presence triggers 400 with an educational pointer to the canonical form (policy flipped from silent-ignore to aggressive-400 on 2026-05-21). JWT auth required."
)
async def get_docs_file(
    path        : str  = Query( ..., description="Path of the form `<project>/<rel>`; URL-decoded automatically. First segment names the registered project." ),
    scope       : str  = Query( None, description="RETIRED — presence triggers 400 with educational error. Use `path=<project>/<rel>` form instead. Retired per Q-R2 of 2026-05-15 doc-viewer scope unification; aggressive-400 policy ratified 2026-05-21." ),
    current_user: dict = Depends( get_current_user ),
):
    """
    Serve a documentation file OR directory listing via the unified scope registry.

    URL format: `?path=<project>/<rel>` where the first path segment names a
    registered project (see GET /api/docs/scopes). The remainder is resolved
    under that project's root subject to:
      (a) the universal secrets blocklist floor (~46 patterns covering
          credentials, dev artifacts, IDE files, personal config)
      (b) the project's `.docview.yml` whitelist if present (otherwise
          wildcard semantics per Q2-C); plus any `extra_blocklist`
          regex patterns declared in the manifest

    Polymorphic by resolved path type:
        - File → PlainTextResponse with appropriate media type
        - Directory → JSONResponse with {kind, scope, path, parent, entries}

    Requires:
        - JWT bearer token in Authorization header (enforced by get_current_user)
        - path is `<project>/<rel>` form; URL-decoded automatically; leading slashes stripped
        - File extension must be in MEDIA_TYPES (for file branch)

    Ensures:
        - 200 + appropriate response on success
        - 401 if missing/invalid auth (raised by get_current_user)
        - 400 for missing project prefix, unknown project, paths outside the whitelist,
          traversal artifacts, unsupported extensions, or secrets-blocklist matches
        - 404 if the resolved path does not exist on disk

    Raises:
        - HTTPException 401: invalid/missing auth (from get_current_user)
        - HTTPException 400: invalid/unsafe path, unknown project, unsupported extension,
                             secrets blocklist match, OR presence of the retired
                             `?scope=` query parameter (aggressive-deprecation policy
                             ratified 2026-05-21 — see R&D doc-viewer-scope-unification §AC4b.7)
        - HTTPException 404: file or directory not found
        - HTTPException 500: read failure
    """
    # ---------------------------------------------------------------------
    # Aggressive deprecation of legacy `?scope=` query parameter.
    # Policy flipped from silent-ignore (Phase 4b AC4b.7 original) to 400
    # with educational pointer on 2026-05-21 — silent-ignore made dead syntax
    # invisible to emitters, defeating the migration purpose.
    # ---------------------------------------------------------------------
    if scope is not None:
        try:
            registered = sorted( _get_scope_registry().keys() )
            project_list = ", ".join( registered )
        except Exception:
            project_list = "(see GET /api/docs/scopes)"
        raise HTTPException(
            status_code = 400,
            detail      = (
                "The `?scope=` query parameter is RETIRED. "
                "Use path-prefix form: `?path=<project>/<file>`. "
                f"Registered projects: {project_list}. "
                "See planning-is-prompting workflow/doc-viewer-links.md and "
                "Lupin CLAUDE.md § 'Doc Viewer Scope' for the canonical reference."
            ),
        )

    project_name, scope_cfg, rel_path, full_path = _resolve_scoped( path, _get_scope_registry() )

    # Bind scope_cfg into the parent_validator so the directory listing's
    # "parent" field uses per-scope whitelist logic.
    return _serve(
        full_path,
        rel_path,
        scope            = project_name,
        parent_validator = lambda p, _cfg=scope_cfg: _is_whitelisted_in_scope( _cfg, p ),
    )


@router.get(
    "/api/docs/scopes",
    summary     = "List registered doc-viewer scopes (admin / debugging utility)",
    description = "Returns the unified scope registry as a JSON object. Each entry shows scope name, root path, allowed_prefixes, allowed_root_files (from manifest if present), and a source marker ('manifest' vs 'ini-only'). Phase 3 of doc-viewer scope unification; consumed primarily by cosa-voice MCP integration for runtime scope discovery."
)
async def get_scopes( current_user: dict = Depends( get_current_user ) ):
    """
    Return a snapshot of the active scope registry.

    Requires:
        - JWT bearer token (enforced by get_current_user)

    Ensures:
        - returns JSON `{scopes: [...]}` where each entry has fields:
            name              : scope identifier
            root              : in-container absolute path
            allowed_prefixes  : list[str] (manifest's authoritative list if
                                manifest present; else INI fallback)
            allowed_root_files: list[str] (manifest only; empty when no manifest)
            extra_blocklist   : list[str] (manifest only; empty when no manifest)
            source            : "manifest" | "ini-only"
    """
    registry = _get_scope_registry()
    scopes_payload = []
    for name, cfg in sorted( registry.items() ):
        if cfg.manifest is not None:
            scopes_payload.append( {
                "name"               : name,
                "root"               : cfg.root,
                "allowed_prefixes"   : list( cfg.manifest.allowed_prefixes ),
                "allowed_root_files" : list( cfg.manifest.allowed_root_files ),
                "extra_blocklist"    : list( cfg.manifest.extra_blocklist ),
                "source"             : "manifest",
            } )
        else:
            scopes_payload.append( {
                "name"               : name,
                "root"               : cfg.root,
                "allowed_prefixes"   : list( cfg.allowed_prefixes ),
                "allowed_root_files" : [],
                "extra_blocklist"    : [],
                "source"             : "ini-only",
            } )

    return JSONResponse( content={ "scopes": scopes_payload } )


def _serve( full_path: str, rel_path: str, scope: str, parent_validator ) -> JSONResponse | PlainTextResponse | FileResponse:
    """
    Common file/directory dispatch — shared by legacy `docs` branch and registry branch.

    Requires:
        - full_path is an absolute filesystem path inside the scope root (caller verified)
        - rel_path is the scope-relative path string used for response composition
        - scope is the scope name string
        - parent_validator is a callable taking a candidate parent path and returning
          True iff that parent should be exposed in the directory listing's `parent` field

    Ensures:
        - directory → JSONResponse with the standard listing shape; secrets blocklist
          filtering applied per-entry inside list_directory
        - file (image/*, audio/*, video/*, application/pdf) → FileResponse streaming
          binary bytes with the matching media_type (images 2026-05-21; audio, video
          and PDF 2026-09-24, ticket 668aa0a3)
        - file (text/*) → PlainTextResponse with the appropriate MEDIA_TYPES entry
        - 404 if path doesn't exist; 400 if extension not in MEDIA_TYPES; 500 on read failure
    """
    # Directory branch (polymorphic response) — must come before isfile check
    if os.path.isdir( full_path ):
        listing = list_directory(
            abs_dir          = full_path,
            rel_dir          = rel_path,
            scope            = scope,
            allowed_exts     = set( MEDIA_TYPES.keys() ),
            parent_validator = parent_validator,
        )
        return JSONResponse( content=listing )

    if not os.path.isfile( full_path ):
        raise HTTPException(
            status_code = 404,
            detail      = f"Path not found: {rel_path}"
        )

    _, ext = os.path.splitext( full_path )
    ext = ext.lower()

    if ext not in MEDIA_TYPES:
        raise HTTPException(
            status_code = 400,
            detail      = f"Unsupported file type: {ext}"
        )

    media_type = MEDIA_TYPES[ ext ]

    # Binary branch (image/audio/video/pdf): stream bytes via FileResponse — never
    # decode as utf-8. The SPA dispatches on the media type to <img>, <audio>,
    # <video> or an inline PDF frame.
    #
    # ⚠️ ACCEPTED ON PURPOSE (ticket 668aa0a3): this return comes BEFORE the credential
    # CONTENT check below, which can only read text. So a binary is guarded by the
    # whitelist and the NAME blocklist only — key material saved as .pdf/.mp3/.mp4
    # would be served. Judged low risk: nothing writes keys under media extensions.
    if media_type.startswith( BINARY_MEDIA_PREFIXES ):
        return FileResponse( path=full_path, media_type=media_type )

    # 🔴 LAST LINE OF DEFENCE (bug afdc938f). The whitelist said yes and the NAME
    # blocklist said yes; the BYTES get the final word. This family has been patched
    # by filename twice — application_default_credentials.json (023e72cb), then seven
    # more still served — and the next name nobody predicted is served the moment
    # someone commits it. A name is a guess about content; this reads the content.
    #
    # Runs on EVERY text file, not just *.json: gating on the extension would let
    # key.txt walk through and re-introduce the filename dependency one layer down.
    # FAIL CLOSED — unreadable or undecodable BLOCKS, because a check that serves
    # what it could not read looks like protection while providing none.
    #
    # 🔴 THE REFUSAL NOW SAYS WHICH REFUSAL IT IS (row ee1670bc). Both outcomes below
    # refuse — the floor has not moved — but they are different facts and want
    # different actions from the reader. "This file is a credential" sends you to look
    # at the file; "this file could not be read" sends you to look at the disk, the
    # permissions, or the bind-mount. Reporting the second as the first sent people
    # hunting for key material that was never there.
    from cosa.rest.routers._scope_registry import credential_verdict
    verdict = credential_verdict( full_path )
    if verdict == "credential":
        raise HTTPException(
            status_code = 400,
            detail      = ( "Refused: this file's CONTENT is credential material (service-account "
                            "key, OAuth token, or private key). The doc viewer never serves key "
                            "material, whatever the file is named." )
        )
    if verdict == "unreadable":
        raise HTTPException(
            status_code = 500,
            detail      = ( "Error reading file: it could not be read or decoded, so the doc viewer "
                            "cannot rule out credential material and refuses to serve it. This is "
                            "NOT a finding about the file's content — check that the file exists, is "
                            "readable, is valid UTF-8, and that any bind-mount it lives on is up." )
        )

    # Text branch: utf-8 read + PlainTextResponse (existing behavior preserved).
    try:
        with open( full_path, "r", encoding="utf-8" ) as f:
            content = f.read()
        return PlainTextResponse( content=content, media_type=media_type )
    except Exception as e:
        raise HTTPException(
            status_code = 500,
            detail      = f"Error reading file: {str( e )}"
        )


# ---------------------------------------------------------------------------
# Upload (ticket 416d4b00, Rick's rulings 2026-09-24)
# ---------------------------------------------------------------------------

# 100 MB. A cap the operator can raise; without one a single request can fill the disk.
UPLOAD_MAX_BYTES = 100 * 1024 * 1024
_UPLOAD_CHUNK    = 1024 * 1024
_ON_CONFLICT     = ( "refuse", "replace", "rename" )


def _upload_registry() -> dict:
    """
    The scopes an upload may target: every registered repo, plus the built-in io folder.

    io is not in the registry (it is a reserved name, served by /api/io/file), but it IS
    browsable in the viewer, and Rick ruled "any folder I can browse". It gets a wildcard
    ScopeConfig so it passes through the very same gate as the repos.
    """
    registry = dict( _get_scope_registry() )
    registry[ "io" ] = ScopeConfig(
        name             = "io",
        root             = os.path.join( cu.get_project_root(), "io" ),
        allowed_prefixes = (),
    )
    return registry


def _safe_upload_name( raw: str ) -> str:
    """
    Reduce a client-supplied filename to one safe path component, or refuse.

    Ensures:
        - returns the basename with no directory part
        - raises 400 for empty, ".", "..", hidden (leading "."), NUL, or an
          extension the viewer does not serve
    """
    name = os.path.basename( ( raw or "" ).replace( "\\", "/" ) ).strip()
    if not name or name in ( ".", ".." ) or name.startswith( "." ) or "\x00" in name:
        raise HTTPException( status_code=400, detail=f"Unusable file name: {raw!r}" )
    ext = os.path.splitext( name )[ 1 ].lower()
    if ext not in MEDIA_TYPES:
        raise HTTPException( status_code=400, detail=f"Unsupported file type: {ext or '(none)'}" )
    return name


def _next_free_name( directory: str, name: str ) -> str:
    """`notes.md` -> `notes-2.md`, `notes-3.md`, … — the first that does not exist."""
    stem, ext = os.path.splitext( name )
    n = 2
    while os.path.exists( os.path.join( directory, f"{stem}-{n}{ext}" ) ):
        n += 1
    return f"{stem}-{n}{ext}"


@router.post(
    "/api/docs/upload",
    status_code = 201,
    summary     = "Upload a file into a doc-viewer folder (admins only)",
    description = "Multipart form: `dir` = `<project>/<rel-dir>` (or `io/<rel-dir>`), `file` = the file, `on_conflict` = refuse|replace|rename (default refuse). The target folder must pass every guard the viewer applies to reading (whitelist, secrets blocklists, traversal, symlink landing). 201 → {path, name, size, view_url, replaced}; 400 bad name/type/path or credential content; 403 folder not writable on this server; 404 folder missing; 409 name taken (detail carries `suggested_name`); 413 over the size cap."
)
async def upload_docs_file(
    dir         : str        = Form( ..., description="Target folder, `<project>/<rel-dir>` or `io/<rel-dir>`" ),
    file        : UploadFile = File( ..., description="The file to store" ),
    on_conflict : str        = Form( "refuse", description="refuse | replace | rename" ),
    admin_user  : dict       = Depends( require_admin ),
):
    """
    Store one uploaded file in a folder the doc viewer can browse.

    Requires:
        - an admin JWT (require_admin)
        - `dir` names an existing folder that passes the viewer's read guards

    Ensures:
        - the bytes land atomically: written to a hidden temp file in the SAME folder,
          then os.replace'd into place, so a reader never sees a half-written file and
          a failed upload leaves nothing behind
        - an existing name is never overwritten unless on_conflict == "replace"
        - a text upload is refused if its CONTENT is credential material — the same
          check the viewer applies before serving it
        - every successful upload is logged with who, where, how big and how

    Raises:
        - HTTPException 400 / 403 / 404 / 409 / 413 as described in the route
    """
    if on_conflict not in _ON_CONFLICT:
        raise HTTPException( status_code=400, detail=f"on_conflict must be one of {', '.join( _ON_CONFLICT )}" )

    project_name, scope_cfg, rel_dir, full_dir = _resolve_scoped( dir.rstrip( "/" ), _upload_registry() )
    if not os.path.isdir( full_dir ):
        raise HTTPException( status_code=404, detail=f"Folder not found: {dir}" )

    name       = _safe_upload_name( file.filename )
    target_rel = f"{rel_dir}/{name}" if rel_dir else name

    # The FILE's own path must pass the gate too — a folder that may be browsed can still
    # hold names the blocklist refuses (`.env`, `credentials.json`, …).
    _resolve_scoped( f"{project_name}/{target_rel}", _upload_registry() )

    target   = os.path.join( full_dir, name )
    replaced = False
    if os.path.exists( target ):
        if on_conflict == "refuse":
            raise HTTPException(
                status_code = 409,
                detail      = {
                    "error"          : "exists",
                    "message"        : f"{name} already exists in {dir}",
                    "suggested_name" : _next_free_name( full_dir, name ),
                },
            )
        if on_conflict == "rename":
            name       = _next_free_name( full_dir, name )
            target_rel = f"{rel_dir}/{name}" if rel_dir else name
            target     = os.path.join( full_dir, name )
        else:
            replaced = True

    temp = os.path.join( full_dir, f".upload-{uuid.uuid4().hex}.part" )
    size = 0
    try:
        with open( temp, "wb" ) as out:
            while True:
                chunk = await file.read( _UPLOAD_CHUNK )
                if not chunk:
                    break
                size += len( chunk )
                if size > UPLOAD_MAX_BYTES:
                    raise HTTPException( status_code=413, detail=f"File exceeds the {UPLOAD_MAX_BYTES // ( 1024 * 1024 )} MB upload cap" )
                out.write( chunk )

        # Text types (markdown, code, JSON, YAML…) get the same CONTENT check the viewer
        # runs before serving. Binaries cannot be read as text, exactly as on the read path.
        if not MEDIA_TYPES[ os.path.splitext( name )[ 1 ].lower() ].startswith( BINARY_MEDIA_PREFIXES ):
            from cosa.rest.routers._scope_registry import credential_verdict
            verdict = credential_verdict( temp )
            if verdict == "credential":
                raise HTTPException( status_code=400, detail="Refused: this file's CONTENT is credential material. The doc viewer never stores or serves key material." )
            if verdict == "unreadable":
                raise HTTPException( status_code=400, detail="Refused: a text file must be valid UTF-8 so its content can be checked for credential material." )

        os.chmod( temp, 0o644 )
        os.replace( temp, target )
    except OSError as e:
        if e.errno in ( errno.EROFS, errno.EACCES, errno.EPERM ):
            raise HTTPException( status_code=403, detail=f"This folder is not writable on this server: {dir}" )
        raise HTTPException( status_code=500, detail=f"Upload failed: {e}" )
    finally:
        if os.path.exists( temp ):
            os.remove( temp )

    public_path = f"{project_name}/{target_rel}"
    print( f"[DOCS-UPLOAD] user={admin_user.get( 'email' )} path={public_path} bytes={size} mode={on_conflict}{' (replaced)' if replaced else ''}" )
    return {
        "path"     : public_path,
        "name"     : name,
        "size"     : size,
        "replaced" : replaced,
        "view_url" : "/app/docs?path=" + quote( public_path, safe="/" ),
    }


@router.get(
    "/api/docs/health",
    summary     = "Docs files health check",
    description = "Report registered scopes (with manifest presence + on-disk reachability) plus the io/ directory status and the full MEDIA_TYPES extension list. Unauthenticated."
)
async def docs_files_health():
    """
    Health check for docs files endpoint.

    Ensures:
        - returns dict with project_root, io/ status, per-scope registry detail
          (name → root, exists, allowed_prefixes, manifest flag), and the
          full MEDIA_TYPES extension list
        - intentionally unauthenticated — health endpoints are public probes
    """
    project_root = cu.get_project_root()
    io_root      = os.path.join( project_root, "io" )

    registry = _get_scope_registry()
    scopes_status = {
        name: {
            "root"             : cfg.root,
            "exists"           : os.path.isdir( cfg.root ),
            "allowed_prefixes" : list(
                cfg.manifest.allowed_prefixes if cfg.manifest is not None else cfg.allowed_prefixes
            ),
            "manifest"         : cfg.manifest is not None,
        }
        for name, cfg in sorted( registry.items() )
    }

    return {
        "status"       : "ok",
        "project_root" : project_root,
        "io"           : { "root": io_root, "exists": os.path.isdir( io_root ) },
        "scopes"       : scopes_status,
        "media_types"  : sorted( MEDIA_TYPES.keys() ),
    }
