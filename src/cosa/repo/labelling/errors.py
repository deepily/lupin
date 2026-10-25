"""The named errors of the labelling tools."""

BAD_ITEM         = "BAD_ITEM"
PACKET_LEAK      = "PACKET_LEAK"
BAD_LABEL        = "BAD_LABEL"
KAPPA_UNDEFINED  = "KAPPA_UNDEFINED"


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
