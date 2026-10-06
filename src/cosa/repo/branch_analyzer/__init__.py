"""
Branch Analyzer Package

A git branch comparison and analysis tool for the COSA framework.

Analyzes git diffs between any two branches, categorizes changes by file type (Python, JavaScript,
TypeScript, etc.) and separates code from comments/docstrings for Python and JavaScript.
HEAD resolves automatically to the actual branch name. Configuration comes from YAML files
(no ConfigurationManager dependency). Output formats are console, JSON and markdown, with a clear
comparison context (repository, branches, direction). Errors use custom exceptions. All functions carry
Design by Contract documentation per COSA framework standards.

Default Behavior:
    Compares your current branch (HEAD) to main: repo_path '.', base_branch 'main' (configurable), head_branch 'HEAD'.

Main Classes:
- BranchChangeAnalyzer: Main orchestrator for analysis workflow
- GitDiffParser: Handles git subprocess operations safely (includes branch name resolution)
- FileTypeClassifier: Configurable file type detection
- LineClassifier: Code vs comment detection for multiple languages
- StatisticsCollector: Aggregates and computes statistics
- ReportFormatter: Formats output in multiple formats (includes comparison context)
- ConfigLoader: Loads and validates YAML configuration

Programmatic Usage, current branch vs main, then another repository with explicit branches (format is 'console', 'json' or 'markdown'):
    Example:
        from cosa.repo.branch_analyzer import BranchChangeAnalyzer
        analyzer = BranchChangeAnalyzer()
        results  = analyzer.analyze()
        print( analyzer.format_results( results, format='console' ) )
        analyzer = BranchChangeAnalyzer( repo_path='cosa', base_branch='main', head_branch='HEAD', debug=True )

Command Line, run from the src directory:
    Example:
        python -m cosa.repo.run_branch_analyzer                  # Current directory, HEAD -> main
        python -m cosa.repo.run_branch_analyzer --repo-path cosa # Analyze COSA repo from Lupin src
        python -m cosa.repo.run_branch_analyzer --base main --head feature-branch
        python -m cosa.repo.run_branch_analyzer --output json --config my_config.yaml --verbose

Author: COSA Framework Team, Version: 1.0.0
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
