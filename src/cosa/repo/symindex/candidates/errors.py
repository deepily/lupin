"""
Named errors of the candidate stage.

Each failure carries a code, so a caller reports the cause and never guesses it.
"""

STORAGE_KEY_MISSING    = "STORAGE_KEY_MISSING"
DEPENDENCY_MISSING     = "DEPENDENCY_MISSING"
ENGINE_MISMATCH        = "ENGINE_MISMATCH"
ENGINE_NOT_LOADED      = "ENGINE_NOT_LOADED"
VECTOR_SET_UNAVAILABLE = "VECTOR_SET_UNAVAILABLE"
VECTOR_SET_CORRUPT     = "VECTOR_SET_CORRUPT"
EMBEDDING_SHAPE        = "EMBEDDING_SHAPE"


class CandidateError( Exception ):
    """
    A candidate-stage failure with a stable code.

    Requires:
        - code is one of the module's code constants

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
