---
capability: duplicate-check-refile
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.duplicate_check_refile.RefileError@db8c97d407
  - lupin_mcp.duplicate_check_refile.FilingFailed@96b99fba14
  - lupin_mcp.duplicate_check_refile.RecordNotWritten@181aef2b24
  - lupin_mcp.duplicate_check_refile.read_result@d4d66d4973
  - lupin_mcp.duplicate_check_refile.refile@18f8e984c1
  - lupin_mcp.duplicate_check_refile.main@bbdf347fd0
---
# Duplicate check refile
`lupin_mcp.duplicate_check_refile` files again the findings in a saved result file of the daily check. Use it when a run left findings in the file and no rows in the store. The row rules are in [[duplicate-check-filing]].

## What it does
- `read_result( path )` parses the file and checks it. It raises `RefileError` when there is no findings list or a finding lacks `id`, `name`, `file`, `line`, `others`, `window` or `correlation_key`.
- A file written before findings were kept on every run has no findings list and is refused.
- `refile( path, filer, now )` hands the findings and the file's folder to the filer, where the spool lives. The default filer is `live_filer` from the daily check.
- After the filer returns, the file gains one `refilings` entry, `{ at, answer }`. Nothing is written before that, so a failed run leaves the file as it was.
- A finding already on a triage row is not listed again, and one already in the spool is not spooled twice. The keys hold no date.
- `FilingFailed` means the filer raised and the file is unchanged. `RecordNotWritten` means the rows were filed but the record was not. It carries the answer.
- `main` takes a result file path and prints the answer as JSON.

## Exit codes
- 0: every finding is filed or already was.
- 1: some are still queued for retry or were refused.
- 3: nothing could be done, or the rows were filed and the record was not. In that case the answer prints first, then a warning.
