"""Sign-in pages: register and log in, with their refusals."""
import re

import pytest
import requests
from playwright.sync_api import expect

from .conftest import PASSWORD


def _fill_register( page, email, password, confirm ):
    page.get_by_label( "Email Address" ).fill( email )
    page.get_by_label( "Password", exact=True ).fill( password )
    page.get_by_label( "Confirm Password" ).fill( confirm )
    page.get_by_role( "button", name="Create Account" ).click()


@pytest.mark.feature( "F01" )
def test_register_creates_an_account_that_can_log_in( page, server_url ):
    email = "f01-new-user@example.com"
    page.goto( f"{server_url}/app/auth/register" )
    expect( page.get_by_role( "heading", name="Create Your Account" ) ).to_be_visible()
    _fill_register( page, email, PASSWORD, PASSWORD )
    expect( page.get_by_text( "Account created successfully! Redirecting to login..." ) ).to_be_visible()
    page.wait_for_url( re.compile( r"/app/auth/login" ), timeout=10000 )
    response = requests.post( f"{server_url}/auth/login", json={ "email": email, "password": PASSWORD }, timeout=10 )
    assert response.status_code == 200


@pytest.mark.feature( "F01" )
def test_register_marks_each_password_requirement_as_it_is_met( page, server_url ):
    page.goto( f"{server_url}/app/auth/register" )
    for text in ( "At least 8 characters", "One uppercase letter", "One lowercase letter", "One number", "One special character (!@#$%^&*)" ):
        expect( page.get_by_text( text ) ).to_be_visible()
    before = page.get_by_text( "At least 8 characters" ).get_attribute( "class" )
    page.get_by_label( "Password", exact=True ).fill( "abcdefgh" )
    after = page.get_by_text( "At least 8 characters" ).get_attribute( "class" )
    assert before != after, "typing 8 characters must change how the length requirement is shown"


@pytest.mark.feature( "F02" )
def test_register_refusals_show_their_messages( page, server_url, account ):
    cases = (
        ( "", "", "", "Please fill in all fields" ),
        ( "not-an-address", PASSWORD, PASSWORD, "Please enter a valid email address" ),
        ( "f02-weak@example.com", "weak", "weak", "Password is too weak. Please meet all requirements." ),
        ( "f02-mismatch@example.com", PASSWORD, PASSWORD + "x", "Passwords do not match" ),
    )
    sent = []
    page.on( "request", lambda request: sent.append( request.url ) if request.url.endswith( "/auth/register" ) else None )
    for email, password, confirm, message in cases:
        page.goto( f"{server_url}/app/auth/register" )
        _fill_register( page, email, password, confirm )
        expect( page.get_by_text( message ) ).to_be_visible()
    assert sent == [], "the four client-side refusals must not reach the server"
    page.goto( f"{server_url}/app/auth/register" )
    _fill_register( page, account.email, PASSWORD, PASSWORD )
    expect( page.get_by_role( "alert" ).or_( page.get_by_text( re.compile( r"already|exists|registered", re.I ) ) ).first ).to_be_visible()


@pytest.mark.feature( "F03" )
def test_login_goes_to_app_by_default_and_to_redirect_when_given( page, server_url, account ):
    page.goto( f"{server_url}/app/auth/login" )
    expect( page.get_by_role( "heading", name="Welcome to Lupin" ) ).to_be_visible()
    expect( page.get_by_role( "link", name="Register" ) ).to_be_visible()
    page.get_by_label( "Email Address" ).fill( account.email )
    page.get_by_label( "Password", exact=True ).fill( account.password )
    page.get_by_role( "button", name="Login" ).click()
    page.wait_for_url( f"{server_url}/app", timeout=10000 )


@pytest.mark.feature( "F03" )
def test_login_follows_a_redirect_that_starts_with_app( page, server_url, account ):
    page.goto( f"{server_url}/app/auth/login?redirect=/app/auth/profile" )
    page.get_by_label( "Email Address" ).fill( account.email )
    page.get_by_label( "Password", exact=True ).fill( account.password )
    page.get_by_role( "button", name="Login" ).click()
    page.wait_for_url( f"{server_url}/app/auth/profile", timeout=10000 )


@pytest.mark.feature( "F03" )
def test_login_ignores_a_redirect_outside_app( page, server_url, account ):
    page.goto( f"{server_url}/app/auth/login?redirect=https://example.org/" )
    page.get_by_label( "Email Address" ).fill( account.email )
    page.get_by_label( "Password", exact=True ).fill( account.password )
    page.get_by_role( "button", name="Login" ).click()
    page.wait_for_url( f"{server_url}/app", timeout=10000 )


@pytest.mark.feature( "F04" )
def test_login_refusals_show_their_messages( page, server_url, account ):
    page.goto( f"{server_url}/app/auth/login" )
    page.get_by_role( "button", name="Login" ).click()
    expect( page.get_by_text( "Please enter both email and password" ) ).to_be_visible()
    page.get_by_label( "Email Address" ).fill( account.email )
    page.get_by_label( "Password", exact=True ).fill( account.password + "x" )
    page.get_by_role( "button", name="Login" ).click()
    expect( page.get_by_text( "Invalid email or password. Please check your credentials and try again." ) ).to_be_visible()
    assert page.url.endswith( "/app/auth/login" ) or "/app/auth/login" in page.url
