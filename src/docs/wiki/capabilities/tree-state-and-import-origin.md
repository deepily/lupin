---
capability: tree-state-and-import-origin
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.utils.tree_state.bundle_hash@fae856f310
  - cosa.utils.tree_state.capture_start_bundle@cc164cd5d5
  - cosa.utils.tree_state.capture_start_sha@6d1ec4a729
  - cosa.utils.tree_state.main@5d171315ae
  - cosa.utils.tree_state.tree_state_line@88427aa45a
  - cosa.utils.import_origin.import_origin_field@25b728cd84
---
# Tree state and import origin

Two standard-library helpers that say which checkout a test run measured. Gate order is in [[gate-reachability]] and [[scheduled-test-suite]]. `tree_state_line` is also listed in [[shared-utilities]].

## What it does
- `tree_state_line( git, start_sha=None, start_bundle=None )` returns one `[tree-state]` line, always, and never raises. It carries sha, `root=`, branch, behind and ahead counts, fetch age, dirty counts and `dirty-paths=`.
- With a start sha it adds `run-span=`, which is `unmoved`, `<a>..<b>` or `UNKNOWN`.
- `capture_start_sha( git )` returns a short sha or `"UNKNOWN"`, never None.
- `bundle_hash( root )` is a 12-hex digest of the served `.js` and `manifest.json` files under `src/lupin_app/static/dist/`. It ignores the manifest `built` time. It returns `none` with no `dist/` and `UNKNOWN` on a read error.
- `capture_start_bundle( git )` wraps `bundle_hash`. `main` prints the line and always exits 0. `src/scripts/lib/tree-state.sh` runs it.
- `import_origin_field( modules, lupin_root )` returns one `imports=` token: `same-tree`, `single-module ...`, a split across checkouts, a coherent foreign tree, or `UNKNOWN`.
- `modules` is a list of `( name, module_or_None, depth )`. The function imports nothing.

## Don't
- Don't read `unmoved` as "the working tree held still". Only the HEAD shas were compared.

## Invariants
- Unknown is never clear: `UNKNOWN` sha, bundle and import values are distinct from a pass.
