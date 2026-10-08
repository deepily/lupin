"""
A per-run secret that lets a test suite vouch for the jobs it starts.

The v2 doors honour a caller's lineage claim only for an admin, the test account, or the
parent job's owner. A test that registers a fresh random user holds none of those, so its job
waits behind the suite that is waiting on it. This module adds a fourth lawful holder: a caller
that presents the secret the server issued for the run that currently holds the monopoly slot.

The store keeps only the digest of each token, in memory, behind a lock. A restart forgets every
token, which fails closed. The parent id is public, since GET /api/busy publishes it, and the
token is not: no endpoint may return a job's environment or arguments.

The token reaches the child through the environment, so any process the suite starts can read it.
The variable name keeps a credential word, so the redaction layer hunts its value in test output.
"""

import hashlib
import hmac
import secrets
import threading
import time
from typing import Callable, Optional

from cosa.config.configuration_manager import ConfigurationManager

TOKEN_ENV_NAME      = "LUPIN_TEST_MONOPOLIZE_PARENT_TOKEN"
TOKEN_HEADER        = "X-Lupin-Lineage-Token"
TOKEN_HEADER_MAX    = 256
TOKEN_ENABLED_KEY   = "v2 parent stamp token enabled"
EXPIRY_SLACK_SECONDS = 600

REASON_UNKNOWN      = "token_unknown"
REASON_MISMATCH     = "token_mismatch"
REASON_EXPIRED      = "token_expired"
REASON_NOT_ACTIVE   = "not_active_monopolizer"

_lock  = threading.Lock()
_store = { }


def token_enabled() -> bool:
    """
    Whether this server issues and accepts a per-run suite token.

    Ensures:
        - returns False when the INI key is absent, which is the case in Baseline and Production
        - is read per call, so the job and the vet cannot disagree about the switch
    """
    config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
    return bool( config_mgr.get( TOKEN_ENABLED_KEY, default=False, return_type="boolean" ) )


def _digest( token: str ) -> str:
    """The SHA-256 hex digest of a token, which is ASCII and so safe to compare in constant time."""
    return hashlib.sha256( token.encode( "utf-8" ) ).hexdigest()


def issue( parent_id: str, ttl_seconds: float, now: Optional[ float ] = None ) -> str:
    """
    Create the token for one sweep and remember its digest against the parent id.

    Requires:
        - parent_id is a non-empty string, the id of the job that holds the monopoly slot
        - ttl_seconds is a positive number

    Ensures:
        - returns a fresh URL-safe token of at least 40 characters
        - the store holds the digest and the expiry, never the token
        - a second call for the same parent replaces the first, so only the newer token checks

    Raises:
        - ValueError if parent_id is empty or ttl_seconds is not positive
    """
    if not parent_id: raise ValueError( "parent_id must be a non-empty string" )
    if ttl_seconds <= 0: raise ValueError( f"ttl_seconds must be positive, got {ttl_seconds!r}" )
    started = time.monotonic() if now is None else now
    token   = secrets.token_urlsafe( 32 )
    with _lock:
        _store[ parent_id ] = ( _digest( token ), started + ttl_seconds )
    return token


def revoke( parent_id: str ) -> None:
    """
    Forget the token issued for a parent.

    Ensures:
        - after the call no token checks for this parent
        - revoking a parent that has no token is a no-op
    """
    with _lock:
        _store.pop( parent_id, None )


def clear() -> None:
    """Forget every token. Tests call this so one case cannot leak a token into the next."""
    with _lock:
        _store.clear()


def check( parent_id: Optional[ str ], token: Optional[ str ], active_monopolizer: Callable[ [ ], Optional[ str ] ],
           now: Optional[ float ] = None ) -> tuple:
    """
    Decide whether a presented token vouches for a parent id.

    Requires:
        - active_monopolizer is a callable returning the id of the job that holds the monopoly
          slot, or None. It is read only after the digest matches and the token is unexpired.

    Ensures:
        - returns ( True, None ) when the digest matches, the token has not expired, and the
          parent is the active monopolizer
        - otherwise returns ( False, reason ) with reason one of token_unknown, token_mismatch,
          token_expired, not_active_monopolizer
        - the reason is a fixed word and never contains the token
        - an empty, non-string, non-ASCII or over-long token is token_mismatch when the parent
          has a token, and never raises
        - the digests are compared with hmac.compare_digest
    """
    with _lock:
        entry = _store.get( parent_id ) if isinstance( parent_id, str ) else None
    if entry is None: return False, REASON_UNKNOWN
    stored_digest, expires_at = entry
    if not isinstance( token, str ) or not token or len( token ) > TOKEN_HEADER_MAX or not token.isascii():
        return False, REASON_MISMATCH
    if not hmac.compare_digest( _digest( token ), stored_digest ): return False, REASON_MISMATCH
    current = time.monotonic() if now is None else now
    if current >= expires_at: return False, REASON_EXPIRED
    if active_monopolizer() != parent_id: return False, REASON_NOT_ACTIVE
    return True, None
