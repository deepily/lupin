---
capability: repo-tools-branch-stats-and-reports
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.repo.branch_analyzer.statistics_collector.StatisticsCollector@0fa052f565
  - cosa.repo.branch_analyzer.report_formatter.BaseReportFormatter@7f4c9eebb3
  - cosa.repo.branch_analyzer.report_formatter.ReportFormatter@895701e1af
  - cosa.repo.branch_change_analysis.analyze_diff@2b79547464
  - cosa.repo.branch_change_analysis.get_file_type@cc68e7cc74
  - cosa.repo.branch_change_analysis.is_javascript_comment@053d509a34
  - cosa.repo.branch_change_analysis.is_python_comment_or_docstring@ce74eb2dc2
---
# Branch analyzer: totals, reports and the old script

The output side of `BranchChangeAnalyzer` (see [[branch-and-directory-loc-analysis]]), plus the older standalone script it replaced.

## `StatisticsCollector`
- `record_line( file_type, "add" | "remove", line_category=None, file_path=None )` counts one line. An add also counts toward `code`, `comment` or `docstring` when a category is passed. A remove counts toward the language's `removed` only for python, javascript and typescript. A `file_path` is kept in a set of changed files.
- `get_summary()` returns `overall`, `by_file_type` (sorted by added plus removed, largest first), `language_details` and `files_changed_set`. With nothing added all three percentages are 0.0. Otherwise `docstring` appears in them only when it is above zero.
- `reset()` empties every count.

## `ReportFormatter`
- `BaseReportFormatter( config )` reads the border characters, number settings and the `json_output` and `markdown_output` sections. It calls `_read_column_widths`, which raises `NotImplementedError` unless a subclass overrides it.
- `ReportFormatter` overrides it to read the `file_type`, `counts` and `net_change` widths, with defaults 15, 10 and 12.
- `format_console`, `format_json` and `format_markdown` each take `( stats, base_branch, head_branch, repo_path=".", ... )` and return a string. They never print.
- Console output has a banner, the overall block, a file-type table and one block per language present. JSON holds the branches, the absolute repository path and `statistics`, plus `metadata` (time, format, version) unless `json_output.include_metadata` is false. Markdown uses tables, and a repository-and-time block unless `markdown_output.include_timestamp` is false.

## `branch_change_analysis.py`
- A standalone script: `python -m cosa.repo.branch_change_analysis` calls `analyze_diff()`, which runs `git diff main...HEAD` in the current directory and prints a report. It has no config and no arguments.
- `get_file_type( filename )` maps 14 hard-coded extensions and answers `other` for the rest. `is_python_comment_or_docstring( line )` answers `comment`, `docstring`, `code`, or `None` for a blank line. `is_javascript_comment( line )` answers `comment`, `code` or `None`.
- Prefer `BranchChangeAnalyzer`. Its classifier and config replace all four.
