---
capability: checked-hash-bytecode
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.utils.checked_hash_pyc.actor@8b04c2e00b
  - cosa.utils.checked_hash_pyc.census@dce6d898b5
  - cosa.utils.checked_hash_pyc.converted_count@6a814792ab
  - cosa.utils.checked_hash_pyc.is_installed@109d72aec5
  - cosa.utils.checked_hash_pyc.ledger_path@b88b2e7245
  - cosa.utils.checked_hash_pyc.main@5820dbf05e
  - cosa.utils.checked_hash_pyc.pyc_mode@c23f20aba6
  - cosa.utils.checked_hash_pyc.record@6d1ec24d65
  - cosa.utils.checked_hash_pyc.to_checked_hash@091ed7d69f
  - cosa.utils.checked_hash_pyc.uninstall@1d286d01ef
---
# Checked-hash bytecode

`checked_hash_pyc` is the write-time control that `src/sitecustomize.py` installs. It makes bytecode validate on source content, not on mtime. `install()` is also described in [[shared-utilities]].

## What it does
- `install()` swaps timestamp pyc headers for checked-hash ones, for sources under `$LUPIN_ROOT/src` only.
- `uninstall()` restores the stock write. It returns True only if a patch was removed.
- `is_installed()` and `converted_count()` report the patch state and how many files it converted.
- `pyc_mode( data_or_path )` returns `checked-hash`, `unchecked-hash`, `timestamp` or `unreadable`.
- `to_checked_hash( data, source_bytes )` rewrites a timestamp header.
- `census( roots )` returns `( counts, offenders )` for this interpreter's pycs. It skips vendored trees and pytest-rewritten pycs.
- `record`, `ledger_path` and `actor` append one line to `io/pyc-mode-ledger.jsonl` under `LUPIN_ROOT`.
- `main` runs the census and writes one ledger line. It exits 0 only when it found pycs and none are offenders. It exits 1 for offenders, and 2 when it found no pycs at all, printing `scanned 0 pycs`.

## Don't
- Don't use a bare truth test on `install()`. `ALREADY_INSTALLED` and `UNSUPPORTED_INTERPRETER` raise `TypeError` in a boolean context.
- Don't read a clean `main()` as "converted". It is 0 when no pycs are found at all.

## Invariants
- An empty `roots` set means nothing is in scope for the patch. It fails closed.
- A pyc rewrite failure falls through to CPython's own bytes.
