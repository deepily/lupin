---
capability: doc-lint-metrics-measure
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.repo.doc_lint.doc_metrics.package_files@65f1770ddb
  - cosa.repo.doc_lint.doc_metrics.doc_texts@f3320712a4
  - cosa.repo.doc_lint.doc_metrics.package_metrics@81748c882a
  - cosa.repo.doc_lint.doc_metrics.files_metrics@31b353b9d2
  - cosa.repo.doc_lint.doc_metrics.compare@5b4604945e
  - cosa.repo.doc_lint.doc_metrics.build_report@00f53aa8c2
  - cosa.repo.doc_lint.doc_metrics.render_table@886b9fe568
  - cosa.repo.doc_lint.doc_metrics.main@77c40a3187
---
# Doc-lint metrics measure

Measures documentation tokens and marker rates per package at a revision, before and after a change. The dashboard built on it is in [[doc-lint-metrics-dashboard]]; the marker counts come from [[doc-lint-marker-counts]].

## Measuring
- `package_files` lists the in-scope `.py` and `.dart` files under a package at a revision, from git. With no revision it lists the tracked files still on disk.
- `doc_texts` returns the docstrings of a Python file or the doc blocks of a Dart file. A Python file that does not parse returns `None`, so the caller can count it.
- `package_metrics` and `files_metrics` return files, unparsed paths, tokens, summed marker counts and rates per thousand tokens.

## Comparing
- `compare` is true when tokens fell, no file that parsed before fails to parse, and every marker rate is at or below its earlier value. Unparsed files are compared as a set, so one file breaking while another is fixed still refuses.
- `build_report` measures every package at base and head, with the files added, removed and improved. `render_table` renders it as a markdown table. It notes that fewer tokens can mean deleted documentation.

## Calling it
- `main` prints the table, or JSON with `--format json`. When the first argument is `dashboard`, the rest goes to the dashboard command.
