"""
Utilities Unit Tests

Unit tests for the cosa.utils package — the shared utility surface:
- ApiResourceManager singleton (rate-limit / API contention)
- Stopwatch, XML, pandas, GCS, code-runner, notification, and config-loader helpers

Zero external dependencies — all network, filesystem, and third-party
integrations are mocked for isolated, deterministic testing.
"""
