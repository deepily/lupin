"""
Detect drift between an app-side API key file and its Secret Manager copy.

WHY THIS EXISTS (2026-07-25): the model server's X-API-Key lives in TWO
hand-synced places — `src/conf/keys/{key_name}` (what every client sends) and
Secret Manager `{secret_id}` (what the Cloud Run model server mounts and
validates against). Nothing compared them. The app-side key was re-minted at
some point; Secret Manager kept version 1 from 2025-11-12; and the mismatch
stayed INVISIBLE for ~8 months until a user pressed the microphone button and
got a 401. Full record: task-store row 30198303.

The failure mode this guards is specifically a SILENT one: both authorities
are individually well-formed, both look healthy in isolation, and only their
EQUALITY is the invariant. That is exactly the shape a routine check catches
and a human reading either side alone never will.

DESIGN — hash comparison, not a live auth probe. A live probe (call the model
server with the key, assert 200) tests a strictly stronger property and would
catch more causes. It is deliberately NOT the default: the model server is a
scale-to-zero L4 GPU service, so probing it cold-starts real billable
hardware. A routine guard must be free to run. The live probe belongs in a
deliberate, opt-in deep check.

Plaintext is NEVER returned or logged — only sha256 digests. A drift report
is safe to print, paste into a ticket, or attach to a notification.
"""

import hashlib
import os
import subprocess
from typing import Callable, Optional


# Digest prefix length used in human-facing reports. Full digests are
# available on the returned dict; the short form is what gets printed, since
# 16 hex chars is far past collision-by-accident for a 2-value comparison.
_SHORT = 16


def sha256_of( text: str ) -> str:
    """
    Return the hex sha256 of a string.

    Requires:
        - text is a string

    Ensures:
        - returns a 64-char lowercase hex digest
        - encodes as UTF-8 (matches how both authorities store the key)

    Raises:
        - AttributeError if text is not a string
    """
    return hashlib.sha256( text.encode( "utf-8" ) ).hexdigest()


def fingerprint_key_file( key_path: str ) -> Optional[ str ]:
    """
    Hash the app-side key file's STRIPPED contents.

    Stripping is not cosmetic — it mirrors the two readers exactly:
    `du.get_api_key()` returns `get_file_as_string( path ).strip()`, and the
    model server does `f.read().strip()` (lupin_model_server/main.py:123). A
    fingerprint that did not strip would report drift on a trailing newline
    that neither consumer can observe.

    Requires:
        - key_path is a non-empty string

    Ensures:
        - returns the sha256 hex digest of the stripped file contents
        - returns None if the file is absent or unreadable
        - never raises on a missing/unreadable file
        - never returns or logs the plaintext
    """
    try:
        with open( key_path, "r", encoding="utf-8" ) as f:
            return sha256_of( f.read().strip() )
    except ( OSError, UnicodeDecodeError ):
        return None


def fingerprint_secret_manager(
    secret_id  : str,
    project_id : str,
    version    : str = "latest",
    runner     : Callable = subprocess.run
) -> Optional[ str ]:
    """
    Hash the Secret Manager copy WITHOUT ever surfacing the plaintext.

    `runner` is injected so this is unit-testable with no gcloud, no network,
    and no real secret — the alternative (mocking module globals) is what
    makes credential code untested in practice.

    Requires:
        - secret_id and project_id are non-empty strings
        - runner has subprocess.run's signature and returns an object with
          `returncode` and `stdout`

    Ensures:
        - returns the sha256 hex digest of the stripped secret value
        - returns None when gcloud is absent, unauthenticated, times out, or
          the secret/version does not exist
        - never returns or logs the plaintext
        - never raises

    Raises:
        - nothing; every failure mode collapses to None by design, because a
          drift check that crashes the caller is worse than one that reports
          "could not determine"
    """
    cmd = [
        "gcloud", "secrets", "versions", "access", version,
        f"--secret={secret_id}",
        f"--project={project_id}",
    ]
    try:
        result = runner( cmd, capture_output=True, text=True, timeout=90 )
    except ( FileNotFoundError, OSError, subprocess.TimeoutExpired ):
        return None

    if result.returncode != 0:
        return None
    if not result.stdout:
        return None

    return sha256_of( result.stdout.strip() )


def check_key_drift(
    key_path   : str,
    secret_id  : str,
    project_id : str,
    version    : str = "latest",
    runner     : Callable = subprocess.run
) -> dict:
    """
    Compare the app-side key file against its Secret Manager copy.

    Requires:
        - key_path, secret_id, project_id are non-empty strings

    Ensures:
        - returns a dict with keys: status, key_file_sha256, secret_sha256,
          key_path, secret_id, project_id, version, detail
        - status is exactly one of:
            "match"        both readable and equal
            "drift"        both readable and DIFFERENT — the 30198303 failure
            "unknown"      one or both sides unreadable; NOT a pass
        - digests in the dict are full 64-char hex, or None when unreadable
        - `detail` names the remedy on drift, and names WHICH side was
          unreadable on unknown
        - never returns or logs plaintext
        - "unknown" is deliberately NOT folded into "match": a check that
          cannot see one side has not verified anything, and reporting that
          as a pass is the alarm-gated-on-the-healthy-value defect
    """
    key_hash    = fingerprint_key_file( key_path )
    secret_hash = fingerprint_secret_manager( secret_id, project_id, version, runner )

    report = {
        "key_file_sha256" : key_hash,
        "secret_sha256"   : secret_hash,
        "key_path"        : key_path,
        "secret_id"       : secret_id,
        "project_id"      : project_id,
        "version"         : version,
    }

    if key_hash is None or secret_hash is None:
        missing = []
        if key_hash    is None: missing.append( f"key file ({key_path})" )
        if secret_hash is None: missing.append( f"Secret Manager ({secret_id}:{version})" )
        report[ "status" ] = "unknown"
        report[ "detail" ] = (
            "UNDETERMINED — could not read: " + " and ".join( missing ) +
            ". This is NOT a pass; the comparison did not happen."
        )
        return report

    if key_hash == secret_hash:
        report[ "status" ] = "match"
        report[ "detail" ] = f"OK — both sides are {key_hash[ :_SHORT ]}…"
        return report

    report[ "status" ] = "drift"
    report[ "detail" ] = (
        f"DRIFT — key file is {key_hash[ :_SHORT ]}… but Secret Manager "
        f"{secret_id}:{version} is {secret_hash[ :_SHORT ]}…. Clients will "
        f"authenticate with the key file and be REJECTED (401). Remedy: "
        f"`gcloud secrets versions add {secret_id} --project={project_id} "
        f"--data-file=-` fed the STRIPPED key-file contents, then let the "
        f"service pick up the new version (a scale-to-zero service resolves "
        f"`latest` on its next cold start; otherwise roll a revision)."
    )
    return report


def format_report( report: dict ) -> str:
    """
    Render a drift report as a single human-readable line.

    Requires:
        - report is a dict returned by check_key_drift()

    Ensures:
        - returns a string beginning with a status marker
        - contains no plaintext key material
    """
    marker = { "match": "OK", "drift": "FAIL", "unknown": "WARN" }.get( report[ "status" ], "????" )
    return f"[{marker}] key-drift {report[ 'key_path' ]} vs {report[ 'secret_id' ]}: {report[ 'detail' ]}"


def quick_smoke_test():
    """Exercise the three verdicts with an injected runner — no gcloud, no network."""
    import cosa.utils.util as du

    du.print_banner( "secret_drift quick_smoke_test", prepend_nl=True )

    class _R:
        def __init__( self, rc, out ):
            self.returncode = rc
            self.stdout     = out

    tmp_path = "/tmp/_secret_drift_smoke_key"
    with open( tmp_path, "w" ) as f: f.write( "ck_live_abc\n" )

    try:
        same = check_key_drift( tmp_path, "sid", "proj", runner=lambda *a, **k: _R( 0, "ck_live_abc\n" ) )
        print( f"match   -> {same[ 'status' ]}" )
        assert same[ "status" ] == "match", same

        diff = check_key_drift( tmp_path, "sid", "proj", runner=lambda *a, **k: _R( 0, "ck_live_zzz" ) )
        print( f"drift   -> {diff[ 'status' ]}" )
        assert diff[ "status" ] == "drift", diff

        gone = check_key_drift( tmp_path, "sid", "proj", runner=lambda *a, **k: _R( 1, "" ) )
        print( f"unknown -> {gone[ 'status' ]}" )
        assert gone[ "status" ] == "unknown", gone

        print( format_report( diff ) )
        print( "✓ secret_drift smoke passed" )
    finally:
        os.remove( tmp_path )


if __name__ == "__main__":
    quick_smoke_test()
