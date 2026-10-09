"""
The lean podcast proxy, server side: the door check for a document a seat names.

A seat asks for a podcast of a document on Rick's behalf. It names the document in the doc
viewer's form, `<scope>/<path within scope>`, for example `lupin/io/tmp/summary.md`. The fleet
tool turns a host path into that form on the host. The server never sees a host path and never
trusts one.

This module resolves the form through the server's own scope registry. It judges the file with
the doc viewer's whole read check, not a copy of its rule.

The check runs in this order:

- shape: a non-blank string in the form scope/path.
- the viewer: `_resolve_scoped` applies the floor blocklist, the scope whitelist, the per-scope
  patterns, and judges the path again where a link lands.
- the handle: `_open_judged_file` opens the file first and judges the open handle. A link swapped
  in after the check cannot redirect the read.
- the content: `credential_verdict` refuses key material whatever the file is called.
- the kind: a text extension a podcast script can use.

Every refusal is a `DoorRefusal` whose message names the path as the caller sent it.
"""

import hashlib
import os

from fastapi import HTTPException

from cosa.rest.routers._scope_registry import credential_verdict
from cosa.rest.routers._pinned_open import PROC_FD
from cosa.rest.v2.source_document import ALLOWED_SOURCE_EXTENSIONS

_READ_CHUNK = 1024 * 1024


class DoorRefusal( Exception ):
    """A podcast request the door refuses. The message is the sentence the caller reads."""


def _viewer():
    """
    The doc viewer's check functions, imported when first used.

    Importing the router module at load time would pull the web application into every importer.
    So the import waits for the first call.
    """
    from cosa.rest.routers import docs_files
    return docs_files


def check_source( scope_path, registry=None ):
    """
    Judge a document a seat named, and describe it, or refuse.

    Requires:
        - scope_path is whatever the caller sent
        - registry, when given, maps scope name -> ScopeConfig; None means the server's own registry

    Ensures:
        - returns { scope, rel, name, server_path, size, sha256 } for a file that passed every guard
          in the module docstring; server_path is where the server reads it, size and sha256 are
          measured from the opened file
        - raises DoorRefusal, naming the path as sent, for a blank or malformed path, an unknown
          scope, a path the viewer's whitelist or blocklist refuses, a link that lands outside the
          scope, a missing file, a folder, an unreadable file, credential content and an extension
          a podcast cannot read
        - the opened handle is closed on every path out
        - nothing here trusts a host path: the caller's text is only the key into the registry

    Raises:
        - DoorRefusal
    """
    if not isinstance( scope_path, str ) or not scope_path.strip():
        raise DoorRefusal( "A podcast needs a document path in the form <scope>/<path>, and none was given." )
    sent = scope_path.strip()
    if "/" not in sent.lstrip( "/" ):
        raise DoorRefusal( f"'{sent}' is not a scoped path. Send it as <scope>/<path within scope>." )
    viewer = _viewer()
    if registry is None: registry = viewer._get_scope_registry()

    try:
        scope, cfg, rel, full_path = viewer._resolve_scoped( sent, registry )
    except HTTPException as refusal:
        raise DoorRefusal( f"'{sent}' was refused: {refusal.detail}." ) from refusal

    extension = os.path.splitext( full_path )[ 1 ].lower()
    if extension not in ALLOWED_SOURCE_EXTENSIONS:
        raise DoorRefusal( f"'{sent}' is a {extension or 'no-extension'} file. A podcast reads {', '.join( ALLOWED_SOURCE_EXTENSIONS )}." )

    try:
        fd = viewer._open_judged_file( full_path, cfg )
    except HTTPException as refusal:
        raise DoorRefusal( f"'{sent}' was refused: {refusal.detail}." ) from refusal

    try:
        verdict = credential_verdict( f"{PROC_FD}/{fd}" )
        if verdict == "credential":
            raise DoorRefusal( f"'{sent}' was refused: its content is credential material." )
        if verdict == "unreadable":
            raise DoorRefusal( f"'{sent}' could not be read or decoded as text, so it cannot be judged." )
        digest, size = hashlib.sha256(), 0
        with open( f"{PROC_FD}/{fd}", "rb" ) as handle:
            for chunk in iter( lambda: handle.read( _READ_CHUNK ), b"" ):
                digest.update( chunk )
                size += len( chunk )
    finally:
        os.close( fd )

    return { "scope": scope, "rel": rel, "name": os.path.basename( rel ), "server_path": full_path,
             "size": size, "sha256": digest.hexdigest() }
