"""
The test port of the run harness: run the frozen acceptance tests against a run's server.

Each test gets a verdict.

The tests run from the run's worktree, so a run that edits them or the server would be graded by its own changes.
Before every test run the whole tree is compared with the frozen commit.
Any change outside the client folder refuses the run, so no file pytest reads can be edited.
The verdict of a test is read from the junit file pytest writes, one entry per test id, and a skip is not a pass.
"""
import os
import xml.etree.ElementTree as ET

from cosa.repo.doc_lint import pool_builder
from lupin_mcp.reuse_harness import commands
from lupin_mcp.reuse_harness import errors as err
from lupin_mcp.reuse_harness.freeze import TEST_DIR
from lupin_mcp.reuse_harness.worktree import CLIENT_ROOT

# A run may change the client folder and nothing else (plan 3, section 7.2, ground rule 2). The rule is the whole tree, not a list of files.
BUILD_COMMAND = ( "npm", "--prefix", CLIENT_ROOT, "run", "build" )
TEST_TIMEOUT  = 3600
BUILD_TIMEOUT = 600
TAIL          = 20


class Acceptance:
    """Runs the acceptance tests of one run."""

    def __init__( self, commit, notify_api_key, report_dir, runner=commands.run_command, build_command=BUILD_COMMAND, python=None, environ=None, removed=() ):
        """
        Remember what a test run needs.

        Requires:
            - commit is the full frozen sha the run's worktree was cut from
            - notify_api_key is the key the run's server accepts from the sender side of the tests
            - report_dir exists and is outside the worktree
            - removed are the paths the arm's worktree was cut without; deleting them is not tampering
            - runner( argv, env=, cwd=, timeout= ) returns ( exit code, output )

        Ensures:
            - nothing is run yet; python defaults to the worktree's own interpreter
        """
        self.commit         = commit
        self.notify_api_key = notify_api_key
        self.report_dir     = report_dir
        self.runner         = runner
        self.build_command  = list( build_command )
        self.removed        = tuple( removed )
        self.python         = python
        self.environ        = os.environ if environ is None else environ
        self.calls          = 0

    def run( self, handle, path, test_ids ):
        """
        Run the acceptance tests against the run's server, then try the client's build.

        Requires:
            - handle is the server handle of the run and path its worktree
            - test_ids are the frozen test ids, "<file>::<function>"

        Ensures:
            - returns { results : { test id : bool }, client_builds : bool }, results keyed by test_ids alone
            - a test passes only when every one of its cases passed; a skip, an error, a missing case or an unreadable file is a fail
            - the junit file of each call is kept in report_dir

        Raises:
            - HarnessError TESTS_TAMPERED naming the frozen paths that differ from the frozen commit
            - HarnessError TESTS_NOT_RUN if pytest did not finish or wrote no readable report
        """
        self._check_untouched( path )
        self.calls += 1
        report      = os.path.join( self.report_dir, f"junit-{self.calls}.xml" )
        env         = dict( self.environ )
        env.update( { "EXPERIMENT_SERVER_URL" : handle[ "url" ], "EXPERIMENT_NOTIFY_API_KEY" : self.notify_api_key } )
        python      = self.python or os.path.join( path, ".venv", "bin", "python" )
        code, output = self.runner( [ python, "-m", "pytest", TEST_DIR, f"--junitxml={report}", "-q", "-p", "no:cacheprovider" ], env=env, cwd=path, timeout=TEST_TIMEOUT )
        if code not in ( 0, 1 ) or not os.path.exists( report ): raise err.HarnessError( err.TESTS_NOT_RUN, f"pytest answered {code}: {self._tail( output )}" )
        results      = self._read( report, test_ids )
        built, _     = self.runner( self.build_command, env=env, cwd=path, timeout=BUILD_TIMEOUT )
        return { "results" : results, "client_builds" : built == 0 }

    def _check_untouched( self, path ):
        """Refuse a tree that differs from the frozen commit outside the client folder."""
        hidden  = [ line[ 2: ] for line in pool_builder.run_git( path, [ "ls-files", "-v" ] ).decode( "utf-8" ).splitlines() if line[ 0 ] != "H" ]
        changes = [ line.split( "\t", 1 ) for line in pool_builder.run_git( path, [ "diff", "--name-status", "--no-renames", self.commit ] ).decode( "utf-8" ).splitlines() ]
        added   = pool_builder.run_git( path, [ "ls-files", "--others", "--exclude-standard" ] ).decode( "utf-8" ).splitlines()
        changed = [ name for status, name in changes if not self._allowed( status, name ) ]
        added   = [ name for name in added if not self._in_client( name ) ]
        if hidden: raise err.HarnessError( err.TESTS_TAMPERED, f"files hidden from git by an assume-unchanged or skip-worktree flag: {sorted( hidden )[ :TAIL ]}" )
        if changed or added: raise err.HarnessError( err.TESTS_TAMPERED, f"paths outside {CLIENT_ROOT} differ from {self.commit}: {sorted( changed + added )[ :TAIL ]}" )

    def _in_client( self, name ):
        """Say whether a path is in the client folder."""
        return name.startswith( CLIENT_ROOT + "/" )

    def _allowed( self, status, name ):
        """Say whether a change is the client folder's, or the deletion of a path the arm removed."""
        return self._in_client( name ) or ( status == "D" and any( name == gone or name.startswith( gone + "/" ) for gone in self.removed ) )

    def _read( self, report, test_ids ):
        """Read a junit report into one verdict per test id."""
        try:
            cases = ET.parse( report ).getroot().iter( "testcase" )
        except ET.ParseError as error:
            raise err.HarnessError( err.TESTS_NOT_RUN, f"the report is not readable: {error}" ) from error
        passed = {}
        for case in cases:
            test_id = case.get( "classname", "" ).replace( ".", "/" ) + ".py::" + case.get( "name" ).split( "[" )[ 0 ]
            clean   = not any( child.tag in ( "failure", "error", "skipped" ) for child in case )
            passed[ test_id ] = passed.get( test_id, True ) and clean
        return { test_id : passed.get( test_id, False ) for test_id in test_ids }

    def _tail( self, output ):
        """Return the last lines of a command's output."""
        return " | ".join( output.splitlines()[ -TAIL: ] )
