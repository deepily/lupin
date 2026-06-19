"""
Unit tests for cosa.repo.git_loc_delta.exceptions.

Tests the git_loc_delta exception surface: GitLocDeltaError (base, with a
message + optional context dict and a context-aware __str__), DateRangeError
(adds since/until/branch context), and the GitCommandError re-export from the
sibling branch_analyzer package (Reuse Map R2 — consumers catch either tool's
git failures via one import). Coverage drives the context-dict construction,
None-field omission, __str__ both branches, attribute preservation, the
re-export identity, and the inheritance contract.

Part of the CoSA 100% coverage campaign (repo module group).
"""
import pytest

from cosa.repo.git_loc_delta.exceptions import (
    GitLocDeltaError,
    DateRangeError,
    GitCommandError,
)
import cosa.repo.git_loc_delta.exceptions as gld_exc
from cosa.repo.branch_analyzer.exceptions import GitCommandError as BAGitCommandError


class TestGitLocDeltaError:
    """The base exception: message + optional context, context-aware __str__."""

    def test_defaults_context_to_empty_dict( self ):
        """Ensures: message stored verbatim; omitted context becomes {} not None."""
        err = GitLocDeltaError( "broke" )
        assert err.message == "broke"
        assert err.context == {}

    def test_preserves_supplied_context( self ):
        """Ensures: a supplied context dict is stored as-is."""
        err = GitLocDeltaError( "boom", context={ "k": "v" } )
        assert err.context == { "k": "v" }

    def test_str_without_context_is_bare_message( self ):
        """Ensures: __str__ returns just the message when context is empty."""
        assert str( GitLocDeltaError( "plain" ) ) == "plain"

    def test_str_with_context_appends_pairs( self ):
        """Ensures: __str__ appends a '(Context: k=v)' suffix when context present."""
        rendered = str( GitLocDeltaError( "bad", context={ "a": 1, "b": 2 } ) )
        assert rendered.startswith( "bad (Context: " )
        assert "a=1" in rendered and "b=2" in rendered

    def test_is_raisable( self ):
        """Ensures: the base type is a real, raisable Exception."""
        with pytest.raises( GitLocDeltaError ):
            raise GitLocDeltaError( "raise me" )


class TestDateRangeError:
    """Invalid/empty date or branch range; carries since/until/branch context."""

    def test_full_fields_stored_and_in_context( self ):
        """
        Ensures:
            - since/until/branch stored verbatim on attributes
            - each non-None field surfaces in the context dict
        """
        err = DateRangeError( "bad range", since="2026-01-01", until="2026-01-02", branch="wip" )
        assert err.since == "2026-01-01"
        assert err.until == "2026-01-02"
        assert err.branch == "wip"
        assert err.context == { "since": "2026-01-01", "until": "2026-01-02", "branch": "wip" }

    def test_none_fields_omitted_from_context( self ):
        """
        Ensures:
            - all-None optional fields yield an empty context (bare __str__)
            - the attributes are still present as None
        """
        err = DateRangeError( "empty range" )
        assert err.context == {}
        assert err.since is None and err.until is None and err.branch is None
        assert str( err ) == "empty range"

    def test_partial_fields_only_present_ones_in_context( self ):
        """
        Ensures:
            - only the supplied subset (here: branch) appears in context;
              the None since/until are omitted
        """
        err = DateRangeError( "branch only", branch="feature-x" )
        assert err.context == { "branch": "feature-x" }
        assert "since" not in err.context
        assert "until" not in err.context

    def test_subclass_of_base( self ):
        """Ensures: DateRangeError is catchable as GitLocDeltaError."""
        assert issubclass( DateRangeError, GitLocDeltaError )
        with pytest.raises( GitLocDeltaError ):
            raise DateRangeError( "boom" )


class TestGitCommandErrorReexport:
    """GitCommandError is re-exported from branch_analyzer (R2 reuse)."""

    def test_reexport_is_the_branch_analyzer_class( self ):
        """
        Ensures:
            - the name exported here is the SAME object as branch_analyzer's
              GitCommandError (a true re-export, not a redefinition)
        """
        assert GitCommandError is BAGitCommandError

    def test_appears_in_module_all( self ):
        """Ensures: GitCommandError is advertised in the module __all__."""
        assert "GitCommandError" in gld_exc.__all__


class TestModuleAll:
    """__all__ advertises exactly the public surface, all resolvable."""

    def test_all_names_present_and_exact( self ):
        """
        Ensures:
            - __all__ is exactly the three public names
            - every advertised name resolves to a real module attribute
        """
        assert set( gld_exc.__all__ ) == {
            "GitLocDeltaError", "DateRangeError", "GitCommandError"
        }
        for name in gld_exc.__all__:
            assert hasattr( gld_exc, name )
