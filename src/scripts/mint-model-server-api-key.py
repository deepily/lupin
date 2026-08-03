#!/usr/bin/env python3
"""
Mint the model-server API key (`model-server-api`).

WHY THIS IS NOT `create_service_account.py`
-------------------------------------------
That script mints a key AND inserts a bcrypt hash into the `api_keys` table,
because its key is validated against THAT SERVER'S database — per-deployment,
minted on the target.

The model server has **no database**. `lupin_model_server/main.py` reads one
Secret-Manager-mounted file at boot, bcrypt-hashes it in memory, and compares
every incoming `X-API-Key` against that single hash. Its authority is a secret
version, not a table, and the correct value is IDENTICAL on every host.

⇒ An `api_keys` row for this key would imply an authority that does not exist.
  This script therefore mints a value and writes a file, and does nothing else.

THE DEFECT THIS EXISTS TO END (rows 574fd1dc / 6cc52525)
--------------------------------------------------------
One file — `notification-api-claude-code-dev` — served both consumers. On the
dev box their two authorities coincide by accident (dev's key was seeded into
Secret Manager), so the design flaw was invisible there. On the VM they cannot
coincide: its key was minted into the VM's own database (right for the Lupin
API) and was never in Secret Manager (wrong for the model server) — measured
2026-07-28 as a fingerprint matching NEITHER secret version. `/embeddings/
generate` returned 100% 401 for ~38h.

Usage:
    python src/scripts/mint-model-server-api-key.py            # dry run
    python src/scripts/mint-model-server-api-key.py --apply
    python src/scripts/mint-model-server-api-key.py --apply --force

Next step (NOT done here — see the R&D doc's rotation ordering):
    src/scripts/cloud-run-setup-secrets.sh \
        --secret-name lupin-model-server-api \
        --key-file    src/conf/keys/model-server-api
"""

import os
import re
import sys
import stat
import hashlib
import argparse
import secrets

lupin_root = os.environ.get( "LUPIN_ROOT" )
if lupin_root is None:
    raise RuntimeError( "LUPIN_ROOT not set — export LUPIN_ROOT=/path/to/project" )
src_path = os.path.join( lupin_root, "src" )
if src_path not in sys.path: sys.path.insert( 0, src_path )

import cosa.utils.util as cu

# The SAME predicate the model server applies at boot AND to every incoming
# request (lupin_model_server/main.py:80). Duplicated deliberately: this script
# must not import the model-server package (it ships in a separate GPU image),
# and a key that fails this regex is refused at boot with `api_key_hash` left
# None -> 503 on every authed endpoint. Minting one would be shipping a dud.
CK_LIVE_RE = re.compile( r"^ck_live_[A-Za-z0-9_-]{64,}$" )

KEY_NAME     = "model-server-api"
KEY_MODE     = 0o600
TOKEN_BYTES  = 48        # -> 64 base64url chars, satisfying the {64,} floor


def generate_model_server_key() -> str:
    """
    Generate a `ck_live_*` API key for the model server.

    Requires:
        - nothing

    Ensures:
        - returns a string matching CK_LIVE_RE
        - uses secrets.token_urlsafe (CSPRNG), never random
        - the value is NOT written, logged, or retained by this function

    Returns:
        str: the plaintext key, e.g. "ck_live_9x7Kp3mN..."

    Raises:
        - RuntimeError if the generated key fails CK_LIVE_RE (would be a
          library-behaviour change, not a caller error — fail loud rather than
          hand back a key the server will refuse at boot)
    """
    key = f"ck_live_{secrets.token_urlsafe( TOKEN_BYTES )}"
    if not CK_LIVE_RE.match( key ):
        raise RuntimeError(
            f"generated key does not match {CK_LIVE_RE.pattern} — refusing to "
            f"emit a key the model server would refuse at boot (length {len( key )})"
        )
    return key


def key_fingerprint( plaintext: str ) -> str:
    """
    Stable, non-reversible identifier for WHICH key this is.

    ⚠️ THE PREDICATE IS LOAD-BEARING AND MUST MATCH THE SERVER'S.
    `lupin_model_server/main.py` fingerprints `f.read().strip()`, and the client
    reads via `du.get_api_key()` which also strips (`cosa/utils/util.py:754`).
    So the comparable value is the STRIPPED one.

    Measured 2026-07-28: hashing this file RAW gives `26f45dbc7276` while the
    same key STRIPPED gives `26e3c096d4df` — the file carries a trailing
    newline. Comparing a raw fingerprint against a stripped one manufactures a
    discrepancy that does not exist, and nearly did during the 574fd1dc
    investigation. **State the predicate wherever this number is printed.**

    Requires:
        - plaintext is a non-empty string

    Ensures:
        - returns 12 lowercase hex chars — sha256 of the STRIPPED value
        - is directly comparable to /health's `api_key_fingerprint`
        - never returns any part of the key itself

    Returns:
        str: 12 hex chars (48 bits) — a version tag, not a credential
    """
    return hashlib.sha256( plaintext.strip().encode( "utf-8" ) ).hexdigest()[ :12 ]


def key_file_path() -> str:
    """
    Resolve the destination path for the model-server key.

    Requires:
        - LUPIN_ROOT is set (enforced at import)

    Ensures:
        - returns <project_root>/src/conf/keys/model-server-api
        - does NOT create, read, or write the file

    Returns:
        str: absolute path
    """
    return f"{cu.get_project_root()}/src/conf/keys/{KEY_NAME}"


def write_key( key: str, path: str, force: bool = False ) -> None:
    """
    Write the key to disk at mode 600.

    Requires:
        - key matches CK_LIVE_RE
        - path is an absolute path

    Ensures:
        - refuses to overwrite an existing file unless force is True
        - file is created mode 600 (owner read/write only)
        - parent directory is created if absent

    Raises:
        - ValueError if key fails CK_LIVE_RE
        - FileExistsError if path exists and force is False
    """
    if not CK_LIVE_RE.match( key ):
        raise ValueError( f"refusing to write a key that fails {CK_LIVE_RE.pattern}" )

    if os.path.exists( path ) and not force:
        # Clobbering is how a working deployment loses its key with no record.
        # The caller must say so explicitly.
        raise FileExistsError(
            f"{path} already exists — refusing to overwrite. Re-run with --force "
            f"ONLY if you intend to rotate, and read the rotation ordering in "
            f"src/rnd/v0.1.9/2026.07.28-model-server-api-key-decoupling.md first: "
            f"the model server hashes its key at BOOT, so callers must be updated "
            f"AFTER the service re-reads the new secret, never before."
        )

    os.makedirs( os.path.dirname( path ), exist_ok=True )

    # Create with 600 from the outset rather than chmod-after-write: a
    # world-readable window, however brief, is a window.
    fd = os.open( path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, KEY_MODE )
    try:
        os.write( fd, key.encode( "utf-8" ) )
    finally:
        os.close( fd )

    # An existing file re-opened with --force keeps its ORIGINAL mode; O_CREAT's
    # mode argument applies only on creation. Assert the end state instead.
    os.chmod( path, KEY_MODE )


def main() -> int:
    parser = argparse.ArgumentParser( description="Mint the model-server API key." )
    parser.add_argument( "--apply", action="store_true", help="actually write the key (default: dry run)" )
    parser.add_argument( "--force", action="store_true", help="overwrite an existing key file (rotation)" )
    args = parser.parse_args()

    path = key_file_path()

    cu.print_banner( "Mint model-server API key" )
    print( f"  key name : {KEY_NAME}" )
    print( f"  path     : {path}" )
    print( f"  exists   : {os.path.exists( path )}" )
    print( f"  mode     : {'--apply' if args.apply else 'DRY RUN (no file written)'}" )
    print()

    if not args.apply:
        print( "Dry run — nothing written. Re-run with --apply to mint." )
        return 0

    key = generate_model_server_key()
    try:
        write_key( key, path, force=args.force )
    except FileExistsError as e:
        print( f"ERROR: {e}" )
        return 1

    actual_mode = stat.S_IMODE( os.stat( path ).st_mode )

    # NEVER print the value. The fingerprint is the SAME predicate the model
    # server's /health exposes (sha256 of the STRIPPED value, first 12) so the
    # two are directly comparable — that comparison is the deploy verification.
    print( f"✓ wrote {path}" )
    print( f"  mode        : {oct( actual_mode )}" )
    print( f"  fingerprint : {key_fingerprint( key )}" )
    print()
    print( "NEXT — and the ORDER matters (the model server hashes at BOOT):" )
    print( "  1. seed Secret Manager  : src/scripts/cloud-run-setup-secrets.sh \\" )
    print( f"                              --secret-name lupin-model-server-api --key-file src/conf/keys/{KEY_NAME}" )
    print( "  2. terraform apply with the new api_key_secret_version  <- instances re-hash" )
    print( "  3. ONLY THEN distribute this file to caller hosts" )
    print()
    print( "  Reversing 2 and 3 401s every caller until instances recycle — that is bug 574fd1dc." )
    return 0


if __name__ == "__main__":
    sys.exit( main() )
