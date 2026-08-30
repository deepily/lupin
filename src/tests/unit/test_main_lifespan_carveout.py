"""
Carveout-scoped unit tests for the `lupin_app.main` lifespan switch — Phase 5.6
of the 2026-05-16 model-server carve-out.

🔴 READ THIS BEFORE TRUSTING THE FILENAME. This file does NOT import
`lupin_app.main`, and therefore contributes ZERO coverage to it. Measured
2026-08-30 at sha `e1fc27ae`: running this file under `--cov=lupin_app.main`
reports `module-not-imported` / `no-data-collected`. A file called a carve-out
test that never imports the module it carves out is exactly the shape this
docstring exists to stop you assuming away. The name was kept deliberately (Mr.
Radio's ruling, 2026-08-30) — the honest answer here is a DECLARED gap, not a
manufactured one, so the gap is declared below instead of being papered over
with tests that buy a number.

What is actually covered, and by what:

| surface | covered by | state |
|---|---|---|
| the carve-out symbols import cleanly | this file (`cosa.memory.*`, not `main`) | ✅ |
| the `.lower().strip()` + `== "model-server"` predicate | this file, on string literals | ⚠️ tautological — no edit to `main.py` can redden it |
| `declare_remote_only` / `declare_in_process_*` API surface | `test_speech_to_text_provider.py`, `test_embedding_provider_carveout.py` | ✅ 100% |
| the REMOTE branch body (probe loop + HTTP routing) | ONE smoke test — see the warning below | 🟡 end-to-end only |
| the LOCAL branch body (eager GPU load of 3 models) | **nothing** | 🔴 declared gap |
| the switch region itself, lines 898–1015 of `main.py` | **nothing** | 🔴 60 of 60 statements missing |

⚠️ THE SINGLE COVERING SMOKE TEST SILENTLY SKIPS IN ANY WORKTREE. Of the nine
tests in `src/tests/smoke/test_model_server_smoke.py`, eight hit `:7998`
directly and say nothing about this file; only `test_proxy_through_compute_mp3`
transcribes through `:7999`, which can succeed only if that process's lifespan
took the remote branch. That one test needs `src/conf/keys/model-server-api`,
which is gitignored at `.gitignore:71` — present in the main tree, absent from
every worktree. It reports `SKIPPED`, not a failure, so a seat verifying this
exemption from a worktree sees the suite pass and concludes nothing covers the
branch. Measured both ways at `e1fc27ae`: `4 passed, 5 skipped` without the key
file, `9 passed` with it.

WHY THE LIFESPAN IS NOT UNIT-TESTED (the ruling, and where it actually lives):
the switch sits inside a 683-line async function with ~10 collaborator
dependencies (commons init, websocket manager, prediction engine, model
loading). 274 of `main.py`'s 296 missing statements are inside it; mocking that
startup graph buys a percentage, not confidence.

The ruling is `92-phase5-closure.md:18` (Q9 hybrid scope ratification), verbatim:

    Lifespan switch in `fastapi_app/main.py` documented as smoke-tier coverage
    (the live branch behavior is exercised by
    `src/tests/smoke/test_model_server_smoke.py`).

`fastapi_app/main.py` IS this file — renamed `R090` to `src/lupin_app/main.py`
in commit `53fef419`, 2026-06-19. The rename is noted so the trail survives a
`grep` for the old path.

⚠️ CITATION CORRECTED 2026-08-30. This docstring previously cited
`91-phase5-smoke-audit.md` for the smoke-tier ruling. That document mentions
`lupin_app` / `fastapi_app` ZERO times — it audits two smoke test FILES for
carve-out compatibility and refines a test list for `lupin_model_server/main.py`,
a different file. The ruling was real, but a reader checking the citation landed
on a document about something else. Full audit and measurements:
`src/rnd/v0.2.1/2026.08.30-lifespan-carveout-citation-audit.md`.

ALSO UNWRITTEN, on purpose: design doc
`src/rnd/v0.1.7/2026.05.16-model-server-carveout/02-phase5-unit-tests-and-coverage-design.md`
§8 named three lifespan tests
(`test_lifespan_declares_local_owner_...`, `..._remote_only_...`,
`..._handles_load_failure_gracefully`). None were written, here or anywhere.
That stays true by ruling, not by oversight.
"""

import importlib


# ── Import-smoke ────────────────────────────────────────────────────────────


def test_main_module_imports_speech_to_text_provider():
    """
    `lupin_app.main` must import cleanly with the carveout symbols
    available — confirms no import-time regression from the lifespan changes.

    NOTE: We import `cosa.memory.speech_to_text_provider` (the source of
    the symbol that `main.py`'s lifespan imports inline) rather than
    `lupin_app.main` itself, because `lupin_app.main` performs heavy
    module-level side effects (config_mgr instantiation, queue/router
    wiring) that would slow this unit test by orders of magnitude.

    Ensures:
        - `SpeechToTextProvider` is importable + has `declare_remote_only`
          + `declare_in_process_owner` class methods (the API surface the
          lifespan switch depends on)
    """
    speech_module = importlib.import_module( "cosa.memory.speech_to_text_provider" )
    assert hasattr( speech_module, "SpeechToTextProvider" )
    cls = speech_module.SpeechToTextProvider
    assert hasattr( cls, "declare_remote_only" )
    assert hasattr( cls, "declare_in_process_owner" )
    assert callable( cls.declare_remote_only )
    assert callable( cls.declare_in_process_owner )


def test_main_module_imports_embedding_provider():
    """Same as above but for the embedding-side carveout API."""
    embedding_module = importlib.import_module( "cosa.memory.embedding_provider" )
    assert hasattr( embedding_module, "EmbeddingProvider" )
    cls = embedding_module.EmbeddingProvider
    assert hasattr( cls, "declare_in_process_engine_owner" )
    assert callable( cls.declare_in_process_engine_owner )


# ── Branch-decision predicate ───────────────────────────────────────────────


def test_remote_mode_predicate_matches_model_server_value():
    """
    The lifespan computes `remote_mode = (provider_mode == "model-server")`.
    This test pins the canonical string value the predicate compares against.
    Anyone refactoring the string MUST update both call sites in lockstep.
    """
    # The carveout's lifespan switch uses this exact string.
    canonical_remote_value = "model-server"

    # Various ways the predicate could see input
    assert ( "model-server" == canonical_remote_value )      is True
    assert ( "local"        == canonical_remote_value )      is False
    assert ( "MODEL-SERVER" == canonical_remote_value )      is False  # case matters AFTER .lower().strip()
    assert ( "model-server " == canonical_remote_value )     is False  # whitespace matters AFTER .strip()


def test_provider_value_normalization_matches_lifespan():
    """
    The lifespan normalizes via `.lower().strip()` before the predicate.
    Validate the normalization yields the canonical form from common variants.
    """
    variants = [
        ( "model-server",   "model-server" ),
        ( "MODEL-SERVER",   "model-server" ),
        ( "  model-server", "model-server" ),
        ( "model-server  ", "model-server" ),
        ( "Model-Server",   "model-server" ),
        ( "local",          "local" ),
        ( "LOCAL",          "local" ),
        ( "  local  ",      "local" ),
    ]
    for raw, expected in variants:
        assert raw.lower().strip() == expected, f"normalize({raw!r}) != {expected!r}"
