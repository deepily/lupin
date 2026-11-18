#!/usr/bin/env python3
"""
The `local_data` test tier: checks that read Rick's real answers.

Rick's real questions and answers live under the main checkout's gitignored `io/`
folder and are never committed. A test that needs them carries the `local_data`
marker. In a worktree the folder is absent, so the test skips.
This module makes that skip loud instead of letting it read as a pass:

    - every skipped `local_data` test is printed by name, with its reason, in the
      terminal summary;
    - a run started with `--require-local-data` exits non-zero when any `local_data`
      test skipped, or when none ran at all.

The hooks are wired from `src/conftest.py`; the logic lives here so it can be unit
tested without importing a conftest.
"""

import os

import pytest

import cosa.utils.util as cu

MARKER_NAME         = "local_data"
LOCAL_DATA_REL_DIR  = "/io/write-ups/online-preference-learning"
MANIFEST_FILE_NAME  = "manifest-before.txt"
REQUIRE_OPTION      = "--require-local-data"
OVERRIDE_ENV_VAR    = "LUPIN_LOCAL_DATA_DIR"


def local_data_dir():
    """
    Absolute path of the local-only data folder, resolved from the project root.

    Requires:
        - LUPIN_ROOT names the tree the run is measuring

    Ensures:
        - returns LUPIN_LOCAL_DATA_DIR when it is set (the tests point it at an empty or
          a planted folder to drive both the skip and the run path)
        - otherwise returns the project root plus the relative data folder
        - never checks that the folder exists
    """
    override = os.environ.get( OVERRIDE_ENV_VAR )
    if override: return override
    return cu.get_project_root() + LOCAL_DATA_REL_DIR


def require_local_file( file_name ):
    """
    Return the absolute path of one local data file, or skip the calling test by name.

    Requires:
        - file_name is a file name inside the local data folder
        - the caller carries the `local_data` marker

    Ensures:
        - returns the path when the file exists
        - otherwise skips with a reason that names the missing path, so the terminal
          summary can print it

    Raises:
        - pytest.skip.Exception (a skip, not a failure) when the file is absent
    """
    path = local_data_dir() + "/" + file_name
    if not os.path.isfile( path ):
        pytest.skip( f"local data file absent: {path}" )
    return path


def skip_reason( report ):
    """
    The human-readable reason a skipped test report carries.

    Requires:
        - report is a skipped pytest report whose longrepr is a ( path, line, message ) tuple
          or a plain string

    Ensures:
        - returns the message with pytest's "Skipped: " prefix removed
    """
    longrepr = report.longrepr
    message  = longrepr[ 2 ] if isinstance( longrepr, tuple ) else str( longrepr )
    return message.removeprefix( "Skipped: " )


class LocalDataLedger:
    """
    Tallies what happened to the `local_data` tests in one run.

    Requires:
        - on_report is called once per test report, in run order

    Ensures:
        - counts every `local_data` test that reached its call phase or skipped
        - keeps one ( node id, reason ) pair per skipped test
    """

    def __init__( self ):
        self.skipped = []
        self.ran     = 0

    def on_report( self, report ):
        """
        Record one test report if it belongs to a `local_data` test.

        Requires:
            - report is a pytest TestReport

        Ensures:
            - a skipped `local_data` report adds one ( node id, reason ) pair
            - a `local_data` report from the call phase adds one to `ran`
            - any other report changes nothing
        """
        if MARKER_NAME not in report.keywords: return
        if report.skipped:
            self.skipped.append( ( report.nodeid, skip_reason( report ) ) )
        elif report.when == "call":
            self.ran += 1

    def summary_lines( self ):
        """
        The lines the terminal summary prints, zero case included.

        Ensures:
            - always returns at least one line, so a run that never touched the tier
              reads differently from a run that skipped it silently
            - one line per skipped test, naming the test and its reason
        """
        lines = [ f"[local_data] ran={self.ran} skipped={len( self.skipped )}" ]
        for node_id, reason in self.skipped:
            lines.append( f"[local_data] SKIPPED {node_id}: {reason}" )
        return lines

    def should_fail( self, required ):
        """
        Whether the run must exit non-zero because of this tier.

        Requires:
            - required is True when the run was started with --require-local-data

        Ensures:
            - False whenever the option is off
            - True when the option is on and any `local_data` test skipped
            - True when the option is on and no `local_data` test ran, because a
              required tier that never ran proved nothing
        """
        if not required: return False
        return bool( self.skipped ) or self.ran == 0


def add_require_option( parser ):
    """
    Register the --require-local-data command-line flag.

    Requires:
        - parser is the pytest Parser handed to pytest_addoption

    Ensures:
        - the flag is a boolean, off by default
    """
    parser.addoption( REQUIRE_OPTION, action="store_true", default=False,
                      help="Fail the run when any local_data test skipped (or none ran): "
                           "the real-data check in the main checkout." )
