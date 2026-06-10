<!-- FROZEN VISUAL FIXTURE — do not modify, rename, add, or remove files in this
     directory. The doc-viewer directory-listing visual snapshot
     (test_doc_viewer_multi_repo.py::test_visual_external_scope_listing) pins the
     exact contents of this directory. Any change here will require a rebaseline. -->

# Doc-Viewer Listing Fixture (external-scope chrome)

This directory is a **frozen fixture** used by the doc-viewer directory-listing
visual regression test. It exists so the snapshot is deterministic by
construction (ts-127620e1 fix), instead of pointing at the live, ever-growing
`claude-plans/` repo whose file count changes between baseline and run.

Scope-specific functional coverage for external repos lives in the sibling
non-snapshot tests in `test_doc_viewer_multi_repo.py`.
