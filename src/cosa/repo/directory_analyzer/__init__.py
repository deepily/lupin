"""
Directory Analyzer Package

A professional directory analysis tool for COSA framework that counts lines of code
across directory trees, categorizing by file type and separating code from documentation.

This package provides comprehensive analysis of directory contents, counting total lines
regardless of git repository boundaries. Designed to meet COSA framework standards with
proper error handling, configuration management, and multiple output formats.

Key Features:
- Analyzes all files in a directory tree
- Categorizes by file type (Python, JavaScript, TypeScript, etc.)
- Separates code from comments/docstrings for Python and JavaScript
- Configurable exclusions (directories, file patterns)
- Handles encoding issues gracefully
- Multiple output formats: console, JSON, markdown
- Reuses classifiers from branch_analyzer package
- Full Design by Contract documentation
- COSA framework standards compliant

Main Classes:
- DirectoryAnalyzer: Main orchestrator for analysis workflow
- DirectoryScanner: Walks filesystem, handles exclusions
- DirectoryStatisticsCollector: Aggregates statistics
- DirectoryReportFormatter: Formats output in multiple formats

Programmatic Usage:
    from cosa.repo.directory_analyzer import DirectoryAnalyzer

    # Simple usage - analyze a directory
    analyzer = DirectoryAnalyzer()
    results = analyzer.analyze( '/path/to/project' )
    print( analyzer.format_results( results, '/path/to/project' ) )

    # Advanced usage
    analyzer = DirectoryAnalyzer(
        config_path = 'my_config.yaml',
        debug       = True,
        verbose     = True
    )

    results = analyzer.analyze( '/path/to/project' )
    console_output  = analyzer.format_results( results, '/path/to/project', format='console' )
    json_output     = analyzer.format_results( results, '/path/to/project', format='json' )
    markdown_output = analyzer.format_results( results, '/path/to/project', format='markdown' )

Command Line:
    # From src directory
    cd /path/to/lupin/src

    # Basic usage (analyze current directory)
    python -m cosa.repo.run_directory_analyzer --path .

    # Analyze specific directory
    python -m cosa.repo.run_directory_analyzer --path /path/to/project

    # Output formats
    python -m cosa.repo.run_directory_analyzer --path . --output json
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
