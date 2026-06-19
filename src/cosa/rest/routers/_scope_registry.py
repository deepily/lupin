"""
Scope registry for the multi-repo doc viewer.

Built at FastAPI startup from `[Lupin: Baseline]` INI keys:

    external repos                              = name1, name2, ...
    external repo <name> path                   = /absolute/in-container/path
    external repo <name> allowed prefixes       = src/, docs/, ...

Each registered scope becomes addressable via `/api/docs/file?scope=<name>&path=<rel>`.

Built-in scopes (`docs`, `io`) are NOT in this registry — they predate it and live
inline in `docs_files.py` / `io_files.py`. The registry exposes only USER-CONFIGURED
external scopes.

Secrets blocklist (§3e) applies to ALL scopes, registered or built-in, and runs
AFTER the per-scope whitelist (defense-in-depth).

Design doc: src/rnd/v0.1.7/2026.05.12-multi-repo-doc-viewer.md
Generated on: 2026-05-12
"""

import os
import re
from dataclasses import dataclass, field
from typing import Optional, Tuple

import cosa.utils.util as du
from cosa.config.docview_manifest import DocviewManifest, load_manifest_for_scope


# ---------------------------------------------------------------------------
# ScopeConfig
# ---------------------------------------------------------------------------

@dataclass( frozen=True )
class ScopeConfig:
    """
    Frozen description of one external scope.

    Fields:
        name             : Short scope name (used in `?scope=<name>`).
        root             : Absolute filesystem path inside the container.
        allowed_prefixes : Tuple of path prefixes (relative to root). Empty tuple
                           AND no manifest → wildcard ("all paths under root are
                           reachable" subject to MEDIA_TYPES + secrets blocklist).
                           When a manifest is present, the manifest's
                           `allowed_prefixes` is authoritative; this field is
                           treated as the fallback for repos that ship neither.
        manifest         : Optional `DocviewManifest` loaded from
                           `<root>/.docview.yml` at build time. When present,
                           the manifest's allowed_prefixes, allowed_root_files,
                           and extra_blocklist are the authority for this scope.
        extra_blocklist_patterns: Pre-compiled regex patterns derived from
                           manifest.extra_blocklist (if any). Empty tuple
                           when no manifest or no extras.
    """

    name                     : str
    root                     : str
    allowed_prefixes         : tuple
    manifest                 : Optional[ DocviewManifest ] = None
    extra_blocklist_patterns : tuple                       = ()


# ---------------------------------------------------------------------------
# Secrets blocklist — applies to ALL scopes (built-in + external)
# ---------------------------------------------------------------------------

SECRETS_BLOCKLIST_PATTERNS = (
    # ----- Credentials (pre-existing + extensions) -----
    # Dotfiles known to carry secrets
    re.compile( r"^\.env(\.|$)" ),
    re.compile( r"^\.netrc$" ),
    re.compile( r"^\.pgpass$" ),
    re.compile( r"^\.credentials" ),                              # F4/F5: any .credentials*

    # Common credential-bearing names (word-boundary anchored to avoid
    # false-positives on substrings like "secretive_methods" or
    # "credentialism" — both legitimate filenames that should NOT be blocked).
    re.compile( r"\bcredentials?\b", re.IGNORECASE ),
    re.compile( r"\bsecrets?\b",     re.IGNORECASE ),
    re.compile( r"\bpassword\b",     re.IGNORECASE ),             # F4 add

    # Key/cert file extensions
    re.compile( r"\.pem$", re.IGNORECASE ),
    re.compile( r"\.key$", re.IGNORECASE ),
    re.compile( r"\.pfx$", re.IGNORECASE ),
    re.compile( r"\.p12$", re.IGNORECASE ),
    re.compile( r"\.gpg$", re.IGNORECASE ),                       # F4 add
    re.compile( r"\.asc$", re.IGNORECASE ),                       # F4 add

    # SSH key filenames
    re.compile( r"id_rsa",     re.IGNORECASE ),
    re.compile( r"id_ed25519", re.IGNORECASE ),
    re.compile( r"id_dsa",     re.IGNORECASE ),
    re.compile( r"id_ecdsa",   re.IGNORECASE ),

    # ----- Local config (F4: never expose per-user / per-host overrides) -----
    re.compile( r"^CLAUDE\.local\.md$" ),
    re.compile( r"\.local\.md$",   re.IGNORECASE ),
    re.compile( r"\.local\.json$", re.IGNORECASE ),
    re.compile( r"\.local\.ya?ml$", re.IGNORECASE ),
    re.compile( r"^\.gitconfig-local$" ),

    # ----- Dev artifacts (F4 + F5 case-insensitive) -----
    re.compile( r"^\.venv$",         re.IGNORECASE ),
    re.compile( r"^node_modules$",   re.IGNORECASE ),
    re.compile( r"^__pycache__$",    re.IGNORECASE ),
    re.compile( r"\.pyc$",           re.IGNORECASE ),
    re.compile( r"\.pyo$",           re.IGNORECASE ),
    re.compile( r"^dist$",           re.IGNORECASE ),
    re.compile( r"^build$",          re.IGNORECASE ),
    re.compile( r"^target$",         re.IGNORECASE ),
    re.compile( r"^\.coverage$",     re.IGNORECASE ),
    re.compile( r"^coverage$",       re.IGNORECASE ),
    re.compile( r"^\.pytest_cache$", re.IGNORECASE ),
    re.compile( r"^\.tox$",          re.IGNORECASE ),

    # ----- IDE / editor (F4 + F5 case-insensitive) -----
    re.compile( r"^\.idea$",     re.IGNORECASE ),
    re.compile( r"^\.vscode$",   re.IGNORECASE ),
    re.compile( r"^\.DS_Store$", re.IGNORECASE ),
    re.compile( r"\.swp$",       re.IGNORECASE ),
    re.compile( r"\.swo$",       re.IGNORECASE ),
    re.compile( r"^Thumbs\.db$", re.IGNORECASE ),

    # ----- Personal config / cloud (F4 + F5 case-insensitive) -----
    re.compile( r"^\.bash_history$", re.IGNORECASE ),
    re.compile( r"^\.ssh$",          re.IGNORECASE ),
    re.compile( r"^\.aws$",          re.IGNORECASE ),
    re.compile( r"^\.gnupg$",        re.IGNORECASE ),
    re.compile( r"^\.kube$",         re.IGNORECASE ),
    re.compile( r"^\.docker$",       re.IGNORECASE ),
)


def _is_secrets_path( relative_path: str ) -> bool:
    """
    Return True iff any path segment matches a SECRETS_BLOCKLIST_PATTERNS entry.

    Requires:
        - relative_path is a non-empty project-relative path string with no
          leading slash. Forward-slash separators only (POSIX-style).

    Ensures:
        - returns True if any segment of `relative_path` matches any blocklist
          pattern (basename AND any intermediate directory name are checked)
        - returns False otherwise
        - empty input returns False (cheap guard for callers)
    """
    if not relative_path:
        return False

    for part in relative_path.split( "/" ):
        if not part:
            continue
        for pattern in SECRETS_BLOCKLIST_PATTERNS:
            if pattern.search( part ):
                return True
    return False


# ---------------------------------------------------------------------------
# Whitelist + path resolution per scope
# ---------------------------------------------------------------------------

def _is_whitelisted_in_scope( scope_cfg: ScopeConfig, relative_path: str ) -> bool:
    """
    Return True iff `relative_path` is permitted by the scope's whitelist.

    Resolution order (Phase 3 manifest extension):
        1. If `scope_cfg.manifest` is set, the manifest's `allowed_prefixes` +
           `allowed_root_files` is the authority for this scope. Empty manifest
           lists mean "no paths permitted" (explicit-opt-in semantics).
        2. If no manifest, fall back to the INI-derived
           `scope_cfg.allowed_prefixes`. Empty → wildcard (per Q2-C
           missing-manifest semantics).
        3. Bare scope-root listing (empty relative_path) is always allowed so
           directory listings work.

    Requires:
        - scope_cfg is a ScopeConfig instance
        - relative_path is a project-relative path string with no leading slash

    Ensures:
        - returns True when the path passes the active whitelist (manifest or
          INI prefixes), False otherwise
        - empty relative_path returns True (root listing affordance)
    """
    if not relative_path:
        return True

    # Manifest authority (Q2-C / Q3-A): when present, use it.
    if scope_cfg.manifest is not None:
        m = scope_cfg.manifest
        # Root-file whitelist: exact-match check (only for top-level files).
        if "/" not in relative_path and relative_path in m.allowed_root_files:
            return True
        # Prefix whitelist
        for prefix in m.allowed_prefixes:
            if relative_path.startswith( prefix ):
                return True
            if relative_path == prefix.rstrip( "/" ):
                return True
        return False

    # No manifest — INI-derived behavior (wildcard if empty).
    if not scope_cfg.allowed_prefixes:
        return True
    for prefix in scope_cfg.allowed_prefixes:
        if relative_path.startswith( prefix ):
            return True
        if relative_path == prefix.rstrip( "/" ):
            return True
    return False


def _is_secrets_path_for_scope( scope_cfg: ScopeConfig, relative_path: str ) -> bool:
    """
    Combined floor + per-scope extra blocklist check.

    The universal floor (`SECRETS_BLOCKLIST_PATTERNS`) is checked first. If
    no floor pattern matches, the scope's `extra_blocklist_patterns` (from
    `manifest.extra_blocklist`, if any) are checked. Per Q4-B repos can only
    ADD patterns; they cannot remove floor patterns.
    """
    if _is_secrets_path( relative_path ):
        return True

    if not scope_cfg.extra_blocklist_patterns:
        return False

    for part in relative_path.split( "/" ):
        if not part:
            continue
        for pattern in scope_cfg.extra_blocklist_patterns:
            if pattern.search( part ):
                return True
    return False


def resolve_in_scope( scope_cfg: ScopeConfig, decoded_path: str ) -> str:
    """
    Resolve `decoded_path` against `scope_cfg.root`, blocking directory traversal.

    Requires:
        - scope_cfg is a ScopeConfig instance whose `root` is an absolute path
        - decoded_path is a URL-decoded relative path (no leading slash); may be ""

    Ensures:
        - returns an absolute filesystem path under (or equal to) scope_cfg.root
        - raises ValueError if normalized path escapes scope_cfg.root

    Raises:
        - ValueError when the resolved path would escape the scope root
    """
    full_path = os.path.normpath( os.path.join( scope_cfg.root, decoded_path ) )
    root      = scope_cfg.root.rstrip( os.sep )

    if full_path != root and not full_path.startswith( root + os.sep ):
        raise ValueError( f"Path escapes scope root: {decoded_path!r} (scope={scope_cfg.name!r})" )
    return full_path


# ---------------------------------------------------------------------------
# Registry build — invoked once at FastAPI startup
# ---------------------------------------------------------------------------

_RESERVED_SCOPE_NAMES = ( "docs", "io" )


def build_scope_registry( config_mgr ) -> dict:
    """
    Read `external repos` INI block and return a name → ScopeConfig dict.

    Requires:
        - config_mgr is a ConfigurationManager instance with the `external repos`
          key registered (default `[]` is OK — empty registry is legal)

    Ensures:
        - returns dict[str, ScopeConfig]
        - skips scopes whose name collides with built-ins (`docs`, `io`); logs warning
        - skips scopes whose `path` value is missing or does not exist on disk;
          logs warning (so an environment without a particular repo mounted doesn't
          fail startup)
        - prefixes are stripped of surrounding whitespace; empty prefix strings drop out
        - the dict is intended to be process-lifetime constant after startup

    Raises:
        - None — all failure modes are non-fatal warnings (registry build never
          aborts boot)
    """
    names = config_mgr.get( "external repos", default=[], return_type="list-string" )
    registry: dict = { }

    for raw_name in names:
        name = raw_name.strip()
        if not name:
            continue

        if name in _RESERVED_SCOPE_NAMES:
            print( f"[scope_registry] WARNING: external repo name {name!r} collides with built-in scope; skipping" )
            continue

        try:
            root = config_mgr.get( f"external repo {name} path", default=None, silent=True )
        except Exception:
            root = None

        if not root or not os.path.isdir( root ):
            print( f"[scope_registry] WARNING: external repo {name!r}: path {root!r} not found on disk; skipping" )
            continue

        try:
            prefixes_raw = config_mgr.get(
                f"external repo {name} allowed prefixes",
                default        = [ ],
                return_type    = "list-string",
                silent         = True,
            )
        except Exception:
            prefixes_raw = [ ]

        prefixes = tuple( p.strip() for p in prefixes_raw if p and p.strip() )

        # Phase 3: load `<root>/.docview.yml` if present. Failures fall back
        # to None (caller treats None as wildcard per Q2-C).
        manifest = load_manifest_for_scope( root )

        extra_blocklist_patterns: tuple
        if manifest is not None and manifest.extra_blocklist:
            extra_blocklist_patterns = tuple(
                re.compile( pat ) for pat in manifest.extra_blocklist
            )
        else:
            extra_blocklist_patterns = ()

        registry[ name ] = ScopeConfig(
            name                     = name,
            root                     = root,
            allowed_prefixes         = prefixes,
            manifest                 = manifest,
            extra_blocklist_patterns = extra_blocklist_patterns,
        )

    print( f"[scope_registry] registered {len( registry )} external scope(s): {sorted( registry )}" )
    return registry


# ---------------------------------------------------------------------------
# Inline smoke test — runs against the local INI when invoked directly
# ---------------------------------------------------------------------------

def quick_smoke_test():
    du.print_banner( "_scope_registry smoke test", prepend_nl=True )

    # 1) ScopeConfig is frozen
    try:
        sc = ScopeConfig( name="x", root="/tmp", allowed_prefixes=( ) )
        try:
            sc.name = "y"          # type: ignore[misc]
            print( "✗ ScopeConfig should be frozen but allowed mutation" )
        except Exception:
            print( "✓ ScopeConfig is frozen" )
    except Exception as e:
        print( f"✗ ScopeConfig construction failed: {e}" )

    # 2) Secrets blocklist
    blocked = [
        ".env", ".env.production", ".env.local",
        "credentials.json", "secrets.yaml",
        "id_rsa", "id_rsa.pub", "id_ed25519",
        "sub/dir/credentials.json",
        ".netrc", ".pgpass",
        "deploy.pem", "tls.key",
    ]
    allowed = [
        "environment.md", "environments.py",
        "pem-helper.py", "key_values.txt",
        "secretive_methods.py", "credentialism.txt",
        "src/rnd/foo.md",
    ]
    failures = 0
    for p in blocked:
        if not _is_secrets_path( p ):
            print( f"✗ _is_secrets_path missed: {p!r}" )
            failures += 1
    for p in allowed:
        if _is_secrets_path( p ):
            print( f"✗ _is_secrets_path false positive: {p!r}" )
            failures += 1
    print( f"{'✓' if failures == 0 else '✗'} secrets blocklist: {failures} failure(s)" )

    # 3) Whitelist semantics
    wild = ScopeConfig( name="wild", root="/tmp", allowed_prefixes=( ) )
    strict = ScopeConfig( name="s", root="/tmp", allowed_prefixes=( "src/", "docs/" ) )
    ok = True
    ok &= _is_whitelisted_in_scope( wild,   "anything/at/all.md" )
    ok &= _is_whitelisted_in_scope( wild,   "" )
    ok &= _is_whitelisted_in_scope( strict, "src/foo.py" )
    ok &= _is_whitelisted_in_scope( strict, "src" )
    ok &= _is_whitelisted_in_scope( strict, "" )
    ok &= not _is_whitelisted_in_scope( strict, "lib/foo.py" )
    ok &= not _is_whitelisted_in_scope( strict, "lib" )
    print( f"{'✓' if ok else '✗'} whitelist semantics" )

    # 4) Path traversal block
    try:
        resolve_in_scope( strict, "../etc/passwd" )
        print( "✗ resolve_in_scope failed to block traversal" )
    except ValueError:
        print( "✓ resolve_in_scope blocks traversal" )

    du.print_banner( "_scope_registry smoke test complete", prepend_nl=True )


if __name__ == "__main__":
    quick_smoke_test()
