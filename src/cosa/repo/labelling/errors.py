"""The named errors of the labelling tools."""

import sys

BAD_ITEM         = "BAD_ITEM"
PACKET_LEAK      = "PACKET_LEAK"
BAD_LABEL        = "BAD_LABEL"
KAPPA_UNDEFINED  = "KAPPA_UNDEFINED"
SANDBOX_UNAVAILABLE = "SANDBOX_UNAVAILABLE"
PROVENANCE_MISSING  = "PROVENANCE_MISSING"
STORE_LOCKED        = "STORE_LOCKED"


class LabellingError( Exception ):
    """
    A failure of the labelling tools with a stable code.

    Requires:
        - code is one of the constants of this module

    Ensures:
        - str( exc ) is the code, then ": <detail>" when a detail is given
        - code and detail are kept as attributes
    """

    def __init__( self, code, detail="" ):
        """Build the error from a code and an optional detail."""
        super().__init__( f"{code}: {detail}" if detail else code )
        self.code   = code
        self.detail = detail


def fail( message, code ):
    """
    Report a command-line failure.

    Requires:
        - message is a string; code is an int exit code

    Ensures:
        - prints the message to stderr
        - returns the exit code
    """
    print( message, file=sys.stderr )
    return code
