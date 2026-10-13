"""TFE-to-CC: Claude Code engine variant of the first and third TFE phases.

Design: src/docs/decisions/2026.04.19-tfe-to-cc-parallel-claude-code-engine.md
Live test of the first phase: src/rnd/v0.1.6/2026.04.10-test-fix-expediter/20-tfe-to-cc-phase1-live-test.md

This module is a peer to the SDK-based TFE path. Engine selection will be a runtime
choice through two INI flags (future work):
    Example:
        test fix expediter phase 1 engine = sdk | claude_code
        test fix expediter phase 3 engine = sdk | claude_code
"""
