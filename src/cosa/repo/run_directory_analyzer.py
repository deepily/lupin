#!/usr/bin/env python3
"""
Directory Analyzer - Command Line Interface

Professional command-line interface for analyzing directory contents and
counting lines of code by file type.

Design Principles:
- Clear, helpful error messages
- Follows POSIX command-line conventions
- Exit codes: 0=success, 1=error, 2=invalid args
- Progress feedback for long operations
- Supports all output formats (console/JSON/markdown)

Default Behavior:
    By default (no arguments), analyzes the current directory:
    - --path defaults to . (current directory)
    - Excludes common directories (.git, __pycache__, node_modules, etc.)
    - Skips binary files automatically

Usage Examples:
    # Basic usage - analyze current directory
    python -m cosa.repo.run_directory_analyzer

    # Analyze specific directory
    python -m cosa.repo.run_directory_analyzer --path /path/to/project

    # Analyze COSA directory from Lupin src
    cd /path/to/lupin/src
    python -m cosa.repo.run_directory_analyzer --path cosa

    # JSON output
    python -m cosa.repo.run_directory_analyzer --output json > analysis.json

    # Save to file
    python -m cosa.repo.run_directory_analyzer --save-output report.txt

    # Verbose/debug modes
    python -m cosa.repo.run_directory_analyzer --verbose
    python -m cosa.repo.run_directory_analyzer --debug

Command Line Arguments:
    --path PATH           Directory to analyze (default: . = current directory)
    --config FILE         Configuration file path (default: embedded default_config.yaml)
    --output FORMAT       Output format: console, json, markdown (default: console)
    --save-output FILE    Save output to file instead of stdout
    --verbose, -v         Verbose output (show progress)
    --debug, -d           Debug mode (show internal operations)
    --help, -h            Show this help message
"""

import sys
import argparse
from pathlib import Path

from cosa.repo.directory_analyzer import DirectoryAnalyzer, DirectoryAnalyzerError


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
        prog        = 'directory_analyzer',
        description = 'Analyze directory contents - count lines of code by file type with code vs comment separation',
        epilog      = 'Example: python -m cosa.repo.run_directory_analyzer --path /path/to/project',
        formatter_class = argparse.RawDescriptionHelpFormatter
    )

    # Directory path
    parser.add_argument(
        '--path',
        type    = str,
        default = '.',
        metavar = 'PATH',
        help    = 'Directory to analyze (default: . = current directory)'
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
        default = 'console',
        metavar = 'FORMAT',
        help    = 'Output format: console, json, markdown (default: console)'
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
        help    = 'Verbose output (show progress)'
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
            print( "[directory_analyzer] Initializing...", file=sys.stderr )

        analyzer = DirectoryAnalyzer(
            config_path = args.config,
            debug       = args.debug,
            verbose     = args.verbose
        )

        # Run analysis
        if args.verbose or args.debug:
            print( f"[directory_analyzer] Analyzing: {args.path}", file=sys.stderr )

        stats = analyzer.analyze( args.path )

        # Format results
        if args.verbose or args.debug:
            print( f"[directory_analyzer] Formatting as {args.output}", file=sys.stderr )

        output = analyzer.format_results( stats, args.path, format=args.output )

        # Output results
        if args.save_output:
            # Save to file
            output_path = Path( args.save_output )
            output_path.write_text( output, encoding='utf-8' )

            if args.verbose or args.debug:
                print( f"[directory_analyzer] Output saved to {output_path}", file=sys.stderr )
        else:
            # Print to stdout
            print( output )

        return 0

    except DirectoryAnalyzerError as e:
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
