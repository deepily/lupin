#!/usr/bin/env python3
"""
Mint the model-server API key (`model-server-api`) and write it to a file.

Unlike create_service_account.py, this inserts no api_keys row. The model server has no
database: it reads one Secret-Manager-mounted file at boot and bcrypt-hashes it in memory.

Ensures:
    - create_service_account.py mints a key and inserts a bcrypt hash into api_keys,
      because its key is validated against that server's own database, per deployment
    - the model server compares every incoming X-API-Key against one in-memory hash, so
      its authority is a secret version, not a table, and the value is identical on every
      host; an api_keys row would imply an authority that does not exist, so this script
      mints a value, writes a file, and does nothing else
    - one file must never serve both the model server and the Lupin API: their authorities
      coincide only where the dev key was seeded into Secret Manager; on the VM the key
      lives in that VM's database (right for the Lupin API) and never in Secret Manager
      (wrong for the model server), so /embeddings/generate answered 401 on every call
    - usage: python src/scripts/mint-model-server-api-key.py for a dry run, then add
      --apply to write, and --apply --force to overwrite an existing file
    - this script does not run the next step, which seeds Secret Manager (follow the
      rotation ordering in the model-server key decoupling design doc):
      src/scripts/cloud-run-setup-secrets.sh --secret-name lupin-model-server-api
      --key-file src/conf/keys/model-server-api
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
        - the value is not written, logged, or retained by this function

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
    Stable, non-reversible identifier for which key this is.

    The predicate must match the server's. lupin_model_server/main.py fingerprints
    `f.read().strip()`, and the client's du.get_api_key() also strips.

    Requires:
        - plaintext is a non-empty string

    Ensures:
        - returns 12 lowercase hex chars, the sha256 of the stripped value
        - hashing the raw file would include its trailing newline and give a different
          digest, so a raw and a stripped fingerprint of one key look like two keys;
          state the predicate wherever this number is printed
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
        - does not create, read, or write the file

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
