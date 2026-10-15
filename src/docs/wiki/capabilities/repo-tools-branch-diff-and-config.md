---
capability: repo-tools-branch-diff-and-config
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.repo.branch_analyzer.config_loader.ConfigLoader@cd1d13eb7f
  - cosa.repo.branch_analyzer.file_classifier.FileTypeClassifier@fa1a7fc184
  - cosa.repo.branch_analyzer.git_diff_parser.DiffLine@4067301659
  - cosa.repo.branch_analyzer.git_diff_parser.GitDiffParser@2ef8ba8b33
  - cosa.repo.branch_analyzer.exceptions.BranchAnalyzerError@74237c241a
  - cosa.repo.branch_analyzer.exceptions.GitCommandError@7d2a06b9a8
  - cosa.repo.branch_analyzer.exceptions.ConfigurationError@644f22c909
  - cosa.repo.branch_analyzer.exceptions.ParserError@5b50872bdb
  - cosa.repo.branch_analyzer.exceptions.ClassificationError@65a36784b7
---
# Branch analyzer: config, diff reading and errors

The input side of `BranchChangeAnalyzer` (see [[branch-and-directory-loc-analysis]]). These parts read the YAML settings, run `git diff` and sort files by type. They are in `cosa.repo.branch_analyzer`.

## `ConfigLoader`
- `ConfigLoader( config_path=None, debug=False ).load()` reads the packaged `default_config.yaml`, deep-merges a user file over it when `config_path` is given, validates the result and returns the dict.
- `get( "git.default_base_branch", default=... )` walks a dotted path and returns the default for a missing key. Before `load()` it raises `ValueError`.
- Validation needs the sections `git`, `file_types`, `analysis`, `output` and `formatting`. `git.diff_algorithm` must be myers, minimal, patience or histogram, `output.default_format` console, json or markdown, and the four `analysis` flags booleans.
- A missing, unparsable or non-dict file raises `ConfigurationError`.

## `FileTypeClassifier`
- `classify( filename )` maps the lowercase extension through `file_types.extensions`. A missing extension, an unknown one and `/dev/null` all give `other`; it never raises.
- `add_extension( ".ext", "category" )` adds a mapping at run time. It raises `ClassificationError` for a name without a leading dot, or for an empty category.
- `get_extension`, `is_binary` (true when the category is `binary`), `get_all_extensions` (a copy) and `get_categories` (always holds `other`) are read helpers.

## `GitDiffParser` and `DiffLine`
- `GitDiffParser( config, repo_path=".", ... )` checks that git runs, then reads `git.diff_algorithm`, `git.extra_diff_options` and `performance.git_timeout` (60 seconds).
- `get_diff( base, head )` runs `git diff --diff-algorithm=<algo> base...head` and returns a list of `DiffLine( content, operation, file_path, line_number )`. The operation is `add`, `remove`, `context` or `meta`.
- Inside a hunk the first character decides, so an added line that begins with `++` is still an add.
- `get_changed_files( base, head )` returns `--name-only` paths. `get_branch_name( ref )` gives the abbreviated name, or the ref itself when git cannot resolve it or answers `HEAD`.

## Errors
- Every error derives from `BranchAnalyzerError( message, context )`, whose text appends the context.
- `GitCommandError` carries `command`, `return_code`, `stderr` and `stdout`, with the two outputs cut to 200 characters in the context.
- `ConfigurationError` carries `config_path`, `field` and `value`. `ParserError` and `ClassificationError` carry line or file details.
