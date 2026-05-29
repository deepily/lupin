"""TFE-to-CC: Claude Code engine variant for TFE Phases 1 + 3.

Design: src/rnd/v0.1.6/2026.04.10-test-fix-expediter/19-tfe-to-cc-design.md
Phase 1 live test: src/rnd/v0.1.6/2026.04.10-test-fix-expediter/20-tfe-to-cc-phase1-live-test.md

This module is a peer to the SDK-based TFE path. Selection between engines
is runtime via INI flags (future work):
    test fix expediter phase 1 engine = sdk | claude_code
    test fix expediter phase 3 engine = sdk | claude_code
"""
