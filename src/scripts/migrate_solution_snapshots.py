#!/usr/bin/env python3
"""
Solution Snapshot Migration Script

This script adds the default user_id to all existing solution snapshot files
to support the new user-context architecture.

Usage:
    python src/scripts/migrate_solution_snapshots.py [--dry-run] [--backup]

Options:
    --dry-run   : Show what would be changed without making changes
    --backup    : Create .bak files before modifying originals
"""

import os
import sys
import json
import argparse
import shutil
from pathlib import Path
from typing import Dict, List, Any

# Add the project root to Python path for imports
project_root = Path(__file__).parent.parent.parent
sys.path.append(str(project_root / "src"))

import cosa.utils.util as du


class SolutionSnapshotMigrator:
    """Migrates solution snapshot files to include user_id."""
    
    DEFAULT_USER_ID = "ricardo_felipe_ruiz_6bdc"
    SOLUTIONS_DIR = "/src/conf/long-term-memory/solutions"
    
    def __init__(self, dry_run: bool = False, create_backup: bool = False, debug: bool = False):
        """
        Initialize the solution snapshot migrator with operational flags.
        
        Requires:
            - All parameters must be boolean values
            
        Ensures:
            - Sets migration operational modes (dry_run, backup, debug)
            - Initializes statistics dictionary for tracking migration results
            - Prepares migrator for file processing operations
            
        Args:
            dry_run: If True, show changes without applying them (default: False)
            create_backup: If True, create .bak files before modification (default: False)
            debug: If True, show detailed debug output (default: False)
            
        Returns:
            None
            
        Raises:
            No exceptions raised during initialization
        """
        self.dry_run = dry_run
        self.create_backup = create_backup
        self.debug = debug
        self.stats = {
            "total_files": 0,
            "migrated_files": 0,
            "skipped_files": 0,
            "error_files": 0,
            "backup_files": 0
        }
        
    def log(self, message: str, level: str = "INFO") -> None:
        """Log a message with timestamp."""
        print(f"[{level}] {message}")
        
    def debug_log(self, message: str) -> None:
        """Log a debug message if debug mode is enabled."""
        if self.debug:
            self.log(message, "DEBUG")
            
    def get_solutions_directory(self) -> Path:
        """Get the absolute path to the solutions directory."""
        project_root = du.get_project_root()
        solutions_path = Path(project_root + self.SOLUTIONS_DIR)
        
        if not solutions_path.exists():
            raise FileNotFoundError(f"Solutions directory not found: {solutions_path}")
            
        return solutions_path
        
    def find_snapshot_files(self, solutions_dir: Path) -> List[Path]:
        """Find all JSON snapshot files in the solutions directory."""
        snapshot_files = []
        
        # Find all .json files
        for json_file in solutions_dir.rglob("*.json"):
            if json_file.is_file():
                snapshot_files.append(json_file)
                
        self.debug_log(f"Found {len(snapshot_files)} JSON files")
        return sorted(snapshot_files)
        
    def load_snapshot(self, file_path: Path) -> Dict[str, Any]:
        """Load and parse a snapshot JSON file."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            self.debug_log(f"Loaded snapshot: {file_path.name}")
            return data
        except Exception as e:
            raise ValueError(f"Failed to load {file_path}: {e}")
            
    def needs_migration(self, snapshot_data: Dict[str, Any]) -> bool:
        """Check if a snapshot needs user_id migration."""
        # Check if user_id already exists
        if "user_id" in snapshot_data:
            self.debug_log(f"Snapshot already has user_id: {snapshot_data.get('user_id')}")
            return False
            
        # Check if this is a valid solution snapshot (has expected fields)
        required_fields = ["question", "answer", "id_hash"]
        for field in required_fields:
            if field not in snapshot_data:
                self.debug_log(f"Snapshot missing required field '{field}' - may not be a solution snapshot")
                return False
                
        return True
        
    def migrate_snapshot(self, snapshot_data: Dict[str, Any]) -> Dict[str, Any]:
        """Add user_id to snapshot data."""
        migrated_data = snapshot_data.copy()
        migrated_data["user_id"] = self.DEFAULT_USER_ID
        
        self.debug_log(f"Added user_id: {self.DEFAULT_USER_ID}")
        return migrated_data
        
    def save_snapshot(self, file_path: Path, snapshot_data: Dict[str, Any]) -> None:
        """Save migrated snapshot data to file."""
        if self.dry_run:
            self.log(f"DRY RUN: Would save migrated data to {file_path}")
            return
            
        # Create backup if requested
        if self.create_backup:
            backup_path = file_path.with_suffix(file_path.suffix + ".bak")
            shutil.copy2(file_path, backup_path)
            self.stats["backup_files"] += 1
            self.debug_log(f"Created backup: {backup_path}")
            
        # Write migrated data
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(snapshot_data, f, indent=2, ensure_ascii=False)
            
        self.debug_log(f"Saved migrated snapshot: {file_path}")
        
    def migrate_file(self, file_path: Path) -> bool:
        """
        Migrate a single snapshot file to include default user_id.
        
        Requires:
            - file_path must be a valid Path object to existing JSON file
            - File must be readable and writable (unless dry_run mode)
            - File must contain valid JSON format
            
        Ensures:
            - Loads snapshot data from file
            - Checks if migration is needed (user_id missing)
            - Adds default user_id if required
            - Saves migrated data back to file (unless dry_run)
            - Returns True if migrated, False if skipped
            
        Args:
            file_path: Path to the snapshot JSON file to migrate
            
        Returns:
            bool: True if file was migrated, False if skipped
            
        Raises:
            Exception: If migration fails (file I/O, JSON parsing, etc.)
            FileNotFoundError: If file does not exist
            PermissionError: If file cannot be read/written
        """
        self.log(f"Processing: {file_path.name}")
        
        # Load the snapshot
        try:
            snapshot_data = self.load_snapshot(file_path)
        except Exception as e:
            self.log(f"ERROR loading {file_path.name}: {e}", "ERROR")
            raise
            
        # Check if migration is needed
        if not self.needs_migration(snapshot_data):
            self.log(f"SKIPPED: {file_path.name} (already has user_id or invalid format)")
            return False
            
        # Perform migration
        try:
            migrated_data = self.migrate_snapshot(snapshot_data)
            self.save_snapshot(file_path, migrated_data)
            self.log(f"MIGRATED: {file_path.name}")
            return True
        except Exception as e:
            self.log(f"ERROR migrating {file_path.name}: {e}", "ERROR")
            raise
            
    def migrate_all(self) -> None:
        """Migrate all solution snapshot files."""
        self.log("Starting solution snapshot migration...")
        self.log(f"Target user_id: {self.DEFAULT_USER_ID}")
        
        if self.dry_run:
            self.log("DRY RUN MODE - No files will be modified")
        if self.create_backup:
            self.log("BACKUP MODE - .bak files will be created")
            
        # Find solutions directory
        try:
            solutions_dir = self.get_solutions_directory()
            self.log(f"Solutions directory: {solutions_dir}")
        except Exception as e:
            self.log(f"FATAL: {e}", "ERROR")
            return
            
        # Find all snapshot files
        snapshot_files = self.find_snapshot_files(solutions_dir)
        self.stats["total_files"] = len(snapshot_files)
        
        if not snapshot_files:
            self.log("No JSON files found in solutions directory")
            return
            
        self.log(f"Found {len(snapshot_files)} snapshot files to process")
        
        # Process each file
        for file_path in snapshot_files:
            try:
                if self.migrate_file(file_path):
                    self.stats["migrated_files"] += 1
                else:
                    self.stats["skipped_files"] += 1
            except Exception as e:
                self.stats["error_files"] += 1
                self.log(f"Failed to process {file_path.name}: {e}", "ERROR")
                
        # Print summary
        self.print_summary()
        
    def print_summary(self) -> None:
        """Print migration summary statistics."""
        self.log("="*60)
        self.log("MIGRATION SUMMARY")
        self.log("="*60)
        self.log(f"Total files found:     {self.stats['total_files']}")
        self.log(f"Successfully migrated: {self.stats['migrated_files']}")
        self.log(f"Skipped (no change):   {self.stats['skipped_files']}")
        self.log(f"Errors encountered:    {self.stats['error_files']}")
        if self.create_backup:
            self.log(f"Backup files created:  {self.stats['backup_files']}")
        self.log("="*60)
        
        if self.stats["error_files"] > 0:
            self.log("WARNING: Some files had errors. Check the log above.", "WARN")
        elif self.stats["migrated_files"] > 0:
            if self.dry_run:
                self.log("Ready for migration! Re-run without --dry-run to apply changes.")
            else:
                self.log("Migration completed successfully!")
        else:
            self.log("No files needed migration.")


def main():
    """Main entry point for the migration script."""
    parser = argparse.ArgumentParser(
        description="Migrate solution snapshot files to include user_id",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python migrate_solution_snapshots.py --dry-run          # Preview changes
  python migrate_solution_snapshots.py --backup           # Migrate with backups
  python migrate_solution_snapshots.py --dry-run --debug  # Preview with debug output
        """
    )
    
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be changed without making changes"
    )
    
    parser.add_argument(
        "--backup",
        action="store_true",
        help="Create .bak files before modifying originals"
    )
    
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Show detailed debug output"
    )
    
    args = parser.parse_args()
    
    # Create and run migrator
    migrator = SolutionSnapshotMigrator(
        dry_run=args.dry_run,
        create_backup=args.backup,
        debug=args.debug
    )
    
    try:
        migrator.migrate_all()
    except KeyboardInterrupt:
        print("\nMigration interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"FATAL ERROR: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()