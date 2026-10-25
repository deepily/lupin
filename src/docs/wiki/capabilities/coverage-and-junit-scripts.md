---
capability: coverage-and-junit-scripts
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - scripts.detect_thread_credited_coverage.exclusive_lines@ca3f7d1687
  - scripts.detect_thread_credited_coverage.call_time_lines@a14c6951e5
  - scripts.detect_thread_credited_coverage.make_scope_classifier@a0e9730fe8
  - scripts.detect_thread_credited_coverage.bucket_findings@b16a11040e
  - scripts.detect_thread_credited_coverage.verdict_exit_code@200dd9e2c7
  - scripts.detect_thread_credited_coverage.main@a5e454365f
  - scripts.e2e_junit_diff.load@e64cfe1cab
  - scripts.e2e_junit_diff.classify@80128376ea
  - scripts.e2e_junit_diff.render@d6ac62a696
  - scripts.e2e_junit_diff.main@bf8ed8c61f
  - scripts.thread_attribution_plugin.pytest_configure@a995e97573
  - scripts.thread_attribution_plugin.pytest_unconfigure@41a88e8ba8
---
# Thread-credited coverage and junit diff scripts
Scripts that check what a test run measured.
- `detect_thread_credited_coverage.py` finds lines a background thread credited, not a test. A daemon started at import credits product lines nobody tested.
- `thread_attribution_plugin.py` is the pytest plugin it uses. `pytest_configure` and `pytest_unconfigure` install and remove the trace of which thread ran each first-party line.
- `exclusive_lines` keeps the lines only a non-test thread reached, minus exempted threads. `call_time_lines` lists lines that run only when a function is called.
- `make_scope_classifier` answers whether a line runs inside a function body. A file it cannot parse answers yes for every line.
- `bucket_findings` splits the reduction into the buckets the verdict reads. `verdict_exit_code` returns 1 when any call-time line was found.
- `e2e_junit_diff.py` compares two junit XML runs by test id. `load` maps each test case to its outcome.
- `classify` splits the two maps into regressions, pre-existing failures, fixed cases and more. `render` writes the report. `main` returns 1 on any regression.
