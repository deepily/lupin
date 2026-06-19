"""
Git Diff Parser for Branch Analyzer

Safely executes git commands and parses diff output. Provides robust
error handling, timeout support, and structured diff line representation.

Design Principles:
- Never call subprocess without try/catch
- Always use timeout for git commands
- Provide clear error messages with recovery suggestions
- Return structured data (not raw strings)

Usage:
    from cosa.repo.branch_analyzer.git_diff_parser import GitDiffParser

    parser = GitDiffParser( config, debug=True )

    diff_lines = parser.get_diff( base='main', head='HEAD' )
    # Returns: List of DiffLine objects

    file_list = parser.get_changed_files( base='main', head='HEAD' )
    # Returns: List of changed file paths
"""

import subprocess
from dataclasses import dataclass
from typing import List, Optional

from .exceptions import GitCommandError


@dataclass
class DiffLine:
    """Represents a single line from git diff output."""
    content    : str            # Full line content
    operation  : str            # 'add', 'remove', 'context', 'meta'
    file_path  : Optional[str]  # Current file being diffed (None for meta lines)
    line_number: int            # Line number in diff output


class GitDiffParser:
    """
    Executes git commands and parses diff output safely.

    Handles subprocess errors, timeouts, and provides structured
    diff data for analysis.
    """

    def __init__( self, config: dict, repo_path: str = '.', debug: bool = False, verbose: bool = False ):
        """
        Initialize git diff parser.

        Requires:
            - config is dict with git settings
            - repo_path is valid directory path
            - debug is boolean
            - verbose is boolean

        Ensures:
            - Parser ready to execute git commands
            - Timeout and algorithm configured from config

        Raises:
            - GitCommandError if git not available
        """
        self.debug     = debug
        self.verbose   = verbose
        self.config    = config
        self.repo_path = repo_path

        # Get settings from config
        git_config      = config.get( 'git', {} )
        self.algorithm  = git_config.get( 'diff_algorithm', 'histogram' )
        self.extra_opts = git_config.get( 'extra_diff_options', [] )

        perf_config  = config.get( 'performance', {} )
        self.timeout = perf_config.get( 'git_timeout', 60 )

        # Verify git is available
        self._check_git_available()

        if self.debug:
            print( f"[GitDiffParser] Algorithm: {self.algorithm}, Timeout: {self.timeout}s" )
            print( f"[GitDiffParser] Repository: {self.repo_path}" )

    def get_diff( self, base: str, head: str ) -> List[DiffLine]:
        """
        Get diff between two git references.

        Requires:
            - base is valid git reference
            - head is valid git reference
            - Git repository exists in current directory

        Ensures:
            - Returns list of DiffLine objects
            - Each line tagged with operation and metadata

        Raises:
            - GitCommandError if git command fails
        """
        # Build git diff command
        command = [
            'git', 'diff',
            f'--diff-algorithm={self.algorithm}',
            f'{base}...{head}'
        ]
        command.extend( self.extra_opts )

        if self.debug:
            print( f"[GitDiffParser] Running: {' '.join(command)}" )

        # Execute command with error handling
        try:
            result = subprocess.run(
                command,
                capture_output = True,
                text           = True,
                timeout        = self.timeout,
                cwd            = self.repo_path
            )
        except subprocess.TimeoutExpired:
            raise GitCommandError(
                message     = f"Git diff timed out after {self.timeout} seconds",
                command     = command,
                return_code = -1
            )
        except FileNotFoundError:
            raise GitCommandError(
                message     = "Git command not found. Is git installed?",
                command     = command
            )
        except Exception as e:
            raise GitCommandError(
                message     = f"Failed to execute git diff: {e}",
                command     = command
            )

        # Check return code
        if result.returncode != 0:
            raise GitCommandError(
                message     = f"Git diff failed with return code {result.returncode}",
                command     = command,
                return_code = result.returncode,
                stderr      = result.stderr,
                stdout      = result.stdout
            )

        # Parse diff output into structured lines
        diff_lines = self._parse_diff_output( result.stdout )

        if self.debug:
            print( f"[GitDiffParser] Parsed {len(diff_lines)} diff lines" )

        return diff_lines

    def get_changed_files( self, base: str, head: str ) -> List[str]:
        """
        Get list of changed files.

        Requires:
            - base is valid git reference
            - head is valid git reference

        Ensures:
            - Returns list of file paths
            - Paths relative to repository root

        Raises:
            - GitCommandError if git command fails
        """
        command = ['git', 'diff', '--name-only', f'{base}...{head}']

        if self.debug:
            print( f"[GitDiffParser] Running: {' '.join(command)}" )

        try:
            result = subprocess.run(
                command,
                capture_output = True,
                text           = True,
                timeout        = self.timeout,
                cwd            = self.repo_path
            )
        except subprocess.TimeoutExpired:
            raise GitCommandError(
                message     = f"Git command timed out after {self.timeout} seconds",
                command     = command,
                return_code = -1
            )
        except Exception as e:
            raise GitCommandError(
                message     = f"Failed to execute git command: {e}",
                command     = command
            )

        if result.returncode != 0:
            raise GitCommandError(
                message     = "Failed to get changed files",
                command     = command,
                return_code = result.returncode,
                stderr      = result.stderr
            )

        files = [f.strip() for f in result.stdout.split( '\n' ) if f.strip()]
        return files

    def get_branch_name( self, ref: str ) -> str:
        """
        Resolve git reference to branch name.

        Requires:
            - ref is valid git reference (e.g., 'HEAD', 'main', 'feature-branch')

        Ensures:
            - Returns actual branch name
            - Returns ref itself if cannot be resolved

        Raises:
            - Never raises (returns ref on error)
        """
        # Try to resolve symbolic ref (e.g., HEAD -> actual branch name)
        try:
            result = subprocess.run(
                ['git', 'rev-parse', '--abbrev-ref', ref],
                capture_output = True,
                text           = True,
                timeout        = 5,
                cwd            = self.repo_path
            )

            if result.returncode == 0:
                branch_name = result.stdout.strip()
                if branch_name and branch_name != 'HEAD':
                    return branch_name
        except Exception:
            pass

        # If that didn't work, return the original ref
        return ref

    def _check_git_available( self ) -> None:
        """Verify git is available."""
        try:
            result = subprocess.run(
                ['git', '--version'],
                capture_output = True,
                text           = True,
                timeout        = 5,
                cwd            = self.repo_path
            )
            if result.returncode != 0:
                raise GitCommandError(
                    message = "Git command returned error",
                    command = ['git', '--version']
                )
        except FileNotFoundError:
            raise GitCommandError(
                message = "Git not found. Please install git.",
                command = ['git', '--version']
            )
        except Exception as e:
            raise GitCommandError(
                message = f"Failed to verify git availability: {e}",
                command = ['git', '--version']
            )

    def _parse_diff_output( self, output: str ) -> List[DiffLine]:
        """Parse git diff output into structured lines."""
        lines = output.split( '\n' )
        diff_lines = []
        current_file = None

        for i, line in enumerate( lines ):
            # Track current file
            if line.startswith( 'diff --git' ):
                parts = line.split()
                if len( parts ) >= 4:
                    current_file = parts[3].lstrip( 'b/' )

            # Determine operation
            operation = self._classify_diff_line( line )

            diff_lines.append( DiffLine(
                content     = line,
                operation   = operation,
                file_path   = current_file,
                line_number = i + 1
            ) )

        return diff_lines

    def _classify_diff_line( self, line: str ) -> str:
        """Classify diff line by operation."""
        if not line:
            return 'context'
        elif line.startswith( '+' ) and not line.startswith( '+++' ):
            return 'add'
        elif line.startswith( '-' ) and not line.startswith( '---' ):
            return 'remove'
        elif line.startswith( ('diff ', 'index ', '--- ', '+++ ', '@@ ', 'Binary ') ):
            return 'meta'
        else:
            return 'context'
