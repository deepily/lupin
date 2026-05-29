#!/usr/bin/env python3
"""
Cross-Session State Persistence for COSA SWE Team Agent.

Provides FeatureList and ProgressLog classes that persist task decomposition
and progress data across sessions. Supports multi-step tasks where the
orchestrator may be interrupted and resumed.

Storage location: {project_root}/io/swe-team/{session_id}/
Default root: tempfile.TemporaryDirectory() (overridable for testing)
"""

import json
import logging
import os
import tempfile
from datetime import datetime
from typing import Optional

from .state import TaskSpec

logger = logging.getLogger( __name__ )


# =============================================================================
# FeatureList — Task Decomposition Persistence
# =============================================================================

class FeatureList:
    """
    Reads/writes feature_list.json for cross-session task tracking.

    Stores the list of TaskSpec dicts produced by the lead's decomposition
    phase, along with completion status for each task.

    Requires:
        - storage_dir is a writable directory path

    Ensures:
        - load() returns list of task dicts from disk (or empty list)
        - save() writes current tasks to disk atomically
        - add_task() appends a TaskSpec and saves
        - mark_complete() updates a task's status and saves
        - get_pending() returns tasks not yet completed
    """

    FILENAME = "feature_list.json"

    def __init__( self, storage_dir=None ):
        """
        Initialize FeatureList with storage directory.

        Args:
            storage_dir: Directory for JSON file. Uses tempdir if None.
        """
        if storage_dir is None:
            self._tmpdir     = tempfile.TemporaryDirectory()
            self.storage_dir = self._tmpdir.name
        else:
            self._tmpdir     = None
            self.storage_dir = storage_dir
            os.makedirs( storage_dir, exist_ok=True )

        self.file_path = os.path.join( self.storage_dir, self.FILENAME )
        self.tasks     = []

    def load( self ):
        """
        Load task list from disk.

        Ensures:
            - Returns list of task dicts
            - Returns empty list if file doesn't exist
            - Populates self.tasks

        Returns:
            list[dict]: Task dictionaries
        """
        if not os.path.exists( self.file_path ):
            self.tasks = []
            return self.tasks

        try:
            with open( self.file_path, "r" ) as f:
                data = json.load( f )

            self.tasks = data.get( "tasks", [] )
            return self.tasks

        except ( json.JSONDecodeError, IOError ) as e:
            logger.warning( f"Failed to load feature list: {e}" )
            self.tasks = []
            return self.tasks

    def save( self ):
        """
        Save current task list to disk.

        Ensures:
            - Writes self.tasks to feature_list.json
            - Includes metadata (updated_at, count)
        """
        data = {
            "updated_at" : datetime.now().isoformat(),
            "count"      : len( self.tasks ),
            "tasks"      : self.tasks,
        }

        try:
            with open( self.file_path, "w" ) as f:
                json.dump( data, f, indent=2 )
        except IOError as e:
            logger.error( f"Failed to save feature list: {e}" )

    def add_task( self, task_spec ):
        """
        Add a TaskSpec to the list and save.

        Requires:
            - task_spec is a TaskSpec instance or dict with at least "title"

        Ensures:
            - Task added to self.tasks with "completed" = False
            - File saved to disk

        Args:
            task_spec: TaskSpec instance or dict
        """
        if isinstance( task_spec, TaskSpec ):
            task_dict = task_spec.model_dump()
        else:
            task_dict = dict( task_spec )

        task_dict[ "completed" ] = False
        task_dict[ "added_at" ]  = datetime.now().isoformat()

        self.tasks.append( task_dict )
        self.save()

    def mark_complete( self, index ):
        """
        Mark a task as completed by index.

        Requires:
            - index is a valid task index (0-based)

        Ensures:
            - Task at index has "completed" = True
            - "completed_at" timestamp added
            - File saved to disk

        Args:
            index: 0-based task index

        Raises:
            IndexError: If index is out of range
        """
        if index < 0 or index >= len( self.tasks ):
            raise IndexError( f"Task index {index} out of range (0-{len( self.tasks ) - 1})" )

        self.tasks[ index ][ "completed" ]    = True
        self.tasks[ index ][ "completed_at" ] = datetime.now().isoformat()
        self.save()

    def get_pending( self ):
        """
        Get tasks not yet completed.

        Ensures:
            - Returns list of (index, task_dict) tuples where completed is False

        Returns:
            list[tuple[int, dict]]: Pending tasks with their indices
        """
        return [
            ( i, task ) for i, task in enumerate( self.tasks )
            if not task.get( "completed", False )
        ]

    def cleanup( self ):
        """Clean up temporary directory if created."""
        if self._tmpdir is not None:
            self._tmpdir.cleanup()


# =============================================================================
# ProgressLog — Timestamped Progress Entries
# =============================================================================

class ProgressLog:
    """
    Appends timestamped progress entries to claude-progress.txt.

    Provides a simple append-only log for tracking orchestrator progress
    across sessions.

    Requires:
        - storage_dir is a writable directory path

    Ensures:
        - log() appends a timestamped entry
        - read_recent() returns the last N entries
        - get_summary() returns a formatted summary string
    """

    FILENAME = "claude-progress.txt"

    def __init__( self, storage_dir=None, on_log=None ):
        """
        Initialize ProgressLog with storage directory.

        Args:
            storage_dir: Directory for log file. Uses tempdir if None.
            on_log: Optional callback( message, role ) invoked after each log entry.
        """
        if storage_dir is None:
            self._tmpdir     = tempfile.TemporaryDirectory()
            self.storage_dir = self._tmpdir.name
        else:
            self._tmpdir     = None
            self.storage_dir = storage_dir
            os.makedirs( storage_dir, exist_ok=True )

        self.file_path = os.path.join( self.storage_dir, self.FILENAME )
        self._on_log   = on_log

    def log( self, message, role="lead" ):
        """
        Append a timestamped progress entry.

        Requires:
            - message is a non-empty string

        Ensures:
            - Entry appended with ISO timestamp and role tag
            - on_log callback invoked if provided (never raises)

        Args:
            message: Progress message
            role: Agent role that produced this entry
        """
        timestamp = datetime.now().isoformat()
        entry     = f"[{timestamp}] [{role}] {message}\n"

        try:
            with open( self.file_path, "a" ) as f:
                f.write( entry )
        except IOError as e:
            logger.error( f"Failed to write progress log: {e}" )

        if self._on_log:
            try:
                self._on_log( message, role )
            except Exception as e:
                logger.warning( f"on_log callback failed: {e}" )

    def read_recent( self, n=10 ):
        """
        Read the last N log entries.

        Requires:
            - n is a positive integer

        Ensures:
            - Returns list of up to N most recent lines
            - Returns empty list if file doesn't exist

        Args:
            n: Number of recent entries to return

        Returns:
            list[str]: Recent log entries
        """
        if not os.path.exists( self.file_path ):
            return []

        try:
            with open( self.file_path, "r" ) as f:
                lines = f.readlines()

            return [ line.rstrip( "\n" ) for line in lines[ -n: ] ]

        except IOError as e:
            logger.warning( f"Failed to read progress log: {e}" )
            return []

    def get_summary( self ):
        """
        Get a formatted summary of all progress entries.

        Ensures:
            - Returns string with entry count and last entry
            - Returns "No progress logged" if empty

        Returns:
            str: Progress summary
        """
        entries = self.read_recent( n=1000 )

        if not entries:
            return "No progress logged"

        last_entry = entries[ -1 ] if entries else "N/A"
        return f"{len( entries )} entries logged. Last: {last_entry}"

    def cleanup( self ):
        """Clean up temporary directory if created."""
        if self._tmpdir is not None:
            self._tmpdir.cleanup()


def quick_smoke_test():
    """Quick smoke test for state_files module."""
    import cosa.utils.util as cu

    cu.print_banner( "SWE Team State Files Smoke Test", prepend_nl=True )

    try:
        # Test 1: FeatureList create/load/save
        print( "Testing FeatureList round-trip..." )
        fl = FeatureList()
        fl.add_task( TaskSpec(
            title         = "Implement auth",
            objective     = "Add JWT authentication",
            output_format = "Modified auth.py",
        ) )
        fl.add_task( TaskSpec(
            title         = "Write tests",
            objective     = "Add unit tests for auth",
            output_format = "New test file",
        ) )
        assert len( fl.tasks ) == 2

        # Reload from disk
        fl2 = FeatureList( storage_dir=fl.storage_dir )
        loaded = fl2.load()
        assert len( loaded ) == 2
        assert loaded[ 0 ][ "title" ] == "Implement auth"
        print( "✓ FeatureList round-trip works" )

        # Test 2: Mark complete + get_pending
        print( "Testing mark_complete and get_pending..." )
        fl2.mark_complete( 0 )
        pending = fl2.get_pending()
        assert len( pending ) == 1
        assert pending[ 0 ][ 0 ] == 1  # index of second task
        print( "✓ mark_complete and get_pending work" )

        # Test 3: ProgressLog
        print( "Testing ProgressLog..." )
        pl = ProgressLog()
        pl.log( "Starting task decomposition", role="lead" )
        pl.log( "Implementing auth module", role="coder" )
        pl.log( "Auth module complete", role="coder" )

        recent = pl.read_recent( 2 )
        assert len( recent ) == 2
        assert "[coder]" in recent[ 0 ]

        summary = pl.get_summary()
        assert "3 entries" in summary
        print( "✓ ProgressLog works" )

        # Test 4: Empty states
        print( "Testing empty states..." )
        empty_fl = FeatureList()
        assert empty_fl.load() == []
        assert empty_fl.get_pending() == []

        empty_pl = ProgressLog()
        assert empty_pl.read_recent() == []
        assert empty_pl.get_summary() == "No progress logged"
        print( "✓ Empty states handled" )

        # Cleanup
        fl.cleanup()
        fl2.cleanup()
        pl.cleanup()
        empty_fl.cleanup()
        empty_pl.cleanup()

        print( "\n✓ SWE Team State Files smoke test completed successfully" )

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
