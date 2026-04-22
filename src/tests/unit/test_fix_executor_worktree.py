"""
Unit tests for Bug 9 worktree plumbing in FixExecutor + BFE orchestrator.

Verifies:
  - FixExecutor accepts worktree_cwd param and stores it on the instance
  - BFE's _build_coder_options + _build_tester_options respect the
    orchestrator's _worktree_cwd state (set by worktree_scope context manager)
  - TFE's _build_tfe_coder_options + _build_tfe_tester_options do the same

These tests do NOT exercise the actual SDK or git subprocess — they verify
the cwd plumbing only. Live behavior is covered by test_worktree_context.py
and (eventually) a scheduled live E2E.

See: src/rnd/v0.1.6/2026.04.16-bug-9-worktree-isolation.md
"""

import inspect
from unittest.mock import MagicMock, patch

import pytest


# ===========================================================================
# FixExecutor: constructor accepts worktree_cwd, stores on instance
# ===========================================================================

class TestFixExecutorWorktreeCwd:
    """FixExecutor stores worktree_cwd for the orchestrator's consumption."""

    def test_constructor_accepts_worktree_cwd_param( self ):
        from cosa.agents.shared.fix_executor import FixExecutor
        sig = inspect.signature( FixExecutor.__init__ )
        assert "worktree_cwd" in sig.parameters, \
            "FixExecutor must accept worktree_cwd param (Bug 9)"
        assert sig.parameters[ "worktree_cwd" ].default is None, \
            "worktree_cwd default must be None for backward compatibility"

    def test_constructor_defaults_worktree_cwd_to_none( self ):
        """Default behavior: no worktree_cwd = None (pre-Bug-9 behavior)."""
        import cosa.agents.bug_fix_expediter.prompts.fix  # noqa: register 'bfe' key
        from cosa.agents.shared.fix_executor import FixExecutor

        cfg = MagicMock( max_fix_attempts=1, wall_clock_timeout_secs=30,
                         feedback_timeout_seconds=10 )
        ex = FixExecutor(
            config                = cfg,
            fix_context           = MagicMock(),
            job_id                = "test-job",
            prompt_builder_key    = "bfe",
            voice_io_module       = MagicMock(),
            cosa_interface_module = MagicMock(),
            notify_fn             = MagicMock(),
            is_cancelled_fn       = lambda: False,
            delegate_to_coder_fn  = MagicMock(),
            verify_fix_fn         = MagicMock(),
        )
        assert ex.worktree_cwd is None

    def test_constructor_stores_worktree_cwd_when_provided( self ):
        """When worktree_cwd is passed, FixExecutor stores it verbatim."""
        import cosa.agents.bug_fix_expediter.prompts.fix  # noqa
        from cosa.agents.shared.fix_executor import FixExecutor

        cfg = MagicMock( max_fix_attempts=1, wall_clock_timeout_secs=30,
                         feedback_timeout_seconds=10 )
        ex = FixExecutor(
            config                = cfg,
            fix_context           = MagicMock(),
            job_id                = "test-job",
            prompt_builder_key    = "bfe",
            voice_io_module       = MagicMock(),
            cosa_interface_module = MagicMock(),
            notify_fn             = MagicMock(),
            is_cancelled_fn       = lambda: False,
            delegate_to_coder_fn  = MagicMock(),
            verify_fix_fn         = MagicMock(),
            worktree_cwd          = "/tmp/isolated-wt",
        )
        assert ex.worktree_cwd == "/tmp/isolated-wt"


# ===========================================================================
# BFEOrchestrator: _build_coder_options + _build_tester_options respect
# self._worktree_cwd when set
# ===========================================================================

class TestBFEOrchestratorCwdPlumbing:
    """When orchestrator._worktree_cwd is set, SDK options use that path."""

    def _make_bfe_orchestrator( self ):
        """Construct a BFEOrchestrator without live config/proxy dependencies."""
        from cosa.agents.bug_fix_expediter.orchestrator import BFEOrchestrator
        cfg = MagicMock(
            worker_model          = "claude-sonnet-4-6",
            max_fix_attempts      = 2,
            budget_usd            = 1.0,
            trust_mode            = "shadow",
        )
        # Bypass __init__ proxy init (ignore ImportError/Exception branches)
        orch = BFEOrchestrator(
            dead_job_context = MagicMock(),
            extra_context    = "",
            config           = cfg,
            session_id       = "sess-001",
            job_id           = "bfe-test",
            debug            = False,
        )
        return orch

    def test_worktree_scope_method_exists( self ):
        from cosa.agents.bug_fix_expediter.orchestrator import BFEOrchestrator
        assert hasattr( BFEOrchestrator, "worktree_scope" )

    def test_worktree_cwd_default_is_none( self ):
        orch = self._make_bfe_orchestrator()
        assert orch._worktree_cwd is None

    def test_coder_options_use_project_root_when_worktree_cwd_is_none( self ):
        """Baseline: no worktree → _build_coder_options uses project root."""
        orch = self._make_bfe_orchestrator()
        orch._worktree_cwd = None

        fake_root = "/fake/project/root"
        with patch( "cosa.agents.bug_fix_expediter.orchestrator.cu.get_project_root",
                    return_value=fake_root ):
            opts = orch._build_coder_options( guard=MagicMock(), cosa_interface=MagicMock() )

        assert opts.cwd == fake_root

    def test_coder_options_use_worktree_cwd_when_set( self ):
        """Bug 9: when orchestrator._worktree_cwd set, Coder SDK runs in that cwd."""
        orch = self._make_bfe_orchestrator()
        orch._worktree_cwd = "/tmp/bfe-worktree"

        with patch( "cosa.agents.bug_fix_expediter.orchestrator.cu.get_project_root",
                    return_value="/fake/project/root" ):
            opts = orch._build_coder_options( guard=MagicMock(), cosa_interface=MagicMock() )

        assert opts.cwd == "/tmp/bfe-worktree"

    def test_tester_options_use_worktree_cwd_when_set( self ):
        """Bug 9: Tester options also respect worktree_cwd."""
        orch = self._make_bfe_orchestrator()
        orch._worktree_cwd = "/tmp/bfe-worktree-2"

        with patch( "cosa.agents.bug_fix_expediter.orchestrator.cu.get_project_root",
                    return_value="/fake/project/root" ):
            opts = orch._build_tester_options( guard=MagicMock(), cosa_interface=MagicMock() )

        assert opts.cwd == "/tmp/bfe-worktree-2"


# ===========================================================================
# TFEOrchestrator: parity — _build_tfe_coder_options + _build_tfe_tester_options
# ===========================================================================

class TestTFEOrchestratorCwdPlumbing:
    """Same contract as BFE but on the TFE orchestrator."""

    def _make_tfe_orchestrator( self ):
        from cosa.agents.test_fix_expediter.orchestrator import TFEOrchestrator
        cfg = MagicMock(
            worker_model       = "claude-sonnet-4-6",
            max_fix_attempts   = 2,
            budget_usd         = 1.0,
        )
        orch = TFEOrchestrator(
            remediation_context = MagicMock(),
            config              = cfg,
            user_id             = "u1",
            user_email          = "u1@example.com",
            session_id          = "sess-1",
            job_id              = "tfe-test",
            dry_run             = True,
            debug               = False,
        )
        return orch

    def test_worktree_scope_method_exists( self ):
        from cosa.agents.test_fix_expediter.orchestrator import TFEOrchestrator
        assert hasattr( TFEOrchestrator, "worktree_scope" )

    def test_worktree_cwd_default_is_none( self ):
        orch = self._make_tfe_orchestrator()
        assert orch._worktree_cwd is None

    def test_tfe_coder_options_use_project_root_when_none( self ):
        orch = self._make_tfe_orchestrator()
        orch._worktree_cwd = None

        fake_root = "/fake/tfe/root"
        with patch( "cosa.agents.test_fix_expediter.orchestrator.cu.get_project_root",
                    return_value=fake_root ):
            opts = orch._build_tfe_coder_options( guard=MagicMock(), cosa_interface_module=MagicMock() )

        assert opts.cwd == fake_root

    def test_tfe_coder_options_use_worktree_cwd( self ):
        orch = self._make_tfe_orchestrator()
        orch._worktree_cwd = "/tmp/tfe-worktree"

        with patch( "cosa.agents.test_fix_expediter.orchestrator.cu.get_project_root",
                    return_value="/fake/project/root" ):
            opts = orch._build_tfe_coder_options( guard=MagicMock(), cosa_interface_module=MagicMock() )

        assert opts.cwd == "/tmp/tfe-worktree"

    def test_tfe_tester_options_use_worktree_cwd( self ):
        orch = self._make_tfe_orchestrator()
        orch._worktree_cwd = "/tmp/tfe-worktree-2"

        with patch( "cosa.agents.test_fix_expediter.orchestrator.cu.get_project_root",
                    return_value="/fake/project/root" ):
            opts = orch._build_tfe_tester_options( guard=MagicMock(), cosa_interface_module=MagicMock() )

        assert opts.cwd == "/tmp/tfe-worktree-2"
