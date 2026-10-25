"""Sign-in pages: protected pages, profile, change password, log out."""
import re

import pytest
import requests
from playwright.sync_api import expect

from .conftest import make_password

NEW_PASSWORD = make_password()


def _log_in_on_login_page( page, account ):
    page.get_by_label( "Email Address" ).fill( account.email )
    page.get_by_label( "Password", exact=True ).fill( account.password )
    page.get_by_role( "button", name="Login" ).click()


@pytest.mark.feature( "F05" )
def test_a_visitor_without_a_session_is_sent_to_login_and_back( page, server_url, account ):
    page.goto( f"{server_url}/app/auth/profile" )
    expect( page ).to_have_url( re.compile( r"/app/auth/login\?.*redirect=" ), timeout=10000 )
    assert "redirect=" in page.url and "profile" in page.url
    _log_in_on_login_page( page, account )
    expect( page ).to_have_url( f"{server_url}/app/auth/profile", timeout=10000 )


@pytest.mark.feature( "F05" )
def test_notifications_page_also_requires_a_session( page, server_url ):
    page.goto( f"{server_url}/app/notifications" )
    expect( page ).to_have_url( re.compile( r"/app/auth/login" ), timeout=10000 )


@pytest.mark.feature( "F05" )
def test_a_session_survives_a_reload( signed_in, server_url ):
    signed_in.goto( f"{server_url}/app/auth/profile" )
    signed_in.reload()
    expect( signed_in.get_by_role( "heading", name="Your Profile" ) ).to_be_visible()


@pytest.mark.feature( "F06" )
def test_profile_shows_the_account_and_no_admin_section( signed_in, server_url, account ):
    me = account.me()
    signed_in.goto( f"{server_url}/app/auth/profile" )
    expect( signed_in.get_by_role( "heading", name="Your Profile" ) ).to_be_visible()
    for label in ( "Email", "User ID", "Roles", "Email Verified", "Account Status" ):
        expect( signed_in.get_by_text( label, exact=True ) ).to_be_visible()
    expect( signed_in.get_by_text( me[ "email" ] ) ).to_be_visible()
    expect( signed_in.get_by_text( me[ "id" ] ) ).to_be_visible()
    for role in me[ "roles" ]: expect( signed_in.get_by_text( role.upper() ) ).to_be_visible()
    expect( signed_in.get_by_text( "Verified" if me[ "email_verified" ] else "Not Verified", exact=True ) ).to_be_visible()
    expect( signed_in.get_by_text( "Active" if me[ "is_active" ] else "Inactive", exact=True ) ).to_be_visible()
    expect( signed_in.get_by_role( "button", name="Change Password" ) ).to_be_visible()
    expect( signed_in.get_by_role( "button", name="Logout" ) ).to_be_visible()
    expect( signed_in.get_by_text( "ADMIN ACCESS" ) ).to_have_count( 0 )


@pytest.mark.feature( "F07" )
def test_change_password_refusals( signed_in, server_url, account ):
    signed_in.goto( f"{server_url}/app/auth/change-password" )
    expect( signed_in.get_by_role( "heading", name="Change Password" ) ).to_be_visible()
    update = signed_in.get_by_role( "button", name="Update Password" )
    update.click()
    expect( signed_in.get_by_text( "Please fill in all fields" ) ).to_be_visible()
    signed_in.get_by_label( "Current Password" ).fill( account.password )
    signed_in.get_by_label( "New Password", exact=True ).fill( NEW_PASSWORD )
    signed_in.get_by_label( "Confirm New Password" ).fill( NEW_PASSWORD + "x" )
    update.click()
    expect( signed_in.get_by_text( "New passwords do not match" ) ).to_be_visible()
    signed_in.get_by_label( "New Password", exact=True ).fill( account.password )
    signed_in.get_by_label( "Confirm New Password" ).fill( account.password )
    update.click()
    expect( signed_in.get_by_text( "New password must be different from current password" ) ).to_be_visible()
    signed_in.get_by_label( "New Password", exact=True ).fill( "weak" )
    signed_in.get_by_label( "Confirm New Password" ).fill( "weak" )
    update.click()
    expect( signed_in.get_by_text( "Password does not meet requirements. Please check the list below." ) ).to_be_visible()


@pytest.mark.feature( "F07" )
def test_change_password_takes_effect_and_cancel_returns_to_profile( signed_in, server_url, account ):
    signed_in.goto( f"{server_url}/app/auth/change-password" )
    signed_in.get_by_role( "button", name="Cancel" ).click()
    expect( signed_in ).to_have_url( f"{server_url}/app/auth/profile", timeout=10000 )
    signed_in.get_by_role( "button", name="Change Password" ).click()
    signed_in.get_by_label( "Current Password" ).fill( account.password )
    signed_in.get_by_label( "New Password", exact=True ).fill( NEW_PASSWORD )
    signed_in.get_by_label( "Confirm New Password" ).fill( NEW_PASSWORD )
    signed_in.get_by_role( "button", name="Update Password" ).click()
    expect( signed_in.get_by_text( "Password updated successfully!" ) ).to_be_visible()
    expect( signed_in ).to_have_url( re.compile( r"/app/auth/login" ), timeout=15000 )      # the page logs the user out about 2 seconds later
    new = requests.post( f"{server_url}/auth/login", json={ "email": account.email, "password": NEW_PASSWORD }, timeout=10 )
    old = requests.post( f"{server_url}/auth/login", json={ "email": account.email, "password": account.password }, timeout=10 )
    assert new.status_code == 200
    assert old.status_code != 200


@pytest.mark.feature( "F08" )
def test_logout_ends_the_session( signed_in, server_url ):
    signed_in.goto( f"{server_url}/app/auth/profile" )
    signed_in.get_by_role( "button", name="Logout" ).click()
    expect( signed_in ).to_have_url( re.compile( r"/app/auth/login" ), timeout=10000 )
    signed_in.goto( f"{server_url}/app/auth/profile" )
    expect( signed_in ).to_have_url( re.compile( r"/app/auth/login" ), timeout=10000 )
