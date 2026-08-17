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


def _scan_fingerprint( findings ):
    """One digest over the whole masked result set — location, key and value digest."""
    import hashlib
    rows = sorted( f"{o}|{n}|{k}|{d}" for o, n, k, _len, d in findings )
    return hashlib.sha256( "\n".join( rows ).encode() ).hexdigest()


def _masked_rows( findings ):
    """
    The masked identity of each finding, WITHOUT its line number.

    Deliberate: a credential is the same credential when the file is reformatted or an
    import is added above it. Keying on the line would turn every unrelated edit into a
    re-triage, and a check that cries wolf gets its accepted set rubber-stamped.
    """
    return { f"{origin.split( ':', 1 )[ -1 ]}|{key}|{digest}"
             for origin, _lineno, key, _len, digest in findings }


def test_a_detector_change_forces_a_full_rescan():
    """
    The trigger a calendar cannot cover (Mr Radio, 2026-08-17), built so it cannot be
    cleared by editing a number.

    WHY THE TRIGGER. The pre-commit gate only ever sees ADDED lines, so nothing in it can
    find a secret already sitting in the tree. A full re-scan finds those, and the moment
    it pays most is a DETECTOR IMPROVEMENT: one word-boundary fix made every
    SCREAMING_SNAKE secret visible for the first time, two of them live at the public tip.
    A weekly cadence would have sat on those for up to six more days.

    WHY IT IS NOT AN HONOUR SYSTEM. "What stops someone updating the pinned hash without
    running the scan?" — Mr Radio, and he was right to ask. A recorded hash proves nothing
    on its own. So this test does not compare hashes at all: it RE-RUNS the scan over the
    published ref every time and checks the recorded fingerprint against what it just
    measured. The only way to write a fingerprint that passes is to have scanned.

    An earlier version of this test skipped the scan when the recorded detector hash still
    matched. That was the hole: paste the new hash and the skip fires. It was removed
    rather than argued with, and the cost is the ~5s this test spends re-scanning.

    It goes red whenever origin/main moves, by design. Pushes here are rare and gated, and
    a moved public tip is exactly when somebody should look again.

    The planted positives above are the other half: a detector change that BLINDS the
    scanner turns several of them red regardless of what is recorded here. This test is
    aimed at the change that WIDENS it — where the positives stay green, the scanner now
    sees things it could not before, and nobody re-scanned the tree.
    """
    import hashlib
    import json
    import subprocess

    root     = cu.get_project_root()
    scanner  = root + "/src/scripts/secret_scan.py"
    record   = root + "/src/tests/unit/fixtures/secret_scan_last_full_scan.json"
    recorded = json.load( open( record ) )

    detector_now = hashlib.sha256( open( scanner, "rb" ).read() ).hexdigest()
    ref_now      = subprocess.run( [ "git", "rev-parse", recorded[ "scanned_ref" ] ], cwd=root,
                                   capture_output=True, text=True ).stdout.strip()

    steps = chr( 10 ).join( "    " + s for s in recorded[ "_how_to_clear_the_red" ] )
    what  = ( "THE DETECTOR CHANGED" if detector_now != recorded[ "detector_sha256" ]
              else "THE PUBLISHED TIP MOVED" if ref_now != recorded[ "scanned_ref_sha" ]
              else "THE RECORDED SCAN DOES NOT MATCH WHAT THIS SCANNER MEASURES" )

    measured = _scan_fingerprint( secret_scan.scan_ref( recorded[ "scanned_ref" ], cwd=root ) )
    assert measured == recorded.get( "scan_fingerprint" ), (
        f"{what} SINCE THE LAST RECORDED FULL SCAN, and re-running it here does not match "
        "what is on record. Re-scan, TRIAGE the output, and record the result — the "
        "fingerprint is measured by this test, so it cannot be filled in without scanning:\n"
        f"{steps}\n"
        f"    detector_sha256   : {detector_now}\n"
        f"    scanned_ref_sha   : {ref_now}\n"
        f"    scan_fingerprint  : {measured}\n"
        f"    last recorded     : {recorded[ 'scanned_at' ]}, "
        f"{recorded[ 'distinct_values_at_tip' ]} distinct values, "
        f"{recorded[ 'real_findings' ]} real"
    )


def test_findings_never_carry_the_value():
    """A report that quotes the secret has spread it. Masked output is part of the contract."""
    secret   = "Xq7vNb2Rt9zLm4w"
    findings = secret_scan.scan_text( f"password = {secret}\n", "conf/app.ini" )
    assert findings
    assert not any( secret in str( field ) for row in findings for field in row ), \
        "the scanner leaked a raw credential value into its own output"


def test_the_branch_we_commit_to_carries_no_untriaged_finding():
    """
    THE REF THIS CONTROL WAS MISSING (Rachel, reviewing row 85959aaf).

    The test above scans `origin/main`, which answers "what can a stranger read". It is
    NOT what this fleet commits to. Measured 2026-08-17: the working branch was 645
    commits and two weeks ahead of `origin/main`. So a credential committed that day was
    seen by nothing — the gate reads only ADDED lines and is not installed, and the full
    scan read a ref nobody had pushed to in a fortnight. A standing inventory of a
    snapshot is not a standing inventory.

    WHY AN ACCEPTED SET AND NOT A FINGERPRINT. The branch moves many times a day. A
    fingerprint over it would be red permanently, and a check that is always red is a
    check nobody reads. So this pins the masked identity of every finding that has been
    TRIAGED, and fails only on one that has not: an ordinary commit is green, a new
    credential-shaped line is red.

    It cannot be cleared by editing a number. The digest of a value can only be produced
    from the value, and adding a row to `branch_accepted` names the file and the key it
    is accepting — a reviewable act, unlike overwriting a single hash.
    """
    import json

    root     = cu.get_project_root()
    record   = root + "/src/tests/unit/fixtures/secret_scan_last_full_scan.json"
    recorded = json.load( open( record ) )

    accepted = set( recorded[ "branch_accepted" ] )
    measured = _masked_rows( secret_scan.scan_ref( recorded[ "branch_ref" ], cwd=root ) )
    untriaged = sorted( measured - accepted )

    steps = chr( 10 ).join( "    " + s for s in recorded[ "_how_to_clear_the_red" ] )
    assert not untriaged, (
        f"{len( untriaged )} finding(s) on {recorded[ 'branch_ref' ]} have never been triaged. "
        "Values are masked — key, path and a truncated digest, never the secret:\n"
        + chr( 10 ).join( "    " + row for row in untriaged )
        + "\n\nIf one is real, remove it and read it from the environment or the secret store. "
          "If it is a false positive, triage it and add its row above to branch_accepted:\n"
        + steps
    )
