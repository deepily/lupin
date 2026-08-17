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

    # 🔴 SECOND ROUND (Tiffany, 2026-08-17). The names above only cover files that
    # SPELL "credentials" or "secret"; most real Google keys do not. On the RUNNING
    # branch (1e13786b) 13 of 17 real credential filenames passed this blocklist.
    #
    # The service-account family below was already closed on THIS branch — kept here
    # as a pin, not claimed as new. The four after it were still being SERVED.
    "service-account.json",
    "service_account.json",
    "sa_key.json",
    "src/conf/service-account.json",
    # genuinely new coverage:
    "adc.json",
    "authorized_user.json",
    "firebase-adminsdk-abc12.json",
    "gcp-key.json",
    "gcloud-key.json",
    "bigquery-key.json",
]

# `token.json` sits in NEITHER list on purpose. It is ambiguous enough that
# test_docview_credential_content_block.py asserts it stays served BY NAME, and the
# content check is what catches a real one. Asserting it here would put two suites in
# direct contradiction — which is how a security list acquires a rule nobody can
# explain.

# Legitimate filenames the word-boundary anchoring was introduced to protect.
# The fix must not win by simply blocking more.
MUST_SERVE = [
    "credentialism.txt",
    "secretive_methods.py",
    "secretively.py",

    # 🔴 The lookalikes the SECOND round was narrowed around. Each was measured
    # against the whole served tree BEFORE its pattern went in: a bare `*-key*.json`
    # would have blocked `config-key-migration-map.json`, 30 copies of a legitimate
    # config doc, so the key rule names providers instead.
    "src/conf/config-key-migration-map.json",
    "api-keys.json",
    "tokenizer_config.json",
    "token-counts.json",
]

# 🔴 A PRE-EXISTING FALSE POSITIVE ON THIS BRANCH — reported, NOT quietly fixed.
#
# The `service[-_. ]?account` pattern (added on this branch, not by me) carries no
# extension anchor, so it blocks SOURCE FILES whose names merely discuss service
# accounts. Measured across the mounted served tree: 54 real files, all copies of
# `create_service_account.py` / `create_service_account_postgres.py`.
#
# These are xfail rather than deleted because the defect belongs in the suite where
# somebody trips on it, not only in a review doc. They are also NOT silently patched:
# tightening a security pattern to buy back a false positive is the exact move that
# opened the byte-order-mark hole one commit earlier, so the narrowing is the pattern
# owner's call, not the reviewer's. The cost here is usability — a readable file that
# will not open — not exposure.
FALSE_POSITIVES_REPORTED_NOT_FIXED = [
    "src/scripts/create_service_account.py",
    "src/scripts/create_service_account_postgres.py",
    "service-accounts.md",                              # documentation ABOUT keys is not a key
]


@pytest.mark.xfail( reason="pre-existing: service-account pattern has no extension anchor; blocks 54 real source files", strict=True )
@pytest.mark.parametrize( "path", FALSE_POSITIVES_REPORTED_NOT_FIXED )
def test_source_files_discussing_service_accounts_should_stay_served( path ):
    assert _is_secrets_path( path ) is False


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
