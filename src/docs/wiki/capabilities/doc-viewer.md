---
capability: doc-viewer
pin_algorithm: py3.13.xf75af6/ts5.9.3
pins:
  - cosa.rest.routers.docs_files.get_docs_file@f6b61c9fe4
  - cosa.rest.routers.docs_files.upload_docs_file@ed41be996e
  - cosa.rest.routers.io_files.get_io_file@2e917695fd
  - cosa.rest.routers._scope_registry.build_scope_registry@31e0911165
  - cosa.rest.routers._scope_registry.resolve_in_scope@b5d0cf1c5e
  - cosa.rest.routers._scope_registry.credential_verdict@6392b090c3
  - cosa.rest.upload_size_guard.UploadSizeGuard@bee5e4c2a7
  - cosa.config.docview_manifest.DocviewManifest@000517ca8a
---
# Doc viewer

The doc viewer serves repo files and the `io/` folder to the browser, and lets an admin upload into them. A request names its file as `path=<project>/<rel>`, and the first segment must be a registered project.

## What it does
- `get_docs_file` (`GET /api/docs/file`) resolves the path through one gate, then returns a file or a directory listing.
- `get_io_file` (`GET /api/io/file`) is the older, separate door for `io/`. It accepts `.pptx`, which the docs door does not.
- `build_scope_registry` reads the INI `external repos` block each time it is called. It skips names that collide with `docs` or `io`. The docs router calls it once and caches the result.
- A repo's `.docview.yml` (`DocviewManifest`) narrows what is served. A missing, oversized, unparsable or invalid manifest means the INI `allowed prefixes` apply, or a wildcard if there are none. The floor blocklist still applies.
- `upload_docs_file` (`POST /api/docs/upload`, admin only) takes `on_conflict` of `refuse`, `replace` or `rename`. Files over 100 MB are refused.

## Don't
- Don't write a second copy of the path rule for a new endpoint. Upload calls the same `_resolve_scoped` that reading uses.
- Don't judge a path with `normpath`. It never follows a symlink, so `resolve_in_scope` uses `realpath` and the guards run again where the path lands.
- Don't add a manifest field that loosens the blocklist. `DocviewManifest` rejects unknown fields.
- Don't pass `?scope=`. It is retired and answers 400.

## Invariants
- The secrets blocklist runs before the project name is looked up. The whitelist and the manifest's extra blocklist follow.
- An upload is staged in a hidden temp file, then placed with `os.link`, or `os.replace` when replacing. Only `replace` overwrites an existing name.
- Every upload is scanned end to end for a PEM private key. Text and SVG uploads also get the credential-content check that reading applies.
- `UploadSizeGuard` (mounted in `lupin_app/main.py`) refuses a declared length over the cap plus 1 MB unread. It aborts an undeclared or understated body once the count passes that limit.
- The docs router's registry is cached per process and dropped by `/api/init`. A new file type goes into `MEDIA_TYPES` in `docs_files.py`.
