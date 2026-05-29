"""
Branch Change Analyzer - Main Orchestrator

Coordinates all components to analyze git branch changes. This is the main
entry point for programmatic use of the branch analyzer.

Design Principles:
- Orchestrate without reimplementation (delegates to specialists)
- Provides simple public API while hiding complexity
- Full error handling with clear error messages
- Progress feedback for long-running operations
- Automatic HEAD resolution to actual branch names
- Clear comparison context in all outputs

Default Behavior:
    By default (no arguments), compares your current branch (HEAD) to main:
    - repo_path defaults to '.' (current directory)
    - base_branch defaults to 'main' (from config)
    - head_branch defaults to 'HEAD' (auto-resolves to actual branch name)
    - All git operations run in specified repository

Usage:
    from cosa.repo.branch_analyzer import BranchChangeAnalyzer

    # Simple usage - compare current branch to main
    analyzer = BranchChangeAnalyzer()
    stats = analyzer.analyze()
    output = analyzer.format_results( stats )
    print( output )

    # Analyze different repository (e.g., COSA from Lupin src)
    analyzer = BranchChangeAnalyzer( repo_path='cosa' )
    stats = analyzer.analyze()

    # Advanced usage
    analyzer = BranchChangeAnalyzer(
        config_path = 'my_config.yaml',
        base_branch = 'develop',        # What you're comparing FROM
        head_branch = 'feature-branch', # What you're comparing TO
        repo_path   = '/path/to/repo',  # Repository to analyze
        debug       = True,
        verbose     = True
    )

    stats = analyzer.analyze()
    console_output  = analyzer.format_results( stats, format='console' )
    json_output     = analyzer.format_results( stats, format='json' )
    markdown_output = analyzer.format_results( stats, format='markdown' )

Understanding Outputs:
    All output formats include:
    - Resolved branch names (HEAD → actual branch name)
    - Repository absolute path
    - Comparison direction indicator
    - Detailed statistics and breakdowns

    Console format includes helpful explanation when HEAD is used.
"""

from typing import Dict, Any, Optional

from .config_loader import ConfigLoader
from .file_classifier import FileTypeClassifier
from .line_classifier import LineClassifier
from .git_diff_parser import GitDiffParser
from .statistics_collector import StatisticsCollector
from .report_formatter import ReportFormatter
from .exceptions import BranchAnalyzerError


class BranchChangeAnalyzer:
    """
    Main orchestrator for branch change analysis.

    Coordinates configuration loading, git operations, classification,
    statistics collection, and report formatting.
    """

    def __init__( self, config_path: Optional[str] = None,
                  base_branch: Optional[str] = None,
                  head_branch: Optional[str] = None,
                  repo_path: Optional[str] = None,
                  debug: bool = False,
                  verbose: bool = False ):
        """
        Initialize branch change analyzer.

        Requires:
            - config_path is None or valid file path
            - base_branch is None or valid git reference
            - head_branch is None or valid git reference
            - repo_path is None or valid directory path
            - debug is boolean
            - verbose is boolean

        Ensures:
            - Analyzer initialized and ready to run analysis
            - Configuration loaded and validated
            - All components initialized

        Raises:
            - BranchAnalyzerError if initialization fails
        """
        self.debug     = debug
        self.verbose   = verbose
        self.repo_path = repo_path or '.'

        # Load configuration
        try:
            config_loader = ConfigLoader( config_path=config_path, debug=debug )
            self.config = config_loader.load()
        except Exception as e:
            raise BranchAnalyzerError( f"Failed to load configuration: {e}" )

        # Override branch settings from command line if provided
        if base_branch:
            self.config['git']['default_base_branch'] = base_branch
        if head_branch:
            self.config['git']['default_head_branch'] = head_branch

        # Get final branch values
        self.base_branch = self.config['git']['default_base_branch']
        self.head_branch = self.config['git']['default_head_branch']

        # Initialize components
        self.file_classifier = FileTypeClassifier( self.config, debug=debug, verbose=verbose )
        self.line_classifier = LineClassifier( self.config, debug=debug, verbose=verbose )
        self.git_parser      = GitDiffParser( self.config, repo_path=self.repo_path, debug=debug, verbose=verbose )
        self.stats_collector = StatisticsCollector( debug=debug, verbose=verbose )
        self.formatter       = ReportFormatter( self.config, debug=debug, verbose=verbose )

        # Resolve branch names (HEAD -> actual branch name)
        self.base_branch_resolved = self.git_parser.get_branch_name( self.base_branch )
        self.head_branch_resolved = self.git_parser.get_branch_name( self.head_branch )

        if self.debug:
            print( f"[BranchChangeAnalyzer] Initialized (base={self.base_branch}, head={self.head_branch})" )
            print( f"[BranchChangeAnalyzer] Resolved: base={self.base_branch_resolved}, head={self.head_branch_resolved}" )

    def analyze( self ) -> Dict[str, Any]:
        """
        Run complete analysis.

        Requires:
            - Git repository exists in current directory
            - base_branch and head_branch are valid references

        Ensures:
            - Returns complete statistics dict
            - Statistics include overall summary, breakdowns, language details

        Raises:
            - BranchAnalyzerError if analysis fails
        """
        if self.debug:
            print( f"[BranchChangeAnalyzer] Starting analysis: {self.base_branch}...{self.head_branch}" )

        try:
            # Get diff from git
            diff_lines = self.git_parser.get_diff( self.base_branch, self.head_branch )

            if self.verbose:
                print( f"[BranchChangeAnalyzer] Processing {len(diff_lines)} diff lines" )

            # Process each line
            self._process_diff_lines( diff_lines )

            # Get summary statistics
            stats = self.stats_collector.get_summary()

            if self.debug:
                print( f"[BranchChangeAnalyzer] Analysis complete: {stats['overall']['files_changed']} files changed" )

            return stats

        except Exception as e:
            raise BranchAnalyzerError( f"Analysis failed: {e}" )

    def format_results( self, stats: Dict[str, Any], format: str = 'console' ) -> str:
        """
        Format analysis results.

        Requires:
            - stats is dict from analyze()
            - format is one of: 'console', 'json', 'markdown'

        Ensures:
            - Returns formatted string ready for output
            - Format matches requested type

        Raises:
            - ValueError if format invalid
        """
        # Pass resolved branch names and repo path to formatter
        format_kwargs = {
            'stats'              : stats,
            'base_branch'        : self.base_branch_resolved,
            'head_branch'        : self.head_branch_resolved,
            'repo_path'          : self.repo_path,
            'base_branch_input'  : self.base_branch,
            'head_branch_input'  : self.head_branch
        }

        if format == 'console':
            return self.formatter.format_console( **format_kwargs )
        elif format == 'json':
            return self.formatter.format_json( **format_kwargs )
        elif format == 'markdown':
            return self.formatter.format_markdown( **format_kwargs )
        else:
            raise ValueError( f"Invalid format: {format}. Must be 'console', 'json', or 'markdown'" )

    def _process_diff_lines( self, diff_lines: list ) -> None:
        """
        Process diff lines and collect statistics.

        Requires:
            - diff_lines is list of DiffLine objects

        Ensures:
            - All lines processed and statistics updated
            - File types classified
            - Code vs comments separated for supported languages

        Raises:
            - Never raises (logs errors if debug enabled)
        """
        # Track state for each file (for multiline constructs)
        file_states = {}

        for diff_line in diff_lines:
            # Skip meta lines
            if diff_line.operation == 'meta' or diff_line.operation == 'context':
                continue

            file_path = diff_line.file_path
            if not file_path:
                continue

            # Classify file type
            file_type = self.file_classifier.classify( file_path )

            # For added lines, try to classify as code vs comment
            line_category = None
            if diff_line.operation == 'add':
                # Check if this language supports code/comment separation
                if self.line_classifier.supports_language( file_type ):
                    # Get or create state for this file
                    if file_path not in file_states:
                        file_states[file_path] = self.line_classifier.create_state( file_type )

                    state = file_states[file_path]

                    # Remove the diff prefix (+) before classification
                    line_content = diff_line.content[1:] if diff_line.content.startswith( '+' ) else diff_line.content

                    # Classify line
                    line_category, state = self.line_classifier.classify_line(
                        line_content,
                        file_type,
                        state
                    )

                    # Update state
                    file_states[file_path] = state

            # Record in statistics
            self.stats_collector.record_line(
                file_type     = file_type,
                operation     = diff_line.operation,
                line_category = line_category,
                file_path     = file_path
            )

        if self.verbose:
            print( f"[BranchChangeAnalyzer] Processed {len(file_states)} files with state tracking" )


def quick_smoke_test():
    """
    Quick smoke test for Branch Analyzer.

    Tests all major components:
    - Configuration loading
    - File type classification
    - Line classification (Python/JavaScript)
    - Statistics collection
    - Report formatting (console/JSON/markdown)

    Requires:
        - cosa.utils.util available for print_banner
        - Test can run without git repository

    Ensures:
        - Tests complete with ✓ or ✗ indicators
        - Clear progress messages
        - Uses COSA print_banner formatting

    Raises:
        - Never raises (catches all exceptions)
    """
    import cosa.utils.util as du

    du.print_banner( "Branch Analyzer Smoke Test", prepend_nl=True )

    try:
        # Test 1: Configuration loading
        print( "Testing configuration loading..." )
        from .config_loader import ConfigLoader
        loader = ConfigLoader( debug=False )
        config = loader.load()
        assert config is not None
        assert 'git' in config
        assert 'file_types' in config
        print( "✓ Configuration loaded successfully" )

        # Test 2: File classification
        print( "Testing file classification..." )
        from .file_classifier import FileTypeClassifier
        classifier = FileTypeClassifier( config, debug=False )
        assert classifier.classify( "test.py" ) == "python"
        assert classifier.classify( "test.js" ) == "javascript"
        assert classifier.classify( "test.unknown" ) == "other"
        print( "✓ File classification working" )

        # Test 3: Line classification (Python)
        print( "Testing line classification (Python)..." )
        from .line_classifier import LineClassifier
        line_classifier = LineClassifier( config, debug=False )
        state = line_classifier.create_state( 'python' )
        category, state = line_classifier.classify_line( "# comment", 'python', state )
        assert category == 'comment'
        category, state = line_classifier.classify_line( "x = 42", 'python', state )
        assert category == 'code'
        print( "✓ Python line classification working" )

        # Test 4: Line classification (JavaScript)
        print( "Testing line classification (JavaScript)..." )
        state = line_classifier.create_state( 'javascript' )
        category, state = line_classifier.classify_line( "// comment", 'javascript', state )
        assert category == 'comment'
        category, state = line_classifier.classify_line( "var x = 42;", 'javascript', state )
        assert category == 'code'
        print( "✓ JavaScript line classification working" )

        # Test 5: Statistics collection
        print( "Testing statistics collection..." )
        from .statistics_collector import StatisticsCollector
        collector = StatisticsCollector( debug=False )
        collector.record_line( 'python', 'add', line_category='code' )
        collector.record_line( 'python', 'add', line_category='comment' )
        collector.record_line( 'python', 'remove' )
        stats = collector.get_summary()
        assert stats['overall']['total_added'] == 2
        assert stats['overall']['total_removed'] == 1
        print( "✓ Statistics collection working" )

        # Test 6: Report formatting (Console)
        print( "Testing console formatting..." )
        from .report_formatter import ReportFormatter
        formatter = ReportFormatter( config, debug=False )
        console_output = formatter.format_console( stats, 'main', 'HEAD' )
        assert len( console_output ) > 0
        assert 'OVERALL SUMMARY' in console_output
        print( "✓ Console formatting working" )

        # Test 7: Report formatting (JSON)
        print( "Testing JSON formatting..." )
        json_output = formatter.format_json( stats, 'main', 'HEAD' )
        assert len( json_output ) > 0
        assert 'base_branch' in json_output
        print( "✓ JSON formatting working" )

        # Test 8: Report formatting (Markdown)
        print( "Testing Markdown formatting..." )
        markdown_output = formatter.format_markdown( stats, 'main', 'HEAD' )
        assert len( markdown_output ) > 0
        assert '# Code Changes Analysis' in markdown_output
        print( "✓ Markdown formatting working" )

        # Test 9: Exception hierarchy
        print( "Testing exception hierarchy..." )
        from .exceptions import (
            BranchAnalyzerError,
            GitCommandError,
            ConfigurationError,
            ParserError,
            ClassificationError
        )
        assert issubclass( GitCommandError, BranchAnalyzerError )
        assert issubclass( ConfigurationError, BranchAnalyzerError )
        print( "✓ Exception hierarchy valid" )

        print( "\n✓ All smoke tests passed successfully!" )

    except AssertionError as e:
        print( f"\n✗ Smoke test assertion failed: {e}" )
        import traceback
        traceback.print_exc()
    except Exception as e:
        print( f"\n✗ Smoke test failed with exception: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    quick_smoke_test()
