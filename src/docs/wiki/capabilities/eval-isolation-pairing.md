---
capability: eval-isolation-pairing
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - scripts.eval_isolation_guard.parse_permitted_stores@8aea90a80e
  - scripts.eval_isolation_guard.require_isolated_snapshot_table@7d06dd14f0
  - scripts.eval_isolation_guard.require_arms_distinct_and_clean@aec44e5c91
  - scripts.eval_isolation_guard.assert_paired_isolation@8bebd148fd
  - scripts.eval_isolation_guard.count_store_rows@d3f1272c8f
  - scripts.eval_isolation_guard.agentic_command_names@543385a570
  - scripts.eval_isolation_guard.pin_carries_leak_fix@467e1fe032
  - scripts.eval_isolation_guard.require_leak_free_corpus@13c832860f
---
# Eval isolation guard: pairing and corpus

The second property of the paired eval guard: the arms must write different stores, each starting empty. It also refuses a corpus that would hit a known argument leak. The write-target checks are on [[eval-isolation-write-target]].

## Safety allowlist
- `parse_permitted_stores` turns the `v2 eval permitted snapshot stores` value into a set of `database.table` strings. A blank or absent value gives an empty set, which fails closed.
- `require_isolated_snapshot_table` returns nothing when write-back is off. When it is on, it returns the destination only if the allowlist holds it. An empty allowlist, or a destination outside it, raises `IsolationNotConfigured`.

## Validity
- `require_arms_distinct_and_clean` passes only when the two destinations differ and both row counts are 0. It shares no allowlist with the safety check.
- A shared destination would let v1's writes warm v2's cold pass. A non-empty destination leaves residue in the cold baseline. Each raises `PairedTargetsNotIsolated` with its own message.
- `assert_paired_isolation` is the caller: it queries each store's row count through a counter function, then applies that check.
- `count_store_rows` runs a real count against the database named in the `database.table` string. It swaps only the URL path, so a query or fragment cannot name another database.

## Leak-free corpus
- `agentic_command_names` reads, live from the argument-contract registry, the router commands that extract runtime arguments. These are the leak site.
- `pin_carries_leak_fix` is true when the fix commit is an ancestor of the pinned v1 sha. An empty pin raises `ValueError`.
- `require_leak_free_corpus` returns the corpus commands unchanged when they avoid those commands or the pin carries the fix. Otherwise it raises `PairedCorpusExercisesLeak`, naming each offending command and the pin.
