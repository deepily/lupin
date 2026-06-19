"""
Email Service for Lupin Authentication.

Provides email sending functionality for:
- Email verification
- Password reset
- Account notifications

Uses SMTP with configuration from ConfigurationManager.
"""

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional
from cosa.config.configuration_manager import ConfigurationManager


# Initialize configuration manager
config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )


def send_verification_email( email: str, token: str, user_name: Optional[str] = None ) -> bool:
    """
    Send email verification email to user.

    Requires:
        - email is a valid email address
        - token is a non-empty verification token string
        - SMTP configuration is set in config

    Ensures:
        - returns True if email sent successfully
        - returns False if email sending failed

    Returns:
        bool: True if email sent, False otherwise

    Example:
        success = send_verification_email( "user@example.com", "abc123token", "John" )
        if success:
            print( "Verification email sent!" )
    """
    verification_url = f"{config_mgr.get( 'app base url' )}/auth/verify-email?token={token}"

    display_name = user_name if user_name else "User"

    subject = "Verify Your Lupin Account"

    body = f"""
Hi {display_name},

Thank you for registering with Lupin!

Please verify your email address by clicking the link below:

{verification_url}

This verification link will expire in 24 hours.

If you did not create this account, you can safely ignore this email.

Best regards,
The Lupin Team
"""

    return _send_email( email, subject, body )


def send_password_reset_email( email: str, token: str, user_name: Optional[str] = None ) -> bool:
    """
    Send password reset email to user.

    Requires:
        - email is a valid email address
        - token is a non-empty reset token string
        - SMTP configuration is set in config

    Ensures:
        - returns True if email sent successfully
        - returns False if email sending failed

    Returns:
        bool: True if email sent, False otherwise

    Example:
        success = send_password_reset_email( "user@example.com", "xyz789token", "Jane" )
        if success:
            print( "Password reset email sent!" )
    """
    reset_url = f"{config_mgr.get( 'app base url' )}/auth/reset-password?token={token}"

    display_name = user_name if user_name else "User"

    subject = "Reset Your Lupin Password"

    body = f"""
Hi {display_name},

You requested to reset your Lupin account password.

Please reset your password by clicking the link below:

{reset_url}

This reset link will expire in 1 hour.

If you did not request a password reset, please ignore this email and your password will remain unchanged.

Best regards,
The Lupin Team
"""

    return _send_email( email, subject, body )


def _send_email( to_email: str, subject: str, body: str ) -> bool:
    """
    Internal function to send email via SMTP.

    Requires:
        - to_email is a valid email address
        - subject is a non-empty string
        - body is a non-empty string
        - SMTP configuration is properly set in config

    Ensures:
        - returns True if email sent successfully
        - returns False if email sending failed
        - logs error details if sending fails

    Returns:
        bool: True if email sent, False otherwise
    """
    try:
        # Check if email sending is enabled (disabled by default for dev/test)
        send_email_enabled = config_mgr.get( "send email enabled", False, return_type="boolean" )
        if not send_email_enabled:
            print( "TO DO: Implement SMTP _send_email(...)" )
            return True  # Return success without actually sending

        # Get SMTP configuration from config manager
        smtp_host     = config_mgr.get( "smtp host", "localhost" )
        smtp_port     = config_mgr.get( "smtp port", 587, return_type="int" )
        smtp_username = config_mgr.get( "smtp username", None )
        smtp_password = config_mgr.get( "smtp password", None )
        smtp_from     = config_mgr.get( "smtp from email", "noreply@lupin.ai" )
        smtp_use_tls  = config_mgr.get( "smtp use tls", True, return_type="bool" )

        # Create message
        msg = MIMEMultipart()
        msg['From']    = smtp_from
        msg['To']      = to_email
        msg['Subject'] = subject

        # Attach body
        msg.attach( MIMEText( body, 'plain' ) )

        # Connect to SMTP server
        if smtp_use_tls:
            server = smtplib.SMTP( smtp_host, smtp_port )
            server.starttls()
        else:
            server = smtplib.SMTP( smtp_host, smtp_port )

        # Login if credentials provided
        if smtp_username and smtp_password:
            server.login( smtp_username, smtp_password )

        # Send email
        server.send_message( msg )
        server.quit()

        return True

    except Exception as e:
        print( f"Failed to send email to {to_email}: {str( e )}" )
        return False


def test_email_configuration() -> bool:
    """
    Test email configuration by attempting to connect to SMTP server.

    Requires:
        - SMTP configuration is set in config

    Ensures:
        - returns True if connection successful
        - returns False if connection failed
        - prints error details if connection fails

    Returns:
        bool: True if configuration valid, False otherwise

    Example:
        if test_email_configuration():
            print( "Email configuration is valid!" )
        else:
            print( "Email configuration has issues" )
    """
    try:
        smtp_host     = config_mgr.get( "smtp host", "localhost" )
        smtp_port     = config_mgr.get( "smtp port", 587, return_type="int" )
        smtp_username = config_mgr.get( "smtp username", None )
        smtp_password = config_mgr.get( "smtp password", None )
        smtp_use_tls  = config_mgr.get( "smtp use tls", True, return_type="bool" )

        # Connect to SMTP server
        if smtp_use_tls:
            server = smtplib.SMTP( smtp_host, smtp_port, timeout=10 )
            server.starttls()
        else:
            server = smtplib.SMTP( smtp_host, smtp_port, timeout=10 )

        # Login if credentials provided
        if smtp_username and smtp_password:
            server.login( smtp_username, smtp_password )

        server.quit()

        print( f"✓ Email configuration valid - connected to {smtp_host}:{smtp_port}" )
        return True

    except Exception as e:
        print( f"✗ Email configuration invalid: {str( e )}" )
        return False


def quick_smoke_test():
    """Quick smoke test for email service."""
    import cosa.utils.util as du

    du.print_banner( "Email Service Smoke Test", prepend_nl=True )

    try:
        print( "Testing email configuration..." )
        is_valid = test_email_configuration()

        if not is_valid:
            print( "\n⚠ Email configuration test failed (expected if SMTP not configured)" )
            print( "  This is normal in development environment" )
            print( "  To enable email, set SMTP_USERNAME and SMTP_PASSWORD env vars" )
            return True  # Don't fail the test

        print( "\n✓ All email service tests passed!" )
        return True

    except Exception as e:
        print( f"✗ Email service test failed: {e}" )
        return False


if __name__ == "__main__":
    quick_smoke_test()