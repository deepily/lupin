"""
Statistics Collector for Directory Analyzer

Aggregates line-level data into summary statistics for directory analysis.
Tracks totals by file type and provides code vs comment breakdowns for
supported languages.

Design Principles:
- Atomic updates (thread-safe if needed in future)
- Percentage calculations with division-by-zero protection
- Flexible aggregation (by file type, language)
- Efficient memory usage (running totals, not line storage)

Usage:
    from cosa.repo.directory_analyzer.statistics_collector import DirectoryStatisticsCollector

    collector = DirectoryStatisticsCollector( debug=True )

    # Record lines
    collector.record_line( 'python', line_category='code', file_path='test.py' )
    collector.record_line( 'python', line_category='comment' )
    collector.record_line( 'javascript' )

    # Get summary
    stats = collector.get_summary()
    # Returns comprehensive statistics dict
"""

from collections import defaultdict
from typing import Dict, Any, Optional


class DirectoryStatisticsCollector:
    """
    Aggregates line-level statistics for directory analysis.

    Tracks total lines by file type and separates code from
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
        self.by_file_type = defaultdict( lambda: { 'total': 0, 'files': 0 } )

        # Language-specific breakdowns (Python, JavaScript, etc.)
        self.by_language = defaultdict( lambda: {
            'code'     : 0,
            'comment'  : 0,
            'docstring': 0,
            'total'    : 0
        } )

        # File tracking (to avoid counting files multiple times)
        self.files_by_type = defaultdict( set )

        if self.debug:
            print( "[DirectoryStatisticsCollector] Initialized" )

    def record_line( self, file_type: str, line_category: Optional[str] = None,
                    file_path: Optional[str] = None ) -> None:
        """
        Record a single line.

        Requires:
            - file_type is non-empty string
            - line_category is None or one of: 'code', 'comment', 'docstring'
            - file_path is None or string

        Ensures:
            - Statistics updated atomically
            - File tracked if file_path provided

        Raises:
            - Never raises (ignores invalid input)
        """
        # Record by file type
        self.by_file_type[file_type]['total'] += 1

        # Track file
        if file_path:
            self.files_by_type[file_type].add( file_path )

        # Record language-specific breakdown for supported languages
        if file_type in ['python', 'javascript', 'typescript']:
            self.by_language[file_type]['total'] += 1

            if line_category in ['code', 'comment', 'docstring']:
                self.by_language[file_type][line_category] += 1
            elif line_category is None:
                # If no category provided, count as code
                self.by_language[file_type]['code'] += 1

    def record_file( self, file_type: str, file_path: str ) -> None:
        """
        Record a file (without incrementing line count).

        Used when we need to ensure a file is tracked even if it has 0 lines.

        Requires:
            - file_type is non-empty string
            - file_path is non-empty string

        Ensures:
            - File added to tracking set for file_type

        Raises:
            - Never raises
        """
        self.files_by_type[file_type].add( file_path )

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
        # Update file counts from tracking sets
        for file_type, files in self.files_by_type.items():
            self.by_file_type[file_type]['files'] = len( files )

        # Calculate overall totals
        total_lines = sum( counts['total'] for counts in self.by_file_type.values() )
        total_files = sum( len( files ) for files in self.files_by_type.values() )

        # Sort file types by total lines (descending)
        sorted_types = sorted(
            self.by_file_type.items(),
            key     = lambda x: x[1]['total'],
            reverse = True
        )

        # Build breakdown list
        breakdown = []
        for file_type, counts in sorted_types:
            total = counts['total']
            files = counts.get( 'files', 0 )

            # Calculate percentage
            pct = 100.0 * total / total_lines if total_lines > 0 else 0.0

            breakdown.append( {
                'file_type'  : file_type,
                'total'      : total,
                'files'      : files,
                'percentage' : pct
            } )

        # Build language-specific breakdowns
        language_details = {}
        for lang in ['python', 'javascript', 'typescript']:
            if lang in self.by_language:
                stats = self.by_language[lang]
                code      = stats['code']
                comment   = stats['comment']
                docstring = stats.get( 'docstring', 0 )
                total     = stats['total']

                # Calculate percentages
                percentages = {}
                if total > 0:
                    percentages['code'] = 100.0 * code / total
                    percentages['comment'] = 100.0 * comment / total
                    if docstring > 0:
                        percentages['docstring'] = 100.0 * docstring / total
                    else:
                        percentages['docstring'] = 0.0
                else:
                    percentages = { 'code': 0.0, 'comment': 0.0, 'docstring': 0.0 }

                language_details[lang] = {
                    'code'        : code,
                    'comment'     : comment,
                    'docstring'   : docstring,
                    'total'       : total,
                    'percentages' : percentages
                }

        return {
            'overall' : {
                'total_lines' : total_lines,
                'total_files' : total_files
            },
            'by_file_type'     : breakdown,
            'language_details' : language_details
        }

    def reset( self ) -> None:
        """Reset all statistics to zero."""
        self.by_file_type.clear()
        self.by_language.clear()
        self.files_by_type.clear()

        if self.debug:
            print( "[DirectoryStatisticsCollector] Statistics reset" )
