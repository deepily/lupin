# Watch-Note: `test_io_files_router::test_relative_io_prefix_stripped` — non-reproducing

**For:** Rick's morning gate · **Filed:** 2026-06-03 by Rachel 🕊️ (author, agents/root + Batch #5) · **Relayed via:** Tiberius 👑 → María 🌸 (framework steward)

**Status: EVIDENCED NON-REPRODUCING — no standing red. NOT a skip/xfail/mask.** The full canonical gate is green; the held backlog rides this green.

## What happened

During my Batch-#4 verification, the full canonical gate
(`PYTHONPATH=src src/cosa/.venv/bin/python -m pytest src/tests/unit/ src/cosa/tests/unit/ -q`)
showed **1 failure**: `src/cosa/tests/unit/rest/test_io_files_router.py::TestGetIoFile::test_relative_io_prefix_stripped`.
It did not reproduce on any subsequent run.

## Evidence (bytes-first, no confab)

| Run | Result | Notes |
|---|---|---|
| gate4 | **1 failed** / 13298 passed | the single observation of the failure |
| gate5 (`--tb=long`) | 0 failed / **13300 passed** | failure gone; +peer commits landed |
| confirm-1 (fresh PYTHONHASHSEED) | 0 failed / **13300 passed** | |
| confirm-2 (fresh PYTHONHASHSEED) | 0 failed / **13300 passed** | |

**3 consecutive full-gate passes green**, each a distinct hash seed.

## Why this is non-reproducing, not hidden

- **Collection order is deterministic** — no `pytest-randomly` / `pytest-random-order` / `xdist` installed. Same test-set + same code ⇒ same order ⇒ same result.
- **The test-set CHANGED under the run** between gate4 and gate5: peer coverage commits landed — `0278e92` (cosa.rest notifications-router, +2 tests) and `ecc33cc` (cosa.orchestration). The live 5-author grind moved the collection.
- Every sub-tree is green in isolation: `rest/` alone (2365 passed), `cosa/tests/unit/` alone (8123 passed), Lupin tree + victim (pass), each cosa subdir + victim (pass). The failure only ever appeared in the single gate4 full-combined run.
- The victim **fully mocks** `cu.get_project_root` and `_is_secrets_path` in `setUp`, so a config/registry *value* bleed (FM-21) cannot reach its assertion — making a genuine standing leak unlikely and a transient collection-order/loop-state artifact (candidate FM-22, name held by María pending recurrence) the better-fitting explanation.

**Conclusion:** the gate4 red most plausibly **self-healed via an intervening peer commit** changing the collection. No leak-shaped fix was applied, because nothing is currently failing to fix — and forcing one without a reproduction would be confabulation.

## If it recurs (the real fix, deferred until there is a reproduction)

1. Capture the `--tb=long` assertion (path-mismatch vs call-count vs `asyncio.run` loop error vs hash-order) — the mechanism names the fix.
2. Resolve **at source**: order-independence / deterministic seed / hermetic teardown of whatever upstream test bleeds. **Never** skip/xfail to go green.
3. Cross-reference the **SECONDARY** deliverable: a global autouse hermetic-config fixture in a new `src/cosa/tests/conftest.py` (`cache_registry.invalidate_all()` + `ConfigurationManager(_reset_singleton=True)` + config-submodule sys.modules/parent-attr eviction) — the general kill for the FM-21 class. Lands only if isolation-verified squeaky-clean, between batches, revert-staged; otherwise deferred to this same morning gate.

## Related
- FM-21 (non-hermetic config/registry test bleed) — the confirmed instance I fixed at source: `9ed2f56` (test_expeditor_handlers `patch.dict(sys.modules,...)` parent-attr leak).
- Gate-Zero parent-attribute trap: `src/conftest.py::_evict_real_fastapi_main_after_test`.
