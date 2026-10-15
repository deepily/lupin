---
capability: rest-routers-file-door-guards
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.rest.routers._pinned_open.PinnedPathGone@208df8538b
  - cosa.rest.routers._pinned_open.PinnedPathUnlinked@29d4b526ca
  - cosa.rest.routers._pinned_open.landed_path_of_fd@15e6cd4875
  - cosa.rest.routers._scope_registry.ScopeConfig@2968c2ea43
  - cosa.rest.routers._scope_registry.is_credential_file@c75ba3cccb
  - cosa.rest.routers._scope_registry.landed_within_roots@3d40917f06
  - cosa.rest.routers._scope_registry.landed_relative_path@c981c5dba9
  - cosa.rest.routers.docs_files.get_scopes@72d7e69f57
  - cosa.rest.routers.docs_files.docs_files_health@b36dbd10b5
  - cosa.rest.routers.io_files.io_files_health@1325e89b6d
---
# File door guards and health routes

The helpers the doc viewer and the `io/` file door share, with their scope and health routes. The viewer itself is in [[doc-viewer]].

## What it does
- `PinnedPathGone` means the path is absent or the wrong kind. `PinnedPathUnlinked`, a subclass, means the file was unlinked after it opened.
- `landed_path_of_fd( fd )` reads `/proc/self/fd` for where a descriptor really lives. It raises `PinnedPathUnlinked` when the target shows `(deleted)`.
- `ScopeConfig` is the frozen description of one scope: name, root, allowed prefixes, the optional manifest and extra blocklist patterns.
- `is_credential_file( path )` is true when the bytes look like credentials: service-account JSON, a private key or token fields, or a PEM key. An unreadable file also returns true.
- `landed_within_roots( real_path, roots )` is true when the path sits inside a root by directory identity, so a second mount of the same directory counts.
- `landed_relative_path( real_path, root )` gives the path relative to the root, or an empty string for the root itself. Call it only after `landed_within_roots` is true.
- `get_scopes`, `GET /api/docs/scopes`, lists every scope for a signed-in user: name, root, allowed prefixes, root files, extra blocklist and a `manifest` or `ini-only` source.
- `docs_files_health` (`GET /api/docs/health`) reports each scope's root, whether it exists, its prefixes and manifest flag, plus the `io/` status and media types. `io_files_health` (`GET /api/io/health`) reports `io/` and the file counts under `deep-research` and `podcasts`. Neither needs a login.

## Don't
- Don't serve a file because the check could not read it. Unreadable means refused.
- Don't judge a path string and open it later. Open first, then judge the descriptor.

## Invariants
- The credential check reads at most 8 KiB, widened once to 1 MiB for a JSON container.
