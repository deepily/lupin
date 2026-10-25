---
capability: repo-tools-symindex-librarian-queue
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.repo.symindex.librarian_queue.finding_package@1124d49614
  - cosa.repo.symindex.librarian_queue.group_by_package@5db6e7f9bd
  - cosa.repo.symindex.librarian_queue.fingerprint@323e340ee0
  - cosa.repo.symindex.librarian_queue.render_rollup@1e6f9973c9
  - cosa.repo.symindex.librarian_queue.read_fingerprint@f140852d3d
  - cosa.repo.symindex.librarian_queue.is_cleared@116c4ce104
  - cosa.repo.symindex.librarian_queue.closing_receipt@ea117641c8
  - cosa.repo.symindex.librarian_queue.clear_note@50a9c2fb3e
  - cosa.repo.symindex.librarian_queue.read_pending@cd24118452
  - cosa.repo.symindex.librarian_queue.write_pending@964e71e16c
  - cosa.repo.symindex.librarian_queue.Librarian@e52b1bc8d9
  - cosa.repo.symindex.wiki_lint.package_of@696be45858
---
# Wiki librarian queue

Turns wiki lint findings into task-store rows. The daily tick ([[repo-tools-symindex-librarian-tick-run]]) calls it with the lint output.

## One rollup row per package
- `finding_package` names a finding's package: an orphan or package finding uses its own, a stale or dangling one uses `package_of` of its symbol. That is the first two dotted parts of the id. Anything else goes under `wiki`. `group_by_package` groups a list that way, in input order.
- `render_rollup( package, findings )` returns the title (`[LUPIN] wiki-librarian rollup: <package>`) and a body. The body counts findings by kind, lists at most 25, says how many more, and ends with a `rollup-fingerprint:` line.
- `fingerprint` is a SHA-1 of the sorted JSON of the findings, so the order does not matter. `read_fingerprint` returns the last such line in a body, because an amendment appends and keeps the old text.

## `Librarian.sync( findings, index_sha )`
- The store object needs `query( key )`, `create( payload )` and `amend( id, note )`, each returning `( ok, status, body )`. Rows carry the key `epic:wiki-librarian`, priority P5 by default and the owner and manager personas given.
- A package with findings and no row gets a row. A changed fingerprint gets one amendment. An unchanged one is counted as unchanged.
- A rollup whose package has no findings left is amended once with `clear_note`, which starts with `rollup-cleared:` and the index sha. The tick never closes it. `is_cleared` is true when the last clear notice sits after the last fingerprint, so findings that come back reopen the amendment path.
- `closing_receipt( package, index_sha )` builds the `manager_attestation` receipt, at most 255 characters, the accountable manager closes the row with.
- The return value counts created, amended, unchanged, cleared, waiting, deferred and pending. A store that cannot be read raises `RuntimeError`.

## Refused creates and the cap
- A create the store refuses is appended to the pending file and retried first on the next sync. `read_pending` skips lines that are not JSON objects. `write_pending` writes a temporary file and renames it, and an empty list removes the file.
- `max_creates` caps create calls per sync, retries first. Rollups held back by the cap are counted as deferred and derived again next run.
- `hold_or_create( title, body )` makes one row unless a row with that title is open, and is not subject to the cap.
