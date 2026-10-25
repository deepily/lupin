"""
Named errors of the run harness.

Each failure carries a code, so a caller reports the cause and never guesses it.
"""

BAD_ARM            = "BAD_ARM"
BAD_SPEC           = "BAD_SPEC"
SURFACE_REACHABLE  = "SURFACE_REACHABLE"
SURFACE_MISSING    = "SURFACE_MISSING"
CLIENT_NOT_EMPTY   = "CLIENT_NOT_EMPTY"
DB_NOT_FRESH       = "DB_NOT_FRESH"
DB_NOT_OWN         = "DB_NOT_OWN"
NO_PROGRESS        = "NO_PROGRESS"


class HarnessError( Exception ):
    """
    A run-harness failure with a stable code.

    Requires:
        - code is one of the constants of this module

    Ensures:
        - str( exc ) is the code, followed by ": <detail>" when a detail is given
        - code and detail are kept as attributes
    """

    def __init__( self, code, detail="" ):
        """
        Build the error from a code and an optional detail.

        Ensures:
            - the message starts with the code
        """
        super().__init__( f"{code}: {detail}" if detail else code )
        self.code   = code
        self.detail = detail
