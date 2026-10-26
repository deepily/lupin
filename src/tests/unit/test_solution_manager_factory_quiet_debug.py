"""
Unit tests for the factory's debug-without-verbose arms.

With debug on and verbose off, the factory prints its creation line but not the configuration
detail, which can hold sensitive values. The Postgres manager class is faked.
"""

import sys
import types
from unittest.mock import MagicMock

from cosa.memory.solution_manager_factory import ManagerType, SolutionSnapshotManagerFactory

_PG_MOD = "cosa.memory.postgres_solution_manager"


def _fake_pg( monkeypatch ):
    """Install a fake module whose manager class returns a sentinel; return the class mock."""
    mod = types.ModuleType( _PG_MOD )
    mod.PostgresSolutionManager = MagicMock( return_value="manager" )
    monkeypatch.setitem( sys.modules, _PG_MOD, mod )
    return mod.PostgresSolutionManager


def test_debug_without_verbose_prints_the_creation_line_only( monkeypatch, capsys ):
    """create_manager: the creation line prints, the configuration dict does not."""
    cls = _fake_pg( monkeypatch )
    got = SolutionSnapshotManagerFactory.create_manager( ManagerType.POSTGRES, { "secret": "s3" }, debug=True, verbose=False )
    out = capsys.readouterr().out
    assert got == "manager" and "Creating postgres solution snapshot manager" in out
    assert "Configuration:" not in out and "s3" not in out
    cls.assert_called_once_with( { "secret": "s3" }, True, False )


def test_debug_with_verbose_prints_the_configuration( monkeypatch, capsys ):
    """The control for the arm above: verbose adds the configuration line."""
    _fake_pg( monkeypatch )
    SolutionSnapshotManagerFactory.create_manager( ManagerType.POSTGRES, { "k": "v" }, debug=True, verbose=True )
    assert "Configuration: {'k': 'v'}" in capsys.readouterr().out


def test_from_config_manager_debug_without_verbose_hides_the_detail( monkeypatch, capsys ):
    """create_from_config_manager: the creation line prints, the manager-type detail does not."""
    _fake_pg( monkeypatch )
    cfg = MagicMock()
    cfg.get.side_effect = lambda key, default=None, return_type=None: "postgres" if key.endswith( "manager type" ) else default
    got = SolutionSnapshotManagerFactory.create_from_config_manager( cfg, debug=True, verbose=False )
    out = capsys.readouterr().out
    assert got == "manager" and "from ConfigurationManager" in out
    assert "Performance monitoring" not in out and "Manager type:" not in out


def test_from_config_manager_verbose_adds_the_detail( monkeypatch, capsys ):
    """The control for the arm above: verbose prints the type and the monitoring flag."""
    _fake_pg( monkeypatch )
    cfg = MagicMock()
    cfg.get.side_effect = lambda key, default=None, return_type=None: "postgres" if key.endswith( "manager type" ) else default
    SolutionSnapshotManagerFactory.create_from_config_manager( cfg, debug=True, verbose=True )
    out = capsys.readouterr().out
    assert "Manager type: postgres" in out and "Performance monitoring: True" in out
