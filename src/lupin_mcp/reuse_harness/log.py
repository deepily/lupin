"""
The log port of the run harness: one JSON line per record.

The folder is named by the arm's blind label.

A record may name the arm only by its label.
A record carrying a key called arm is refused.
So a scorer that must not know the arm can read the log.
"""
import json
import os

from lupin_mcp.reuse_harness import errors as err

LOG_FILE = "log.jsonl"


class RunLog:
    """Appends the records of one run."""

    def __init__( self, run_dir ):
        """
        Remember the run's folder.

        Requires:
            - run_dir exists and is named by the arm's label, not by the arm

        Ensures:
            - nothing is written yet
        """
        self.path = os.path.join( run_dir, LOG_FILE )

    def write( self, record ):
        """
        Append one record as a line of JSON with sorted keys.

        Requires:
            - record is a dict of JSON values

        Ensures:
            - the line is on disk when the call returns

        Raises:
            - HarnessError BAD_SPEC if the record has a key called arm
        """
        if "arm" in record: raise err.HarnessError( err.BAD_SPEC, "a log record names the arm by arm_label only" )
        with open( self.path, "a", encoding="utf-8" ) as f: f.write( json.dumps( record, sort_keys=True ) + "\n" )
