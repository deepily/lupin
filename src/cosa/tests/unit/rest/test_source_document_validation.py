#!/usr/bin/env python3
"""
Unit tests for the `source_document` argument validator.

WHY THESE TOUCH A REAL FILESYSTEM. Row 0cd3811a's lesson, paid for once already: every
pre-existing path test in this tree boundary-mocks `os.path.isfile` and `builtins.open`,
so no test in that suite had ever resolved a real path — and a symlink defect was
therefore invisible to all nineteen of them BY CONSTRUCTION. A validator whose entire
job is deciding which real file may be read cannot be tested against a mocked one. So
every fixture here is a real tmpdir, and the symlink is a real symlink.

THE POSITIVE CONTROL IS NOT OPTIONAL. `test_a_real_in_scope_document_is_ACCEPTED` is
what separates "the rule refuses the wrong things" from "the rule refuses everything".
Without it every refusal test below would still pass against a validator that returned
an error unconditionally, and the suite would report a working guard that admits nothing.
"""

import os
import shutil
import tempfile
import unittest

from cosa.rest.v2.source_document import (
    SOURCE_DOCUMENT_ARG,
    MAX_SOURCE_DOCUMENTS,
    parse_source_documents,
    split_scope,
    resolve_within_root,
    validate_source_documents,
)


from cosa.rest.routers._scope_registry import ScopeConfig


def _Scope( name, root, allowed_prefixes=( ) ):
    """A REAL ScopeConfig, not a hand-rolled stand-in.

    🔴 THIS USED TO BE A TWO-ATTRIBUTE FAKE carrying only `name` and `root`, on the
    reasoning that those were "the two lines this validator actually reads". That was true
    when written and stopped being true the moment the validator started applying the
    doc-viewer's own guards, which read `manifest` and `extra_blocklist_patterns` too — so
    every test using the fake blew up with AttributeError.

    Which is the same defect Krishna found one layer out, reproduced inside my own
    harness: a stand-in thinner than the real object proves nothing about the real call,
    and it fails at the moment the code under test starts using the parts you left out.
    ScopeConfig is a frozen dataclass with defaults — there was never a reason to fake it.
    """
    return ScopeConfig( name=name, root=root, allowed_prefixes=allowed_prefixes )


class TestParseSourceDocuments( unittest.TestCase ):
    """Shape only — nothing here touches a disk."""

    def test_absent_argument_is_ABSENT_not_invalid( self ):
        """The argument is optional; three spellings of "nothing" all mean nothing."""
        for raw in ( None, "", "   ", [ ], ( ) ):
            paths, error = parse_source_documents( raw )
            self.assertEqual( paths, [ ], f"raw={raw!r}" )
            self.assertIsNone( error, f"raw={raw!r}" )

    def test_a_bare_string_becomes_a_one_element_list( self ):
        """A caller naming one document should not have to know the argument is plural."""
        paths, error = parse_source_documents( "  docs/notes.md  " )
        self.assertIsNone( error )
        self.assertEqual( paths, [ "docs/notes.md" ] )

    def test_a_list_keeps_the_callers_order( self ):
        """Order is meaningful — it is the order the documents reach the prompt."""
        paths, error = parse_source_documents( [ "io/b.md", "io/a.md" ] )
        self.assertIsNone( error )
        self.assertEqual( paths, [ "io/b.md", "io/a.md" ] )

    def test_a_wrong_TYPE_is_refused_by_name( self ):
        """A dict is a caller mistake, and the message says which type arrived."""
        paths, error = parse_source_documents( { "path": "io/a.md" } )
        self.assertEqual( paths, [ ] )
        self.assertIn( "dict", error )
        self.assertIn( SOURCE_DOCUMENT_ARG, error )

    def test_a_non_string_ELEMENT_is_refused_with_its_index( self ):
        """Naming the index is what makes a ten-element list debuggable."""
        paths, error = parse_source_documents( [ "io/a.md", 7 ] )
        self.assertEqual( paths, [ ] )
        self.assertIn( "entry 1", error )
        self.assertIn( "int", error )

    def test_a_blank_ELEMENT_is_refused_rather_than_silently_dropped( self ):
        """Dropping it would run the research on fewer documents than the caller named."""
        paths, error = parse_source_documents( [ "io/a.md", "   " ] )
        self.assertEqual( paths, [ ] )
        self.assertIn( "entry 1", error )
        self.assertIn( "blank", error )

    def test_more_than_the_list_cap_is_refused( self ):
        """A bound on the LIST, which is not the size ceiling Rick declined."""
        paths, error = parse_source_documents( [ f"io/{n}.md" for n in range( MAX_SOURCE_DOCUMENTS + 1 ) ] )
        self.assertEqual( paths, [ ] )
        self.assertIn( str( MAX_SOURCE_DOCUMENTS ), error )


class TestSplitScope( unittest.TestCase ):
    """The `<scope>/<rel>` form is the doc-viewer's, so a pasted link works."""

    def test_a_scoped_path_splits_into_its_two_halves( self ):
        scope, relative, error = split_scope( "planning-is-prompting/src/rnd/a.md" )
        self.assertIsNone( error )
        self.assertEqual( scope, "planning-is-prompting" )
        self.assertEqual( relative, "src/rnd/a.md" )

    def test_a_leading_slash_is_tolerated( self ):
        """Pasted paths carry one; refusing it would punish a copy-paste."""
        scope, relative, error = split_scope( "/io/deep-research/a.md" )
        self.assertIsNone( error )
        self.assertEqual( scope, "io" )
        self.assertEqual( relative, "deep-research/a.md" )

    def test_an_unscoped_reference_is_REFUSED_rather_than_guessed( self ):
        """Guessing a scope is how a path argument becomes a filesystem argument."""
        for path in ( "notes.md", "/notes.md", "io/", "/io/   " ):
            scope, relative, error = split_scope( path )
            self.assertIsNotNone( error, f"path={path!r}" )
            self.assertIn( "<scope>", error )


class TestResolveWithinRoot( unittest.TestCase ):
    """Real directories, real symlinks — the whole point of this module."""

    def setUp( self ):
        self.tmp  = tempfile.mkdtemp()
        self.root = os.path.join( self.tmp, "scope-root" )
        os.makedirs( os.path.join( self.root, "sub" ) )
        with open( os.path.join( self.root, "sub", "ok.md" ), "w" ) as handle:
            handle.write( "# in scope\n" )
        self.outside = os.path.join( self.tmp, "outside" )
        os.makedirs( self.outside )
        with open( os.path.join( self.outside, "secret.md" ), "w" ) as handle:
            handle.write( "# out of scope\n" )

    def tearDown( self ):
        shutil.rmtree( self.tmp, ignore_errors=True )

    def test_an_ordinary_relative_path_resolves_under_the_root( self ):
        absolute, error = resolve_within_root( self.root, "sub/ok.md" )
        self.assertIsNone( error )
        self.assertEqual( absolute, os.path.realpath( os.path.join( self.root, "sub", "ok.md" ) ) )

    def test_a_dotdot_TRAVERSAL_is_REFUSED( self ):
        absolute, error = resolve_within_root( self.root, "../outside/secret.md" )
        self.assertIsNone( absolute )
        self.assertIn( "outside its scope", error )

    def test_a_SYMLINK_pointing_out_of_the_root_is_REFUSED( self ):
        """THE test this module exists for.

        A normpath check passes this: the path the caller typed never leaves the root.
        Only resolving the link and re-testing containment catches it.
        """
        os.symlink( self.outside, os.path.join( self.root, "escape" ) )
        absolute, error = resolve_within_root( self.root, "escape/secret.md" )
        self.assertIsNone( absolute, "a symlink walked out of the scope root" )
        self.assertIn( "outside its scope", error )

    def test_the_refusal_does_NOT_leak_where_the_symlink_actually_LANDED( self ):
        """The caller cannot browse outside the scope, so the message must not describe it."""
        os.symlink( self.outside, os.path.join( self.root, "escape" ) )
        _, error = resolve_within_root( self.root, "escape/secret.md" )
        self.assertNotIn( self.outside, error )

    def test_a_symlink_that_stays_INSIDE_the_root_is_ALLOWED( self ):
        """Symlinks are not the enemy; leaving the root is. Without this the fix would
        read as "refuse all links", which is a different and wrong rule."""
        os.symlink( os.path.join( self.root, "sub" ), os.path.join( self.root, "alias" ) )
        absolute, error = resolve_within_root( self.root, "alias/ok.md" )
        self.assertIsNone( error )
        self.assertTrue( absolute.startswith( os.path.realpath( self.root ) + os.sep ) )


class TestValidateSourceDocuments( unittest.TestCase ):
    """The whole refusal surface, against a real tree."""

    def setUp( self ):
        self.tmp     = tempfile.mkdtemp()
        self.io_root = os.path.join( self.tmp, "io" )
        os.makedirs( os.path.join( self.io_root, "deep-research" ) )
        self.doc = os.path.join( self.io_root, "deep-research", "notes.md" )
        with open( self.doc, "w" ) as handle:
            handle.write( "# seed context\n" )
        self.image = os.path.join( self.io_root, "deep-research", "chart.png" )
        with open( self.image, "wb" ) as handle:
            handle.write( b"\x89PNG\r\n" )
        self.second = os.path.join( self.io_root, "deep-research", "second.txt" )
        with open( self.second, "w" ) as handle:
            handle.write( "more\n" )
        self.scopes = { "io": _Scope( "io", self.io_root ) }

    def tearDown( self ):
        shutil.rmtree( self.tmp, ignore_errors=True )

    # ------------------------------------------------------------ the positive control
    def test_a_real_in_scope_document_is_ACCEPTED( self ):
        """🔴 THE POSITIVE CONTROL. Every refusal test in this class passes against a
        validator that refuses everything; only this one fails against it."""
        paths, error = validate_source_documents( "io/deep-research/notes.md", self.scopes )
        self.assertIsNone( error )
        self.assertEqual( paths, [ os.path.realpath( self.doc ) ] )

    def test_a_LIST_of_real_documents_is_ACCEPTED_in_order( self ):
        """Rick ruled a list on day one so the shape never has to change later."""
        paths, error = validate_source_documents(
            [ "io/deep-research/second.txt", "io/deep-research/notes.md" ], self.scopes
        )
        self.assertIsNone( error )
        self.assertEqual( paths, [ os.path.realpath( self.second ), os.path.realpath( self.doc ) ] )

    def test_an_absent_argument_is_ACCEPTED_as_nothing( self ):
        """Optional means optional — an absent document is not a refusal."""
        paths, error = validate_source_documents( None, self.scopes )
        self.assertIsNone( error )
        self.assertEqual( paths, [ ] )

    # ------------------------------------------------------------------- the refusals
    def test_an_UNKNOWN_SCOPE_is_refused_and_names_what_is_available( self ):
        paths, error = validate_source_documents( "nowhere/a.md", self.scopes )
        self.assertEqual( paths, [ ] )
        self.assertIn( "nowhere", error )
        self.assertIn( "io", error )

    def test_a_MISSING_file_is_refused( self ):
        paths, error = validate_source_documents( "io/deep-research/absent.md", self.scopes )
        self.assertEqual( paths, [ ] )
        self.assertIn( "does not exist", error )

    def test_a_DIRECTORY_is_refused_with_an_instruction( self ):
        paths, error = validate_source_documents( "io/deep-research", self.scopes )
        self.assertEqual( paths, [ ] )
        self.assertIn( "directory", error )

    def test_an_UNREADABLE_EXTENSION_is_refused( self ):
        """An image cannot be seed context for a text prompt; accepting it would mean
        the agent silently reads nothing useful."""
        paths, error = validate_source_documents( "io/deep-research/chart.png", self.scopes )
        self.assertEqual( paths, [ ] )
        self.assertIn( ".png", error )

    def test_a_SYMLINK_escape_is_refused_END_TO_END( self ):
        """The unit above proves the helper; this proves the rule actually calls it."""
        outside = os.path.join( self.tmp, "outside" )
        os.makedirs( outside )
        with open( os.path.join( outside, "secret.md" ), "w" ) as handle:
            handle.write( "# secrets\n" )
        os.symlink( outside, os.path.join( self.io_root, "escape" ) )

        paths, error = validate_source_documents( "io/escape/secret.md", self.scopes )
        self.assertEqual( paths, [ ] )
        self.assertIn( "outside its scope", error )

    def test_the_FIRST_failure_returns_and_nothing_partial_comes_back( self ):
        """A half-validated list reaching the agent is the silent-degradation shape:
        the research would run on fewer documents than the caller named."""
        paths, error = validate_source_documents(
            [ "io/deep-research/notes.md", "io/deep-research/absent.md" ], self.scopes
        )
        self.assertEqual( paths, [ ], "a partial list survived a refusal" )
        self.assertIn( "absent.md", error )

    def test_NO_SIZE_CEILING_is_applied( self ):
        """Rick's ruling of 2026-09-08, recorded as a test so a later 'tidy-up' that adds
        a limit fails loudly instead of quietly re-deciding it."""
        big = os.path.join( self.io_root, "deep-research", "big.md" )
        with open( big, "w" ) as handle:
            handle.write( "x" * ( 4 * 1024 * 1024 ) )
        paths, error = validate_source_documents( "io/deep-research/big.md", self.scopes )
        self.assertIsNone( error, "a size limit was applied; Rick ruled there is none" )
        self.assertEqual( paths, [ os.path.realpath( big ) ] )


if __name__ == "__main__":
    unittest.main()


class TestTheBrowseGuardsAreActuallyApplied( unittest.TestCase ):
    """🔴 KRISHNA'S SECOND FINDING. The module claimed the read set and the browse set
    could not drift apart, and shared only the scope ROOT.

    Root containment says the file is in the right TREE. The secrets blocklist and the
    prefix whitelist say it is a file a human is allowed to SEE inside that tree. Without
    the latter two this door was strictly MORE PERMISSIVE than /api/docs/file on the very
    same scope — and `.json` is in this module's own extension list, so a
    `.claude/settings.local.json` sailed through.

    A docstring promising a guarantee the code does not implement is worse than no
    docstring: a reader audits the sentence and stops looking.
    """

    def setUp( self ):
        self.tmp  = tempfile.mkdtemp()
        self.root = os.path.join( self.tmp, "repo" )
        os.makedirs( os.path.join( self.root, "src", "rnd" ) )
        os.makedirs( os.path.join( self.root, ".claude" ) )
        os.makedirs( os.path.join( self.root, "private" ) )

        self.ok = os.path.join( self.root, "src", "rnd", "notes.md" )
        with open( self.ok, "w" ) as handle: handle.write( "# fine\n" )

        self.secret = os.path.join( self.root, ".claude", "settings.local.json" )
        with open( self.secret, "w" ) as handle: handle.write( '{"token":"x"}\n' )

        self.offlimits = os.path.join( self.root, "private", "plan.md" )
        with open( self.offlimits, "w" ) as handle: handle.write( "# not browsable\n" )

        self.scopes = { "repo": _Scope( "repo", self.root, allowed_prefixes=( "src/", ) ) }

    def tearDown( self ):
        shutil.rmtree( self.tmp, ignore_errors=True )

    def test_a_CREDENTIAL_BEARING_path_inside_an_allowed_root_is_REFUSED( self ):
        """It is in the right tree, has an allowed extension, and must still be refused."""
        paths, error = validate_source_documents( "repo/.claude/settings.local.json", self.scopes )
        self.assertEqual( paths, [ ], "a credential path was returned to the research agent" )
        self.assertIn( "credential", error )

    def test_a_path_OUTSIDE_the_scopes_allowed_prefixes_is_REFUSED( self ):
        """`private/` is inside the root and outside what the viewer will serve."""
        paths, error = validate_source_documents( "repo/private/plan.md", self.scopes )
        self.assertEqual( paths, [ ] )
        self.assertIn( "outside the readable prefixes", error )

    def test_a_path_INSIDE_the_allowed_prefixes_is_STILL_ACCEPTED( self ):
        """🔴 POSITIVE CONTROL. Both refusals above pass against a door that refuses
        everything; only this one fails against it."""
        paths, error = validate_source_documents( "repo/src/rnd/notes.md", self.scopes )
        self.assertIsNone( error )
        self.assertEqual( paths, [ os.path.realpath( self.ok ) ] )
