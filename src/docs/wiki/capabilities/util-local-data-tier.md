---
capability: util-local-data-tier
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - cosa.utils.local_data_tier.LocalDataLedger@8994f1adb5
  - cosa.utils.local_data_tier.add_require_option@c3ce708342
  - cosa.utils.local_data_tier.local_data_dir@d0394edf83
  - cosa.utils.local_data_tier.require_local_file@9e91dd2a4e
  - cosa.utils.local_data_tier.skip_reason@5cd643573d
---
# The `local_data` test tier

Tests that read Rick's real answers carry the `local_data` marker. Those answers live under the main checkout's gitignored `io/` folder, so in a worktree the folder is absent and the test skips. This module makes that skip loud. The hooks are wired from `src/conftest.py`.

## What it does
- `local_data_dir()` returns `LUPIN_LOCAL_DATA_DIR` when set, otherwise the project root plus `/io/write-ups/online-preference-learning`. It never checks the folder exists.
- `require_local_file( file_name )` returns the file's path, or skips the calling test with a reason naming the missing path.
- `skip_reason( report )` returns a skipped report's message without pytest's skip prefix.
- `add_require_option( parser )` registers `--require-local-data`.
- `LocalDataLedger` tallies one run. `on_report` records a `local_data` skip as a ( node id, reason ) pair and a call-phase report as ran. `summary_lines` always returns at least the `[local_data] ran=N skipped=M` line, then one line per skip.
- `should_fail( required )` is false with the option off. With it on, it is true when any test skipped or when none ran.

## Don't
- Don't read a green run as proof the tier ran. Without `--require-local-data` a skipped tier exits 0.
