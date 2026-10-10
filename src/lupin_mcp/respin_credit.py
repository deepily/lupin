#!/usr/bin/env python3
"""
The one-for-one re-spin credit that lets a re-spin through while skeleton crew is on.

With skeleton crew on, no spawn is allowed. The operator ruled that a re-spin is allowed.
One seat is reaped and the same persona comes straight back, so the fleet stays the same
size. This module is how the spawn path knows a spawn is that case.

When a manager dismisses a seat and names its persona in the re-spin list, one credit is
written. The credit is keyed by the manager's session id and the persona, and it lives
fifteen minutes. The launcher spends it. Spending is one atomic unlink, so two launches
cannot share a credit, and a spent credit is gone.

The credit lives beside the launch reservations in the sessions folder. Every seat runs as
the same operating system user, so the credit is a record and not a lock. It is minted only
for a persona that was actually reaped, which keeps a re-spin one for one.
"""
import datetime
import json
import os
import re

from pathlib import Path
from typing import Any, List, Optional, Tuple

CREDIT_TTL_SECONDS = 900
CREDIT_DIR_ENV     = "LUPIN_RESPIN_CREDIT_DIR"
CREDIT_ENV         = "LUPIN_RESPIN_CREDIT"
CREDIT_SUBDIR      = "respin-credits"

_SAFE_NAME = re.compile( r"^[A-Za-z0-9_\-]+$" )


def credit_dir() -> str:
    """
    The folder that holds the credits.

    Ensures:
        - returns the env override when it is set, which tests use
        - else returns a folder inside the launch reservation folder, so the credits sit
          beside the bridges the launcher already counts
    """
    explicit = os.environ.get( CREDIT_DIR_ENV )
    if explicit:
        return explicit
    from lupin_mcp import fleet_cap_admission
    return str( fleet_cap_admission.reservation_dir() / CREDIT_SUBDIR )


def _path_for( manager_session_id: str, slug: str ) -> Optional[ str ]:
    """The file for one credit, or None when either name could climb out of the folder."""
    if not ( isinstance( manager_session_id, str ) and _SAFE_NAME.match( manager_session_id ) ):
        return None
    if not ( isinstance( slug, str ) and _SAFE_NAME.match( slug ) ):
        return None
    return os.path.join( credit_dir(), f"{manager_session_id}.{slug}.json" )


def _now( now: Optional[ datetime.datetime ] ) -> float:
    """The moment as epoch seconds."""
    moment = now if now is not None else datetime.datetime.now( datetime.timezone.utc )
    return moment.timestamp()


def mint( manager_session_id: str, slugs: List[ str ], now: Optional[ datetime.datetime ] = None ) -> List[ str ]:
    """
    Write one credit for each persona slug.

    Requires:
        - manager_session_id is the manager that reaped the seats
        - slugs are persona slugs of seats that were actually reaped

    Ensures:
        - writes one file per safe slug, replacing an older credit for the same pair
        - skips any name that is not made of letters, digits, hyphen and underscore
        - returns the slugs written, in order

    Raises:
        - OSError when the folder or a file cannot be written
    """
    written = []
    for slug in slugs:
        path = _path_for( manager_session_id, slug )
        if path is None:
            continue
        os.makedirs( os.path.dirname( path ), exist_ok=True )
        record = { "manager_session_id": manager_session_id, "persona_slug": slug, "minted_ts": _now( now ) }
        partial = path + ".partial"
        with open( partial, "w", encoding="utf-8" ) as handle:
            json.dump( record, handle )
            handle.flush()
            os.fsync( handle.fileno() )
        os.replace( partial, path )
        written.append( slug )
    return written


def find( manager_session_id: str, slug: str, now: Optional[ datetime.datetime ] = None ) -> Optional[ dict ]:
    """
    The credit for this manager and persona when it is fresh, else None.

    Ensures:
        - returns the record for an unspent credit younger than CREDIT_TTL_SECONDS
        - returns None when absent, expired, garbled, or for another manager or persona
        - never raises
    """
    path = _path_for( manager_session_id, slug )
    if path is None:
        return None
    try:
        with open( path, "r", encoding="utf-8" ) as handle:
            record = json.load( handle )
        age = _now( now ) - float( record[ "minted_ts" ] )
    except ( OSError, ValueError, KeyError, TypeError ):
        return None
    if age > CREDIT_TTL_SECONDS or record.get( "manager_session_id" ) != manager_session_id:
        return None
    return record


def spend( manager_session_id: str, slug: str, now: Optional[ datetime.datetime ] = None ) -> bool:
    """
    Use up the credit, once.

    Ensures:
        - returns True for exactly one caller when several race for one fresh credit
        - returns False when there is no fresh credit
        - the credit is gone afterwards
        - never raises
    """
    if find( manager_session_id, slug, now=now ) is None:
        return False
    path = _path_for( manager_session_id, slug )
    try:
        os.unlink( path )
    except OSError:
        return False
    return True


def respin_slug( persona_preference: Any, seed_memento: Any, count: int ) -> Optional[ str ]:
    """
    The persona slug when a spawn is a re-spin, else None.

    Requires:
        - persona_preference is what the spawn tool was given

    Ensures:
        - returns a slug only for exactly one named persona, a memento to seed it, and one
          child
        - returns None for the wildcard, a chain of several names, no memento or a batch
    """
    from lupin_mcp.persona_normalization import persona_slug
    from lupin_mcp.session_spawner import persona_chain_csv
    if not seed_memento or count != 1:
        return None
    chain = persona_chain_csv( persona_preference )
    if chain is None or "," in chain or chain.strip() == "*":
        return None
    slug = persona_slug( chain )
    return slug if slug else None


def env_value( manager_session_id: str, slug: str ) -> str:
    """The text the spawn path hands the launcher in the credit env var."""
    return f"{manager_session_id}:{slug}"


def parse_env_value( text: Optional[ str ] ) -> Optional[ Tuple[ str, str ] ]:
    """
    Split the launcher's credit env var back into manager and persona slug.

    Ensures:
        - returns ( manager_session_id, slug ) for text of exactly two safe names
        - returns None for anything else, including None
    """
    if not text:
        return None
    parts = text.split( ":" )
    if len( parts ) != 2:
        return None
    manager, slug = parts
    if not ( _SAFE_NAME.match( manager ) and _SAFE_NAME.match( slug ) ):
        return None
    return manager, slug
