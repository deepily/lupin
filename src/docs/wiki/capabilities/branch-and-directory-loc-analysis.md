---
capability: branch-and-directory-loc-analysis
pin_algorithm: py3.13.xf75af6/ts5.9.3
pins:
  - cosa.repo.branch_analyzer.analyzer.BranchChangeAnalyzer@2a56d71cf4
  - cosa.repo.branch_analyzer.analyzer.BranchChangeAnalyzer.analyze@78c82fdf63
  - cosa.repo.directory_analyzer.analyzer.DirectoryAnalyzer@9929831f1e
  - cosa.repo.directory_analyzer.analyzer.DirectoryAnalyzer.analyze@1eae6b9193
  - cosa.repo.branch_analyzer.line_classifier.LineClassifier@014c81d4ae
  - cosa.repo.directory_analyzer.directory_scanner.DirectoryScanner@7154b0ef7d
  - cosa.repo.git_loc_delta.analyzer.GitLogLocDeltaAnalyzer@787434bf88
  - cosa.repo.git_loc_delta.coverage_guard.reconcile_coverage@492355357f
---
# Branch and directory LoC analysis

Counts lines of code two ways: what a branch changed against a base (`BranchChangeAnalyzer`), and what a directory holds right now (`DirectoryAnalyzer`). Python, JavaScript and TypeScript lines are split into code, comment and docstring. A third tool, `git_loc_delta`, answers what changed on each day.

## Branch delta: `BranchChangeAnalyzer`
- Run it with `python -m cosa.repo.run_branch_analyzer` (flags `--repo-path`, `--base`, `--head`, `--config`, `--output console|json|markdown`, `--save-output`). It exits 0 on success, 1 on error, 130 on Ctrl-C.
- From code: `BranchChangeAnalyzer( repo_path=..., base_branch=..., head_branch=... ).analyze()` returns a stats dict; `format_results( stats, format=... )` renders it. With no arguments it compares `HEAD` to `main`, using a three-dot `git diff`.
- The stats dict has `overall` (`total_added`, `total_removed`, `net_change`, `files_changed`), `by_file_type`, `language_details` and `files_changed_set`.
- Only added lines are split into code, comment and docstring, and only for languages in `analysis.supported_languages` (default python, javascript, typescript); the statistics collectors hard-code those same three names for the per-language report, so a language added to the config is not reported separately. A blank added line counts toward the file type's `added` total but toward none of the three.

## Directory count: `DirectoryAnalyzer`
- Run it with `python -m cosa.repo.run_directory_analyzer --path <dir>` (same output flags). From code: `DirectoryAnalyzer().analyze( path )`, then `format_results( stats, path, format=... )`.
- It returns `overall` (`total_lines`, `total_files`), `by_file_type` and `language_details`.
- Blank lines are never counted. Files of a type outside the supported languages count every non-blank line toward their file type, with no split.

## What the directory scan skips
- A directory is skipped when its name is exactly in `directory.exclude_dirs`. The match is exact string membership, so a glob-looking entry such as `*.lancedb` matches nothing.
- Files matching `directory.exclude_files`, binary files (judged by extension only, so an extensionless file is never binary), files over `max_file_size` and files no configured encoding can decode are skipped. Symlinks are not followed unless `follow_symlinks` is set. Skips are counted in `get_scan_stats()`, except a skipped symlink, which is not counted; none raises.

## Daily deltas: `git_loc_delta`
- `python -m cosa.repo.run_git_loc_delta` buckets `git log --numstat` rows by committer date and file type. Modes: today (default), `--since/--until`, `--branch`. `--all-branches` is refused with `--branch`.
- The log is read with `--no-merges` unless `--include-merges` is given. With the flag the log adds `--diff-merges=first-parent`, so a merge counts what it brought in over its first parent. Lines already counted on the merged branch count again. Binary files are skipped.
- A commit count is the size of a SHA set. The per-(date, file type) `commits` column overlaps and must not be summed.

## Not this tool
- `branch_change_analysis.py` is an older standalone script with a hard-coded `main...HEAD` diff and no config. Use `BranchChangeAnalyzer`.
- Counts are line heuristics, not a parse: a line holding `"""` counts as docstring. Exact docstring or comment counts cannot be had from them.
