---
capability: repo-tools-loc-cli-entrypoints
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.repo.run_branch_analyzer.create_parser@c6a3ddcd10
  - cosa.repo.run_branch_analyzer.main@2f6aea5c65
  - cosa.repo.run_directory_analyzer.create_parser@00747a318e
  - cosa.repo.run_directory_analyzer.main@8cba583006
  - cosa.repo.run_git_loc_delta.create_parser@05a41bac91
  - cosa.repo.run_git_loc_delta.main@3aacb7c06c
  - cosa.repo.run_git_loc_delta_global.create_parser@691234216e
  - cosa.repo.run_git_loc_delta_global.main@661a4ea8db
---
# Line-count command lines

Four `python -m cosa.repo.<name>` entry points over the tools in [[branch-and-directory-loc-analysis]]. Each module has a `create_parser()` that builds the argument parser and a `main()` that returns the exit code, so tests call both without a subprocess.

## Branch and directory
- `run_branch_analyzer`: `--repo-path`, `--base`, `--head`, `--config`, `--output console|json|markdown`, `--save-output`, `-v`, `-d`. Flags left unset fall back to the config file. Exit 0, 1 on error, 130 on Ctrl-C, and 2 for bad arguments.
- `run_directory_analyzer`: `--path` (default `.`), `--config`, `--output` (default console), `--save-output`, `-v`, `-d`. Exit 0, 1 on any error, 130 on Ctrl-C, and 2 for bad arguments.

## Daily delta, one repo
- `run_git_loc_delta` picks one mode: `--today` (the default), `--since` and `--until` (either may stand alone), or `--branch [NAME]` against `--base` (default main).
- `--all-branches` walks every local branch and is refused with `--branch`. `--include-merges` and `--author` filter commits. `--repo-name` sets the `repo` column.
- `--output console|json|csv`. A CSV goes to `io/git-loc-delta/` unless `--save-output` names a path, and its sidecar is written beside it. `--plot` adds a PNG under `io/git-delta-analysis/`, or at `--plot-output`. In `--today` mode, or with under two days of data, it warns and skips.
- It prints "Wrote N rows to ..." for CSV, and a coverage warning on stderr when git and the numstat walk disagree.
- It exits 0, or 1 on a git, date-range or plot failure. An empty branch range prints "No commits in range." and exits 0.

## Daily delta, many repos
- `run_git_loc_delta_global` requires `--repos PATH...`. With no `--since` or `--until` it uses today for both. A bare date is pinned to the whole day.
- Each repo is read straight from git, over all local branches unless `--head-only`. Merges are left out unless `--include-merges`. Results are rolled up per day, and the plot draws one line per repo.
- Output is `--output console|json|csv` and `--plot`. A CSV or PNG without an explicit path goes to `io/loc-delta-global/` under the current directory.
- It exits 0, or 1 on a git error, when no path is a git repository, or on a plot failure. It never reads the per-repo CSVs.
