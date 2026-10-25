"""
Fixtures for the experiment acceptance tests.

Every test gets its own account, registered through the API, so tests are independent.
"""
import os
import uuid

import pytest
import requests



def make_password():
    """Return a fresh password that meets every register-page rule."""
    return f"Aa1!{uuid.uuid4().hex[ :12 ]}"


PASSWORD = make_password()


def pytest_configure( config ):
    """Register the feature marker the acceptance tests carry."""
    config.addinivalue_line( "markers", "feature(id): the feature in the feature list this test covers" )


@pytest.fixture( scope="session" )
def server_url():
    """
    Requires:
        - EXPERIMENT_SERVER_URL is set

    Ensures:
        - returns the server URL without a trailing slash
    """
    url = os.environ.get( "EXPERIMENT_SERVER_URL" )
    if not url: raise RuntimeError( "Set EXPERIMENT_SERVER_URL to the run's server" )
    return url.rstrip( "/" )


@pytest.fixture( scope="session" )
def notify_api_key():
    """
    Requires:
        - EXPERIMENT_NOTIFY_API_KEY is set

    Ensures:
        - returns the API key the sender side uses
    """
    key = os.environ.get( "EXPERIMENT_NOTIFY_API_KEY" )
    if not key: raise RuntimeError( "Set EXPERIMENT_NOTIFY_API_KEY" )
    return key


class Account:
    """A registered user plus API helpers acting as that user or as a sender."""

    def __init__( self, server_url, notify_api_key ):
        self.server_url     = server_url
        self.notify_api_key = notify_api_key
        self.email          = f"exp-{uuid.uuid4().hex[ :10 ]}@example.com"
        self.password       = PASSWORD
        response            = requests.post( f"{server_url}/auth/register", json={ "email": self.email, "password": self.password }, timeout=10 )
        assert response.status_code in ( 200, 201 ), f"register failed: {response.status_code} {response.text}"

    def login_tokens( self ):
        """Return the token pair for this account, from the API."""
        response = requests.post( f"{self.server_url}/auth/login", json={ "email": self.email, "password": self.password }, timeout=10 )
        assert response.status_code == 200, f"login failed: {response.status_code} {response.text}"
        return response.json()[ "tokens" ]

    def bearer( self ):
        """Return an Authorization header for this account."""
        return { "Authorization": f"Bearer {self.login_tokens()[ 'access_token' ]}" }

    def me( self ):
        """Return this account's record from the API."""
        response = requests.get( f"{self.server_url}/auth/me", headers=self.bearer(), timeout=10 )
        return response.json()

    def user_id( self ):
        """Return this account's system user id."""
        return self.me()[ "id" ]

    def awaiting_response( self ):
        """Return the raw text of the response cards still waiting for an answer."""
        response = requests.get( f"{self.server_url}/api/notifications/awaiting-response", headers=self.bearer(), timeout=10 )
        assert response.status_code == 200, f"awaiting-response failed: {response.status_code} {response.text}"
        return response.text

    def send( self, message, sender_id="exp-sender@lupin.deepily.ai", priority="medium", **extra ):
        """Send a notification to this account as an outside sender; returns the response."""
        params = { "message": message, "target_user": self.email, "sender_id": sender_id, "priority": priority, **extra }
        return requests.post( f"{self.server_url}/api/notify", params=params, headers={ "X-API-Key": self.notify_api_key }, timeout=30 )

    def inbox( self ):
        """Return this account's notifications as the API lists them."""
        response = requests.get( f"{self.server_url}/api/notifications/{self.user_id()}", headers=self.bearer(), timeout=10 )
        assert response.status_code == 200, f"inbox failed: {response.status_code} {response.text}"
        body = response.json()
        return body[ "notifications" ] if isinstance( body, dict ) else body


@pytest.fixture
def account( server_url, notify_api_key ):
    """A fresh registered account."""
    return Account( server_url, notify_api_key )


@pytest.fixture
def signed_in( page, server_url, account ):
    """A browser page already signed in as a fresh account, via the login page."""
    page.goto( f"{server_url}/app/auth/login" )
    page.get_by_label( "Email Address" ).fill( account.email )
    page.get_by_label( "Password", exact=True ).fill( account.password )
    page.get_by_role( "button", name="Login" ).click()
    page.wait_for_url( f"{server_url}/app" )
    return page
