"""
Directory Analyzer - Main Orchestrator

Coordinates all components to analyze directory contents. This is the main
entry point for programmatic use of the directory analyzer.

Design Principles:
- Orchestrate without reimplementation (delegates to specialists)
- Provides simple public API while hiding complexity
- Full error handling with clear error messages
- Progress feedback for long-running operations
- Reuses file_classifier and line_classifier from branch_analyzer

Usage:
    from cosa.repo.directory_analyzer import DirectoryAnalyzer

    # Simple usage - analyze current directory
    analyzer = DirectoryAnalyzer()
    stats = analyzer.analyze( '.' )
    output = analyzer.format_results( stats, '.' )
    print( output )

    # Advanced usage
    analyzer = DirectoryAnalyzer(
        config_path = 'my_config.yaml',
        debug       = True,
        verbose     = True
    )

    stats = analyzer.analyze( '/path/to/project' )
    console_output  = analyzer.format_results( stats, '/path/to/project', format='console' )
    json_output     = analyzer.format_results( stats, '/path/to/project', format='json' )
    markdown_output = analyzer.format_results( stats, '/path/to/project', format='markdown' )
"""

from typing import Dict, Any, Optional

# Reuse from branch_analyzer
from cosa.repo.branch_analyzer.file_classifier import FileTypeClassifier
from cosa.repo.branch_analyzer.line_classifier import LineClassifier
from cosa.repo.branch_analyzer.config_loader import ConfigLoader

# Local imports
from .directory_scanner import DirectoryScanner
from .statistics_collector import DirectoryStatisticsCollector
from .report_formatter import DirectoryReportFormatter
from .exceptions import DirectoryAnalyzerError, ConfigurationError


class DirectoryAnalyzer:
    """
    Main orchestrator for directory analysis.

    Coordinates configuration loading, directory scanning, classification,
    statistics collection, and report formatting.
    """

    def __init__( self, config_path: Optional[str] = None,
                  debug: bool = False,
                  verbose: bool = False ):
        """
        Initialize directory analyzer.

        Requires:
            - config_path is None or valid file path
            - debug is boolean
            - verbose is boolean

        Ensures:
            - Analyzer initialized and ready to run analysis
            - Configuration loaded and validated
            - All components initialized

        Raises:
            - DirectoryAnalyzerError if initialization fails
        """
        self.debug   = debug
        self.verbose = verbose

        # Load configuration - use our own default config first, then merge with branch_analyzer config
        try:
            # Load branch_analyzer config for file_types and analysis settings
            branch_loader = ConfigLoader( config_path=config_path, debug=debug )
            branch_config = branch_loader.load()

            # Load our directory-specific config
            dir_config = self._load_directory_config()

            # Merge configs - directory config extends branch config
            self.config = self._merge_configs( branch_config, dir_config )

        except Exception as e:
            raise DirectoryAnalyzerError( f"Failed to load configuration: {e}" )

        # Initialize components
        self.file_classifier = FileTypeClassifier( self.config, debug=debug, verbose=verbose )
        self.line_classifier = LineClassifier( self.config, debug=debug, verbose=verbose )
        self.scanner         = DirectoryScanner( self.config, debug=debug, verbose=verbose )
        self.stats_collector = DirectoryStatisticsCollector( debug=debug, verbose=verbose )
        self.formatter       = DirectoryReportFormatter( self.config, debug=debug, verbose=verbose )

        if self.debug:
            print( "[DirectoryAnalyzer] Initialized" )

    def analyze( self, directory_path: str ) -> Dict[str, Any]:
        """
        Run complete analysis on a directory.

        Requires:
            - directory_path is valid directory path

        Ensures:
            - Returns complete statistics dict
            - Statistics include overall summary, breakdowns, language details

        Raises:
            - DirectoryAnalyzerError if analysis fails
        """
        if self.debug:
            print( f"[DirectoryAnalyzer] Starting analysis: {directory_path}" )

        try:
            # Reset statistics for new analysis
            self.stats_collector.reset()

            # Track state for each file (for multiline constructs)
            file_states = {}

            # Scan directory and process files
            file_count = 0
            for file_info in self.scanner.scan( directory_path ):
                file_count += 1

                # Classify file type
                file_type = self.file_classifier.classify( file_info.path )

                # Track this file
                self.stats_collector.record_file( file_type, file_info.path )

                # Process each line
                if self.line_classifier.supports_language( file_type ):
                    # Create state for this file
                    state = self.line_classifier.create_state( file_type )

                    for line in file_info.lines:
                        # Classify line
                        line_category, state = self.line_classifier.classify_line(
                            line,
                            file_type,
                            state
                        )

                        # Record line (skip blank lines unless configured to track)
                        if line_category is not None:
                            self.stats_collector.record_line(
                                file_type     = file_type,
                                line_category = line_category,
                                file_path     = file_info.path
                            )
                else:
                    # Non-analyzed language - just count lines
                    for line in file_info.lines:
                        if line.strip():  # Skip blank lines
                            self.stats_collector.record_line(
                                file_type = file_type,
                                file_path = file_info.path
                            )

                if self.verbose and file_count % 500 == 0:
                    print( f"[DirectoryAnalyzer] Processed {file_count} files..." )

            # Get summary statistics
            stats = self.stats_collector.get_summary()

            # Store scan stats for later use
            self._last_scan_stats = self.scanner.get_scan_stats()

            if self.debug:
                print( f"[DirectoryAnalyzer] Analysis complete: {stats['overall']['total_files']} files, {stats['overall']['total_lines']:,} lines" )

            return stats

        except Exception as e:
            raise DirectoryAnalyzerError( f"Analysis failed: {e}" )

    def format_results( self, stats: Dict[str, Any], directory_path: str,
                        format: str = 'console' ) -> str:
        """
        Format analysis results.

        Requires:
            - stats is dict from analyze()
            - directory_path is string path that was analyzed
            - format is one of: 'console', 'json', 'markdown'

        Ensures:
            - Returns formatted string ready for output
            - Format matches requested type

        Raises:
            - ValueError if format invalid
        """
        # Get scan stats if available
        scan_stats = getattr( self, '_last_scan_stats', None )

        if format == 'console':
            return self.formatter.format_console( stats, directory_path, scan_stats )
        elif format == 'json':
            return self.formatter.format_json( stats, directory_path, scan_stats )
        elif format == 'markdown':
            return self.formatter.format_markdown( stats, directory_path, scan_stats )
        else:
            raise ValueError( f"Invalid format: {format}. Must be 'console', 'json', or 'markdown'" )

    def get_scan_stats( self ) -> Dict[str, Any]:
        """
        Get scan statistics from last analysis.

        Ensures:
            - Returns dict with scan statistics
            - Returns empty dict if no analysis has been run

        Raises:
            - Never raises
        """
        return getattr( self, '_last_scan_stats', {} )

    def _load_directory_config( self ) -> Dict[str, Any]:
        """
        Load directory-specific configuration.

        Ensures:
            - Returns dict with directory configuration
            - Uses default config from package

        Raises:
            - ConfigurationError if config cannot be loaded
        """
        import yaml
        from pathlib import Path

        # Locate default config file (in same directory as this module)
        module_dir    = Path( __file__ ).parent
        default_path  = module_dir / 'default_config.yaml'

        if not default_path.exists():
            raise ConfigurationError(
                message     = "Default directory configuration file not found",
                config_path = str( default_path )
            )

        try:
            with open( default_path, 'r', encoding='utf-8' ) as f:
                config = yaml.safe_load( f )

            if config is None:
                config = {}

            return config

        except yaml.YAMLError as e:
            raise ConfigurationError(
                message     = f"Invalid YAML syntax: {e}",
                config_path = str( default_path )
            )

    def _merge_configs( self, base: Dict[str, Any], override: Dict[str, Any] ) -> Dict[str, Any]:
        """
        Recursively merge override config into base config.

        Override values take precedence. For nested dicts, performs deep merge.

        Requires:
            - base is dict
            - override is dict

        Ensures:
            - Returns merged configuration dict
            - Override values take precedence

        Raises:
            - Never raises
        """
        merged = base.copy()

        for key, override_value in override.items():
            if key in merged and isinstance( merged[key], dict ) and isinstance( override_value, dict ):
                # Recursively merge nested dicts
                merged[key] = self._merge_configs( merged[key], override_value )
            else:
                # Override with new value
                merged[key] = override_value

        return merged


def quick_smoke_test():
    """
    Quick smoke test for Directory Analyzer.

    Tests all major components:
    - Configuration loading
    - Directory scanning
    - File type classification
    - Line classification (Python/JavaScript)
    - Statistics collection
    - Report formatting (console/JSON/markdown)

    Requires:
        - cosa.utils.util available for print_banner
        - Current directory contains at least some files

    Ensures:
        - Tests complete with ✓ or ✗ indicators
        - Clear progress messages
        - Uses COSA print_banner formatting

    Raises:
        - Never raises (catches all exceptions)
    """
    import cosa.utils.util as du
    import tempfile
    import os

    du.print_banner( "Directory Analyzer Smoke Test", prepend_nl=True )

    try:
        # Test 1: Configuration loading
        print( "Testing configuration loading..." )
        analyzer = DirectoryAnalyzer( debug=False )
        assert analyzer.config is not None
        assert 'directory' in analyzer.config
        assert 'file_types' in analyzer.config
        print( "✓ Configuration loaded successfully" )

        # Test 2: Create temp directory with test files
        print( "Creating test directory..." )
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test files
            with open( os.path.join( tmpdir, 'test.py' ), 'w' ) as f:
                f.write( '# A comment\n' )
                f.write( 'def hello():\n' )
                f.write( '    """Docstring"""\n' )
                f.write( '    print("Hello")\n' )

            with open( os.path.join( tmpdir, 'test.js' ), 'w' ) as f:
                f.write( '// A comment\n' )
                f.write( 'function hello() {\n' )
                f.write( '    console.log("Hello");\n' )
                f.write( '}\n' )

            with open( os.path.join( tmpdir, 'README.md' ), 'w' ) as f:
                f.write( '# Test\n' )
                f.write( 'This is a test.\n' )

            print( "✓ Test files created" )

            # Test 3: Directory scanning
            print( "Testing directory scanning..." )
            stats = analyzer.analyze( tmpdir )
            assert stats is not None
            assert 'overall' in stats
            assert stats['overall']['total_files'] == 3
            print( f"✓ Directory scanned: {stats['overall']['total_files']} files, {stats['overall']['total_lines']} lines" )

            # Test 4: Check Python breakdown
            print( "Testing Python code/comment separation..." )
            assert 'language_details' in stats
            assert 'python' in stats['language_details']
            py_stats = stats['language_details']['python']
            assert py_stats['code'] > 0
            assert py_stats['comment'] > 0 or py_stats['docstring'] > 0
            print( f"✓ Python: {py_stats['code']} code, {py_stats['comment']} comment, {py_stats['docstring']} docstring" )

            # Test 5: Console formatting
            print( "Testing console formatting..." )
            console_output = analyzer.format_results( stats, tmpdir, format='console' )
            assert len( console_output ) > 0
            assert 'OVERALL SUMMARY' in console_output
            print( "✓ Console formatting working" )

            # Test 6: JSON formatting
            print( "Testing JSON formatting..." )
            json_output = analyzer.format_results( stats, tmpdir, format='json' )
            assert len( json_output ) > 0
            assert 'directory' in json_output
            print( "✓ JSON formatting working" )

            # Test 7: Markdown formatting
            print( "Testing Markdown formatting..." )
            markdown_output = analyzer.format_results( stats, tmpdir, format='markdown' )
            assert len( markdown_output ) > 0
            assert '# Directory Code Analysis' in markdown_output
            print( "✓ Markdown formatting working" )

            # Test 8: Scan stats
            print( "Testing scan statistics..." )
            scan_stats = analyzer.get_scan_stats()
            assert 'files_scanned' in scan_stats
            assert scan_stats['files_scanned'] == 3
            print( f"✓ Scan stats: {scan_stats['files_scanned']} files scanned" )

        # Test 9: Exception handling
        print( "Testing exception handling..." )
        try:
            analyzer.analyze( '/nonexistent/path/12345' )
            print( "✗ Should have raised exception" )
        except DirectoryAnalyzerError as e:
            print( "✓ DirectoryAnalyzerError raised correctly" )

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
