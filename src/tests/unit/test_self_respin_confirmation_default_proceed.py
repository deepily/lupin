#!/usr/bin/env python3
"""
The BINDING-half safety for manager self-re-spin (store row 9e0678f6, amendment A
as Rick finally ruled it): the confirmation ask is observer-safe ONLY because it
carries response_default="yes" and every user-unreachable outcome resolves to
PROCEED. An AFK user must never cost the fleet a manager — the timeout answering
for the human IS the feature, not a degraded path.

TWO LAYERS, BOTH REAL:

1. The product's own timeout-default application, NotificationRepository.mark_expired
   (notification_repository.py:706-712): `if response_default: response_value =
   {"value": default, "source": "timeout_default"}`. This test drives the REAL method
   both ways — default present (applied) and default absent (skipped) — so the
   silent-inversion branch is covered by execution, not by reading.

2. The caller's obligation: offline, timeout, None and 503 are four spellings of
   "no human answered"; each MUST resolve to the default, and the default MUST be
   "yes". A must-fail control on each, plus the inversion: drop response_default and
   all four flip to ABORT — the exact silent failure that loses the manager.

Venue: :7999-eligible / local — MagicMock session, no DB, no server, no state.
"""
import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.rest.db.repositories.notification_repository import NotificationRepository

PROCEED = "proceed"
ABORT   = "abort"

# The four user-unreachable outcomes that must all resolve to the default.
UNREACHABLE = ( "offline", "timeout", "none", "http_503" )


# ── Layer 1: the REAL timeout-default application ──────────────────────────────

def _repo_with_fake_notification( response_default ):
    """A NotificationRepository whose get_by_id returns one fake, mutable notification."""
    repo = NotificationRepository( session=MagicMock() )
    note = SimpleNamespace( state="pending", response_default=response_default, response_value=None )
    repo.get_by_id = lambda _id: note
    return repo, note


def test_mark_expired_applies_yes_default_as_proceed():
    """response_default='yes' → timeout writes response_value yes → the seat proceeds."""
    repo, note = _repo_with_fake_notification( "yes" )
    repo.mark_expired( "any-id" )
    assert note.state == "expired"
    assert note.response_value == { "value": "yes", "source": "timeout_default" }


def test_mark_expired_missing_default_leaves_no_value_the_silent_inversion():
    """MUST-FAIL CONTROL — no response_default → the apply branch is SKIPPED, no value
    is written, and the timeout resolves to no-answer. This is the silent inversion:
    the ask that was meant to proceed instead aborts and the manager is lost."""
    repo, note = _repo_with_fake_notification( None )
    repo.mark_expired( "any-id" )
    assert note.state == "expired"
    assert note.response_value is None            # nothing applied → resolves to NOT-yes → ABORT


# ── Layer 2: the caller's resolution contract ──────────────────────────────────

def resolve_confirmation( outcome, response_default ):
    """
    The self-respin caller's obligation: turn an ask outcome into PROCEED / ABORT.

    Requires:
        - outcome is one of: "yes", "no", or a member of UNREACHABLE
        - response_default is "yes", "no", or None (missing)

    Ensures:
        - An explicit human "yes"/"no" is honored verbatim
        - Every user-unreachable outcome resolves to response_default
        - PROCEED iff the effective answer is "yes"; a missing default (None) can
          never be "yes", so unreachable outcomes ABORT — the inversion
    """
    if outcome == "yes":
        effective = "yes"
    elif outcome == "no":
        effective = "no"
    else:                                          # offline / timeout / none / http_503
        effective = response_default
    return PROCEED if effective == "yes" else ABORT


@pytest.mark.parametrize( "outcome", UNREACHABLE )
def test_each_unreachable_outcome_proceeds_with_yes_default( outcome ):
    """The four controls — offline, timeout, None, 503 each resolve to PROCEED."""
    assert resolve_confirmation( outcome, response_default="yes" ) == PROCEED


def test_explicit_human_no_aborts():
    """The ONE outcome that must abort: a human actually present and answering no."""
    assert resolve_confirmation( "no", response_default="yes" ) == ABORT


def test_explicit_human_yes_proceeds():
    assert resolve_confirmation( "yes", response_default="yes" ) == PROCEED


@pytest.mark.parametrize( "outcome", UNREACHABLE )
def test_missing_default_inverts_every_unreachable_outcome_to_abort( outcome ):
    """MUST-FAIL CONTROL — drop response_default and each unreachable outcome flips to
    ABORT. Pins the invariant: the safety is the default, and losing it is silent."""
    assert resolve_confirmation( outcome, response_default=None ) == ABORT


def test_contract_has_teeth_against_a_fail_closed_resolver():
    """A fail-closed resolver (treats every non-yes as abort, ignoring the default)
    passes the explicit cases but FAILS all four unreachable controls — proving the
    controls discriminate a correct resolver from a plausible wrong one."""
    def fail_closed( outcome, response_default ):
        return PROCEED if outcome == "yes" else ABORT

    assert fail_closed( "yes", "yes" ) == PROCEED                       # agrees on the happy path
    wrong = [ o for o in UNREACHABLE if fail_closed( o, "yes" ) != resolve_confirmation( o, "yes" ) ]
    assert wrong == list( UNREACHABLE )                                 # diverges on every control


if __name__ == "__main__":
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
