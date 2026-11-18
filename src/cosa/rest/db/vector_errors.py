"""Exceptions raised by vector retrieval, in a module with no imports."""


class QueryVectorRefused( Exception ):
    """A cosine search was given a query vector that cannot be trusted."""

    def __init__( self, reason: str ):
        """
        Keep the reason beside the exception text.

        Requires:
            - reason is a non-empty human-readable string

        Ensures:
            - ``str( exc )`` and ``exc.reason`` both equal reason
        """
        super().__init__( reason )
        self.reason = reason
