<!-- FROZEN VISUAL FIXTURE — do not modify, rename, add, or remove files in this
     directory. The doc-viewer io-style directory-listing visual snapshot
     (test_doc_viewer_directory.py::test_visual_directory_listing_frozen_fixture)
     pins the exact contents of this directory. -->

# Sample Output (fixture)

Frozen fixture file standing in for a generated artifact, used by the
doc-viewer directory-listing visual snapshot so it is deterministic by
construction (ts-127620e1 fix) instead of pointing at the live, self-mutating
`io/` scope (the test harness writes its own results into `io/`).

Functional coverage of the real `io` scope lives in the sibling non-snapshot
tests in `test_doc_viewer_directory.py`.
