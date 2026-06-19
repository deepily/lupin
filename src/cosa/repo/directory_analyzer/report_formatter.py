"""
Report Formatter for Directory Analyzer

Formats analysis statistics in multiple output formats: console (human-readable),
JSON (machine-readable), and Markdown (documentation-friendly).

Design Principles:
- Format-specific optimizations (colors for console, structure for JSON)
- Configuration-driven formatting (column widths, decimals, etc.)
- COSA standards compliance (du.print_banner for console)
- Consistent structure across all formats

Usage:
    from cosa.repo.directory_analyzer.report_formatter import DirectoryReportFormatter

    formatter = DirectoryReportFormatter( config, debug=True )

    # Format as console output
    console_output = formatter.format_console( stats, '/path/to/dir' )
    print( console_output )

    # Format as JSON
    json_output = formatter.format_json( stats, '/path/to/dir' )
    # Save or process JSON

    # Format as Markdown
    markdown_output = formatter.format_markdown( stats, '/path/to/dir' )
    # Save to .md file
"""

import json
from typing import Dict, Any


class DirectoryReportFormatter:
    """
    Formats directory statistics in multiple output formats.

    Supports console (with COSA print_banner), JSON, and Markdown
    formats with configuration-driven formatting options.
    """

    def __init__( self, config: Dict, debug: bool = False, verbose: bool = False ):
        """
        Initialize report formatter.

        Requires:
            - config is dict with formatting settings
            - debug is boolean
            - verbose is boolean

        Ensures:
            - Formatter initialized and ready to format statistics

        Raises:
            - Never raises
        """
        self.debug   = debug
        self.verbose = verbose
        self.config  = config

        # Extract formatting settings
        self.fmt_config      = config.get( 'formatting', {} )
        self.output_config   = config.get( 'output', {} )
        self.json_config     = config.get( 'json_output', {} )
        self.markdown_config = config.get( 'markdown_output', {} )

        # Column widths
        col_widths         = self.fmt_config.get( 'column_widths', {} )
        self.col_file_type = col_widths.get( 'file_type', 18 )
        self.col_lines     = col_widths.get( 'lines', 12 )
        self.col_files     = col_widths.get( 'files', 8 )
        self.col_percent   = col_widths.get( 'percent', 8 )

        # Formatting characters
        self.border_char    = self.fmt_config.get( 'border_char', '=' )
        self.separator_char = self.fmt_config.get( 'separator_char', '-' )
        self.border_width   = self.fmt_config.get( 'section_border_width', 80 )

        # Number formatting
        self.show_percentages = self.output_config.get( 'show_percentages', True )
        self.decimal_places   = self.output_config.get( 'decimal_places', 1 )

        if self.debug:
            print( "[DirectoryReportFormatter] Initialized with console/JSON/markdown support" )

    def format_console( self, stats: Dict[str, Any], directory_path: str,
                        scan_stats: Dict[str, Any] = None ) -> str:
        """
        Format statistics for console output.

        Uses COSA print_banner style and configurable formatting.

        Requires:
            - stats is dict from DirectoryStatisticsCollector.get_summary()
            - directory_path is string path that was analyzed
            - scan_stats is optional dict from DirectoryScanner.get_scan_stats()

        Ensures:
            - Returns formatted string ready for print()
            - Uses COSA formatting conventions

        Raises:
            - Never raises
        """
        output = []

        # Import du.print_banner if available, otherwise use simple formatting
        try:
            import cosa.utils.util as du
            banner = self._create_banner_with_du( "DIRECTORY CODE ANALYSIS" )
        except ImportError:
            banner = self._create_simple_banner( "DIRECTORY CODE ANALYSIS" )

        output.append( banner )
        output.append( "" )

        # Show directory path
        import os
        abs_path = os.path.abspath( directory_path )
        output.append( f"Directory: {abs_path}" )
        output.append( "" )

        # Overall summary
        overall = stats['overall']
        output.append( "OVERALL SUMMARY" )
        output.append( f"  Total lines: {overall['total_lines']:>12,}" )
        output.append( f"  Total files: {overall['total_files']:>12,}" )
        output.append( "" )

        # Scan statistics (if provided)
        if scan_stats:
            skipped = (
                scan_stats.get( 'files_skipped', 0 ) +
                scan_stats.get( 'binary_files_skipped', 0 ) +
                scan_stats.get( 'large_files_skipped', 0 ) +
                scan_stats.get( 'unreadable_files_skipped', 0 )
            )
            if skipped > 0 or scan_stats.get( 'dirs_skipped', 0 ) > 0:
                output.append( "SCAN SUMMARY" )
                if scan_stats.get( 'dirs_skipped', 0 ) > 0:
                    output.append( f"  Directories skipped: {scan_stats['dirs_skipped']:>6,}" )
                if scan_stats.get( 'binary_files_skipped', 0 ) > 0:
                    output.append( f"  Binary files skipped: {scan_stats['binary_files_skipped']:>5,}" )
                if scan_stats.get( 'large_files_skipped', 0 ) > 0:
                    output.append( f"  Large files skipped: {scan_stats['large_files_skipped']:>6,}" )
                if scan_stats.get( 'files_skipped', 0 ) > 0:
                    output.append( f"  Pattern excluded: {scan_stats['files_skipped']:>9,}" )
                output.append( "" )

        # Breakdown by file type
        output.append( "BREAKDOWN BY FILE TYPE" )
        header = f"{'File Type':<{self.col_file_type}} {'Lines':>{self.col_lines}} {'Files':>{self.col_files}} {'%':>{self.col_percent}}"
        output.append( header )
        output.append( self.separator_char * len( header ) )

        for item in stats['by_file_type']:
            file_type  = item['file_type'].capitalize()
            total      = item['total']
            files      = item['files']
            percentage = item['percentage']

            line = f"{file_type:<{self.col_file_type}} {total:>{self.col_lines},} {files:>{self.col_files},} {percentage:>{self.col_percent - 1}.{self.decimal_places}f}%"
            output.append( line )

        output.append( "" )

        # Language-specific breakdowns
        lang_details = stats['language_details']

        if 'python' in lang_details:
            output.extend( self._format_language_breakdown( 'PYTHON', lang_details['python'] ) )

        if 'javascript' in lang_details:
            output.extend( self._format_language_breakdown( 'JAVASCRIPT', lang_details['javascript'] ) )

        if 'typescript' in lang_details:
            output.extend( self._format_language_breakdown( 'TYPESCRIPT', lang_details['typescript'] ) )

        # Footer
        output.append( self.border_char * self.border_width )
        output.append( "" )

        return '\n'.join( output )

    def format_json( self, stats: Dict[str, Any], directory_path: str,
                     scan_stats: Dict[str, Any] = None ) -> str:
        """
        Format statistics as JSON.

        Requires:
            - stats is dict from DirectoryStatisticsCollector.get_summary()
            - directory_path is string path that was analyzed
            - scan_stats is optional dict from DirectoryScanner.get_scan_stats()

        Ensures:
            - Returns valid JSON string
            - Includes metadata if configured

        Raises:
            - Never raises
        """
        import os
        output = {
            'directory'  : os.path.abspath( directory_path ),
            'statistics' : stats
        }

        if scan_stats:
            output['scan_stats'] = scan_stats

        # Add metadata if configured
        if self.json_config.get( 'include_metadata', True ):
            import datetime
            output['metadata'] = {
                'generated_at' : datetime.datetime.now().isoformat(),
                'format'       : 'json',
                'version'      : '1.0'
            }

        # Format JSON
        indent = self.json_config.get( 'indent', 2 ) if self.json_config.get( 'pretty', True ) else None
        sort_keys = self.json_config.get( 'sort_keys', False )

        return json.dumps( output, indent=indent, sort_keys=sort_keys )

    def format_markdown( self, stats: Dict[str, Any], directory_path: str,
                         scan_stats: Dict[str, Any] = None ) -> str:
        """
        Format statistics as Markdown.

        Requires:
            - stats is dict from DirectoryStatisticsCollector.get_summary()
            - directory_path is string path that was analyzed
            - scan_stats is optional dict from DirectoryScanner.get_scan_stats()

        Ensures:
            - Returns valid Markdown string
            - Uses tables for structured data

        Raises:
            - Never raises
        """
        import os
        output = []

        output.append( f"# Directory Code Analysis" )
        output.append( "" )

        # Directory and timestamp
        if self.markdown_config.get( 'include_timestamp', True ):
            import datetime
            output.append( f"**Directory**: `{os.path.abspath(directory_path)}`" )
            output.append( f"**Generated**: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}" )
            output.append( "" )

        # Overall summary
        overall = stats['overall']
        output.append( "## Overall Summary" )
        output.append( "" )
        output.append( f"- **Total lines**: {overall['total_lines']:,}" )
        output.append( f"- **Total files**: {overall['total_files']:,}" )
        output.append( "" )

        # Breakdown by file type
        output.append( "## Breakdown by File Type" )
        output.append( "" )
        output.append( "| File Type | Lines | Files | % |" )
        output.append( "|-----------|-------|-------|---|" )

        for item in stats['by_file_type']:
            file_type  = item['file_type'].capitalize()
            total      = f"{item['total']:,}"
            files      = f"{item['files']:,}"
            percentage = f"{item['percentage']:.1f}%"

            output.append( f"| {file_type} | {total} | {files} | {percentage} |" )

        output.append( "" )

        # Language details
        lang_details = stats['language_details']

        if lang_details:
            output.append( "## Language-Specific Details" )
            output.append( "" )

            for lang_name, lang_stats in lang_details.items():
                output.append( f"### {lang_name.capitalize()}" )
                output.append( "" )
                output.append( f"- **Code**: {lang_stats['code']:,} ({lang_stats['percentages']['code']:.1f}%)" )
                output.append( f"- **Comments**: {lang_stats['comment']:,} ({lang_stats['percentages']['comment']:.1f}%)" )

                if lang_stats['docstring'] > 0:
                    output.append( f"- **Docstrings**: {lang_stats['docstring']:,} ({lang_stats['percentages']['docstring']:.1f}%)" )

                output.append( f"- **Total**: {lang_stats['total']:,}" )
                output.append( "" )

        return '\n'.join( output )

    def _create_banner_with_du( self, title: str ) -> str:
        """Create banner using COSA du.print_banner style."""
        import cosa.utils.util as du
        # Capture du.print_banner output
        import io
        import sys
        old_stdout = sys.stdout
        sys.stdout = buffer = io.StringIO()
        du.print_banner( title )
        sys.stdout = old_stdout
        return buffer.getvalue().rstrip()

    def _create_simple_banner( self, title: str ) -> str:
        """Create simple banner without du.print_banner."""
        border = self.border_char * self.border_width
        return f"{border}\n{title}\n{border}"

    def _format_language_breakdown( self, lang_name: str, lang_stats: Dict ) -> list:
        """Format language-specific breakdown for console output."""
        output = []

        output.append( f"{lang_name} FILES - SOURCE vs DOCUMENTATION" )

        code      = lang_stats['code']
        comment   = lang_stats['comment']
        docstring = lang_stats.get( 'docstring', 0 )
        total     = lang_stats['total']

        percentages = lang_stats['percentages']

        output.append( f"  Source code:  {code:>10,}  ({percentages['code']:>5.1f}%)" )
        output.append( f"  Comments:     {comment:>10,}  ({percentages['comment']:>5.1f}%)" )

        if docstring > 0:
            output.append( f"  Docstrings:   {docstring:>10,}  ({percentages['docstring']:>5.1f}%)" )

        output.append( f"  Total:        {total:>10,}" )
        output.append( "" )

        return output
