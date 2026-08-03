"""
Git Log Parser — yields per-file LoC changes from `git log --numstat`.

Shells out to `git log --numstat --pretty=format:COMMIT|<sha>|<date>|<author>`
and walks the line stream, yielding one `FileChange` dict per non-binary
file row. Binary rows (`-\t-\tpath`) are skipped.

Subprocess pattern mirrors `cosa/repo/branch_analyzer/git_diff_parser.py:115-150`
(capture_output, text, timeout, GitCommandError translation).

Output schema (one dict per yielded row):
    {
        "date":     "2026-05-16",
        "sha":      "abc1234...",
        "author":   "rick@example.com",
        "path":     "src/cosa/repo/foo.py",
        "added":    128,
        "deleted":   42,
    }

Usage:
    parser = GitLogParser( repo_path=".", since="2026-05-15", until="now",
                           include_merges=False, author=None,
                           timeout=60, debug=False, verbose=False )
    for change in parser.iter_changes():
        print( change )
"""

import subprocess
from typing import Iterator, List, Optional

from .date_bounds import normalize_since, normalize_until

from .exceptions import GitCommandError


class GitLogParser:
    """
    Walks `git log --numstat` output and yields per-file LoC changes.

    Binary files (numstat rows starting with `-\t-\t`) are skipped silently.
    Merge commits are excluded by default (controlled by `include_merges`).
    """

    def __init__(
        self,
        repo_path:      str           = ".",
        since:          Optional[str] = None,
        until:          Optional[str] = None,
        rev_range:      Optional[str] = None,
        all_branches:   bool          = False,
        include_merges: bool          = False,
        author:         Optional[str] = None,
        timeout:        int           = 60,
        debug:          bool          = False,
        verbose:        bool          = False,
    ):
        """
        Initialize git-log parser.

        Requires:
            - repo_path is a string pointing at a directory (validated by git)
            - since / until are ISO date strings or None
            - rev_range is a git rev-spec like "main..HEAD" or None
            - all_branches and rev_range are mutually exclusive in practice: a
              rev-range already names its endpoints, so `--branches` alongside it
              would widen the walk past the range the caller asked for. The
              analyzer never sets both; this class does not police it.
            - timeout is a positive integer

        Ensures:
            - Parser ready to call iter_changes()
            - Date range and rev_range can coexist; both are passed to git log
            - all_branches=True walks the union of ALL local branch refs
              (--branches), de-duplicated by git's DAG walk — each commit is
              emitted exactly once even when reachable from several branches
        """
        self.repo_path      = repo_path
        self.since          = since
        self.until          = until
        self.rev_range      = rev_range
        self.all_branches   = all_branches
        self.include_merges = include_merges
        self.author         = author
        self.timeout        = timeout
        self.debug          = debug
        self.verbose        = verbose

    def _build_command( self ) -> List[str]:
        """
        Build the `git log --numstat ...` command list.

        Ensures:
            - Returns a list of command tokens ready for subprocess.run
            - Always uses --date=short for stable ISO date parsing
            - Custom --pretty marker COMMIT|<sha>|<cd>|<aE>| distinguishes commit rows
            - all_branches appends `--branches` (union of local branch refs)

        Date basis (load-bearing — 2026-07-13, bug 37a8beeb):
            The date field is `%cd` (COMMITTER date), NOT `%ad` (author date),
            because `git log --since/--until` filters on the COMMITTER date. Using
            author date to label a row that a committer-date filter selected lets a
            rebased or cherry-picked commit land in a day-bucket outside the very
            window that selected it — and would make the coverage guard false-warn.
            The filter basis and the bucket basis MUST be the same field.
        """
        cmd = [
            "git", "log",
            "--numstat",
            "--date=short",
            "--pretty=format:COMMIT|%H|%cd|%aE",
        ]
        if not self.include_merges:
            cmd.append( "--no-merges" )
        # Bare ISO dates are pinned to day boundaries here, NOT at the caller —
        # coverage_guard mirrors these flags and must normalize identically or
        # its cross-check compares two different questions (row d0b3cd84).
        if self.since: cmd.append( f"--since={normalize_since( self.since )}" )
        if self.until: cmd.append( f"--until={normalize_until( self.until )}" )
        if self.author: cmd.append( f"--author={self.author}" )
        if self.all_branches:
            cmd.append( "--branches" )
        if self.rev_range:
            cmd.append( self.rev_range )
        return cmd

    def _run( self ) -> str:
        """
        Execute the git log command and return stdout.

        Ensures:
            - Returns stdout on success
            - Raises GitCommandError on any failure (timeout, missing git,
              non-zero return code, generic OSError)
        """
        command = self._build_command()
        if self.debug:
            print( f"[GitLogParser] Running: {' '.join(command)}" )

        try:
            result = subprocess.run(
                command,
                capture_output = True,
                text           = True,
                timeout        = self.timeout,
                cwd            = self.repo_path,
            )
        except subprocess.TimeoutExpired:
            raise GitCommandError(
                message     = f"Git log timed out after {self.timeout} seconds",
                command     = command,
                return_code = -1,
            )
        except FileNotFoundError:
            raise GitCommandError(
                message = "Git command not found. Is git installed?",
                command = command,
            )
        except Exception as e:
            raise GitCommandError(
                message = f"Failed to execute git log: {e}",
                command = command,
            )

        if result.returncode != 0:
            raise GitCommandError(
                message     = f"Git log failed with return code {result.returncode}",
                command     = command,
                return_code = result.returncode,
                stderr      = result.stderr,
                stdout      = result.stdout,
            )

        return result.stdout

    def iter_changes( self ) -> Iterator[dict]:
        """
        Yield one dict per non-binary file row in the git log output.

        Requires:
            - Git is installed and repo_path is a valid git repository

        Ensures:
            - Each yielded dict has keys: date, sha, author, path, added, deleted
            - Binary rows (`-\t-\t...`) are silently skipped
            - Empty or whitespace-only lines are skipped
            - Commits with zero non-binary file rows yield nothing
              (they don't contribute to the LoC totals)

        Raises:
            - GitCommandError if the underlying git invocation fails
        """
        stdout = self._run()

        current_sha    = None
        current_date   = None
        current_author = None
        yielded        = 0

        for raw in stdout.splitlines():
            line = raw.rstrip()
            if not line: continue

            if line.startswith( "COMMIT|" ):
                # Header row: COMMIT|<sha>|<date>|<author>
                parts = line.split( "|", 3 )
                if len( parts ) != 4:
                    if self.debug: print( f"[GitLogParser] Skipping malformed commit header: {line!r}" )
                    continue
                _, current_sha, current_date, current_author = parts
                continue

            # File row: <added>\t<deleted>\t<path>
            parts = line.split( "\t", 2 )
            if len( parts ) != 3:
                if self.debug: print( f"[GitLogParser] Skipping malformed file row: {line!r}" )
                continue

            added_s, deleted_s, path = parts
            if added_s == "-" or deleted_s == "-":
                # Binary file — git emits dashes instead of counts.
                if self.verbose: print( f"[GitLogParser] Skipping binary file: {path}" )
                continue

            try:
                added   = int( added_s )
                deleted = int( deleted_s )
            except ValueError:
                if self.debug: print( f"[GitLogParser] Non-integer counts on row: {line!r}" )
                continue

            if current_sha is None:
                # File row before any COMMIT header — malformed output, skip.
                if self.debug: print( f"[GitLogParser] Orphan file row (no commit header): {line!r}" )
                continue

            yield {
                "date":    current_date,
                "sha":     current_sha,
                "author":  current_author,
                "path":    path,
                "added":   added,
                "deleted": deleted,
            }
            yielded += 1

        if self.verbose:
            print( f"[GitLogParser] Yielded {yielded} file change rows" )
