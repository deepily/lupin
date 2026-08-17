"""
The doc viewer must not serve credential files, including the ones whose names
contain a separator before the word "credentials".

Found 2026-08-17 by Tiffany 💍 while reviewing whether to mount Application
Default Credentials into the :8000 test container: the doc viewer serves anything
under `src`, and `credentials.json` was blocked while
`application_default_credentials.json` — the exact filename gcloud writes — was
SERVED.

Mechanism: the pattern was `\bcredentials?\b`. An underscore is a WORD character,
so `\b` does not match between `_` and `credentials`. The boundary that reads as
"whole word" to a human does not read that way on a filename.
"""

import pytest

from cosa.rest.routers._scope_registry import _is_secrets_path


MUST_BLOCK = [
    "application_default_credentials.json",     # the one that was served — gcloud's ADC filename
    "gcloud/application_default_credentials.json",
    "service_account_credentials.json",
    "credentials.json",
    "my_secrets.yaml",
    "db-password.txt",
    "app.secrets",
    ".env",
    "deploy.pem",
]

# Legitimate filenames the word-boundary anchoring was introduced to protect.
# The fix must not win by simply blocking more.
MUST_SERVE = [
    "credentialism.txt",
    "secretive_methods.py",
    "secretively.py",
]


@pytest.mark.parametrize( "path", MUST_BLOCK )
def test_credential_bearing_paths_are_blocked( path ):
    assert _is_secrets_path( path ) is True, f"{path} would be served by the doc viewer"


@pytest.mark.parametrize( "path", MUST_SERVE )
def test_innocent_lookalikes_are_still_served( path ):
    assert _is_secrets_path( path ) is False, f"{path} is not a secret and must stay readable"


def test_the_separator_case_specifically():
    # The regression in one line: same word, one separator, opposite outcome.
    assert _is_secrets_path( "credentials.json" ) is True
    assert _is_secrets_path( "application_default_credentials.json" ) is True
