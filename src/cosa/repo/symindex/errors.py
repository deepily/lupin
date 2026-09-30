"""
Exceptions shared by the symbol-index package and its language extractors.
"""


class DependencyMissing( Exception ):
    """
    A tool the indexer needs is not available on this host (node, typescript, dart, analyzer).

    Requires:
        - what is a short name of the missing tool
    Ensures:
        - str( exc ) names the tool and the reason
        - exc.what carries the tool name so callers can map it to a cause code
    """

    def __init__( self, what, detail="" ):
        super().__init__( f"{what} is missing" + ( f": {detail}" if detail else "" ) )
        self.what = what
