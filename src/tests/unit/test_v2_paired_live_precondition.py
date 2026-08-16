"""Unit — the paired-run precondition PROVES the v1 server is the pinned tree, not merely
that LUPIN_V1_ARM_BASE_URL is SET (row 275cb0b9 follow-up, the sharper half).

This is the CAN-FAIL control: if the sha assertion is removed from
`_require_v1_live_seam_and_worktree`, `test_..._refuses_a_wrong_tree_server` stops refusing
and goes RED. A set-ness-only precondition passes a main-tree server identically, which is
the exact false green on the go/no-go gate this guards.

Runs on :7999 — fully mocked, no live server (read_running_server_sha is monkeypatched, so
no socket is opened). Venue: :7999 unit.
"""
import importlib.util
import os

import pytest


# Load the integration module by FILE PATH (not dotted name — no package-path assumption),
# under a unique module name so it never collides with pytest's own collection of the same
# file. Its top-level puts src/scripts on sys.path, so v1_eval_arm imports right after.
_LUPIN_ROOT = os.environ.get( "LUPIN_ROOT" )
_LIVE_PATH  = os.path.join( _LUPIN_ROOT, "src", "tests", "integration", "test_v2_paired_live.py" ) if _LUPIN_ROOT else None

_spec = importlib.util.spec_from_file_location( "paired_live_under_test", _LIVE_PATH ) if _LIVE_PATH else None
live  = importlib.util.module_from_spec( _spec ) if _spec else None
if _spec:
    _spec.loader.exec_module( live )

import v1_eval_arm   # noqa: E402 - importable only after live's top-level extended sys.path

pytestmark = pytest.mark.skipif( live is None, reason="LUPIN_ROOT unset — cannot locate the paired-live module" )

_ANY_URL = "http://v1-arm:9999"


def test_precondition_refuses_a_wrong_tree_server_naming_the_sha( monkeypatch ):
    # A server that reports a NON-pin sha (e.g. the main tree) must be REFUSED even though
    # the env var is set — and the refusal must NAME the sha it saw (rule 2).
    monkeypatch.setenv( "LUPIN_V1_ARM_BASE_URL", _ANY_URL )
    monkeypatch.setattr( v1_eval_arm, "read_running_server_sha", lambda base: "deadbeefdeadbeef" )
    with pytest.raises( live.PairedPreconditionMissing ) as exc:
        live._require_v1_live_seam_and_worktree()
    message = str( exc.value )
    assert "deadbeef"           in message   # names the WRONG sha it saw
    assert v1_eval_arm.V1_PIN_SHA in message   # and the pin it wanted


def test_precondition_passes_when_server_reports_the_pin( monkeypatch ):
    # The pinned-worktree server (reports the pin) is accepted — no raise. This is the
    # can-fail proof's other half: the guard is not merely "always refuse".
    monkeypatch.setenv( "LUPIN_V1_ARM_BASE_URL", _ANY_URL )
    monkeypatch.setattr( v1_eval_arm, "read_running_server_sha", lambda base: v1_eval_arm.V1_PIN_SHA )
    live._require_v1_live_seam_and_worktree()   # no exception == pinned tree accepted


def test_precondition_still_refuses_when_base_url_unset( monkeypatch ):
    # The original set-ness refusal still stands (the sha probe is ADDED, not a replacement).
    monkeypatch.delenv( "LUPIN_V1_ARM_BASE_URL", raising=False )
    with pytest.raises( live.PairedPreconditionMissing ):
        live._require_v1_live_seam_and_worktree()
