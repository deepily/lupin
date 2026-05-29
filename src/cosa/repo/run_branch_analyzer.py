#!/usr/bin/env python3
"""
Branch Analyzer - Command Line Interface

Professional command-line interface for analyzing git branch changes.
Uses argparse for robust argument parsing and provides clear help text.

Design Principles:
- Clear, helpful error messages
- Follows POSIX command-line conventions
- Exit codes: 0=success, 1=error, 2=invalid args
- Progress feedback for long operations
- Supports all output formats (console/JSON/markdown)
- Automatic HEAD resolution to actual branch names

Default Behavior:
    By default (no arguments), compares your current branch to main:
    - --repo-path defaults to . (current directory)
    - --base defaults to main (configurable via config file)
    - --head defaults to HEAD (auto-resolves to your current branch name)

Usage Examples:
    # Basic usage - compare current branch to main
    python -m cosa.repo.run_branch_analyzer

    # Analyze different repository (e.g., COSA from Lupin src)
    cd /path/to/lupin/src
    python -m cosa.repo.run_branch_analyzer --repo-path cosa

    # Compare specific branches
    python -m cosa.repo.run_branch_analyzer --base develop --head feature-branch

    # Custom config
    python -m cosa.repo.run_branch_analyzer --config my_config.yaml

    # JSON output
    python -m cosa.repo.run_branch_analyzer --output json > analysis.json

    # Save to file
    python -m cosa.repo.run_branch_analyzer --save-output report.txt

    # Verbose/debug modes
    python -m cosa.repo.run_branch_analyzer --verbose
    python -m cosa.repo.run_branch_analyzer --debug

Command Line Arguments:
    --repo-path PATH      Repository to analyze (default: . = current directory)
    --base BRANCH         Base branch - what you're comparing FROM (default: main)
    --head BRANCH         Head branch - what you're comparing TO (default: HEAD, auto-resolved)
    --config FILE         Configuration file path
    --output FORMAT       Output format: console, json, markdown (default: console)
    --save-output FILE    Save output to file instead of stdout
    --verbose, -v         Verbose output
    --debug, -d           Debug mode (shows branch resolution details)
    --help, -h            Show this help message

Understanding HEAD:
    When you use --head HEAD (the default), the tool automatically resolves it to your
    actual branch name. For example, if you're on "wip-feature-x", the output will show
    "wip-feature-x → main" (not "HEAD → main").
"""

import sys
import argparse

from cosa.repo.branch_analyzer import BranchChangeAnalyzer, BranchAnalyzerError


def create_parser() -> argparse.ArgumentParser:
    """
    Create command-line argument parser.

    Ensures:
        - Returns configured ArgumentParser
        - All arguments documented
        - Sensible defaults provided

    Raises:
        - Never raises
    """
    parser = argparse.ArgumentParser(
        prog        = 'branch_analyzer',
        description = 'Analyze git branch changes with categorization by file type and code vs comments',
        epilog      = 'For more information, see README-branch-analyzer.md',
        formatter_class = argparse.RawDescriptionHelpFormatter
    )

    # Repository path
    parser.add_argument(
        '--repo-path',
        type    = str,
        default = '.',
        metavar = 'PATH',
        help    = 'Path to git repository to analyze (default: . = current directory)'
    )

    # Branch arguments
    parser.add_argument(
        '--base',
        type    = str,
        default = None,
        metavar = 'BRANCH',
        help    = 'Base branch for comparison - what you are comparing FROM (default: main)'
    )

    parser.add_argument(
        '--head',
        type    = str,
        default = None,
        metavar = 'BRANCH',
        help    = 'Head branch for comparison - what you are comparing TO (default: HEAD = current branch, auto-resolved to actual name)'
    )

    # Configuration
    parser.add_argument(
        '--config',
        type    = str,
        default = None,
        metavar = 'FILE',
        help    = 'Configuration file path (default: embedded default_config.yaml)'
    )

    # Output format
    parser.add_argument(
        '--output',
        type    = str,
        choices = ['console', 'json', 'markdown'],
        default = None,
        metavar = 'FORMAT',
        help    = 'Output format: console, json, markdown (default: console from config)'
    )

    # Save output
    parser.add_argument(
        '--save-output',
        type    = str,
        default = None,
        metavar = 'FILE',
        help    = 'Save output to file instead of printing to stdout'
    )

    # Verbosity
    parser.add_argument(
        '--verbose', '-v',
        action  = 'store_true',
        help    = 'Verbose output (show progress and details)'
    )

    parser.add_argument(
        '--debug', '-d',
        action  = 'store_true',
        help    = 'Debug mode (show internal operations)'
    )

    return parser


def main() -> int:
    """
    Main entry point for CLI.

    Ensures:
        - Returns exit code (0=success, 1=error, 2=invalid args)
        - Errors printed to stderr
        - Results printed to stdout or file

    Raises:
        - Never raises (catches all exceptions)
    """
    # Parse arguments
    parser = create_parser()
    args   = parser.parse_args()

    try:
        # Initialize analyzer
        if args.verbose or args.debug:
            print( "[branch_analyzer] Initializing...", file=sys.stderr )

        analyzer = BranchChangeAnalyzer(
            config_path = args.config,
            base_branch = args.base,
            head_branch = args.head,
            repo_path   = args.repo_path,
            debug       = args.debug,
            verbose     = args.verbose
        )

        # Run analysis
        if args.verbose or args.debug:
            print( f"[branch_analyzer] Analyzing {analyzer.base_branch}...{analyzer.head_branch}", file=sys.stderr )

        stats = analyzer.analyze()

        # Determine output format
        output_format = args.output
        if not output_format:
            # Get default from config
            output_format = analyzer.config.get( 'output', {} ).get( 'default_format', 'console' )

        # Format results
        if args.verbose or args.debug:
            print( f"[branch_analyzer] Formatting as {output_format}", file=sys.stderr )

        output = analyzer.format_results( stats, format=output_format )

        # Output results
        if args.save_output:
            # Save to file
            output_path = Path( args.save_output )
            output_path.write_text( output, encoding='utf-8' )

            if args.verbose or args.debug:
                print( f"[branch_analyzer] Output saved to {output_path}", file=sys.stderr )
        else:
            # Print to stdout
            print( output )

        return 0

    except BranchAnalyzerError as e:
        # Known errors
        print( f"Error: {e}", file=sys.stderr )

        if args.debug and hasattr( e, 'context' ):
            print( f"Context: {e.context}", file=sys.stderr )

        return 1

    except KeyboardInterrupt:
        print( "\nInterrupted by user", file=sys.stderr )
        return 130  # Standard SIGINT exit code

    except Exception as e:
        # Unexpected errors
        print( f"Unexpected error: {e}", file=sys.stderr )

        if args.debug:
            import traceback
            traceback.print_exc( file=sys.stderr )

        return 1


if __name__ == '__main__':
    sys.exit( main() )
