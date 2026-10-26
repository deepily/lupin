"""
The notifications router tolerates a missing manager-badge helper.

If the voice persona router cannot supply its two badge helpers, the notifications router must
still import, with both names set to None. A fresh copy of the module is executed under a probe
name so the real module that other tests use is not reloaded.
"""

import importlib.util
import sys
import types
from pathlib import Path

import cosa.rest.routers.notifications as real_notifications

_PROBE_NAME = "cosa.rest.routers._notifications_badge_probe"


def _load_copy():
    path = Path( real_notifications.__file__ )
    spec = importlib.util.spec_from_file_location( _PROBE_NAME, path )
    mod  = importlib.util.module_from_spec( spec )
    spec.loader.exec_module( mod )
    return mod


def test_the_real_module_has_both_badge_helpers():
    assert callable( real_notifications._resolve_manager_persona )
    assert callable( real_notifications._manager_badge_for )


def test_a_voice_persona_router_without_the_helpers_leaves_both_names_none( monkeypatch ):
    empty = types.ModuleType( "cosa.rest.routers.voice_persona" )
    monkeypatch.setitem( sys.modules, "cosa.rest.routers.voice_persona", empty )

    probe = _load_copy()

    assert probe._resolve_manager_persona is None
    assert probe._manager_badge_for       is None
    assert probe.router is not None, "the import fallback must not stop the module from building its router"
