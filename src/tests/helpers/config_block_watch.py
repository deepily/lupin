"""
Watch the config block variable while pytest imports test files.

A test file that sets LUPIN_CONFIG_MGR_CLI_ARGS at import time keeps that value for the whole run.
Pytest imports every file before the first test runs. The module fixture that restores the variable
snapshots it after the damage, so it restores the damaged value. This watch names the first file that
changed the variable, and the root conftest turns that into a refusal for a unit-tier run.
"""

import os


class ConfigBlockWatch:
    """Remembers the variable's value at each step of collection and who changed it."""

    def __init__( self, floor ):
        """
        Start watching.

        Requires:
            - floor is the value the variable held before any test file was imported, or None
        """
        self.floor     = floor
        self.last      = floor
        self.offenders = [ ]

    def note( self, nodeid, now ):
        """
        Record one collection step.

        Ensures:
            - appends nodeid to offenders when now differs from the previous step's value
            - the next step compares against now, so one change names one file
        """
        if now != self.last: self.offenders.append( nodeid )
        self.last = now

    def verdict( self, item_paths, unit_dir ):
        """
        The refusal text for a unit-tier run whose collection changed the variable, else None.

        Requires:
            - item_paths are the collected tests' file paths; unit_dir is the unit folder with a trailing separator

        Ensures:
            - returns None when no file changed the variable
            - returns None when any collected test lies outside unit_dir, because the integration and browser
              suites set the variable themselves
            - otherwise returns text that names every offending file and the value it left behind
        """
        if not self.offenders or not item_paths: return None
        if not all( str( path ).startswith( unit_dir ) for path in item_paths ): return None
        names = ", ".join( self.offenders )
        return ( f"Collecting the unit tier changed LUPIN_CONFIG_MGR_CLI_ARGS: it was {self.floor!r} and is now {self.last!r}. "
                 f"First changed while importing: {names}. Restore the variable inside that file; the run would read the wrong config block." )


def unit_dir_of( tests_dir ):
    """The unit folder under the tests folder, with a trailing separator."""
    return os.path.join( tests_dir, "unit" ) + os.sep
