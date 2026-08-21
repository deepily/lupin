#!/usr/bin/env python3
"""
Mock auth hands out a UUID user id, so scoped job ids validate (row befeba88).

⚠️ THE DEFECT WAS SILENT AND HAD BEEN FOR A WHILE. Under AUTH_MODE=mock the user id
was the system id — "interactive_job_tester_8e32". The ordinary API path scopes a job
id as "{sha256}::{user_id}" (`generate_user_scoped_hash`), and
`AsyncNotificationRequest`'s job_id pattern only accepts a UUID after the "::". So
every queue notification under mock auth raised a validation error, which a bare
`except Exception` printed and swallowed: 530 occurrences in one baseline log, runs
completing normally, and an environment that looked like it had working notifications
and had none.

SCOPE, per Tiberius's correction on the row: this fires only where AUTH_MODE=mock is
deliberately set (the v1 baseline arm's launcher). :7999 and :8000 run JWT, where the
user id is already the database row's UUID. Nobody was debugging blind.

THE FIX RULED (Mr Radio, 2026-08-21): mint the id, do not widen the validator. Teaching
one more pattern to tolerate a second id shape leaves the shapes different; minting
makes mock and JWT agree.
"""

import asyncio
import unittest
import uuid

from cosa.rest.user_id_generator import email_to_user_uuid, email_to_system_id
from cosa.rest.auth import verify_mock_token
from cosa.rest.queue_extensions import UserJobTracker
from lupin_cli.notifications.notification_models import AsyncNotificationRequest

# A real SHA256-shaped base hash — the pattern requires 64 hex characters.
_BASE_HASH = "a" * 64
_EMAIL     = "interactive_job_tester_8e32@generated.local"


class TestTheMintedIdIsAUuid( unittest.TestCase ):

    def test_it_is_a_parseable_uuid( self ):
        minted = email_to_user_uuid( _EMAIL )
        self.assertEqual( str( uuid.UUID( minted ) ), minted )

    def test_the_same_email_always_mints_the_same_id( self ):
        """No table, no database, no per-process state — the id must survive a restart."""
        self.assertEqual( email_to_user_uuid( _EMAIL ), email_to_user_uuid( _EMAIL ) )

    def test_case_and_surrounding_space_do_not_change_it( self ):
        self.assertEqual( email_to_user_uuid( "  INTERACTIVE_Job_Tester_8e32@Generated.Local " ),
                          email_to_user_uuid( _EMAIL ) )

    def test_two_emails_do_not_collide( self ):
        self.assertNotEqual( email_to_user_uuid( _EMAIL ),
                             email_to_user_uuid( "someone_else@generated.local" ) )

    def test_an_email_with_no_at_sign_is_refused( self ):
        with self.assertRaises( ValueError ):
            email_to_user_uuid( "not-an-email" )

    def test_an_empty_email_is_refused( self ):
        with self.assertRaises( ValueError ):
            email_to_user_uuid( "" )


class TestAScopedJobIdUnderMockAuthValidates( unittest.TestCase ):
    """
    The end-to-end shape, assembled the way the ordinary API path assembles it.
    """

    def setUp( self ):
        self.tracker = UserJobTracker()
        self.decoded = asyncio.run( verify_mock_token( f"mock_token_email_{_EMAIL}" ) )

    def test_mock_auth_returns_a_uuid_user_id( self ):
        for field in ( "uid", "user_id", "sub" ):
            with self.subTest( field=field ):
                self.assertEqual( str( uuid.UUID( self.decoded[ field ] ) ), self.decoded[ field ] )

    def test_the_scoped_job_id_is_accepted_by_the_notification_model( self ):
        scoped = self.tracker.generate_user_scoped_hash( _BASE_HASH, self.decoded[ "uid" ] )
        request = AsyncNotificationRequest( message="queue update", job_id=scoped )
        self.assertEqual( request.job_id, scoped )

    def test_the_OLD_shape_is_still_rejected( self ):
        """
        CONTROL, and the red-on-revert arm. Scope the same hash with the system id the
        mock path used to hand out and the model refuses it — which is the failure that
        was being caught, printed and dropped 530 times a run. If this ever passes,
        somebody widened the validator instead of minting the id.
        """
        from pydantic import ValidationError
        old_shape = self.tracker.generate_user_scoped_hash( _BASE_HASH, email_to_system_id( _EMAIL ) )
        with self.assertRaises( ValidationError ):
            AsyncNotificationRequest( message="queue update", job_id=old_shape )

    def test_the_system_id_derivation_is_untouched( self ):
        """
        The minting must not disturb what `get_user_info` is keyed on. `email_to_system_id`
        still runs on the token's email and still adds its own 4-hex suffix, and the
        resolved user still carries the "@generated.local" email the mock path invents
        for an unknown system id. Only the id handed OUT became a UUID.
        """
        self.assertEqual( email_to_system_id( _EMAIL ), "interactive_job_tester_8e32_7cf9" )
        self.assertEqual( self.decoded[ "email" ], "interactive_job_tester_8e32_7cf9@generated.local" )

    def test_the_legacy_token_format_mints_a_uuid_too( self ):
        """
        `mock_token_<system_id>` carries no email, so the id is minted from the one the
        mock path generates for it. It is a UUID and it is stable.

        ⚠️ IT IS A DIFFERENT USER FROM THE EMAIL-FORM TOKEN ABOVE, and that is
        PRE-EXISTING, not something this change introduced: the email form runs its
        address through `email_to_system_id` first, which appends a hash suffix, so
        "…_8e32@generated.local" resolves to system id "…_8e32_7cf9". Asserting the two
        forms agree would be asserting a round trip that has never existed.
        """
        legacy = asyncio.run( verify_mock_token( "mock_token_interactive_job_tester_8e32" ) )
        self.assertEqual( str( uuid.UUID( legacy[ "uid" ] ) ), legacy[ "uid" ] )
        self.assertEqual( legacy[ "uid" ],
                          email_to_user_uuid( "interactive_job_tester_8e32@generated.local" ) )
        self.assertNotEqual( legacy[ "uid" ], self.decoded[ "uid" ] )


if __name__ == "__main__":
    unittest.main()
