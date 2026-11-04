"""
Directory Analyzer Package

A directory analysis tool for the COSA framework that counts lines of code across directory trees.
It categorizes by file type and separates code from documentation, regardless of git boundaries.
It follows COSA standards: error handling, configuration management, Design by Contract docs.

Key Features:
- Analyzes all files in a directory tree, categorized by file type (Python, JavaScript, TypeScript, etc.)
- Separates code from comments/docstrings for Python and JavaScript
- Configurable exclusions (directories, file patterns)
- Handles encoding issues gracefully
- Multiple output formats: console, JSON, markdown
- Reuses classifiers from branch_analyzer package

Main Classes:
- DirectoryAnalyzer: Main orchestrator for analysis workflow
- DirectoryScanner: Walks filesystem, handles exclusions
- DirectoryStatisticsCollector: Aggregates statistics
- DirectoryReportFormatter: Formats output in multiple formats

Programmatic Usage:
    from cosa.repo.directory_analyzer import DirectoryAnalyzer

    # Simple usage - analyze a directory
    analyzer = DirectoryAnalyzer()
    results  = analyzer.analyze( '/path/to/project' )
    print( analyzer.format_results( results, '/path/to/project' ) )

    # Advanced usage - format is console, json or markdown
    analyzer = DirectoryAnalyzer( config_path='my_config.yaml', debug=True, verbose=True )
    json_output = analyzer.format_results( results, '/path/to/project', format='json' )

Command Line (from the src directory):
    python -m cosa.repo.run_directory_analyzer --path .
    python -m cosa.repo.run_directory_analyzer --path /path/to/project --output json
    python -m cosa.repo.run_directory_analyzer --path . --verbose

Author: COSA Framework Team
Version: 1.0.0
"""

from .analyzer import DirectoryAnalyzer
from .directory_scanner import DirectoryScanner, FileInfo
from .exceptions import (
    DirectoryAnalyzerError,
    ScannerError,
    ConfigurationError,
    FileReadError
)

__version__ = '1.0.0'
__all__     = [
    'DirectoryAnalyzer',
    'DirectoryScanner',
    'FileInfo',
    'DirectoryAnalyzerError',
    'ScannerError',
    'ConfigurationError',
    'FileReadError',
]
