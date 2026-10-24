"""
Named errors of the need-set tools.

Each failure carries a code, so a caller reports the cause and never guesses it.
"""

QUOTA_UNFILLABLE        = "QUOTA_UNFILLABLE"
KIND_SPLIT_UNSET        = "KIND_SPLIT_UNSET"
QUOTA_INVALID           = "QUOTA_INVALID"
PLAN_ALREADY_WRITTEN    = "PLAN_ALREADY_WRITTEN"
BAD_NEED                = "BAD_NEED"
NEED_LEAKS_KEY          = "NEED_LEAKS_KEY"
CHECKER_EQUALS_DRAFTER  = "CHECKER_EQUALS_DRAFTER"
UNREADABLE_REPLY        = "UNREADABLE_REPLY"
BAD_ITEM                = "BAD_ITEM"
PACKET_LEAK             = "PACKET_LEAK"
BAD_LABEL               = "BAD_LABEL"
KAPPA_UNDEFINED         = "KAPPA_UNDEFINED"
MANIFEST_MISMATCH       = "MANIFEST_MISMATCH"
PROBE_UNREADABLE        = "PROBE_UNREADABLE"
SEED_NOT_VECTORISED     = "SEED_NOT_VECTORISED"
STRIP_FAILED            = "STRIP_FAILED"
BAD_ROUTE               = "BAD_ROUTE"


class NeedsetError( Exception ):
    """
    A need-set failure with a stable code.

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
