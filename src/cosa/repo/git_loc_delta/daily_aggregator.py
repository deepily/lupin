"""
Daily Aggregator — buckets per-file changes into (date, file_type) and per-date totals.

Consumes the dict stream from `GitLogParser.iter_changes()` and emits two views:

1. **By-day-by-type**: `dict[(date, file_type)] → {added, deleted, files_touched, commits}`
2. **Daily totals**: `dict[date] → {added, deleted, files_touched, commits, by_file_type}`

The aggregator classifies each file's type using `branch_analyzer.FileTypeClassifier`,
loaded from the sibling package's `ConfigLoader().load()` (reuse R1).

Design Principles:
- Single-pass over the input stream (no second iteration)
- `files_touched` per (date, file_type) counts UNIQUE paths within that bucket
- `commits` per (date, file_type) counts UNIQUE SHAs touching at least one file of that type
- Totals view is derived from the by-type view after the pass completes

Usage:
    from cosa.repo.git_loc_delta.daily_aggregator import DailyAggregator

    agg = DailyAggregator( debug=False, verbose=False )
    for change in parser.iter_changes():
        agg.record( change )

    by_type = agg.by_type()    # dict[(date, file_type)] → counts
    by_day  = agg.daily()      # dict[date] → counts + by_file_type list
"""

from typing import Dict, Set, Tuple

from cosa.repo.branch_analyzer.config_loader import ConfigLoader
from cosa.repo.branch_analyzer.file_classifier import FileTypeClassifier


class DailyAggregator:
    """
    Aggregates per-file change rows into (date, file_type) buckets and daily totals.
    """

    def __init__( self, debug: bool = False, verbose: bool = False ):
        """
        Initialize aggregator with a shared file-type classifier.

        Requires:
            - cosa.repo.branch_analyzer.config_loader.ConfigLoader is importable
              and produces a config with a `file_types.extensions` section

        Ensures:
            - Classifier ready to call .classify(path)
            - Internal buckets empty
        """
        self.debug   = debug
        self.verbose = verbose

        loader = ConfigLoader( debug=False )
        config = loader.load()
        self.classifier = FileTypeClassifier( config, debug=False )

        # by_type_counts[(date, file_type)] = {added, deleted}
        self._by_type_counts: Dict[Tuple[str, str], Dict[str, int]] = {}
        # by_type_files[(date, file_type)] = set of unique paths
        self._by_type_files: Dict[Tuple[str, str], Set[str]] = {}
        # by_type_commits[(date, file_type)] = set of unique SHAs
        self._by_type_commits: Dict[Tuple[str, str], Set[str]] = {}

        # Track all SHAs and dates seen, for totals
        self._all_dates: Set[str] = set()

    def record( self, change: dict ) -> None:
        """
        Record one file-change row into the appropriate bucket.

        Requires:
            - change is a dict with keys: date, sha, author, path, added, deleted

        Ensures:
            - Bucket counters updated (added/deleted summed)
            - File path added to the per-bucket unique-file set
            - SHA added to the per-bucket unique-commit set
        """
        date      = change["date"]
        sha       = change["sha"]
        path      = change["path"]
        added     = int( change["added"] )
        deleted   = int( change["deleted"] )
        file_type = self.classifier.classify( path )

        key = ( date, file_type )

        if key not in self._by_type_counts:
            self._by_type_counts[key]  = {"added": 0, "deleted": 0}
            self._by_type_files[key]   = set()
            self._by_type_commits[key] = set()

        self._by_type_counts[key]["added"]   += added
        self._by_type_counts[key]["deleted"] += deleted
        self._by_type_files[key].add( path )
        self._by_type_commits[key].add( sha )
        self._all_dates.add( date )

        if self.debug:
            print( f"[DailyAggregator] +{added}/-{deleted} on {date} {file_type} ({path})" )

    def by_type( self ) -> Dict[Tuple[str, str], Dict[str, int]]:
        """
        Return the by-(date,file_type) bucket view.

        Ensures:
            - Returns a fresh dict (caller may mutate without affecting state)
            - Each value carries: added, deleted, files_touched, commits
        """
        out = {}
        for key, counts in self._by_type_counts.items():
            out[key] = {
                "added":          counts["added"],
                "deleted":        counts["deleted"],
                "files_touched":  len( self._by_type_files[key] ),
                "commits":        len( self._by_type_commits[key] ),
            }
        return out

    def daily( self ) -> Dict[str, Dict]:
        """
        Return the per-day totals view, including a sorted by_file_type breakdown.

        Ensures:
            - Returns a fresh dict keyed by date (YYYY-MM-DD)
            - Each value: {added, deleted, files_touched, commits, by_file_type: [{file_type, added, deleted, files_touched, commits}, ...]}
            - by_file_type sorted by `added` descending for consistent display
            - files_touched and commits at the date level count UNIQUE entries across all file types
        """
        # Collapse by-type buckets into per-date rollups
        per_date_added: Dict[str, int] = {}
        per_date_deleted: Dict[str, int] = {}
        per_date_files: Dict[str, Set[str]] = {}
        per_date_commits: Dict[str, Set[str]] = {}
        per_date_types_rows: Dict[str, list] = {}

        by_type = self.by_type()

        for ( date, file_type ), row in by_type.items():
            per_date_added[date]    = per_date_added.get( date, 0 ) + row["added"]
            per_date_deleted[date]  = per_date_deleted.get( date, 0 ) + row["deleted"]
            per_date_files.setdefault( date, set() ).update(
                self._by_type_files[ ( date, file_type ) ]
            )
            per_date_commits.setdefault( date, set() ).update(
                self._by_type_commits[ ( date, file_type ) ]
            )
            per_date_types_rows.setdefault( date, [] ).append({
                "file_type":     file_type,
                "added":         row["added"],
                "deleted":       row["deleted"],
                "files_touched": row["files_touched"],
                "commits":       row["commits"],
            })

        # Sort each date's by_file_type rows by added descending (display stability)
        for date in per_date_types_rows:
            per_date_types_rows[date].sort( key=lambda r: r["added"], reverse=True )

        out = {}
        for date in sorted( self._all_dates ):
            out[date] = {
                "added":         per_date_added.get( date, 0 ),
                "deleted":       per_date_deleted.get( date, 0 ),
                "files_touched": len( per_date_files.get( date, set() ) ),
                "commits":       len( per_date_commits.get( date, set() ) ),
                "by_file_type":  per_date_types_rows.get( date, [] ),
            }
        return out

    def summary( self ) -> Dict[str, int]:
        """
        Return overall totals across the entire date range.

        Ensures:
            - Returns: {total_added, total_deleted, total_files, total_commits, total_days, net}
        """
        total_added   = 0
        total_deleted = 0
        all_files: Set[str]   = set()
        all_commits: Set[str] = set()

        for key, row in self._by_type_counts.items():
            total_added   += row["added"]
            total_deleted += row["deleted"]
            all_files.update( self._by_type_files[key] )
            all_commits.update( self._by_type_commits[key] )

        return {
            "total_added":   total_added,
            "total_deleted": total_deleted,
            "total_files":   len( all_files ),
            "total_commits": len( all_commits ),
            "total_days":    len( self._all_dates ),
            "net":           total_added - total_deleted,
        }

    def is_empty( self ) -> bool:
        """
        Return True if no rows have been recorded (used for empty-range banner).

        Ensures:
            - True iff record() has never been called successfully
        """
        return len( self._by_type_counts ) == 0
