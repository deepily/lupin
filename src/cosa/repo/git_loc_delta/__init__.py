"""
Git LoC Delta Package — per-day LoC analysis driven by `git log --numstat`.

Sister package to `branch_analyzer`. Where branch_analyzer answers
"what did this whole branch change," git_loc_delta answers "what changed when."

Key Features:
- Per-commit walk via `git log --numstat`
- Daily aggregation bucketed by (date, file_type)
- Three output formats: console, JSON, CSV (tidy-long)
- Reuses branch_analyzer's `FileTypeClassifier` + `GitCommandError`
- CLI flags: --today (default), --since/--until, --branch [BRANCH], --base, --output, --save-output

Main Classes:
- GitLogLocDeltaAnalyzer: orchestrator
- GitLogParser:           subprocess + line-stream parser
- DailyAggregator:        bucket aggregator

Programmatic Usage:
    from cosa.repo.git_loc_delta import GitLogLocDeltaAnalyzer

    analyzer = GitLogLocDeltaAnalyzer( mode="today" )
    result   = analyzer.analyze()
    print( result["summary"] )

Command Line:
    python -m cosa.repo.run_git_loc_delta              # today only
    python -m cosa.repo.run_git_loc_delta --branch     # current branch vs main
    python -m cosa.repo.run_git_loc_delta --branch --output csv

Author: María 🌸 (session 3c9fce51, 2026-05-16)
Plan: cosa/rnd/2026.05.16-daily-loc-delta-tool.md
"""

from .analyzer        import GitLogLocDeltaAnalyzer
from .daily_aggregator import DailyAggregator
from .exceptions       import GitLocDeltaError, DateRangeError, GitCommandError
from .git_log_parser   import GitLogParser
from .plotter          import plot_summary

__version__ = "1.1.0"   # 1.1.0 — schema v2 (repo/branch columns + sidecar JSON) + plotter
__all__     = [
    "GitLogLocDeltaAnalyzer",
    "GitLogParser",
    "DailyAggregator",
    "GitLocDeltaError",
    "DateRangeError",
    "GitCommandError",
    "plot_summary",
]
