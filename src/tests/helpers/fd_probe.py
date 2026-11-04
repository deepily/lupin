"""
Count the descriptors a test owns, not the descriptors the process owns.

A test that asserts `len( os.listdir( "/proc/self/fd" ) ) == before` measures every descriptor in the
process. In a full unit run other tests leave sockets and files behind. Garbage collection closes them at
any moment, so the total moves under a test that did nothing. A 41 minute tier once read `assert 40 == 42`,
after the door had closed its own descriptor.

Count only descriptors that point under the test's own temporary folder. A descriptor the door under test
leaves open points there, and an unrelated one does not.
"""
import os

PROC_FD = "/proc/self/fd"


def fds_under( root ):
    """
    Count this process's open descriptors that point at a path under `root`.

    Requires:
        - root is a path (str or path-like), normally the test's own tmp_path

    Ensures:
        - returns the number of descriptors whose link target is `root` or below it
        - a deleted target still counts, since /proc appends " (deleted)" to the same path
        - a descriptor closed while the folder is read is skipped, never an error

    Raises:
        - nothing
    """
    prefix = os.path.realpath( os.fspath( root ) )
    found  = 0
    for name in os.listdir( PROC_FD ):
        try:
            target = os.readlink( f"{PROC_FD}/{name}" )
        except OSError:
            continue
        if target == prefix or target.startswith( prefix + os.sep ): found += 1
    return found
