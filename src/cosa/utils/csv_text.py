"""
The one reading of a hand-typed comma-separated list.

An operator types these values into an INI file, an environment variable or a command-line flag.
Spaces around an entry and empty entries are noise, so every reader drops them.
"""
from typing import List, Optional


def split_csv( text: Optional[ str ], lower: bool = False ) -> List[ str ]:
    """
    Split a comma-separated list into its non-blank entries.

    Requires:
        - text is a string or None
        - lower is a bool

    Ensures:
        - returns the entries in order, each stripped of surrounding blanks
        - entries that are empty after stripping are dropped
        - with lower True, each entry is lowercased
        - returns [] for None or an empty string
    """
    entries = [ entry.strip() for entry in ( text or "" ).split( "," ) ]
    return [ entry.lower() if lower else entry for entry in entries if entry ]
