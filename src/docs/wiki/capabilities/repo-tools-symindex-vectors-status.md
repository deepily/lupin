---
capability: repo-tools-symindex-vectors-status
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.repo.symindex.vector_status.read_stale_hours@6e7b2229bf
  - cosa.repo.symindex.vector_status.age_hours@7805d161b6
  - cosa.repo.symindex.vector_status.compute@daf491ae55
  - cosa.repo.symindex.vector_status.stale_row@ae4ceab828
  - cosa.repo.symindex.vector_status.check@5ee57cd211
  - cosa.repo.symindex.vector_status.main@19db45d16d
---
# Vector set status

Says whether the stored vector set is stale, and files one store row when it is. It builds nothing. The refresh job it watches is on [[repo-tools-symindex-vectors-refresh]].

## Running it
- `python -m cosa.repo.symindex.vector_status [--root R]` prints the status as JSON and exits 0 when fresh, 1 when stale. The command line files no row.
- The librarian tick runs the same check whether or not the refresh job is switched on. It runs it after the sync and export, so only on a due or forced tick that passes its guards.
- The summary gets `vector_status` with `stale` and `reasons`. An `OSError` or `ValueError` from the check is logged and leaves it out.

## How it decides
- `read_stale_hours` reads the key `reuse vector stale hours` and falls back to 36 when it is absent, unparsable or not above zero.
- `age_hours( built_at, now )` returns the age rounded to two places, or None when the time has no offset.
- `compute` reads the set's build info, the published index and its searchable entries, the stored purpose lines and the job's state file. It is stale when the set has no build info, its time cannot be read, or it is older than the limit. It is also stale when the index changed since the build and the daily job has already run today. It names every reason that held.
- An index that is not published leaves its fields None and never counts against the set.

## Filing the row
- `check( root, now, librarian=None, ... )` takes optional `stale_hours`, `config`, `environ`, `screen` and `log` too. It computes, writes `vector-status.json` in the refresh job's folder, and for a stale set calls `librarian.hold_or_create`. The status `row` is `exists`, `created`, `pending` or `unreadable`.
- `stale_row` returns the fixed title `[LUPIN] reuse vector set is stale` and a body with the reasons, the numbers and the rebuild command. One open row therefore stands for the condition.
- A fresh set files nothing and leaves an open row for a person to close.
