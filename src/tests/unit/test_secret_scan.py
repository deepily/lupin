"""
The fixture suite for src/scripts/secret_scan.py — the part that makes a clean sweep
mean something.

WHY IT EXISTS. On 2026-08-17 a credential sat at the tip of public origin/main for four
months. The sweep written to find others MISSED IT TWICE: once when the matcher was
tightened to require a quoted value (his line is an unquoted ini assignment), and once
when a refactored loop broke out of the quoted pattern before ever trying the unquoted
one. Neither miss changed anything visible — the scan just reported a smaller number.
A scanner reporting "nothing found" is indistinguishable from one that cannot see.

WHAT THESE TESTS ARE. Known positives, planted in the shapes that actually fooled it,
plus the decoys that motivated every precision fix. Each positive MUST be found and each
negative MUST NOT be. Add a shape here before you add it to the scanner, and never
"fix" a red test by deleting the case — a deleted case is a blind spot with no alarm.

THE VALUES BELOW ARE SYNTHETIC. Nothing here is a real credential; the real control is
the one line on origin/main the scanner was built for, and it is not reproduced here.
"""

import importlib.util
import sys

import pytest

import cosa.utils.util as cu

sys.path.insert( 0, cu.get_project_root() + "/src/scripts" )

import secret_scan


# ── planted positives — every one of these MUST be found ──────────────────────────
POSITIVES = [
    ( "unquoted ini assignment in a fenced block in markdown",
      "notes.md",
      "Configure it like so:\n\n```ini\n[db]\npassword = Xq7!vNb2Rt9zLm4w\n```\n" ),

    ( "unquoted ini assignment in an .ini file",
      "conf/app.ini",
      "[db]\nhost = localhost\npassword = Xq7vNb2Rt9zLm4w\n" ),

    ( "underscore-prefixed key in a .env file",
      ".env",
      "DB_HOST=localhost\nDB_PASSWORD=Xq7vNb2Rt9zLm4w\n" ),

    ( "assignment in a .cfg file",
      "setup.cfg",
      "[creds]\napi_key = ak_9f2b7c1d4e8a6b3f\n" ),

    ( "quoted literal in python",
      "svc.py",
      'API_KEY = "sk-live-8f3b2a9c7d1e4f6a"\n' ),

    ( "quoted literal behind a typescript declaration keyword",
      "svc.ts",
      'const apiKey = "sk-live-8f3b2a9c7d1e4f6a";\n' ),

    ( "value containing punctuation that could end a naive value regex",
      "conf/app.ini",
      "password = p#a$s!w0rd%Z9\n" ),

    ( "indented assignment inside a class body",
      "svc.py",
      'class Client:\n    def __init__( self ):\n        self.password = "Hs93kdMv02plQ7"\n' ),

    ( "unusual key casing and spelling",
      "conf/app.ini",
      "PASSWORD = Aa11Bb22Cc33Dd\nPasswd = Aa11Bb22Cc33De\ndb_pwd = Aa11Bb22Cc33Df\nx-api-key = Aa11Bb22Cc33Dg\n" ),

    ( "PEM private key block spanning lines",
      "certs/id_rsa",
      "-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQ\n-----END PRIVATE KEY-----\n" ),

    ( "base64 blob wrapped across lines under a yaml block scalar",
      "conf/creds.yaml",
      "service_account_key: >\n  eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiJ9eyJzdWIiOiIxMjM0\n  NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5\n" ),

    ( "credential inside a URL query string",
      "docs/api.md",
      "Call https://api.example.com/v1/sync?token=tk_7f3a9b2c1d8e5f4a6b0c to trigger.\n" ),

    ( "short low-entropy password",
      "conf/app.ini",
      "password = hunterdog\n" ),
]


# ── decoys — every one of these MUST be ignored ───────────────────────────────────
# The first block is why a loose matcher is unusable (nine in ten hits were these).
# The second and third blocks were harvested from real triage passes: each shape
# fooled the scanner on actual repo content before it became a guard.
NEGATIVES = [
    ( "env lookup",             "svc.py",       'password = os.environ[ "DB_PASSWORD" ]\n' ),
    ( "config indirection",     "svc.py",       'api_key = config.get( "api_key" )\n' ),
    ( "path to a key file",     "conf/app.ini", "private_key = /var/secrets/id_rsa\n" ),
    ( "placeholder",            "README.md",    "password = <your-password-here>\n" ),
    ( "template var",           "conf/app.ini", "password = ${DB_PASSWORD}\n" ),
    ( "prose about credentials","docs/x.md",    "The password is rotated by the operator every ninety days.\n" ),
    ( "empty value",            "conf/app.ini", "password =\n" ),
    ( "None literal",           "svc.py",       "password = None\n" ),
    ( "function call",          "svc.py",       "secret = load_secret()\n" ),
    ( "field name in a table",  "docs/x.md",    "| password | string | the account password |\n" ),

    ( "public key path",        "conf/app.ini", "public_key = /etc/ssl/server.pub\n" ),
    ( "primary key column",     "models.py",    'primary_key = "id"\n' ),
    ( "cache key f-string",     "svc.py",       'cache_key = f"user:{user_id}:profile"\n' ),
    ( "token from a response",  "svc.py",       'token = response.json()[ "access_token" ]\n' ),
    ( "token attribute ref",    "svc.py",       "auth_token = self.token\n" ),
    ( "url with no secret",     "docs/x.md",    "See https://api.example.com/v1/sync?page=2&limit=50 for paging.\n" ),
    ( "url token env ref",      "docs/x.md",    "Call https://api.example.com/v1/sync?token=${API_TOKEN} to trigger.\n" ),
    ( "yaml block of prose",    "conf/x.yaml",  "credentials: >\n  see the operator runbook for how these are provisioned\n" ),

    ( "password hash",          "models.py",    'password_hash = "$2b$12$abcdefghijklmnop"\n' ),
    ( "token type",             "auth.py",      'token_type = "bearer"\n' ),
    ( "api key env NAME",       "conf.py",      'API_KEY_NAME = "LUPIN_MODEL_SERVER_API_KEY"\n' ),
    ( "token expiry",           "conf.py",      "refresh_token_expiry = 604800\n" ),
    ( "password column name",   "models.py",    'password_column = "user_pw"\n' ),

    ( "assigns its own name",   "eval.py",      "self.bearer = bearer\n" ),
    ( "reply lookup",           "eval.py",      'bearer = reply.json()[ "access_token" ]\n' ),
    ( "dotted call",            "client.py",    "self.api_key = cu.get_api_key( KEY_FILE_NAME )\n" ),
    ( "typescript coalesce",    "Auth.ts",      "const refreshToken = stored?.refreshToken ?? this.actor.token?.refreshToken;\n" ),
    ( "terraform var ref",      "main.tf",      "  secret  = var.db_password_secret_id\n" ),
    ( "terraform data ref",     "main.tf",      "  password = data.google_secret_manager_secret_version.db_password[0].secret_data\n" ),
    ( "browser storage key",    "queue.js",     "const QUEUE_SESSION_KEY = 'lupin_queue_session_id';\n" ),
    ( "js property wiring",     "queue.js",     "                api_key: notificationState.apiKey\n" ),
    ( "this-property wiring",   "notif.js",     "                authToken: this.authToken,\n" ),
    ( "secret manager NAME",    "history.md",   "  - Secret: `lupin-notification-api-key`\n" ),
]


@pytest.mark.parametrize( "name,path,text", POSITIVES, ids=[ p[ 0 ] for p in POSITIVES ] )
def test_planted_credential_is_found( name, path, text ):
    """A shape that has hidden a real credential before must never go quiet again."""
    findings = secret_scan.scan_text( text, path )
    assert findings, f"BLIND SPOT — the scanner no longer sees: {name}"


@pytest.mark.parametrize( "name,path,text", NEGATIVES, ids=[ n[ 0 ] for n in NEGATIVES ] )
def test_decoy_is_ignored( name, path, text ):
    """Recall is worthless if the report is unreadable — these are why."""
    findings = secret_scan.scan_text( text, path )
    assert not findings, f"FALSE POSITIVE — the scanner now flags: {name} ({findings})"


DIFF = """diff --git a/conf/app.ini b/conf/app.ini
--- a/conf/app.ini
+++ b/conf/app.ini
@@ -3,0 +4 @@ [db]
+password = Xq7vNb2Rt9zLm4w
@@ -20,2 +21,2 @@ [cache]
-ttl = 30
+ttl = 60
diff --git a/README.md b/README.md
--- a/README.md
+++ b/README.md
@@ -10,0 +11,2 @@
+first added line
+second added line
"""


def test_hook_reads_added_line_numbers_from_the_diff():
    """
    The gate scopes to ADDED lines. If the hunk arithmetic is wrong it either misses the
    new secret or fires on lines the commit never touched — and the second failure gets
    the hook switched off, which is the worse one.
    """
    # the hook's filename carries hyphens, so it loads by path rather than by import
    spec = importlib.util.spec_from_file_location(
        "precommit_secret_scan", cu.get_project_root() + "/src/scripts/pre-commit-secret-scan.py" )
    hook = importlib.util.module_from_spec( spec )
    spec.loader.exec_module( hook )

    added = hook.added_lines_by_file( DIFF )
    assert added[ "conf/app.ini" ] == { 4, 21 }
    assert added[ "README.md" ]    == { 11, 12 }


def test_findings_never_carry_the_value():
    """A report that quotes the secret has spread it. Masked output is part of the contract."""
    secret   = "Xq7vNb2Rt9zLm4w"
    findings = secret_scan.scan_text( f"password = {secret}\n", "conf/app.ini" )
    assert findings
    assert not any( secret in str( field ) for row in findings for field in row ), \
        "the scanner leaked a raw credential value into its own output"
