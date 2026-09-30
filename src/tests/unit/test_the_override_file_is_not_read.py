#!/usr/bin/env python3
"""
A seat that rewrites the old override file must not be able to change policy (row 80513825).

THE DEFECT. Every writer on this host is one UID, so the JSON file under
`$LUPIN_FLOW_RATIO_DIR` could be rewritten by anything, and the manager-pull rescission,
approver allowlist and enforcement flag all read it. Rick's ruling was to put the settings
behind login; the file is now read once per database at boot and never again.

THE WITNESS. Each arm writes the file the way a seat would — directly, bypassing the setter —
with values that would flip the policy, and asserts the effective policy did not move. It
names no module internals beyond the public readers and the env var, so against the pre-fix
code it fails on the ASSERTION (the file's values took effect), not on a missing attribute.
"""
import json

import pytest

import cosa.rest.task_approval_settings as approval


@pytest.fixture
def settings_dir( tmp_path, monkeypatch ):
    monkeypatch.setenv( "LUPIN_FLOW_RATIO_DIR", str( tmp_path ) )
    return tmp_path


def _write_file( directory, body ):
    ( directory / "task-approval-settings.json" ).write_text( json.dumps( body ) )


def test_a_direct_file_write_cannot_switch_enforcement_on( settings_dir ):
    before = approval.get_enforcement_active()
    _write_file( settings_dir, { "enforcement_active": not before } )
    assert approval.get_enforcement_active() is before


def test_a_direct_file_write_cannot_lift_the_manager_pull_rescission( settings_dir ):
    before = approval.get_manager_pull_disabled()
    _write_file( settings_dir, { "manager_pull_disabled": not before } )
    assert approval.get_manager_pull_disabled() is before


def test_a_direct_file_write_with_a_valid_stamp_cannot_lift_the_rescission( settings_dir ):
    """
    The old stamp only stopped a hand-edit: a writer that can compute it (any process holding
    the signing key, which the server containers and a seat's test run both do) got through.
    Signed with the module's own helper, the file below is exactly what the old validated
    writer would have produced, and it must still change nothing.
    """
    assert approval._stamp_secret() is not None, "no signing key here, so this arm would be vacuous"
    before = approval.get_manager_pull_disabled()
    body   = { "manager_pull_disabled": not before }
    body[ approval.STAMP_KEY ] = approval._expected_stamp( body )
    _write_file( settings_dir, body )
    assert approval.get_manager_pull_disabled() is before


def test_a_direct_file_write_cannot_add_an_approver( settings_dir ):
    before = approval.get_approvers()
    _write_file( settings_dir, { "approvers": [ "mallory" ] } )
    assert approval.get_approvers() == before
    assert "mallory" not in approval.get_approvers()


def test_a_direct_file_write_cannot_add_an_approver_account( settings_dir ):
    before = approval.get_approver_accounts()
    _write_file( settings_dir, { "approver_accounts": { "mallory@example.com": "rick" } } )
    assert approval.get_approver_accounts() == before
