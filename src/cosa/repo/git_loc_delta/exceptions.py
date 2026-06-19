"""
Git LoC Delta Custom Exceptions

Provides exception types for the git_loc_delta package. `GitCommandError`
is re-exported from the sibling `branch_analyzer` package so consumers can
catch either tool's git failures with a single import.

Exception Hierarchy:
    GitLocDeltaError (base, this package)
    ├── DateRangeError (invalid or impossible --since/--until/--branch range)
    └── (uses sibling) GitCommandError (re-exported from branch_analyzer)

Design Principles:
- Reuse `GitCommandError` from branch_analyzer (Pass 1 Reuse Map R2)
- Add only the date-range failure mode that's specific to per-day analysis
- Human-readable messages with context preservation
"""

from cosa.repo.branch_analyzer.exceptions import GitCommandError


class GitLocDeltaError( Exception ):
    """
    Base exception for all git_loc_delta errors.

    All package-specific exceptions inherit from this class, allowing
    consumers to catch any git_loc_delta error with a single except clause.

    Attributes:
        message (str): Human-readable error message
        context (dict): Optional context information
    """

    def __init__( self, message, context=None ):
        """
        Initialize base exception.

        Requires:
            - message is non-empty string
            - context is None or dict

        Ensures:
            - Exception initialized with message and optional context
        """
        super().__init__( message )
        self.message = message
        self.context = context or {}

    def __str__( self ):
        """
        Format error message with context if available.

        Ensures:
            - Returns formatted message including context key=value pairs
        """
        if self.context:
            context_str = ", ".join( f"{k}={v}" for k, v in self.context.items() )
            return f"{self.message} (Context: {context_str})"
        return self.message


class DateRangeError( GitLocDeltaError ):
    """
    Raised when the requested date range or branch range is invalid or empty.

    Examples:
        - --since after --until
        - --branch on the base branch itself (merge-base == HEAD)
        - --branch with a non-existent branch name

    Attributes:
        message (str): Human-readable error message
        since (str | None): Resolved --since value
        until (str | None): Resolved --until value
        branch (str | None): Branch name if --branch mode
    """

    def __init__( self, message, since=None, until=None, branch=None ):
        """
        Initialize date-range error.

        Requires:
            - message is non-empty string

        Ensures:
            - Exception captures since/until/branch context for debugging
        """
        context = {}
        if since  is not None: context["since"]  = since
        if until  is not None: context["until"]  = until
        if branch is not None: context["branch"] = branch
        super().__init__( message, context=context )
        self.since  = since
        self.until  = until
        self.branch = branch


__all__ = [
    "GitLocDeltaError",
    "DateRangeError",
    "GitCommandError",
]
