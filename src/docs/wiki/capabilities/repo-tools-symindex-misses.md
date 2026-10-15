---
capability: repo-tools-symindex-misses
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.repo.symindex.miss_record.is_miss@d84985fdfd
  - cosa.repo.symindex.miss_record.render_block@fb632437da
  - cosa.repo.symindex.miss_record.scan_blocks@548ef09e5c
  - cosa.repo.symindex.miss_record.parse_block@e1f8338a64
  - cosa.repo.symindex.miss_record.row_time@20112f7a92
  - cosa.repo.symindex.miss_record.collect_with_skips@daa34483ee
  - cosa.repo.symindex.miss_record.collect@619ff228ad
  - cosa.repo.symindex.miss_record.Export@b81457902d
  - cosa.repo.symindex.miss_record.export_report@5fe70d2578
  - cosa.repo.symindex.miss_record.export_misses@c31be89642
---
# Reuse miss records

A reuse-check miss is carried as a fenced json block inside a task-store row body. The tick ([[repo-tools-symindex-librarian-tick-run]]) exports these blocks to `misses.jsonl`.

## The block
- A miss has exactly four fields: `receipt_id`, `symbol` and `caught_by` as non-empty strings, and `repaired` as a bool. `is_miss` checks that and nothing else.
- `render_block( miss )` returns the fenced block with sorted keys, so one miss renders to the same bytes. A malformed miss raises `ValueError`.
- `scan_blocks( body )` returns `( misses, skipped )`. CRLF is read as LF, and each block that is not JSON or not a miss adds one reason to skipped. `parse_block` returns only the misses.

## Collecting
- `row_time` reads a row's `updated_ts` as an aware datetime, a trailing Z and a missing offset both read as UTC. It returns None when the field is absent and the module's `OLDEST` when it cannot be read.
- `collect_with_skips( rows )` reads rows oldest first. A later block for the same `( receipt_id, symbol )` wins, so a repair that broke again reads as not repaired. It returns misses sorted by that pair, and skipped entries as `{ title, reason }`. A row whose time cannot be read sorts first and is named in skipped. `collect` returns only the misses.

## Exporting
- `export_report( rows, path, allow_empty=False )` writes one sorted-key JSON object per line to a temporary file and renames it over `path`, mode 0644. It returns an `Export` with `written` and `skipped`.
- It raises `ValueError` rather than replace a populated file with an empty export, unless `allow_empty` is set. `OSError` comes through when the folder cannot be written.
- `export_misses` returns only the written count.
