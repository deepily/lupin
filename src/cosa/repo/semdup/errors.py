"""The named errors of the semantic duplicate checker."""

CONFIG_DRIFT          = "CONFIG_DRIFT"
CONFIG_ALREADY_FROZEN = "CONFIG_ALREADY_FROZEN"
CONFIG_UNDECIDED      = "CONFIG_UNDECIDED"
POLICY_UNDECIDED      = "POLICY_UNDECIDED"
POLICY_UNKNOWN        = "POLICY_UNKNOWN"
EXTRACT_INCOMPLETE    = "EXTRACT_INCOMPLETE"
DEPENDENCY_MISSING    = "DEPENDENCY_MISSING"
BLINDNESS_BREACH      = "BLINDNESS_BREACH"
JUDGE_UNREADABLE      = "JUDGE_UNREADABLE"
RUN_INCOMPLETE        = "RUN_INCOMPLETE"
NO_PASSING_TESTS      = "NO_PASSING_TESTS"
NO_FLAGS              = "NO_FLAGS"
BAD_PAIR_SOURCE       = "BAD_PAIR_SOURCE"

CODES = frozenset( {
    CONFIG_DRIFT, CONFIG_ALREADY_FROZEN, CONFIG_UNDECIDED, POLICY_UNDECIDED, POLICY_UNKNOWN, EXTRACT_INCOMPLETE, DEPENDENCY_MISSING,
    BLINDNESS_BREACH, JUDGE_UNREADABLE, RUN_INCOMPLETE, NO_PASSING_TESTS, NO_FLAGS, BAD_PAIR_SOURCE,
} )


class SemdupError( Exception ):
    """
    A failure of the duplicate checker, named by a code so a caller never reads a message.

    Requires:
        - code is one of the named codes in this module
        - detail is a string

    Ensures:
        - exc.code and exc.detail carry the arguments
        - str( exc ) is "<code>: <detail>"

    Raises:
        - ValueError if code is not a named code
    """

    def __init__( self, code, detail ):
        """
        Build the error from a code and its detail.

        Requires:
            - code is one of the named codes in this module
            - detail is a string

        Ensures:
            - both are kept as attributes

        Raises:
            - ValueError if code is not a named code
        """
        if code not in CODES: raise ValueError( f"unknown semdup error code {code!r}" )
        super().__init__( f"{code}: {detail}" )
        self.code   = code
        self.detail = detail
