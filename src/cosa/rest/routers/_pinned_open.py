"""
Open a file or folder first, then judge the object that was opened.

A path string that is judged and opened later can be swapped for a symlink in between. The doc
viewer and the io door both open the path first. They read where the descriptor lives
(`/proc/self/fd/N`, Linux only), judge that, and serve through the descriptor.

This module owns the descriptor mechanics and nothing else. It raises `PinnedPathGone` and lets
the caller's own judge raise the refusal. Each door keeps its own messages and status codes.
"""
import os
import stat

PROC_FD = "/proc/self/fd"


class PinnedPathGone( Exception ):
    """The path is absent, unlinked, or not the kind of object that was asked for."""


def landed_path_of_fd( fd ):
    """
    Where the inode behind `fd` lives right now.

    Requires:
        - fd is an open descriptor

    Ensures:
        - returns the absolute path /proc reports for the descriptor

    Raises:
        - PinnedPathGone when the inode has been unlinked
        - OSError when /proc cannot be read, which the caller treats as a refusal
    """
    landed = os.readlink( f"{PROC_FD}/{fd}" )
    if landed.endswith( " (deleted)" ):
        raise PinnedPathGone( landed )
    return landed


def open_pinned( full_path, judge, directory=False ):
    """
    Open `full_path`, then run `judge` on where it landed. The caller closes it.

    Requires:
        - judge is a callable( landed_path ) that raises to refuse
        - directory is True to pin a folder, False to pin a regular file

    Ensures:
        - returns a descriptor for a regular file (or a folder) that `judge` accepted
        - the descriptor is closed before any exception leaves

    Raises:
        - PinnedPathGone when the open fails, the object is the wrong kind, or it was unlinked
        - whatever `judge` raises
    """
    flags = os.O_RDONLY | os.O_CLOEXEC | ( os.O_DIRECTORY if directory else os.O_NONBLOCK )
    try:
        fd = os.open( full_path, flags )
    except OSError as error:
        raise PinnedPathGone( full_path ) from error
    try:
        if not directory and not stat.S_ISREG( os.fstat( fd ).st_mode ):
            raise PinnedPathGone( full_path )
        judge( landed_path_of_fd( fd ) )
    except BaseException:
        os.close( fd )
        raise
    return fd
