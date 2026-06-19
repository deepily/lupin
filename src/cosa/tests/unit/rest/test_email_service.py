"""
Unit tests for cosa.rest.email_service.

Both external seams are mocked: ConfigurationManager ( config_mgr ) and smtplib —
so NO real config reads, NO real SMTP connections, NO network. Covers:

    - send_verification_email   ( URL/body assembly, user_name default )
    - send_password_reset_email ( URL/body assembly, user_name default )
    - _send_email               ( disabled short-circuit, TLS/creds variants, failure )
    - test_email_configuration  ( TLS/creds variants, failure )
"""

import unittest
from unittest.mock import patch

from cosa.rest.email_service import (
    send_verification_email,
    send_password_reset_email,
    _send_email,
    test_email_configuration,
)


def _cfg( overrides ):
    """
    Requires:
        - overrides is a dict of config-key -> value

    Ensures:
        - Returns a config_mgr.get-compatible side_effect that returns the override
          for a known key, else the caller-supplied default
    """
    def get( key, default=None, return_type=None ):
        return overrides.get( key, default )
    return get


class TestSendVerificationEmail( unittest.TestCase ):
    """
    Tests for send_verification_email().

    Ensures:
        - Builds the verification URL with the token
        - Uses the supplied user_name, defaulting to "User"
        - Delegates to _send_email and returns its result
    """

    def test_with_user_name( self ):
        """
        Ensures:
            - Supplied user_name appears in the body; token in the URL
        """
        with patch( 'cosa.rest.email_service.config_mgr' ) as mock_cfg, \
             patch( 'cosa.rest.email_service._send_email', return_value=True ) as mock_send:
            mock_cfg.get.return_value = "http://base"
            result = send_verification_email( "u@e.com", "tok123", "John" )
            self.assertTrue( result )
            to_email, subject, body = mock_send.call_args[0]
            self.assertEqual( to_email, "u@e.com" )
            self.assertIn( "Verify Your Lupin Account", subject )
            self.assertIn( "Hi John", body )
            self.assertIn( "token=tok123", body )

    def test_without_user_name_defaults_to_user( self ):
        """
        Ensures:
            - Omitted user_name yields "Hi User" in the body
        """
        with patch( 'cosa.rest.email_service.config_mgr' ) as mock_cfg, \
             patch( 'cosa.rest.email_service._send_email', return_value=True ) as mock_send:
            mock_cfg.get.return_value = "http://base"
            send_verification_email( "u@e.com", "tok123" )
            _, _, body = mock_send.call_args[0]
            self.assertIn( "Hi User", body )


class TestSendPasswordResetEmail( unittest.TestCase ):
    """
    Tests for send_password_reset_email().

    Ensures:
        - Builds the reset URL with the token
        - Uses the supplied user_name, defaulting to "User"
    """

    def test_with_user_name( self ):
        """
        Ensures:
            - Supplied user_name + reset token appear in subject/body
        """
        with patch( 'cosa.rest.email_service.config_mgr' ) as mock_cfg, \
             patch( 'cosa.rest.email_service._send_email', return_value=True ) as mock_send:
            mock_cfg.get.return_value = "http://base"
            result = send_password_reset_email( "u@e.com", "rtok456", "Jane" )
            self.assertTrue( result )
            to_email, subject, body = mock_send.call_args[0]
            self.assertIn( "Reset Your Lupin Password", subject )
            self.assertIn( "Hi Jane", body )
            self.assertIn( "token=rtok456", body )

    def test_without_user_name_defaults_to_user( self ):
        """
        Ensures:
            - Omitted user_name yields "Hi User" in the body
        """
        with patch( 'cosa.rest.email_service.config_mgr' ) as mock_cfg, \
             patch( 'cosa.rest.email_service._send_email', return_value=True ) as mock_send:
            mock_cfg.get.return_value = "http://base"
            send_password_reset_email( "u@e.com", "rtok456" )
            _, _, body = mock_send.call_args[0]
            self.assertIn( "Hi User", body )


class TestSendEmailInternal( unittest.TestCase ):
    """
    Tests for _send_email().

    Ensures:
        - Disabled config short-circuits to True without SMTP
        - TLS + credentials path logs in and sends
        - Non-TLS + no-credentials path skips starttls/login
        - SMTP exceptions are swallowed -> False
    """

    def test_disabled_returns_true_without_smtp( self ):
        """
        Ensures:
            - send-email-disabled returns True without touching smtplib
        """
        with patch( 'cosa.rest.email_service.config_mgr' ) as mock_cfg, \
             patch( 'cosa.rest.email_service.smtplib' ) as mock_smtplib:
            mock_cfg.get.side_effect = _cfg( { "send email enabled": False } )
            self.assertTrue( _send_email( "a@b.com", "subj", "body" ) )
            mock_smtplib.SMTP.assert_not_called()

    def test_tls_with_credentials_sends( self ):
        """
        Ensures:
            - TLS enabled + credentials -> starttls + login + send_message + quit
        """
        with patch( 'cosa.rest.email_service.config_mgr' ) as mock_cfg, \
             patch( 'cosa.rest.email_service.smtplib' ) as mock_smtplib:
            mock_cfg.get.side_effect = _cfg( {
                "send email enabled": True, "smtp use tls": True,
                "smtp host": "host", "smtp port": 587,
                "smtp username": "u", "smtp password": "p", "smtp from email": "from@x",
            } )
            server = mock_smtplib.SMTP.return_value
            self.assertTrue( _send_email( "a@b.com", "subj", "body" ) )
            server.starttls.assert_called_once()
            server.login.assert_called_once_with( "u", "p" )
            server.send_message.assert_called_once()
            server.quit.assert_called_once()

    def test_no_tls_no_credentials_sends( self ):
        """
        Ensures:
            - TLS disabled + no creds -> no starttls, no login, still sends
        """
        with patch( 'cosa.rest.email_service.config_mgr' ) as mock_cfg, \
             patch( 'cosa.rest.email_service.smtplib' ) as mock_smtplib:
            mock_cfg.get.side_effect = _cfg( {
                "send email enabled": True, "smtp use tls": False,
                "smtp host": "host", "smtp port": 25,
                "smtp username": None, "smtp password": None, "smtp from email": "from@x",
            } )
            server = mock_smtplib.SMTP.return_value
            self.assertTrue( _send_email( "a@b.com", "subj", "body" ) )
            server.starttls.assert_not_called()
            server.login.assert_not_called()
            server.send_message.assert_called_once()

    def test_smtp_exception_returns_false( self ):
        """
        Ensures:
            - An SMTP connection error is swallowed -> False
        """
        with patch( 'cosa.rest.email_service.config_mgr' ) as mock_cfg, \
             patch( 'cosa.rest.email_service.smtplib' ) as mock_smtplib:
            mock_cfg.get.side_effect = _cfg( {
                "send email enabled": True, "smtp use tls": True,
                "smtp host": "host", "smtp port": 587,
                "smtp username": "u", "smtp password": "p", "smtp from email": "from@x",
            } )
            mock_smtplib.SMTP.side_effect = OSError( "connection refused" )
            self.assertFalse( _send_email( "a@b.com", "subj", "body" ) )


class TestEmailConfiguration( unittest.TestCase ):
    """
    Tests for test_email_configuration().

    Ensures:
        - TLS + creds connection path succeeds
        - Non-TLS no-creds path succeeds
        - Connection failure returns False
    """

    def test_tls_with_credentials_ok( self ):
        """
        Ensures:
            - TLS + creds -> starttls + login + quit -> True
        """
        with patch( 'cosa.rest.email_service.config_mgr' ) as mock_cfg, \
             patch( 'cosa.rest.email_service.smtplib' ) as mock_smtplib:
            mock_cfg.get.side_effect = _cfg( {
                "smtp use tls": True, "smtp host": "host", "smtp port": 587,
                "smtp username": "u", "smtp password": "p",
            } )
            server = mock_smtplib.SMTP.return_value
            self.assertTrue( test_email_configuration() )
            server.starttls.assert_called_once()
            server.login.assert_called_once_with( "u", "p" )
            server.quit.assert_called_once()

    def test_no_tls_no_credentials_ok( self ):
        """
        Ensures:
            - Non-TLS + no creds -> no starttls/login -> True
        """
        with patch( 'cosa.rest.email_service.config_mgr' ) as mock_cfg, \
             patch( 'cosa.rest.email_service.smtplib' ) as mock_smtplib:
            mock_cfg.get.side_effect = _cfg( {
                "smtp use tls": False, "smtp host": "host", "smtp port": 25,
                "smtp username": None, "smtp password": None,
            } )
            server = mock_smtplib.SMTP.return_value
            self.assertTrue( test_email_configuration() )
            server.starttls.assert_not_called()
            server.login.assert_not_called()

    def test_connection_failure_returns_false( self ):
        """
        Ensures:
            - A connection error returns False
        """
        with patch( 'cosa.rest.email_service.config_mgr' ) as mock_cfg, \
             patch( 'cosa.rest.email_service.smtplib' ) as mock_smtplib:
            mock_cfg.get.side_effect = _cfg( { "smtp use tls": True, "smtp host": "host", "smtp port": 587 } )
            mock_smtplib.SMTP.side_effect = OSError( "connection refused" )
            self.assertFalse( test_email_configuration() )


if __name__ == "__main__":
    unittest.main()
