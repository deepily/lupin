"""TFE-to-CC: Claude Code engine variant of the first and third TFE phases.

Design: src/rnd/v0.1.6/2026.04.10-test-fix-expediter/19-tfe-to-cc-design.md
Live test of the first phase: src/rnd/v0.1.6/2026.04.10-test-fix-expediter/20-tfe-to-cc-phase1-live-test.md

This module is a peer to the SDK-based TFE path. Engine selection will be a runtime
choice through two INI flags (future work), one for the first phase and one for the
third. Each takes the value sdk or claude_code. The design document names both flags.
"""
