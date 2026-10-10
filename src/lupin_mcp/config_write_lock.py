#!/usr/bin/env python3
"""
The lock that serialises writes to the main configuration file.

The fleet cap and the skeleton crew switch are both written into the main configuration file.
Each writer reads the whole file, edits one line and replaces it. Two writes at nearly the
same moment could lose one, so each write takes one lock first.

The lock file lives in the flow-ratio folder, outside the source tree, so it never shows up
as an untracked file beside the configuration file.

    in a container   $LUPIN_FLOW_RATIO_DIR/.lupin-app.ini.lock
    on the host      <fleet data root>/flow-ratio/.lupin-app.ini.lock

The container folder is the same host folder as the host path. The bind mount the poke
switch already uses provides it. The server and the host processes therefore lock one file.
"""
import fcntl
import os

from contextlib import contextmanager
from typing import Iterator

LOCK_DIR_ENV = "LUPIN_CONFIG_LOCK_DIR"
FLOW_DIR_ENV = "LUPIN_FLOW_RATIO_DIR"
LOCK_FILENAME = ".lupin-app.ini.lock"


def lock_dir() -> str:
    """
    The folder that holds the write lock.

    Ensures:
        - returns the env override when it is set, which tests use
        - else returns the flow-ratio mount's folder when that env is set
        - else returns the flow-ratio folder under the fleet data root on the host
    """
    explicit = os.environ.get( LOCK_DIR_ENV )
    if explicit:
        return explicit
    flow_dir = os.environ.get( FLOW_DIR_ENV )
    if flow_dir:
        return flow_dir
    from lupin_cli.claude_code.hooks.lib.heartbeat_hold import fleet_data_root
    return os.path.join( str( fleet_data_root() ), "flow-ratio" )


def lock_path() -> str:
    """
    The lock file every write of the configuration file holds.

    Ensures:
        - lives inside `lock_dir()`
    """
    return os.path.join( lock_dir(), LOCK_FILENAME )


@contextmanager
def write_lock() -> Iterator[ None ]:
    """
    Hold the exclusive write lock for the body of a with block.

    Requires:
        - the lock folder can be created and written

    Ensures:
        - waits for any other holder, on the host or in a container
        - releases the lock when the block ends, including when it raises

    Raises:
        - OSError when the folder or the lock file cannot be created
    """
    os.makedirs( lock_dir(), exist_ok=True )
    handle = open( lock_path(), "w" )
    try:
        fcntl.flock( handle.fileno(), fcntl.LOCK_EX )
        yield
    finally:
        try:
            fcntl.flock( handle.fileno(), fcntl.LOCK_UN )
        finally:
            handle.close()
