"""
Content hash of a file.

Many tools pin an input by the sha256 of its bytes. This is the one place that reads a file
for that, in bounded chunks so a large file does not have to fit in memory.
"""

import hashlib

CHUNK_BYTES = 1 << 20


def file_sha256( path ):
    """
    Return the sha256 hex digest of a file's bytes.

    Requires:
        - path is a path-like or string naming a readable file

    Ensures:
        - returns a 64-character lowercase hex digest
        - reads in chunks of CHUNK_BYTES

    Raises:
        - OSError if the file cannot be read
    """
    digest = hashlib.sha256()
    with open( path, "rb" ) as handle:
        for chunk in iter( lambda: handle.read( CHUNK_BYTES ), b"" ):
            digest.update( chunk )
    return digest.hexdigest()
