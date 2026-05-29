"""
Statistics Collector for Branch Analyzer

Aggregates line-level data into summary statistics. Tracks totals by
file type and provides code vs comment breakdowns for supported languages.

Design Principles:
- Atomic updates (thread-safe if needed in future)
- Percentage calculations with division-by-zero protection
- Flexible aggregation (by file type, language, operation)
- Efficient memory usage (running totals, not line storage)

Usage:
    from cosa.repo.branch_analyzer.statistics_collector import StatisticsCollector

    collector = StatisticsCollector( debug=True )

    # Record lines
    collector.record_line( 'python', 'add', line_category='code' )
    collector.record_line( 'python', 'add', line_category='comment' )
    collector.record_line( 'javascript', 'remove' )

    # Get summary
    stats = collector.get_summary()
    # Returns comprehensive statistics dict
"""

from collections import defaultdict
from typing import Dict, Any, Optional


class StatisticsCollector:
    """
    Aggregates line-level statistics.

    Tracks additions/removals by file type and separates code from
    documentation for supported languages.
    """

    def __init__( self, debug: bool = False, verbose: bool = False ):
        """
        Initialize statistics collector.

        Requires:
            - debug is boolean
            - verbose is boolean

        Ensures:
            - Collector initialized with empty statistics
            - Ready to record lines

        Raises:
            - Never raises
        """
        self.debug   = debug
        self.verbose = verbose

        # Overall statistics by file type
        self.by_file_type = defaultdict( lambda: { 'added': 0, 'removed': 0 } )

        # Language-specific breakdowns (Python, JavaScript, etc.)
        self.by_language = defaultdict( lambda: {
            'code'     : 0,
            'comment'  : 0,
            'docstring': 0,
            'removed'  : 0
        } )

        # File counts
        self.files_changed = set()

        if self.debug:
            print( "[StatisticsCollector] Initialized" )

    def record_line( self, file_type: str, operation: str,
                    line_category: Optional[str] = None,
                    file_path: Optional[str] = None ) -> None:
        """
        Record a single line.

        Requires:
            - file_type is non-empty string
            - operation is 'add' or 'remove'
            - line_category is None or one of: 'code', 'comment', 'docstring'
            - file_path is None or string

        Ensures:
            - Statistics updated atomically
            - File tracked if file_path provided

        Raises:
            - Never raises (ignores invalid input)
        """
        if operation == 'add':
            self.by_file_type[file_type]['added'] += 1

            # Record language-specific breakdown
            if line_category in ['code', 'comment', 'docstring']:
                self.by_language[file_type][line_category] += 1

        elif operation == 'remove':
            self.by_file_type[file_type]['removed'] += 1

            # Record removal for language-specific types
            if file_type in ['python', 'javascript', 'typescript']:
                self.by_language[file_type]['removed'] += 1

        # Track file
        if file_path:
            self.files_changed.add( file_path )

    def get_summary( self ) -> Dict[str, Any]:
        """
        Compute comprehensive summary statistics.

        Ensures:
            - Returns dict with totals, breakdowns, percentages
            - All counts are non-negative integers
            - Percentages are floats (0.0-100.0)
            - Division by zero handled gracefully

        Raises:
            - Never raises
        """
        # Calculate overall totals
        total_added = sum( counts['added'] for counts in self.by_file_type.values() )
        total_removed = sum( counts['removed'] for counts in self.by_file_type.values() )

        # Sort file types by total changes
        sorted_types = sorted(
            self.by_file_type.items(),
            key     = lambda x: x[1]['added'] + x[1]['removed'],
            reverse = True
        )

        # Build breakdown list
        breakdown = []
        for file_type, counts in sorted_types:
            added = counts['added']
            removed = counts['removed']
            net = added - removed

            breakdown.append( {
                'file_type' : file_type,
                'added'     : added,
                'removed'   : removed,
                'net'       : net,
                'total'     : added + removed
            } )

        # Build language-specific breakdowns
        language_details = {}
        for lang in ['python', 'javascript', 'typescript']:
            if lang in self.by_language:
                stats = self.by_language[lang]
                code = stats['code']
                comment = stats['comment']
                docstring = stats.get( 'docstring', 0 )
                removed = stats['removed']

                total_added = code + comment + docstring
                net = total_added - removed

                # Calculate percentages
                percentages = {}
                if total_added > 0:
                    percentages['code'] = 100.0 * code / total_added
                    percentages['comment'] = 100.0 * comment / total_added
                    if docstring > 0:
                        percentages['docstring'] = 100.0 * docstring / total_added
                else:
                    percentages = { 'code': 0.0, 'comment': 0.0, 'docstring': 0.0 }

                language_details[lang] = {
                    'code'        : code,
                    'comment'     : comment,
                    'docstring'   : docstring,
                    'removed'     : removed,
                    'total_added' : total_added,
                    'net'         : net,
                    'percentages' : percentages
                }

        return {
            'overall' : {
                'total_added'   : total_added,
                'total_removed' : total_removed,
                'net_change'    : total_added - total_removed,
                'files_changed' : len( self.files_changed )
            },
            'by_file_type'      : breakdown,
            'language_details'  : language_details,
            'files_changed_set' : list( self.files_changed )
        }

    def reset( self ) -> None:
        """Reset all statistics to zero."""
        self.by_file_type.clear()
        self.by_language.clear()
        self.files_changed.clear()

        if self.debug:
            print( "[StatisticsCollector] Statistics reset" )
