"""
Repo-owned `.docview.yml` manifest parser for the unified scope registry.

Per Q2-C of the doc-viewer scope unification design, each registered repo
MAY ship a `.docview.yml` at its root declaring what the doc viewer is
allowed to serve under its scope. Missing manifest = wildcard access
(subject to the universal floor blocklist in `_scope_registry.py`).

Schema (version 1):

    version           : 1
    allowed_prefixes  : [ src/, docs/, ... ]      # path prefixes within scope root
    allowed_root_files: [ README.md, CHANGELOG.md, ... ]   # exact filenames at root
    extra_blocklist   : [ "regex1", "regex2" ]    # ADDITIONS to universal floor
                                                  # (cannot WEAKEN floor per Q4-B)

Strict mode (`ConfigDict(extra="forbid")`): any unknown field is rejected at
parse time. This catches malicious or careless manifests trying to declare
e.g. `remove_from_blocklist` (which is intentionally absent — per Q4-B
repos cannot weaken the floor).

File-size cap: callers MUST enforce a ≤64 KB cap on the raw YAML BEFORE
invoking `yaml.safe_load`. Oversized manifests are treated as absent
(wildcard fallback) with a WARN log. See AC3.5.

Design anchor: `src/rnd/v0.1.7/2026.05.15-doc-viewer-scope-unification.md` §5.3 + §7 Phase 3.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator


# 64 KB upper bound per design AC3.5 — anything bigger is treated as absent.
MAX_MANIFEST_BYTES = 64 * 1024


class DocviewManifest( BaseModel ):
    """
    Pydantic model for `.docview.yml` repo manifest.

    Strict mode: unknown fields are REJECTED. This is the load-bearing defense
    that prevents a repo from declaring `remove_from_blocklist` or any other
    floor-weakening field.
    """

    model_config = ConfigDict( extra="forbid" )

    version           : int       = Field( default=1, ge=1, le=1 )
    allowed_prefixes  : List[ str ] = Field( default_factory=list )
    allowed_root_files: List[ str ] = Field( default_factory=list )
    extra_blocklist   : List[ str ] = Field( default_factory=list )

    @field_validator( "extra_blocklist" )
    @classmethod
    def compile_blocklist_patterns( cls, value: List[ str ] ) -> List[ str ]:
        """
        Reject malformed regex at parse time so /api/init surfaces the error
        instead of failing later during a serve request.
        """
        for pattern in value:
            try:
                re.compile( pattern )
            except re.error as e:
                raise ValueError( f"Invalid regex in extra_blocklist: {pattern!r} ({e})" )
        return value


def load_manifest_for_scope( scope_root: str ) -> Optional[ DocviewManifest ]:
    """
    Load `<scope_root>/.docview.yml` if it exists, is under the size cap, and
    parses cleanly. Return None for any failure mode (caller treats None as
    wildcard semantics per Q2-C).

    Requires:
        - scope_root is an absolute path string to a directory that exists

    Ensures:
        - Returns DocviewManifest instance if file present + parses
        - Returns None if:
          * file is absent
          * file exceeds MAX_MANIFEST_BYTES
          * yaml.safe_load raises
          * Pydantic validation raises (including unknown fields per
            extra="forbid")
        - All non-fatal failures emit a WARN to stdout with the path + reason
    """
    manifest_path = Path( scope_root ) / ".docview.yml"
    if not manifest_path.is_file():
        return None

    # AC3.5 — file-size cap; oversized treated as absent
    try:
        size = manifest_path.stat().st_size
    except OSError as e:  # pragma: no cover — defensive against TOCTOU race after is_file() check
        print( f"[docview_manifest] WARN: stat failed on {manifest_path}: {e}" )
        return None

    if size > MAX_MANIFEST_BYTES:
        print(
            f"[docview_manifest] WARN: oversize manifest {manifest_path} "
            f"({size} bytes > {MAX_MANIFEST_BYTES} cap); falling back to wildcard"
        )
        return None

    try:
        raw = manifest_path.read_text( encoding="utf-8" )
    except OSError as e:
        print( f"[docview_manifest] WARN: read failed on {manifest_path}: {e}" )
        return None

    try:
        parsed = yaml.safe_load( raw )
    except yaml.YAMLError as e:
        print( f"[docview_manifest] WARN: YAML parse failed on {manifest_path}: {e}" )
        return None

    if parsed is None:
        # Empty YAML file → treat as absent (wildcard).
        return None

    if not isinstance( parsed, dict ):
        print(
            f"[docview_manifest] WARN: manifest {manifest_path} root is not a mapping "
            f"(got {type(parsed).__name__}); falling back to wildcard"
        )
        return None

    try:
        return DocviewManifest( **parsed )
    except Exception as e:
        print( f"[docview_manifest] WARN: validation failed on {manifest_path}: {e}" )
        return None
