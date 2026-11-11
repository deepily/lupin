---
capability: utils-utc-stamp
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.utils.utc_stamp.utc_compact_stamp@583baad5b3
---
# Compact UTC stamp

One helper in `cosa.utils.utc_stamp` builds the stamp used in file and folder names, for example `20261111T225539Z`.

## What it does
- `utc_compact_stamp( now=None )` returns the stamp for `now`, or for the present UTC moment when `now` is None.
- The result is 16 characters, sorts as text and holds nothing a filesystem refuses.

## Don't
- Don't write another `strftime( "%Y%m%dT%H%M%SZ" )`. Five copies were folded into this one.
- Don't pass a local-time datetime. It is formatted as given and still ends in Z.
- Don't use it for a stamp a person reads. Those use the EDT formatter in [[timestamps-clock-and-dm-word-count]].

## Invariants
- It reads the clock only when `now` is None.
- Callers: the WIP-commit and rescue-branch labels in `worktree_reaper`, the two migration scripts and the two TFE live scripts.
