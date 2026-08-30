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


def _require_ref( ref, root ):
    """
    Skip loudly when the ref cannot be read, rather than failing for the wrong reason.

    Rachel's F6: on a `git archive` export with no git metadata, the re-scan tests fail —
    not because a credential is loose, but because there is no repository to read. A red
    that means "wrong environment" trains people to ignore a red that means "secret".

    The skip names what went unverified, because a silent skip is how a control quietly
    stops being one.
    """
    import subprocess
    probe = subprocess.run( [ "git", "rev-parse", "--verify", "--quiet", ref ], cwd=root,
                            capture_output=True, text=True )
    if probe.returncode != 0 or not probe.stdout.strip():
        pytest.skip( f"NOT VERIFIED HERE: ref '{ref}' is unreadable in this checkout "
                     "(no git metadata, or the ref was never fetched), so the standing "
                     "credential inventory was not re-measured on this run." )


def _masked_rows( findings ):
    """
    The masked identity of each finding, WITHOUT its line number.

    Deliberate: a credential is the same credential when the file is reformatted or an
    import is added above it. Keying on the line would turn every unrelated edit into a
    re-triage, and a check that cries wolf gets its accepted set rubber-stamped.
    """
    return { f"{origin.split( ':', 1 )[ -1 ]}|{key}|{digest}"
             for origin, _lineno, key, _len, digest in findings }


# ── THE AMNESTY, stated in code rather than only in the data (Tiberius, reviewing 72c9e6a2) ──
#
# 190 rows carry this exact string instead of an individual reason. That is a DELIBERATE
# AMNESTY, not an oversight: they were triaged COLLECTIVELY on 2026-08-17 by chloe + rachel
# (see `branch_triage_note`), and re-triaging 190 rows was not part of closing this defect.
#
# IT IS DATED AND IT IS BOUNDED. Dated, because reusing this string on a finding discovered
# after 2026-08-17 is an affirmative false statement rather than a shortcut — the date makes
# that visible to a reviewer. Bounded, because `AMNESTY_ROWS` below pins how many rows may
# ride it: paste it onto a new finding and the count grows and the gate reds. Without that
# pin the amnesty would be an open door with a polite sign on it, which is the shape of the
# defect this whole change is closing.
GRANDFATHER_REASON = "grandfathered: collectively triaged 2026-08-17, see branch_triage_note"
AMNESTY_ROWS       = 190


def amnesty_rows( recorded ):
    """
    The rows riding the 2026-08-17 collective triage rather than an individual reason.

    Requires:
        - recorded is the parsed fixture dict with a MAPPING branch_accepted

    Ensures:
        - returns the sorted list of rows whose reason is exactly GRANDFATHER_REASON
        - a row with its OWN reason is not counted, so individually re-triaging one
          SHRINKS the amnesty — the only direction that should ever be free
        - never raises on an empty mapping
    """
    accepted = recorded[ "branch_accepted" ]
    return sorted( row for row, reason in accepted.items() if reason == GRANDFATHER_REASON )



def accepted_rows_and_unjustified( recorded ):
    """
    Split `branch_accepted` into the accepted set and the rows accepted WITHOUT a reason.

    WHY THIS EXISTS (row off the 2026-08-30 working-tree-artifact audit). `branch_accepted`
    was a list of bare strings, so the gate could not tell a TRIAGED acceptance from a
    PASTED one — and the pasting move was the documented remediation: the failure message
    told you to add the row, and adding the row was the whole procedure. A real credential
    could therefore be waved through by someone following the instructions correctly and
    hurriedly. No malice required, which is what made it the likeliest of the seven
    false-greens to actually fire.

    The fix is the discipline the task store already enforces on `->done`: if you cannot
    cite a reason, the work is not done. Every accepted row now carries one.

    Requires:
        - recorded is the parsed fixture dict

    Ensures:
        - returns ( accepted_set, unjustified_rows ) — both derived from the SAME mapping,
          so a row can never be silently accepted while being reported as unjustified
        - a MAPPING is required. A bare list raises TypeError rather than being tolerated:
          a compatibility fallback here would preserve the exact hole this closes
        - a reason that is missing, None, blank, or whitespace-only counts as UNJUSTIFIED
        - never raises on an empty mapping
    """
    accepted = recorded[ "branch_accepted" ]
    if not isinstance( accepted, dict ):
        raise TypeError(
            "branch_accepted must be a MAPPING of row -> reason, not "
            f"{type( accepted ).__name__}. A bare list cannot distinguish a triaged "
            "acceptance from a pasted one, which is the defect this shape closes."
        )

    unjustified = sorted( row for row, reason in accepted.items()
                          if not ( reason or "" ).strip() )
    return set( accepted ), unjustified


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

    _require_ref( recorded[ "scanned_ref" ], root )

    detector_now = hashlib.sha256( open( scanner, "rb" ).read() ).hexdigest()
    ref_now      = subprocess.run( [ "git", "rev-parse", recorded[ "scanned_ref" ] ], cwd=root,
                                   capture_output=True, text=True ).stdout.strip()

    steps = chr( 10 ).join( "    " + s for s in recorded[ "_how_to_clear_the_red" ] )
    what  = ( "THE DETECTOR CHANGED" if detector_now != recorded[ "detector_sha256" ]
              else "THE PUBLISHED TIP MOVED" if ref_now != recorded[ "scanned_ref_sha" ]
              else "THE RECORDED SCAN DOES NOT MATCH WHAT THIS SCANNER MEASURES" )

    findings = secret_scan.scan_ref( recorded[ "scanned_ref" ], cwd=root )
    measured = _scan_fingerprint( findings )
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

    # 🔴 THE FINGERPRINT PROVES A RE-SCAN HAPPENED. IT PROVES NOTHING ABOUT A TRIAGE.
    # Measured 2026-08-30 (row d8683a66): `distinct_values_at_tip` and
    # `candidate_locations_at_tip` appeared in this file exactly ONCE each — inside the
    # failure message above — and were never asserted. So a seat could paste the measured
    # fingerprint into the record, leave the counts at their 2026-08-17 values, and this
    # test would go green while the record claimed 116 distinct values against a scan
    # returning 117. Self-inconsistent record, clean tier, nobody told.
    #
    # Both counts are DERIVED FROM `findings` — the same object the fingerprint is computed
    # from — so like the fingerprint they cannot be filled in without scanning. A mismatch
    # here means the record was HAND-EDITED rather than re-derived, which is the one thing
    # the fingerprint alone cannot see.
    counted = {
        "candidate_locations_at_tip" : len( findings ),
        "distinct_values_at_tip"     : len( { digest for _o, _n, _k, _len, digest in findings } ),
    }
    disagreed = [ field for field, value in counted.items() if recorded.get( field ) != value ]
    assert not disagreed, (
        "THE RECORDED COUNTS DO NOT MATCH THE SCAN THIS TEST JUST RAN — "
        f"{', '.join( disagreed )}. The fingerprint above agrees, so the scan was re-run; "
        "these fields were not re-derived from it. Re-record them from the SAME scan, and "
        "re-do the TRIAGE they summarise — a count that moved means findings moved:\n"
        + "".join( f"    {field:28}: recorded {recorded.get( field )!r}, measured {value!r}\n"
                   for field, value in counted.items() )
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

    _require_ref( recorded[ "branch_ref" ], root )

    accepted, unjustified = accepted_rows_and_unjustified( recorded )

    # Checked BEFORE the scan: an acceptance with no reason is a defect in the record
    # itself, true regardless of what the branch currently carries, and reporting it
    # first stops it hiding behind a slow scan that may pass.
    assert not unjustified, (
        f"{len( unjustified )} accepted row(s) carry NO reason. An acceptance nobody can "
        "justify is indistinguishable from one nobody made:\n"
        + chr( 10 ).join( "    " + row for row in unjustified )
        + "\n\nGive each a one-line reason saying why it is not a real credential."
    )

    measured = _masked_rows( secret_scan.scan_ref( recorded[ "branch_ref" ], cwd=root ) )
    untriaged = sorted( measured - accepted )

    steps = chr( 10 ).join( "    " + s for s in recorded[ "_how_to_clear_the_red" ] )
    assert not untriaged, (
        f"{len( untriaged )} finding(s) on {recorded[ 'branch_ref' ]} have never been triaged. "
        "Values are masked — key, path and a truncated digest, never the secret:\n"
        + chr( 10 ).join( "    " + row for row in untriaged )
        + "\n\nIf one is real, remove it and read it from the environment or the secret store. "
          "If it is a false positive, triage it and add its row to branch_accepted AS A KEY "
          "WHOSE VALUE IS A ONE-LINE REASON — a bare row is refused:\n"
        + steps
    )


# ── the justification gate — negative controls ────────────────────────────────────
#
# THE CASE THIS GATE WAS PASSING, and these prove it now reds. Before 2026-08-30
# `branch_accepted` was a list of bare strings, so a row pasted in without triage was
# indistinguishable from one triaged properly — and pasting was what the failure message
# told you to do. Each control below is the fooling move, executed.

def test_a_pasted_row_with_no_reason_is_refused():
    """THE NEGATIVE CONTROL. This is exactly what the gate used to accept in silence."""
    recorded = { "branch_accepted": {
        "src/cosa/rest/db.py|DB_PASSWORD|sha256:c20cc404fe15": "",   # ← the pasted row
        "src/tests/thing.py|password|sha256:aaaaaaaaaaaa"    : "planted fixture, not real",
    } }
    accepted, unjustified = accepted_rows_and_unjustified( recorded )

    assert unjustified == [ "src/cosa/rest/db.py|DB_PASSWORD|sha256:c20cc404fe15" ]
    # and it is STILL in the accepted set — the two are derived from one mapping, so a row
    # can never be quietly accepted while being reported as unjustified
    assert len( accepted ) == 2


@pytest.mark.parametrize( "reason,label", [
    ( "",       "empty string" ),
    ( "   ",    "whitespace only" ),
    ( "\t\n",   "tabs and newlines" ),
    ( None,     "explicit null" ),
] )
def test_every_shape_of_absent_reason_is_refused( reason, label ):
    """A reason that is present-but-empty must not read as present. `" "` is truthy."""
    recorded = { "branch_accepted": { "a|b|sha256:1": reason } }
    _, unjustified = accepted_rows_and_unjustified( recorded )
    assert unjustified == [ "a|b|sha256:1" ], f"{label} was accepted as a reason"


def test_a_justified_row_passes():
    """The positive control — without it the test above is satisfied by a broken helper."""
    recorded = { "branch_accepted": { "a|b|sha256:1": "synthetic value in a test fixture" } }
    accepted, unjustified = accepted_rows_and_unjustified( recorded )

    assert unjustified == [ ]
    assert accepted == { "a|b|sha256:1" }


def test_a_bare_list_is_refused_rather_than_tolerated():
    """
    A compatibility fallback here would preserve the exact hole this closes, so the old
    shape is a TypeError. Named explicitly because "be lenient with the old format" is the
    obvious next edit somebody makes.
    """
    with pytest.raises( TypeError ) as error:
        accepted_rows_and_unjustified( { "branch_accepted": [ "a|b|sha256:1" ] } )
    assert "MAPPING" in str( error.value )


def test_the_live_fixture_carries_a_reason_for_every_accepted_row():
    """
    The gate applied to the real record — the half that would catch a future paste.

    Kept separate from the scanning test so it runs in milliseconds and fails for its own
    reason: this one is about the RECORD, and stays true whatever the branch carries.
    """
    import json
    recorded = json.load( open( cu.get_project_root()
                                + "/src/tests/unit/fixtures/secret_scan_last_full_scan.json" ) )
    # Same independence rule as the amnesty bound above: read the record directly, then
    # cross-check the helper against it. A helper returning ( set(), [] ) would otherwise
    # certify any record at all.
    direct_unjustified = sorted( row for row, reason in recorded[ "branch_accepted" ].items()
                                 if not ( reason or "" ).strip() )
    accepted, unjustified = accepted_rows_and_unjustified( recorded )

    assert unjustified == direct_unjustified, (
        f"accepted_rows_and_unjustified disagrees with a direct read: helper says "
        f"{len( unjustified )} unjustified, the file says {len( direct_unjustified )}."
    )
    assert accepted, "the record holds no accepted rows at all — this test would pass on anything"

    assert direct_unjustified == [ ], (
        f"{len( direct_unjustified )} accepted row(s) in the live record carry no reason:\n"
        + chr( 10 ).join( "    " + row for row in direct_unjustified )
    )
    # Pins the ACCEPTED count, and says so. It used to say "the grandfathered set changed
    # size", which named a different set (Tiberius, reviewing aab06b9c): today all 190
    # accepted rows ride the amnesty, so the two counts coincide — but the moment one row
    # earns an individual reason the grandfathered set drops to 189 while accepted stays
    # 190, and this would have fired with a message about the wrong thing. The
    # grandfathered set has its own bound in test_the_amnesty_is_bounded_*.
    assert len( accepted ) == 190, (
        f"the ACCEPTED set is now {len( accepted )}, not 190. A row was added or removed — "
        "triage the addition and re-pin deliberately, rather than adjusting this number." )


def test_the_amnesty_is_bounded_and_cannot_absorb_a_new_finding():
    """
    THE SEAM I FLAGGED TO MY OWN REVIEWER, now closed (Tiberius, reviewing 72c9e6a2).

    Giving 190 rows a shared grandfather reason satisfies "every row has a reason" while
    leaving an open door: paste that same string onto a NEW finding and it reads as
    triaged. Pinning the count shuts it — the amnesty may shrink as rows are individually
    re-triaged, never grow.
    """
    import json
    recorded = json.load( open( cu.get_project_root()
                                + "/src/tests/unit/fixtures/secret_scan_last_full_scan.json" ) )

    # ⚠️ COUNTED DIRECTLY FROM THE RECORD, NOT VIA amnesty_rows (Tiberius, reviewing
    # 177c3542). Policing the amnesty with the very helper the amnesty is expressed in
    # means a DEAD helper — one returning [] for any input — makes this test pass
    # vacuously. The instrument cannot be its own control. Two independent readings,
    # cross-checked below, so a broken helper reddens rather than certifies.
    direct = [ row for row, reason in recorded[ "branch_accepted" ].items()
               if reason == GRANDFATHER_REASON ]
    riding = amnesty_rows( recorded )

    assert sorted( riding ) == sorted( direct ), (
        f"amnesty_rows disagrees with a direct read of the record: helper says "
        f"{len( riding )}, the file says {len( direct )}. The helper is wrong, or the "
        "record's shape changed under it — either way the bound below means nothing."
    )
    assert direct, (
        "NO row rides the amnesty. Either every row was individually re-triaged — worth "
        "saying out loud and re-pinning AMNESTY_ROWS to 0 — or this test is reading an "
        "empty record and would pass on anything."
    )

    assert len( direct ) <= AMNESTY_ROWS, (
        f"{len( direct )} rows now ride the 2026-08-17 amnesty, up from {AMNESTY_ROWS}. "
        "A finding discovered after that date cannot have been triaged on it — give the new "
        "row its own reason, or say plainly why the amnesty was widened."
    )


def test_pasting_the_amnesty_string_onto_a_new_finding_is_caught():
    """The negative control for the bound: the fooling move, executed."""
    recorded = { "branch_accepted": { f"row{i}|k|sha256:{i}": GRANDFATHER_REASON
                                      for i in range( AMNESTY_ROWS + 1 ) } }
    riding = amnesty_rows( recorded )

    assert len( riding ) == AMNESTY_ROWS + 1
    assert len( riding ) > AMNESTY_ROWS, "the bound must catch a grown amnesty"


def test_individually_retriaging_a_row_shrinks_the_amnesty():
    """The positive control — shrinking must stay free, or nobody will ever re-triage."""
    recorded = { "branch_accepted": { "a|k|sha256:1": GRANDFATHER_REASON,
                                      "b|k|sha256:2": "checked 2026-08-30: synthetic fixture" } }
    assert amnesty_rows( recorded ) == [ "a|k|sha256:1" ]
