"""
GitLogLocDeltaAnalyzer — orchestrator for the Daily LoC Delta tool.

Wires together the parser, aggregator, and formatters. Resolves date ranges
from the CLI flags (--today / --since / --until / --branch / --base) into
concrete `since` / `until` / `rev_range` arguments for `GitLogParser`.

Reuse map references (verified during REUSE pre-pass):
- Subprocess pattern: `cosa/repo/branch_analyzer/git_diff_parser.py:115-150`
- CLI scaffolding shape: `cosa/repo/run_branch_analyzer.py:69-156`
- quick_smoke_test() template: `cosa/repo/branch_analyzer/analyzer.py:279-407`
- get_project_root(): `cosa/utils/util.py:626`

Usage:
    from cosa.repo.git_loc_delta.analyzer import GitLogLocDeltaAnalyzer

    analyzer = GitLogLocDeltaAnalyzer(
        repo_path      = ".",
        mode           = "today",       # or "branch", or "explicit"
        branch         = None,           # only when mode="branch"
        base           = "main",
        since          = None,           # only when mode="explicit"
        until          = None,
        include_merges = False,
        author         = None,
        debug          = False,
        verbose        = False,
    )

    result = analyzer.analyze()
    # result is a dict with keys: since, until, branch, rev_range, repo_path,
    #                              summary, daily, by_type
"""

import subprocess
from datetime import date as _date
from typing import Optional

import cosa.utils.util as du

from .coverage_guard   import reconcile_coverage
from .daily_aggregator import DailyAggregator
from .exceptions       import DateRangeError, GitCommandError
from .git_log_parser   import GitLogParser


class GitLogLocDeltaAnalyzer:
    """
    Orchestrates parse → aggregate → format for the Daily LoC Delta tool.
    """

    def __init__(
        self,
        repo_path:      str           = ".",
        mode:           str           = "today",
        branch:         Optional[str] = None,
        base:           str           = "main",
        since:          Optional[str] = None,
        until:          Optional[str] = None,
        all_branches:   bool          = False,
        include_merges: bool          = False,
        author:         Optional[str] = None,
        repo_name:      Optional[str] = None,
        timeout:        int           = 60,
        debug:          bool          = False,
        verbose:        bool          = False,
    ):
        """
        Initialize the analyzer.

        Requires:
            - mode is one of: "today", "branch", "explicit"
            - When mode="explicit", at least one of `since` / `until` is set
            - When mode="branch", `base` is a valid ref (default "main"); `branch`
              defaults to the current HEAD if None
            - all_branches is NOT valid in "branch" mode — a branch delta names its
              own endpoints, so widening the walk to every local ref would answer a
              different question than the one asked. Raises ValueError.
            - repo_path is a valid directory
            - repo_name is the explicit repo identity (added 2026-05-21 schema v2);
              None is allowed for backward compatibility but callers writing CSVs
              should always pass it. CLI resolves the default in
              `run_git_loc_delta._resolve_repo_name`

        Ensures:
            - All flags captured for analyze() to consume
            - analyze() result dict carries `repo_name` (may be None if not set)

        The two questions this tool answers (2026-07-13, bugs bbff93a3 / 37a8beeb):

            "What work happened in window W?"      → date-windowed + all_branches=True
            "How far ahead is this branch?"        → mode="branch" (main..<branch>)

            These coincide ONLY when all work sits on the WIP branch, and they diverge
            silently otherwise — a commit that landed on `main` sits on the BASELINE
            side of `main..<branch>` and is uncountable by it, forever. The roll-up
            asks the FIRST question; for weeks it was being answered with the second.
            Do not let these two drift back together.

        Raises:
            - ValueError on an invalid mode, or all_branches in branch mode
        """
        if mode not in ( "today", "branch", "explicit" ):
            raise ValueError( f"Invalid mode: {mode!r} (must be 'today', 'branch', or 'explicit')" )

        if all_branches and mode == "branch":
            raise ValueError(
                "all_branches is not valid in 'branch' mode: a branch delta (base..branch) "
                "already names its endpoints, and --branches would widen the walk past them. "
                "Use mode='explicit' (or 'today') with all_branches=True to ask "
                "'what work happened in this window'."
            )

        self.repo_path      = repo_path
        self.mode           = mode
        self.branch         = branch
        self.base           = base
        self.since          = since
        self.until          = until
        self.all_branches   = all_branches
        self.include_merges = include_merges
        self.author         = author
        self.repo_name      = repo_name
        self.timeout        = timeout
        self.debug          = debug
        self.verbose        = verbose

    def _resolve_range( self ):
        """
        Resolve mode flags into (since, until, rev_range, resolved_branch) for the parser.

        Ensures:
            - `since` and `until` are ISO-date strings or None
            - `rev_range` is a git rev-spec like "main..HEAD" or None
            - `resolved_branch` is the actual branch name for header display, or None

        Raises:
            - DateRangeError on invalid combinations (e.g. since > until, --branch
              on the base branch itself producing an empty range)
        """
        if self.mode == "explicit":
            since = self.since
            until = self.until
            if since and until and since > until:
                raise DateRangeError(
                    message = f"--since ({since}) is after --until ({until})",
                    since   = since,
                    until   = until,
                )
            return ( since, until, None, None )

        if self.mode == "today":
            today_str = _date.today().isoformat()
            return ( today_str, None, None, None )

        # mode == "branch"
        resolved_branch = self.branch
        if resolved_branch is None:
            # Resolve current branch name from `git rev-parse --abbrev-ref HEAD`
            try:
                result = subprocess.run(
                    [ "git", "rev-parse", "--abbrev-ref", "HEAD" ],
                    capture_output = True,
                    text           = True,
                    timeout        = 10,
                    cwd            = self.repo_path,
                )
                if result.returncode != 0:
                    raise GitCommandError(
                        message     = "Could not resolve current branch name",
                        command     = [ "git", "rev-parse", "--abbrev-ref", "HEAD" ],
                        return_code = result.returncode,
                        stderr      = result.stderr,
                    )
                resolved_branch = result.stdout.strip()
            except subprocess.TimeoutExpired:
                raise GitCommandError(
                    message = "git rev-parse --abbrev-ref HEAD timed out",
                    command = [ "git", "rev-parse", "--abbrev-ref", "HEAD" ],
                )

        if resolved_branch == self.base:
            raise DateRangeError(
                message = (
                    f"--branch resolves to '{resolved_branch}' which is the same as --base '{self.base}'. "
                    "Empty rev-range; nothing to analyze."
                ),
                branch  = resolved_branch,
            )

        # Use three-dot is NOT what we want — that's branch_analyzer's territory.
        # Two-dot rev-range gives us commits on `branch` not yet on `base`, which is
        # what `git log A..B` does.
        rev_range = f"{self.base}..{resolved_branch}"
        return ( None, None, rev_range, resolved_branch )

    def analyze( self, reconcile: bool = False ) -> dict:
        """
        Run the full parse → aggregate pipeline and return the analysis dict.

        Requires:
            - reconcile=True additionally runs the coverage guard, which costs one
              extra `git rev-list` invocation per call

        Ensures:
            - Returns a dict with keys: since, until, branch, rev_range, all_branches,
              repo_path, repo_name, summary, daily, by_type, shas
            - `shas` is the set of UNIQUE commit SHAs counted — the only honest basis
              for a commit count (see DailyAggregator.all_shas)
            - `coverage` is present iff reconcile=True; it carries the guard's report
              and its `warning` is the caller's to surface (this method does not print)

        Raises:
            - GitCommandError if any underlying git invocation fails
            - DateRangeError if the resolved date/branch range is invalid
        """
        since, until, rev_range, resolved_branch = self._resolve_range()

        if self.debug:
            print(
                f"[GitLogLocDeltaAnalyzer] mode={self.mode} since={since} until={until} "
                f"rev_range={rev_range} branch={resolved_branch} all_branches={self.all_branches}"
            )

        parser = GitLogParser(
            repo_path      = self.repo_path,
            since          = since,
            until          = until,
            rev_range      = rev_range,
            all_branches   = self.all_branches,
            include_merges = self.include_merges,
            author         = self.author,
            timeout        = self.timeout,
            debug          = self.debug,
            verbose        = self.verbose,
        )

        agg = DailyAggregator( debug=self.debug, verbose=self.verbose )
        for change in parser.iter_changes():
            agg.record( change )

        result = {
            "since":        since,
            "until":        until,
            "branch":       resolved_branch,
            "rev_range":    rev_range,
            "all_branches": self.all_branches,
            "repo_path":    self.repo_path,
            "repo_name":    self.repo_name,
            "summary":      agg.summary(),
            "daily":        agg.daily(),
            "by_type":      agg.by_type(),
            "shas":         agg.all_shas(),
        }

        if reconcile:
            result[ "coverage" ] = reconcile_coverage(
                repo_path      = self.repo_path,
                counted_shas   = result[ "shas" ],
                since          = since,
                until          = until,
                rev_range      = rev_range,
                all_branches   = self.all_branches,
                include_merges = self.include_merges,
                repo_name      = self.repo_name,
                timeout        = self.timeout,
                debug          = self.debug,
            )

        return result


def quick_smoke_test():
    """
    Quick smoke test for Git LoC Delta.

    Tests the full parse → aggregate → format chain by running over the
    current repo for the last 7 days. Validates dict shape, not exact
    counts (counts vary per-run).

    Requires:
        - Run from a git repository (uses cwd)
        - cosa.utils.util available for print_banner

    Ensures:
        - Tests complete with ✓ or ✗ indicators
        - Uses COSA print_banner formatting
        - Does NOT raise (catches all exceptions)
    """
    from datetime import date, timedelta

    du.print_banner( "Git LoC Delta Smoke Test", prepend_nl=True )

    try:
        # Test 1: Today-mode construction
        print( "Testing today-mode analyzer construction..." )
        analyzer = GitLogLocDeltaAnalyzer( mode="today", debug=False )
        assert analyzer.mode == "today"
        print( "✓ Today-mode analyzer constructed" )

        # Test 2: Date-range resolution
        print( "Testing date-range resolution..." )
        since, until, rev_range, branch = analyzer._resolve_range()
        assert since is not None
        assert rev_range is None
        print( f"✓ Today resolves to since={since}" )

        # Test 3: Explicit-range mode with 7-day window
        print( "Testing explicit 7-day range analysis..." )
        seven_days_ago = ( date.today() - timedelta( days=7 ) ).isoformat()
        analyzer = GitLogLocDeltaAnalyzer(
            mode  = "explicit",
            since = seven_days_ago,
            debug = False,
        )
        result = analyzer.analyze()
        assert "summary" in result
        assert "daily" in result
        assert "by_type" in result
        assert isinstance( result["summary"]["total_added"],   int )
        assert isinstance( result["summary"]["total_deleted"], int )
        print( f"✓ 7-day analysis returned {result['summary']['total_commits']} commits, "
               f"{result['summary']['total_added']} added, {result['summary']['total_deleted']} deleted" )

        # Test 4: Console formatting on real result
        print( "Testing console formatting..." )
        from .report_formatter import format_console
        text = format_console(
            daily   = result["daily"],
            summary = result["summary"],
            since   = result["since"],
        )
        assert len( text ) > 0
        assert "Daily LoC Delta" in text
        print( "✓ Console formatting produced output" )

        # Test 5: JSON formatting on real result
        print( "Testing JSON formatting..." )
        from .report_formatter import format_json
        js = format_json(
            daily   = result["daily"],
            summary = result["summary"],
            since   = result["since"],
        )
        assert len( js ) > 0
        assert '"summary"' in js
        print( "✓ JSON formatting produced output" )

        # Test 6: Empty-input formatting (edge case AC17)
        print( "Testing empty-input formatting..." )
        empty_text = format_console( daily={}, summary={
            "total_added": 0, "total_deleted": 0, "total_files": 0,
            "total_commits": 0, "total_days": 0, "net": 0,
        }, since="2099-01-01" )
        assert "No commits in range" in empty_text
        print( "✓ Empty-input renders the no-commits banner" )

        # Test 7: Exception hierarchy
        print( "Testing exception hierarchy..." )
        from .exceptions import GitLocDeltaError, DateRangeError, GitCommandError
        assert issubclass( DateRangeError, GitLocDeltaError )
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
