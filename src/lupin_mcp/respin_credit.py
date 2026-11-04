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

The credit is not tied to the session name the launcher is given. It licenses one launch
of any name, which keeps the count one for one and nothing more.

The credit lives beside the launch reservations in the sessions folder. Every seat runs as
the same operating system user, so the credit is a record and not a lock. It is minted only
for a persona that was actually reaped, which keeps a re-spin one for one.

Known limits. The switch stops a manager that follows the tool's answer. It is not a barrier
against one that sets out to defeat it. Code injected into the launcher counts as the caller's
own parent. An environment variable that makes the shell run a script with a debug trap is one
way in. That code can restore a credit in the middle of a launch. The same user can also edit
the configuration file. This is documented and not fixed, by the manager's ruling (Cheech, October 10, 2026); the operator may overturn it.
"""
import datetime
import json
import math
import os
import re
import subprocess

from pathlib import Path
from typing import Any, Callable, List, Optional, Tuple

CREDIT_TTL_SECONDS = 900
CREDIT_DIR_ENV     = "LUPIN_RESPIN_CREDIT_DIR"
CREDIT_ENV         = "LUPIN_RESPIN_CREDIT"
CREDIT_SUBDIR      = "respin-credits"
CLAIM_PREFIX       = "claimed."

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
    _sweep_claims( now )
    return written


def _valid_record( record: Any, manager_session_id: str, moment: float ) -> bool:
    """
    Whether a credit record is fresh and trustworthy.

    Ensures:
        - requires a minted time that is a finite number and not a bool
        - requires 0 <= age <= CREDIT_TTL_SECONDS, so a time in the future never lives
        - requires the record to name the same manager as its file
    """
    if not isinstance( record, dict ) or record.get( "manager_session_id" ) != manager_session_id:
        return False
    minted = record.get( "minted_ts" )
    if isinstance( minted, bool ) or not isinstance( minted, ( int, float ) ) or not math.isfinite( minted ):
        return False
    age = moment - float( minted )
    return 0 <= age <= CREDIT_TTL_SECONDS


def find( manager_session_id: str, slug: str, now: Optional[ datetime.datetime ] = None ) -> Optional[ dict ]:
    """
    The credit for this manager and persona when it is fresh, else None.

    Ensures:
        - returns the record for an unspent credit that is 0 to CREDIT_TTL_SECONDS old
        - returns None when absent, expired, garbled, minted in the future or with a
          minted time that is not a finite number
        - returns None for another manager or persona
        - never raises
    """
    path = _path_for( manager_session_id, slug )
    if path is None:
        return None
    try:
        with open( path, "r", encoding="utf-8" ) as handle:
            record = json.load( handle )
    except ( OSError, ValueError ):
        return None
    return record if _valid_record( record, manager_session_id, _now( now ) ) else None


def _claim_path( session_name: Optional[ str ] ) -> Optional[ str ]:
    """The file a claimed credit waits in for this launch, or None for an unsafe name."""
    if not ( isinstance( session_name, str ) and _SAFE_NAME.match( session_name ) ):
        return None
    return os.path.join( credit_dir(), f"{CLAIM_PREFIX}{session_name}.json" )


def spend( manager_session_id: str, slug: str, now: Optional[ datetime.datetime ] = None,
           session_name: Optional[ str ] = None, owner_pid: Optional[ int ] = None ) -> bool:
    """
    Use up the credit, once.

    Requires:
        - session_name is the launch that takes the credit, or None
        - owner_pid is the process that is launching, or None

    Ensures:
        - returns True for exactly one caller when several race for one fresh credit
        - returns False when there is no fresh credit
        - the credit is no longer spendable afterwards
        - with a safe session_name the credit waits in a claim file, so `restore` can give
          it back if that session never starts. Without one it is simply removed
        - the claim file records owner_pid and that process's start time, when given
        - never raises
    """
    if find( manager_session_id, slug, now=now ) is None:
        return False
    path  = _path_for( manager_session_id, slug )
    claim = _claim_path( session_name )
    try:
        if claim is None:
            os.unlink( path )
        else:
            os.rename( path, claim )
    except OSError:
        return False
    if claim is not None and owner_pid is not None:
        _record_owner( claim, owner_pid )
    _sweep_claims( now )
    return True


def _record_owner( claim: str, owner_pid: int ) -> None:
    """
    Write the launcher's pid and start time into a claim file, replacing it whole.

    Ensures:
        - a claim that cannot be read or written is left as it was
        - never raises
    """
    try:
        with open( claim, "r", encoding="utf-8" ) as handle:
            record = json.load( handle )
        record[ "owner_pid" ]   = int( owner_pid )
        record[ "owner_start" ] = _process_start( owner_pid )
        partial = claim + ".partial"
        with open( partial, "w", encoding="utf-8" ) as handle:
            json.dump( record, handle )
            handle.flush()
            os.fsync( handle.fileno() )
        os.replace( partial, claim )
    except ( OSError, ValueError, TypeError, AttributeError ):
        return


def _process_start( pid: int ) -> Optional[ str ]:
    """
    The start time of a process in clock ticks since boot, or None when it cannot be read.

    Ensures:
        - returns the text of field 22 of /proc/<pid>/stat
        - returns None when the process is gone or the file cannot be parsed
        - never raises
    """
    try:
        with open( f"/proc/{int( pid )}/stat", "r", encoding="utf-8" ) as handle:
            text = handle.read()
        return text.rsplit( ")", 1 )[ 1 ].split()[ 19 ]
    except ( OSError, ValueError, IndexError ):
        return None


def _owner_is_running( record: dict ) -> bool:
    """
    Whether the launcher that took a claim is still the same running process.

    Ensures:
        - returns False for a claim that names no owner
        - returns False when the pid is gone, or now belongs to a process with another
          start time
        - never raises
    """
    pid = record.get( "owner_pid" )
    if isinstance( pid, bool ) or not isinstance( pid, int ) or pid <= 0:
        return False
    started = _process_start( pid )
    if started is None:
        return False
    recorded = record.get( "owner_start" )
    return recorded is None or recorded == started


def _session_is_live( session_name: str ) -> bool:
    """
    Whether a live bridge or a tmux session carries this name.

    Ensures:
        - returns True when a live bridge names the session
        - returns True when `tmux has-session` finds it
        - returns False only when tmux ran and found no such session
        - returns True when the check itself cannot run, including tmux missing from the
          search path, so a credit is never handed back on a guess
    """
    try:
        from lupin_mcp import fleet_cap_admission
        if fleet_cap_admission._live_bridge_lookup( session_name ):
            return True
        found = subprocess.run( [ "tmux", "has-session", "-t", f"={session_name}" ],
                                capture_output=True, timeout=5 )
        return found.returncode == 0
    except Exception:
        return True


def restore( session_name: str, now: Optional[ datetime.datetime ] = None,
             live_fn: Optional[ Callable[ [ str ], bool ] ] = None,
             caller_pid: Optional[ int ] = None ) -> bool:
    """
    Give a claimed credit back because the launch it was taken for did not start a session.

    Requires:
        - live_fn, when given, answers whether a session of that name is running
        - caller_pid is the launcher process asking, which defaults to this process's parent

    Ensures:
        - returns True when the credit is spendable again, with its original clock
        - returns False when nothing was claimed under that name, when the credit has since
          expired, or when a newer credit for the same manager and persona already exists
        - returns False and removes the claim when a live bridge or tmux session carries that
          name, so one credit never buys a second seat
        - returns False and keeps the claim while the launcher that took it is still running,
          unless that launcher is the caller. A release from another shell cannot undo a
          launch that has not yet made its session
        - a second restore of the same claim returns False
        - never raises
    """
    claim = _claim_path( session_name )
    if claim is None:
        return False
    try:
        with open( claim, "r", encoding="utf-8" ) as handle:
            record = json.load( handle )
    except ( OSError, ValueError ):
        return False
    if ( live_fn if live_fn is not None else _session_is_live )( session_name ):
        try:
            os.unlink( claim )
        except OSError:
            pass
        return False
    owner = record.get( "owner_pid" ) if isinstance( record, dict ) else None
    asker = caller_pid if caller_pid is not None else os.getppid()
    if isinstance( record, dict ) and owner != asker and _owner_is_running( record ):
        return False
    manager = record.get( "manager_session_id" ) if isinstance( record, dict ) else None
    slug    = record.get( "persona_slug" ) if isinstance( record, dict ) else None
    target  = _path_for( manager, slug )
    try:
        if target is None or not _valid_record( record, manager, _now( now ) ) or os.path.exists( target ):
            os.unlink( claim )
            return False
        os.rename( claim, target )
    except OSError:
        return False
    return True


def _sweep_claims( now: Optional[ datetime.datetime ] ) -> None:
    """
    Remove claim files older than the credit's life.

    Ensures:
        - a claim for a session that did start is cleared once it could no longer be restored
        - a claim whose minted time is unreadable is judged by the file's own time
        - never raises
    """
    try:
        names = os.listdir( credit_dir() )
    except OSError:
        return
    moment = _now( now )
    for name in names:
        if not name.startswith( CLAIM_PREFIX ):
            continue
        path = os.path.join( credit_dir(), name )
        try:
            try:
                with open( path, "r", encoding="utf-8" ) as handle:
                    minted = json.load( handle ).get( "minted_ts" )
            except ( OSError, ValueError, AttributeError ):
                minted = None
            if isinstance( minted, bool ) or not isinstance( minted, ( int, float ) ) or not math.isfinite( minted ):
                minted = os.path.getmtime( path )
            if moment - float( minted ) > CREDIT_TTL_SECONDS:
                os.unlink( path )
        except OSError:
            continue


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
