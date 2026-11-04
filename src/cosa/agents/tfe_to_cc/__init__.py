"""
Prompt builders and output parsers for the Claude Code variant of the test fix expediter.

The package holds prompt builders and parsers only. Only the scripts under src/scripts named
tfe_to_cc_* use it; the TFE orchestrator does not import it.

No engine flag exists: no INI key selects between the SDK and Claude Code, and no orchestrator
or job class is built. Whether to build the engine or retire the package is not decided.

Decision record: src/docs/decisions/2026.04.19-tfe-to-cc-parallel-claude-code-engine.md
Live test of the first phase: src/rnd/v0.1.6/2026.04.10-test-fix-expediter/20-tfe-to-cc-phase1-live-test.md
"""
