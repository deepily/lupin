"""
Branch Analyzer Package

A professional git branch comparison and analysis tool for COSA framework.

This package provides comprehensive analysis of git branch changes, categorizing
modifications by file type and separating code from documentation. Designed to
meet COSA framework standards with proper error handling, configuration management,
and multiple output formats.

Key Features:
- Analyzes git diffs between any two branches
- Automatic HEAD resolution to actual branch names
- Categorizes changes by file type (Python, JavaScript, TypeScript, etc.)
- Separates code from comments/docstrings for Python and JavaScript
- Configurable via YAML files (no ConfigurationManager dependency)
- Multiple output formats: console, JSON, markdown
- Clear comparison context (repository, branches, direction)
- Comprehensive error handling with custom exceptions
- Full Design by Contract documentation
- COSA framework standards compliant

Default Behavior:
    By default, compares your current branch (HEAD) to main:
    - repo_path defaults to '.' (current directory)
    - base_branch defaults to 'main' (configurable)
    - head_branch defaults to 'HEAD' (auto-resolves to actual branch name)

Main Classes:
- BranchChangeAnalyzer: Main orchestrator for analysis workflow
- GitDiffParser: Handles git subprocess operations safely (includes branch name resolution)
- FileTypeClassifier: Configurable file type detection
- LineClassifier: Code vs comment detection for multiple languages
- StatisticsCollector: Aggregates and computes statistics
- ReportFormatter: Formats output in multiple formats (includes comparison context)
- ConfigLoader: Loads and validates YAML configuration

Programmatic Usage:
    from cosa.repo.branch_analyzer import BranchChangeAnalyzer

    # Simple usage - compare current branch to main
    analyzer = BranchChangeAnalyzer()
    results = analyzer.analyze()
    print( analyzer.format_results( results, format='console' ) )

    # Advanced usage - analyze different repository
    analyzer = BranchChangeAnalyzer(
        repo_path   = 'cosa',           # Analyze COSA repo
        base_branch = 'main',           # Compare from main
        head_branch = 'HEAD',           # To current branch (auto-resolved)
        debug       = True,
        verbose     = True
    )

    results = analyzer.analyze()
    console_output  = analyzer.format_results( results, format='console' )
    json_output     = analyzer.format_results( results, format='json' )
    markdown_output = analyzer.format_results( results, format='markdown' )

Command Line:
    # From src directory
    cd /path/to/lupin/src

    # Basic usage (current directory, HEAD → main)
    python -m cosa.repo.run_branch_analyzer

    # Analyze COSA repo from Lupin src
    python -m cosa.repo.run_branch_analyzer --repo-path cosa

    # Compare specific branches
    python -m cosa.repo.run_branch_analyzer --base main --head feature-branch

    # Output formats
    python -m cosa.repo.run_branch_analyzer --output json
    python -m cosa.repo.run_branch_analyzer --config my_config.yaml --verbose

Author: COSA Framework Team
Version: 1.0.0
"""

from .analyzer import BranchChangeAnalyzer
from .exceptions import (
    BranchAnalyzerError,
    GitCommandError,
    ConfigurationError,
    ParserError
)

__version__ = '1.0.0'
__all__     = [
    'BranchChangeAnalyzer',
    'BranchAnalyzerError',
    'GitCommandError',
    'ConfigurationError',
    'ParserError',
]
