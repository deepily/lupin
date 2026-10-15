---
capability: repo-tools-directory-scan-stats-and-reports
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.repo.directory_analyzer.directory_scanner.FileInfo@2dbffbe1c7
  - cosa.repo.directory_analyzer.statistics_collector.DirectoryStatisticsCollector@1bd79c4503
  - cosa.repo.directory_analyzer.report_formatter.DirectoryReportFormatter@f2d393c1c2
  - cosa.repo.directory_analyzer.exceptions.DirectoryAnalyzerError@41f91599ec
  - cosa.repo.directory_analyzer.exceptions.ScannerError@92710a4651
  - cosa.repo.directory_analyzer.exceptions.ConfigurationError@dc59565579
  - cosa.repo.directory_analyzer.exceptions.FileReadError@127eeaeb30
---
# Directory analyzer: records, totals, reports and errors

The parts around `DirectoryScanner` and `DirectoryAnalyzer` (see [[branch-and-directory-loc-analysis]]). They live in `cosa.repo.directory_analyzer`.

## `FileInfo`
- One record per file the scanner yields: `path` (absolute), `relative_path` (to the scan root), `lines`, `line_count`, `size_bytes` and `encoding`.
- An empty file comes back with no lines and encoding `utf-8`. The scanner tries each encoding in `directory.encodings` in order (default list: utf-8, utf-8-sig, latin-1, cp1252) and keeps the first that decodes.

## `DirectoryStatisticsCollector`
- `record_line( file_type, line_category=None, file_path=None )` adds one line to the file type's total. For python, javascript and typescript it also adds to the language total, and a missing category counts as `code`.
- `record_file( file_type, file_path )` registers a file without a line, so an empty file still shows in the file count.
- `get_summary()` returns `overall` (`total_lines`, `total_files`), `by_file_type` (largest first, each with `total`, `files`, `percentage`) and `language_details`. `reset()` clears everything.

## `DirectoryReportFormatter`
- `format_console( stats, directory_path, scan_stats=None )`, `format_json( ... )` and `format_markdown( ... )` return strings and never print.
- When `scan_stats` from `DirectoryScanner.get_scan_stats()` is passed, the console report adds the skipped-file and skipped-directory counts if any is above zero.
- JSON adds `metadata` unless `json_output.include_metadata` is false. Markdown adds its time block unless `markdown_output.include_timestamp` is false.

## Errors
- `DirectoryAnalyzerError( message, context=None )` is the base. `run_directory_analyzer` catches it, prints it to stderr and exits 1.
- `ScannerError( message, path=None, original_error=None )` is raised when the scan root does not exist or is not a directory.
- `ConfigurationError` is raised when the packaged `default_config.yaml` is missing or holds invalid YAML.
- `FileReadError` is defined and imported by the scanner, but no code raises it. Unreadable files are skipped and counted instead.
