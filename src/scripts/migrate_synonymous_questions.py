#!/usr/bin/env python3
"""
Migration script to extract synonymous questions from SolutionSnapshots
and populate the new CanonicalSynonyms table for the Three-Level Architecture.

This script:
1. Reads all SolutionSnapshots from LanceDB
2. Extracts synonymous_questions and synonymous_question_gists
3. Populates the new CanonicalSynonyms table
4. Handles duplicates and conflicts
5. Reports migration statistics
"""

import os
import sys
import json
from collections import OrderedDict
from typing import Dict, List, Tuple, Any, Optional

# Add src directory to path
sys.path.insert( 0, os.path.join( os.path.dirname( __file__ ), '..', '..' ) )
sys.path.insert( 0, os.path.join( os.path.dirname( __file__ ), '..' ) )

# Set up configuration
os.environ['LUPIN_CONFIG_MGR_CLI_ARGS'] = "config_path=/src/conf/lupin-app.ini splainer_path=/src/conf/lupin-app-splainer.ini config_block_id=Lupin:+Development"

import lancedb
import cosa.utils.util as du
from cosa.config.configuration_manager import ConfigurationManager
from cosa.memory.canonical_synonyms_table import CanonicalSynonymsTable
from cosa.utils.util_stopwatch import Stopwatch


class SynonymousMigration:
    """
    Migrates synonymous questions from SolutionSnapshots to CanonicalSynonyms table.
    """

    def __init__( self, debug: bool = True, verbose: bool = True, dry_run: bool = False ):
        """
        Initialize migration tool.

        Args:
            debug: Enable debug output
            verbose: Enable verbose output
            dry_run: If True, don't actually write to database
        """
        self.debug = debug
        self.verbose = verbose
        self.dry_run = dry_run

        # Initialize configuration
        self._config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )

        # Initialize target table
        if not dry_run:
            self.synonyms_table = CanonicalSynonymsTable( debug=debug, verbose=verbose )
        else:
            self.synonyms_table = None

        # Statistics
        self.stats = {
            'snapshots_processed': 0,
            'synonyms_found': 0,
            'synonyms_added': 0,
            'duplicates_skipped': 0,
            'errors': 0
        }

        # Track conflicts
        self.conflicts = []

    def connect_to_snapshots( self ) -> Any:
        """
        Connect to the solution_snapshots table in LanceDB.

        Returns:
            LanceDB table object
        """
        uri = du.get_project_root() + self._config_mgr.get( "database_path_wo_root" )

        if self.debug:
            print( f"Connecting to LanceDB at: {uri}" )

        db = lancedb.connect( uri )

        # Open solution_snapshots table
        if "solution_snapshots" not in db.table_names():
            raise ValueError( "solution_snapshots table not found!" )

        table = db.open_table( "solution_snapshots" )

        if self.verbose:
            print( f"Opened solution_snapshots table with {table.count_rows()} rows" )

        return table

    def parse_synonymous_questions( self, json_str: str ) -> Dict[str, float]:
        """
        Parse JSON-serialized synonymous questions.

        Args:
            json_str: JSON string representing OrderedDict of questions

        Returns:
            Dict mapping question to confidence score
        """
        if not json_str or json_str == "null" or json_str == "{}":
            return {}

        try:
            # Try to parse as JSON
            data = json.loads( json_str )

            # Handle OrderedDict format
            if isinstance( data, list ) and len( data ) > 0:
                # Sometimes stored as list of [key, value] pairs
                return OrderedDict( data )
            elif isinstance( data, dict ):
                return data
            else:
                if self.debug:
                    print( f"Unexpected format for synonymous questions: {type( data )}" )
                return {}

        except json.JSONDecodeError as e:
            if self.debug:
                print( f"Failed to parse synonymous questions: {e}" )
            return {}
        except Exception as e:
            if self.debug:
                print( f"Unexpected error parsing synonymous questions: {e}" )
            return {}

    def migrate_snapshot( self, snapshot: Dict[str, Any] ) -> int:
        """
        Migrate synonyms from a single snapshot.

        Args:
            snapshot: Snapshot data from LanceDB

        Returns:
            Number of synonyms successfully migrated
        """
        migrated = 0
        snapshot_id = snapshot.get( 'id_hash', '' )

        if not snapshot_id:
            if self.debug:
                print( "Skipping snapshot without id_hash" )
            return 0

        # Parse synonymous questions
        synonymous_json = snapshot.get( 'synonymous_questions', '' )
        synonyms = self.parse_synonymous_questions( synonymous_json )

        if self.debug and synonyms:
            print( f"\nSnapshot {snapshot_id[:8]}... has {len( synonyms )} synonyms" )

        # Process each synonym
        for question, confidence in synonyms.items():
            if not question or not question.strip():
                continue

            self.stats['synonyms_found'] += 1

            # Skip if dry run
            if self.dry_run:
                if self.verbose:
                    print( f"  [DRY RUN] Would add: '{du.truncate_string( question, 50 )}'" )
                migrated += 1
                continue

            # Try to add synonym
            try:
                success = self.synonyms_table.add_synonym(
                    snapshot_id=snapshot_id,
                    question_verbatim=question,
                    confidence_score=float( confidence ),
                    source="migration"
                )

                if success:
                    self.stats['synonyms_added'] += 1
                    migrated += 1
                    if self.verbose:
                        print( f"  ✓ Added: '{du.truncate_string( question, 50 )}'" )
                else:
                    self.stats['duplicates_skipped'] += 1
                    if self.debug:
                        print( f"  ○ Duplicate: '{du.truncate_string( question, 50 )}'" )

            except Exception as e:
                self.stats['errors'] += 1
                if self.debug:
                    print( f"  ✗ Error adding '{du.truncate_string( question, 50 )}': {e}" )

        return migrated

    def run_migration( self, limit: Optional[int] = None ) -> None:
        """
        Run the full migration process.

        Args:
            limit: Optional limit on number of snapshots to process
        """
        du.print_banner( "Starting Synonymous Questions Migration", prepend_nl=True )

        if self.dry_run:
            print( "🔍 DRY RUN MODE - No changes will be made" )

        # Start timer
        overall_timer = Stopwatch( msg="Migration process" )

        try:
            # Connect to source table
            snapshots_table = self.connect_to_snapshots()

            # Get all snapshots (or limited set)
            query = snapshots_table.search()
            if limit:
                query = query.limit( limit )

            snapshots = query.to_list()
            total_snapshots = len( snapshots )

            print( f"\nProcessing {total_snapshots} snapshots..." )
            print( "-" * 60 )

            # Process each snapshot
            for i, snapshot in enumerate( snapshots ):
                if i % 100 == 0 and i > 0:
                    print( f"Progress: {i}/{total_snapshots} snapshots processed..." )

                self.migrate_snapshot( snapshot )
                self.stats['snapshots_processed'] += 1

            # Final statistics
            overall_timer.print( "Migration complete!", use_millis=False )
            self.print_statistics()

        except Exception as e:
            print( f"\n✗ Migration failed: {e}" )
            du.print_stack_trace( e, explanation="Migration failed", caller="SynonymousMigration.run_migration()" )
            self.print_statistics()

    def print_statistics( self ) -> None:
        """Print migration statistics."""
        du.print_banner( "Migration Statistics" )

        print( f"Snapshots processed:  {self.stats['snapshots_processed']:,}" )
        print( f"Synonyms found:       {self.stats['synonyms_found']:,}" )
        print( f"Synonyms added:       {self.stats['synonyms_added']:,}" )
        print( f"Duplicates skipped:   {self.stats['duplicates_skipped']:,}" )
        print( f"Errors encountered:   {self.stats['errors']:,}" )

        success_rate = 0.0
        if self.stats['synonyms_found'] > 0:
            success_rate = ( self.stats['synonyms_added'] / self.stats['synonyms_found'] ) * 100

        print( f"\nSuccess rate: {success_rate:.1f}%" )

        if self.conflicts:
            print( f"\n⚠️  {len( self.conflicts )} conflicts detected (see log for details)" )


def main():
    """Main entry point for migration script."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Migrate synonymous questions to CanonicalSynonyms table"
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Limit number of snapshots to process (for testing)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run without making changes (preview mode)"
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Reduce output verbosity"
    )
    parser.add_argument(
        "--no-debug",
        action="store_true",
        help="Disable debug output"
    )

    args = parser.parse_args()

    # Configure verbosity
    debug = not args.no_debug
    verbose = not args.quiet

    # Create and run migration
    migration = SynonymousMigration(
        debug=debug,
        verbose=verbose,
        dry_run=args.dry_run
    )

    migration.run_migration( limit=args.limit )

    # Return exit code based on errors
    sys.exit( 0 if migration.stats['errors'] == 0 else 1 )


if __name__ == "__main__":
    main()