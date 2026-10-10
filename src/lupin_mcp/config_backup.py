#!/usr/bin/env python3
"""
Where the configuration file's write lock and its pre-write backups live.

The fleet cap and the skeleton crew switch are both written into the main configuration file.
Each writer reads the whole file, edits one line and replaces it. Two writes at nearly the
same moment could lose one, so each write takes one lock first.

The lock and the backup copies live in one folder outside the source tree. Neither shows up
as an untracked file beside the configuration file.

    in a container   $LUPIN_FLOW_RATIO_DIR/config-backups
    on the host      <fleet data root>/flow-ratio/config-backups

The container folder is the same host folder as the host path. The bind mount the poke
switch already uses provides it. The server and the host processes therefore lock one file.
"""
import fcntl
import os

from contextlib import contextmanager
from typing import Iterator

BACKUP_DIR_ENV = "LUPIN_CONFIG_BACKUP_DIR"
FLOW_DIR_ENV   = "LUPIN_FLOW_RATIO_DIR"
BACKUP_SUBDIR  = "config-backups"
LOCK_FILENAME  = ".lupin-app.ini.lock"


def backup_dir() -> str:
    """
    The folder that holds the write lock and the backup copies.

    Ensures:
        - returns the env override when it is set, which tests use
        - else returns the flow-ratio mount's config-backups folder when that env is set
        - else returns the config-backups folder under the fleet data root on the host
    """
    explicit = os.environ.get( BACKUP_DIR_ENV )
    if explicit:
        return explicit
    flow_dir = os.environ.get( FLOW_DIR_ENV )
    if flow_dir:
        return os.path.join( flow_dir, BACKUP_SUBDIR )
    from lupin_cli.claude_code.hooks.lib.heartbeat_hold import fleet_data_root
    return os.path.join( str( fleet_data_root() ), "flow-ratio", BACKUP_SUBDIR )


def lock_path() -> str:
    """
    The lock file every write of the configuration file holds.

    Ensures:
        - lives inside `backup_dir()`
    """
    return os.path.join( backup_dir(), LOCK_FILENAME )


@contextmanager
def write_lock() -> Iterator[ None ]:
    """
    Hold the exclusive write lock for the body of a with block.

    Requires:
        - the backup folder can be created and written

    Ensures:
        - waits for any other holder, on the host or in a container
        - releases the lock when the block ends, including when it raises

    Raises:
        - OSError when the folder or the lock file cannot be created
    """
    os.makedirs( backup_dir(), exist_ok=True )
    handle = open( lock_path(), "w" )
    try:
        fcntl.flock( handle.fileno(), fcntl.LOCK_EX )
        yield
    finally:
        try:
            fcntl.flock( handle.fileno(), fcntl.LOCK_UN )
        finally:
            handle.close()
