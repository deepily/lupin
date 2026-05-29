"""
Report Formatter for Branch Analyzer

Formats analysis statistics in multiple output formats: console (human-readable),
JSON (machine-readable), and Markdown (documentation-friendly).

Design Principles:
- Format-specific optimizations (colors for console, structure for JSON)
- Configuration-driven formatting (column widths, decimals, etc.)
- COSA standards compliance (du.print_banner for console)
- Consistent structure across all formats

Usage:
    from cosa.repo.branch_analyzer.report_formatter import ReportFormatter

    formatter = ReportFormatter( config, debug=True )

    # Format as console output
    console_output = formatter.format_console( stats )
    print( console_output )

    # Format as JSON
    json_output = formatter.format_json( stats )
    # Save or process JSON

    # Format as Markdown
    markdown_output = formatter.format_markdown( stats )
    # Save to .md file
"""

import json
from typing import Dict, Any


class ReportFormatter:
    """
    Formats statistics in multiple output formats.

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
        col_widths           = self.fmt_config.get( 'column_widths', {} )
        self.col_file_type   = col_widths.get( 'file_type', 15 )
        self.col_counts      = col_widths.get( 'counts', 10 )
        self.col_net_change  = col_widths.get( 'net_change', 12 )

        # Formatting characters
        self.border_char     = self.fmt_config.get( 'border_char', '=' )
        self.separator_char  = self.fmt_config.get( 'separator_char', '-' )
        self.border_width    = self.fmt_config.get( 'section_border_width', 80 )

        # Number formatting
        self.show_percentages = self.output_config.get( 'show_percentages', True )
        self.decimal_places   = self.output_config.get( 'decimal_places', 1 )

        if self.debug:
            print( "[ReportFormatter] Initialized with console/JSON/markdown support" )

    def format_console( self, stats: Dict[str, Any], base_branch: str, head_branch: str,
                        repo_path: str = '.', base_branch_input: str = None,
                        head_branch_input: str = None ) -> str:
        """
        Format statistics for console output.

        Uses COSA print_banner style and configurable formatting.

        Requires:
            - stats is dict from StatisticsCollector.get_summary()
            - base_branch is resolved base branch name
            - head_branch is resolved head branch name
            - repo_path is repository path
            - base_branch_input is original input (may be symbolic like 'main')
            - head_branch_input is original input (may be 'HEAD')

        Ensures:
            - Returns formatted string ready for print()
            - Uses COSA formatting conventions
            - Shows clear comparison context

        Raises:
            - Never raises
        """
        output = []

        # Import du.print_banner if available, otherwise use simple formatting
        try:
            import cosa.utils.util as du
            banner = self._create_banner_with_du( "BRANCH COMPARISON ANALYSIS" )
        except ImportError:
            banner = self._create_simple_banner( "BRANCH COMPARISON ANALYSIS" )

        output.append( banner )
        output.append( "" )

        # Show repository and branch information
        import os
        abs_repo_path = os.path.abspath( repo_path )
        output.append( f"Repository:     {abs_repo_path}" )
        output.append( f"Base branch:    {base_branch}" )
        output.append( f"Current branch: {head_branch}" )
        output.append( "" )

        # Show comparison direction
        if head_branch_input and head_branch_input == 'HEAD':
            output.append( f"Comparing: {head_branch} → {base_branch}" )
            output.append( f"(Shows what you added/changed in '{head_branch}' compared to '{base_branch}')" )
        else:
            output.append( f"Comparing: {head_branch} → {base_branch}" )

        output.append( "" )

        # Overall summary
        overall = stats['overall']
        output.append( "OVERALL SUMMARY" )
        output.append( f"  Total lines added:   {overall['total_added']:,}" )
        output.append( f"  Total lines removed: {overall['total_removed']:,}" )
        output.append( f"  Net change:          {overall['net_change']:+,}" )
        output.append( f"  Files changed:       {overall['files_changed']:,}" )
        output.append( "" )

        # Breakdown by file type
        output.append( "BREAKDOWN BY FILE TYPE" )
        header = f"{'File Type':<{self.col_file_type}} {'Added':>{self.col_counts}} {'Removed':>{self.col_counts}} {'Net Change':>{self.col_net_change}}"
        output.append( header )
        output.append( self.separator_char * len( header ) )

        for item in stats['by_file_type']:
            file_type = item['file_type'].capitalize()
            added     = item['added']
            removed   = item['removed']
            net       = item['net']

            line = f"{file_type:<{self.col_file_type}} {added:>{self.col_counts},} {removed:>{self.col_counts},} {net:>+{self.col_net_change},}"
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

    def format_json( self, stats: Dict[str, Any], base_branch: str, head_branch: str,
                     repo_path: str = '.', base_branch_input: str = None,
                     head_branch_input: str = None ) -> str:
        """
        Format statistics as JSON.

        Requires:
            - stats is dict from StatisticsCollector.get_summary()
            - base_branch is resolved base branch name
            - head_branch is resolved head branch name
            - repo_path is repository path

        Ensures:
            - Returns valid JSON string
            - Includes metadata if configured

        Raises:
            - Never raises
        """
        import os
        output = {
            'base_branch'    : base_branch,
            'head_branch'    : head_branch,
            'repository'     : os.path.abspath( repo_path ),
            'statistics'     : stats
        }

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

    def format_markdown( self, stats: Dict[str, Any], base_branch: str, head_branch: str,
                         repo_path: str = '.', base_branch_input: str = None,
                         head_branch_input: str = None ) -> str:
        """
        Format statistics as Markdown.

        Requires:
            - stats is dict from StatisticsCollector.get_summary()
            - base_branch is resolved base branch name
            - head_branch is resolved head branch name
            - repo_path is repository path

        Ensures:
            - Returns valid Markdown string
            - Uses tables for structured data

        Raises:
            - Never raises
        """
        import os
        output = []

        output.append( f"# Branch Comparison Analysis: {head_branch} → {base_branch}" )
        output.append( "" )

        # Repository and timestamp
        if self.markdown_config.get( 'include_timestamp', True ):
            import datetime
            output.append( f"**Repository**: `{os.path.abspath(repo_path)}`" )
            output.append( f"**Base branch**: `{base_branch}`" )
            output.append( f"**Current branch**: `{head_branch}`" )
            output.append( f"**Generated**: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}" )
            output.append( "" )

        # Overall summary
        overall = stats['overall']
        output.append( "## Overall Summary" )
        output.append( "" )
        output.append( f"- **Total lines added**: {overall['total_added']:,}" )
        output.append( f"- **Total lines removed**: {overall['total_removed']:,}" )
        output.append( f"- **Net change**: {overall['net_change']:+,}" )
        output.append( f"- **Files changed**: {overall['files_changed']:,}" )
        output.append( "" )

        # Breakdown by file type
        output.append( "## Breakdown by File Type" )
        output.append( "" )
        output.append( "| File Type | Added | Removed | Net Change |" )
        output.append( "|-----------|-------|---------|------------|" )

        for item in stats['by_file_type']:
            file_type = item['file_type'].capitalize()
            added     = f"{item['added']:,}"
            removed   = f"{item['removed']:,}"
            net       = f"{item['net']:+,}"

            output.append( f"| {file_type} | {added} | {removed} | {net} |" )

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

                output.append( f"- **Removed**: {lang_stats['removed']:,}" )
                output.append( f"- **Net change**: {lang_stats['net']:+,}" )
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
        """Format language-specific breakdown."""
        output = []

        output.append( f"{lang_name} FILES - SOURCE vs DOCUMENTATION" )

        code      = lang_stats['code']
        comment   = lang_stats['comment']
        docstring = lang_stats.get( 'docstring', 0 )
        removed   = lang_stats['removed']
        total     = lang_stats['total_added']
        net       = lang_stats['net']

        percentages = lang_stats['percentages']

        output.append( "  Added lines:" )
        output.append( f"    Source code:      {code:>8,}  ({percentages['code']:>5.1f}%)" )
        output.append( f"    Comments:         {comment:>8,}  ({percentages['comment']:>5.1f}%)" )

        if docstring > 0:
            output.append( f"    Docstrings:       {docstring:>8,}  ({percentages['docstring']:>5.1f}%)" )

        output.append( f"    Total added:      {total:>8,}" )
        output.append( f"  Removed lines:      {removed:>8,}" )
        output.append( f"  Net change:         {net:>+8,}" )
        output.append( "" )

        return output
