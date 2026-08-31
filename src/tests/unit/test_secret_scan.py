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

import ast
import contextlib
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


_SCAN_MEMO = {}


def _scan_once( ref, root ):
    """
    Run the published-ref scan at most once per session, and hand both callers the SAME
    findings.

    This is not an optimisation. Two tests need this scan — the fingerprint tripwire and
    the counts guard — and the ~5s cost is exactly the pressure that put the second one
    behind the first, where it never ran. Memoising is what lets the guard stand on its
    own so the failing SET can tell the two reds apart.

    Requires:
        - ref is a readable git ref, root is the repo root

    Ensures:
        - returns the masked findings list for that ref
        - a second call with the same ( ref, root ) returns the identical list object
    """
    key = ( ref, root )
    if key not in _SCAN_MEMO:
        _SCAN_MEMO[ key ] = secret_scan.scan_ref( ref, cwd=root )
    return _SCAN_MEMO[ key ]


# 🔴 THE HOLD IS A DECLARED FACT, NOT A DERIVED ONE — set False only when the postgres
# credential has actually been rotated and Maya's triage on wt-maya-4f0ced13 (034e44ac) has
# merged. Flipping this is a deliberate, reviewable act; that is the entire point of it being
# a constant rather than something computed.
#
# THE FIRST CUT DERIVED IT FROM THE SCANNER'S SHA and Rachel 🕊️ refuted it: the hold is about
# an UNROTATED CREDENTIAL, and no detector sha expresses that. Keyed to ROTATION_HELD_SHA, the
# NEXT detector change — any detector change, for any unrelated reason — makes the scanner stop
# matching, reads as "hold cleared", and prints the contradictory recipe again. Worse, a
# detector change is exactly the event that makes this red fire, so it would have un-gated
# itself precisely when somebody was most likely to be reading it. That is this fleet's own
# "a coordinate is not a reference" rule landing on my gate: I keyed a standing condition to a
# value that moves for reasons that have nothing to do with it.
#
# ⚠️ AND MY OWN CONTROL HAD THE EVIDENCE. The hold-inactive arm showed the recipe printing
# while both reds still fired. I read that as "the gate opens correctly" and never asked
# whether opening was RIGHT in that state. A control answers the question you pose to it.
ROTATION_HOLD_ACTIVE = True


def _rotation_hold_is_active():
    """
    Is the postgres-rotation hold in force right now?

    Ensures:
        - returns the DECLARED hold state, never a value inferred from a sha or a scan
        - takes no arguments, so no caller can accidentally key it to a coordinate
    """
    return ROTATION_HOLD_ACTIVE


# 🔴 THE POINTER BELOW USED TO SEND THE READER TO AN UNGATED COPY OF WHAT IT JUST REFUSED.
# `_how_to_clear_the_red` lives in the fixture as unrefused prose, so the gate was a redirect
# to a clean destination — suppress the recipe here, and the reader simply reads it there.
# The fixture carries this ANNOTATION key beside it now, so the refusal travels with the
# redirect. Mr Radio's ruling drew the line and it is worth stating: gate at the RENDER site
# and never rewrite a RECORDED string — the record is evidence of what was scanned and what
# the then-owner said to do about it — but ADDING a key is annotation, not rewriting, so the
# direct-reader hole closes without touching a recorded value.
FIXTURE_HOLD_KEY = "_rotation_hold"


def _clear_the_red_steps( recorded, root ):
    """
    The recipe for clearing a red — or, while the rotation hold stands, the reason it is
    not being printed.

    🔴 THE RECIPE IS CORRECT AND IT IS REFUSED RIGHT NOW, AND THAT IS ONLY A CONTRADICTION
    ONCE BOTH ARE PRINTED TOGETHER. `_how_to_clear_the_red` ends "update detector_sha256,
    scanned_ref_sha, scan_fingerprint, the counts and real_findings" — precisely what
    ROTATION_HELD_NOTICE, seven lines below it in the same failure message, refuses. Found
    by Rachel 🕊️ 2026-08-30, one level inside the defect it extends: making both reds carry
    the notice stopped the two TESTS disagreeing and left each red arguing with ITSELF.

    SUPPRESSED, NOT DELETED, and the distinction is the whole design. The recipe is right
    and becomes right again the moment the credential is rotated; deleting it would lose
    knowledge to fix a sequencing problem. Ordering costs nothing.

    Requires:
        - recorded is the loaded record dict, root is the repo root

    Ensures:
        - hold ACTIVE  -> a short block saying the recipe is withheld and where to read it
        - hold CLEAR   -> the recorded steps, indented, exactly as before
    """
    if _rotation_hold_is_active():
        return (
            "    (THE RECIPE FOR CLEARING THIS RED IS WITHHELD while the rotation hold below\n"
            "     is active — it ends by telling you to update the record, which is the one\n"
            "     thing that hold refuses. It is not wrong and it is not gone: read it in the\n"
            f"     record's `_how_to_clear_the_red` — `{FIXTURE_HOLD_KEY}`, the record's FIRST\n"
            "     key, repeats this refusal there — and it prints here again once rotation\n"
            "     lands.)"
        )
    return chr( 10 ).join( "    " + s for s in recorded[ "_how_to_clear_the_red" ] )


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

# ─────────────────────────────────────────────────────────────────────────────────────
# 🔴 THIS RED IS DELIBERATE AND IT STAYS RED UNTIL A CREDENTIAL IS ROTATED.
#
# If a secret-scan red is failing for you — the rescan tripwire or the counts gate — the
# remedy is NOT
# to re-scan and record — that work is DONE. It sits on branch `wt-maya-4f0ced13` at
# commit `034e44ac`, and Mr. Radio is holding it unmerged ON PURPOSE.
#
# WHY A GREEN HERE WOULD BE THE DEFECT. The scan behind that commit found the postgres
# password still live at the PUBLIC TIP in 8 locations, plus a JWT signing key and an
# account password that are off the tip but still reachable from `origin/main` history —
# removing a secret from the tip does not unpublish it. Nothing has been scrubbed and
# nothing has been rotated; rotation is Rick's call and comes first. This failing test is
# the only branch-level signal that the credential work is unfinished. Landing the fixture
# deletes that signal while changing nothing about the exposure.
#
# 🔴 THE TRAP IS THAT THE WRONG FIX LOOKS LIKE DILIGENCE. You find a red, you find a
# branch that already contains the fixture, you land it, and every log line reads as
# competence. That is why this notice names a sha you can check instead of a judgement you
# have to re-derive at 3am:
#
#     A fixture change moving `detector_sha256` TO
#         8675ec7a1c0c677e56dc6e243be7af51ee2c715f17ec6a93e1a3c731c360633f
#     is REFUSED until rotation lands. Not deferred, not "probably fine" — refused.
#
# When rotation HAS landed, `wt-maya-4f0ced13` merges whole. Do not split it to land a
# safe half; splitting exists only to let part of it in early, which is the thing being
# prevented.
# ─────────────────────────────────────────────────────────────────────────────────────
ROTATION_HELD_SHA = "8675ec7a1c0c677e56dc6e243be7af51ee2c715f17ec6a93e1a3c731c360633f"
ROTATION_HELD_COMMIT = "034e44ac"   # the held commit carrying the done-but-unmergeable re-scan
def _rotation_held_notice():
    """
    The refusal, emitted ONLY while the hold is active.

    🔴 ONE CONDITION FOR BOTH HALVES, WHICH IS THE WHOLE POINT. The recipe-withholding was
    gated on `_rotation_hold_is_active()` and this notice was gated on nothing, so flipping
    the flag HALF-lifted the hold: measured 2026-08-30 with the flag False, the recipe
    RETURNED while this notice still insisted it was REFUSED — the same contradiction the
    hold exists to remove, pointing the other way. Reproduced independently by Tiberius 👑
    and cleared by Rachel 🕊️ in the same minute. Two halves of one condition on two switches
    WILL drift apart, and them drifting apart IS the defect (Mr Radio's ruling; a second flag
    would have reproduced it with more ceremony).

    Requires:
        - nothing; safe to call in either hold state

    Ensures:
        - hold ACTIVE -> the refusal, naming the held commit and the refused sha
        - hold CLEAR  -> the empty string, so a lifted hold stops shouting
    """
    if not _rotation_hold_is_active(): return ""

    return ROTATION_HELD_NOTICE


# ── THE MESSAGES, AS BUILDERS, SO A GUARD CAN RENDER THEM ─────────────────────────
#
# 🔴 A CALL-SHAPE ASSERTION CANNOT SEE A MISSING REFERENT (Mr Radio 🦉's requirement, and
# my own evidence for it). Clayton 😎's guard DERIVES the reds — the right half, kept below
# unchanged in spirit — and then asks whether each red's SOURCE mentions
# `_rotation_held_notice`. I built the same source-shaped check first and mutation-proved it
# worthless for two of the four things it should catch: a red losing its notice, and the
# guard narrowing itself back to one subject, both SURVIVED. Both are invisible in how the
# code is WRITTEN and plain in what it PRINTS.
#
# These were inline assert expressions, which can only be checked by reading them. As
# functions they can be RENDERED, and the guard asks the question that actually matters:
# does the message a human sees carry the refusal, and carry it where the block says it is?


def _rescan_red_message( what, steps, detector_now, ref_now, measured, recorded ):
    """The rescan red's message. The withheld block promises a notice BELOW; this ends with one."""
    return (
        f"{what} SINCE THE LAST RECORDED FULL SCAN, and re-running it here does not match "
        f"what is on record. {_rescan_lead_sentence()}\n"
        f"{steps}\n"
        f"    detector_sha256   : {detector_now}\n"
        f"    scanned_ref_sha   : {ref_now}\n"
        f"    scan_fingerprint  : {measured}\n"
        f"    last recorded     : {recorded[ 'scanned_at' ]}, "
        f"{recorded[ 'distinct_values_at_tip' ]} distinct values, "
        f"{recorded[ 'real_findings' ]} real"
        + _rotation_held_notice()
    )


def _branch_triage_message( untriaged, steps, recorded ):
    """
    The branch-triage red's message.

    ⚠️ Its TRIAGE instruction is deliberately NOT gated: adding a triaged row with a
    one-line reason is triage, which the hold asks for. The hold separates TRIAGE from
    RECORDING A SCAN, not writes from reads (Mr Radio's ruling, 2026-08-30).
    """
    return (
        f"{len( untriaged )} finding(s) on {recorded[ 'branch_ref' ]} have never been triaged. "
        "Values are masked — key, path and a truncated digest, never the secret:\n"
        + chr( 10 ).join( "    " + row for row in untriaged )
        + "\n\nIf one is real, remove it and read it from the environment or the secret store. "
          "If it is a false positive, triage it and add its row to branch_accepted AS A KEY "
          "WHOSE VALUE IS A ONE-LINE REASON — a bare row is refused:\n"
        + steps
        + _rotation_held_notice()
    )


def _refusal_lands_below_every_promise( message, promise, refusal ):
    """
    Does every "the hold is BELOW" in this message have the refusal below it?

    🔴 BOTH OPERANDS ARE `rindex`, AND EACH SIDE COST A SEPARATE MEASUREMENT.

    The RIGHT side first: written with `.index( promise )` a mutation SURVIVED, because the
    phrase appears twice in the rescan red — once in the lead sentence, once in the withheld
    block — and a refusal sitting between them satisfied the first. Every promise needs the
    refusal below IT, so the binding promise is the LAST.

    The LEFT side is the same bug mirrored, found by Krishna 🦚 reviewing the fix for the
    right one. `.index( refusal )` takes the FIRST mention of the refusal, so a message that
    MENTIONS the refusal early and also appends it properly at the end is rejected. That errs
    safe — a false fail, never a false pass — but it is exactly what this file's own guard
    comment condemns: punishing a shape it should be indifferent to. The binding refusal is
    the last one too.

    ⇒ The pair is the lesson: fixing one end of a two-sided comparison is half a fix, and the
      half you did not look at is the one that reads as correct because you just thought hard
      about its neighbour.

    Requires:
        - message, promise and refusal are strings; promise is matched case-insensitively

    Ensures:
        - True when the message makes no promise at all (nothing to point at)
        - True when the last refusal appears after the last promise
        - False otherwise
        - never raises
    """
    lowered = message.lower()
    if promise.lower() not in lowered: return True
    if refusal not in message:         return False
    return message.rindex( refusal ) > lowered.rindex( promise.lower() )


def _render_every_red_under_a_hold():
    """
    Every red's message, actually rendered, with the hold forced ACTIVE.

    🔴 THE REGISTRY IS CHECKED AGAINST THE DERIVATION, NOT TRUSTED. A hand-written dict of
    builders is exactly the "list of names that rots" Clayton's derivation exists to avoid —
    so the guard asserts this registry covers every red the AST walk finds. A new red with
    no entry here does not slip through; it fails loudly, naming itself.

    Ensures:
        - returns {red name -> the message that red would print}, hold ACTIVE
    """
    recorded = _recorded_for_gate()
    root     = cu.get_project_root()
    with _hold( True ):
        steps = _clear_the_red_steps( recorded, root )
        return {
            "test_a_detector_change_forces_a_full_rescan" : _rescan_red_message(
                "THE DETECTOR CHANGED", steps, "sha-a", "sha-b", "sha-c", recorded ),
            "test_the_branch_we_commit_to_carries_no_untriaged_finding" : _branch_triage_message(
                [ "a|masked|row" ], steps, recorded ),
        }


def _rescan_lead_sentence():
    """
    The sentence that INTRODUCES the recipe — held to the same condition as the recipe.

    🔴 GATING A RECIPE DOES NOTHING WHILE THE SENTENCE ABOVE IT STILL GIVES THE INSTRUCTION.
    Rachel 🕊️ found the recipe printing beside the refusal and the fix gated the recipe LIST.
    One sentence higher, the red opened "Re-scan, TRIAGE the output, and record the result",
    ungated — measured at 39d912ec, rendering THREE lines above the WITHHELD block and ELEVEN
    above "DO NOT CLEAR THIS RED BY RECORDING A SCAN". So the red still argued with itself,
    and in the worst possible ORDER: a reader acting on the first instruction found never
    reaches the refusal eleven lines down (Mr Radio's reading, and the reason this is the
    sharpest item in the sweep).

    THE FACT SURVIVES, THE INSTRUCTION DOES NOT. "The fingerprint cannot be filled in without
    scanning" is true in both states and worth saying in both — it is what stops someone
    pasting a value. Only the imperative is suppressed, and only while the hold stands. Same
    shape as `_rotation_held_notice`: ONE condition, no second flag.

    Requires:
        - nothing; safe to call in either hold state

    Ensures:
        - hold ACTIVE -> no imperative to re-scan, triage or record
        - hold CLEAR  -> the full instruction, exactly as it read before the hold existed
    """
    unfakeable = ( "The fingerprint is measured by this test, so it cannot be filled in "
                   "without scanning" )
    if _rotation_hold_is_active():
        return ( f"{unfakeable} — and while the rotation hold below stands it must not be "
                 "filled in AT ALL. What follows is the state that was measured, not a "
                 "recipe:" )
    return ( "Re-scan, TRIAGE the output, and record the result — "
             f"{unfakeable[ 0 ].lower()}{unfakeable[ 1: ]}:" )


# ── WHAT THE NOTICE MUST STILL SAY, AS LITERALS ───────────────────────────────────
#
# 🔨 MR RADIO 🦉'S RULING, 2026-08-30 — and it is a DISTINCTION, not an exception to the
# earlier one. He ruled we pin the SHAS and deliberately not the wording, because prose should
# stay rewritable and asserting it is churn at rotation for no safety. That ruling stands
# untouched. This is a different class:
#
#   the "below" I declined to pin is a POINTER — a wrong pointer misleads about LOCATION
#   the first line is the REFUSAL — an inverted refusal misleads about the DECISION
#
# ⇒ Prose stays free. MEANING does not. These are the words that make the sentence a refusal
#   rather than a suggestion, and they are LITERALS here on purpose — the moment they are
#   derived from ROTATION_HELD_NOTICE they stop being able to disagree with it.
#
# ⚠️ SHA LITERALS ALONE DO NOT CLOSE THIS, and that was my first proposal. Clayton measured it:
# a notice naming both shas correctly can still say the opposite of a refusal. The shas answer
# "is this notice about the right thing"; only these answer "does it still refuse".
REFUSAL_MARKERS = ( "DO NOT CLEAR THIS RED BY RECORDING A SCAN", "is REFUSED until rotation lands" )


ROTATION_HELD_NOTICE = (
    "\n"
    "  🔴 DO NOT CLEAR THIS RED BY RECORDING A SCAN.\n"
    f"     The re-scan and triage are already done, on branch wt-maya-4f0ced13 at "
    f"{ROTATION_HELD_COMMIT},\n"
    "     HELD UNMERGED until the postgres credential is rotated (Rick's call).\n"
    f"     A fixture change moving detector_sha256 to {ROTATION_HELD_SHA}\n"
    "     is REFUSED until rotation lands. This red is the only branch-level signal that\n"
    "     the credential work is unfinished; greening it changes the signal, not the risk."
)


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

    steps = _clear_the_red_steps( recorded, root )
    what  = ( "THE DETECTOR CHANGED" if detector_now != recorded[ "detector_sha256" ]
              else "THE PUBLISHED TIP MOVED" if ref_now != recorded[ "scanned_ref_sha" ]
              else "THE RECORDED SCAN DOES NOT MATCH WHAT THIS SCANNER MEASURES" )

    findings = _scan_once( recorded[ "scanned_ref" ], root )
    measured = _scan_fingerprint( findings )
    assert measured == recorded.get( "scan_fingerprint" ), _rescan_red_message(
        what, steps, detector_now, ref_now, measured, recorded )

    # The COUNTS guard that used to live here now has its own test — see
    # test_the_recorded_counts_are_derived_from_the_same_scan below. It was moved because
    # an assertion placed behind this one never runs while this one is red, and the failing
    # SET reads identically whether the guard passed, failed, or was never reached.


def test_the_recorded_counts_are_derived_from_the_same_scan():
    """
    The recorded candidate/value counts must come from the scan, not from a keyboard.

    🔴 THIS LIVES IN ITS OWN TEST ON PURPOSE, and the reason is the finding that produced
    it (Mr Radio 🦉 + Rachel 🕊️, 2026-08-30, independently). It was first written as three
    more lines inside test_a_detector_change_forces_a_full_rescan, BEHIND that test's
    fingerprint assertion — and that fingerprint is red in this tree (row 8202d795). An
    assertion behind a failing one is present in the file and absent from the run, and the
    failing SET is byte-identical whether it passed, failed, or never executed. Measured:
    with the guard inline the file reported 1 failed / 60 passed and the guard had not run;
    standing on its own it reports 2 failed, and the second id NAMES this reason.

    ⇒ A guard that shares a test with an assertion ahead of it is only as reachable as that
      assertion. Separate tests are what make a failing set carry information.
    """
    import json

    root     = cu.get_project_root()
    record   = root + "/src/tests/unit/fixtures/secret_scan_last_full_scan.json"
    recorded = json.load( open( record ) )

    _require_ref( recorded[ "scanned_ref" ], root )
    findings = _scan_once( recorded[ "scanned_ref" ], root )

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
    #
    # 🔴 THIS RED CARRIES MAYA'S HOLD NOTICE, AND IT HAS TO. The first cut of this message
    # ended "Re-record them from the SAME scan, and re-do the TRIAGE" — which is exactly the
    # action ROTATION_HELD_NOTICE REFUSES while the postgres credential is unrotated. The
    # two guards landed within minutes of each other (5f288b18 and 3a96ad03) and the branch
    # then emitted TWO reds giving OPPOSITE instructions, with mine reading as the more
    # actionable of the pair. A second red that contradicts the first is worse than no
    # second red: it hands the reader a way to clear a hold by obeying the wrong guard.
    counted = {
        "candidate_locations_at_tip" : len( findings ),
        "distinct_values_at_tip"     : len( { digest for _o, _n, _k, _len, digest in findings } ),
    }
    disagreed = [ field for field, value in counted.items() if recorded.get( field ) != value ]
    assert not disagreed, (
        "THE RECORDED COUNTS DO NOT MATCH THE SCAN THIS TEST JUST RAN — "
        f"{', '.join( disagreed )}. These fields were not re-derived from the scan they "
        "claim to summarise, and a count that moved means FINDINGS moved:\n"
        + "".join( f"    {field:28}: recorded {recorded.get( field )!r}, measured {value!r}\n"
                   for field, value in counted.items() )
        + _rotation_held_notice()
    )

    # 🔴 `real_findings` IS DELIBERATELY NOT ASSERTED HERE, AND THAT IS THE REMAINING HOLE.
    # The two counts above are derivable from `findings`, so they cannot be filled in by
    # hand. `real_findings` is a TRIAGE VERDICT — how many candidates a human judged real —
    # and no scan can compute it, so no assertion here can defend it. Measured 2026-08-30:
    # re-derive both counts after the scan gains a candidate, leave `real_findings` at its
    # old value, and this suite goes GREEN with the new candidate never triaged.
    # ⇒ This test now proves the scan was re-run AND the counts re-derived from it. It still
    #   does not prove anyone LOOKED at what moved. That needs a reviewer, not an assert.
    #
    # (Rachel 🕊️ and Mr Radio 🦉 both raised this against the first cut of the block above,
    # independently, within four minutes. The block was written as though it closed the
    # triage hole; it closes HAND-EDITING of two derived counts, which is a smaller thing.)
    #
    # ⚠️ AND THE GUARD ABOVE IS UNREACHABLE WHILE THE FINGERPRINT ASSERT IS RED. Every
    # assertion in this test runs in sequence, so the counts check only executes once the
    # fingerprint agrees. In the tree this was written in the fingerprint does NOT agree —
    # that is row 8202d795, Maya's — so the guard is carried, not exercised. A new assertion
    # placed behind a failing one is present in the file and absent from the run, and the
    # test id in the failing set reads identically either way.


def test_the_refusal_markers_are_themselves_pinned():
    """
    🔴 THE YARDSTICK CAN BE EDITED, AND NOTHING NOTICED. Found by my own arm 3 while proving
    the pin: shortening `REFUSAL_MARKERS` from two entries to one leaves the file GREEN at
    2 failed / 73 passed. Every check that uses the tuple keeps passing, because they all ask
    "is each marker present" and there is simply one less marker to ask about.

    So the guard could be narrowed to nothing, one entry at a time, and the suite would agree
    at every step. That is Clayton 😎's own line arriving on my own work for the second time
    tonight — NEVER LET AN INSTRUMENT CERTIFY ITSELF — and it is the fourth appearance of the
    shape this file has been chasing all evening: a check protected by nothing but the absence
    of an edit.

    ⚠️ THE LITERALS BELOW ARE SPELLED OUT A SECOND TIME ON PURPOSE. Deriving them from
    `REFUSAL_MARKERS` would make this a tautology — the exact defect that let the notice be
    inverted, since the anchor there was derived from the constant it was checking. Two
    independent spellings can disagree; one spelling read twice cannot.
    """
    # 🔴 EXACT MEMBERSHIP AND COUNT — Mr Radio 🦉's ruling, tightening my first cut, and the
    # reason generalises past this tuple: **a presence-check over a list is satisfied by
    # SHORTENING the list.** My first version asserted each expected marker was `in` the tuple
    # plus `len >= 2`. That catches a removal only because I happened to name both survivors,
    # and says nothing about a tuple that GROWS.
    #
    # 🔴 AND MY FIRST STATEMENT OF *WHY* THAT MATTERS WAS WRONG — Clayton 😎 corrected it, and
    # the correction is worth more than the assert. I wrote that an added entry is "coverage
    # the guard does not have, because nothing checks it". False: BOTH loops check every
    # marker. The real hazard is a marker that is TRIVIALLY SATISFIED. Measured, and it is the
    # strongest single receipt this guard has:
    #
    #     adding `""` to REFUSAL_MARKERS  ->  2 failed / 74 passed, GREEN before this assert
    #
    # `""` is `in` every string, so every presence check passes, the tuple looks longer, and
    # DISCRIMINATION GOES TO ZERO while the suite reports health. That is this file's recurring
    # shape once more: a guard weakened by an edit that makes it look stronger.
    #
    # ⚠️ AND THE PRICE, STATED RATHER THAN OMITTED. This assert also blocks a LEGITIMATE
    # tightening — adding "greening it changes the signal, not the risk", a real phrase from
    # the notice that both loops would genuinely check, reddens here too (measured: 3 failed /
    # 73 passed). That is not a false positive to be fixed; it is the COST of the rule.
    # Widening the guard now takes ONE DELIBERATE TWO-PLACE EDIT — add the marker to the tuple
    # AND to `expected` below, in the same change. Cheap, and it makes widening a decision
    # somebody made rather than a line that drifted in.
    #
    # It is the fixture-that-cannot-discriminate class from CLAUDE.md, arriving on a yardstick
    # rather than on a test: if two quantities can be exchanged without changing the expected
    # output, the check asserts their SUM and not their identity, whatever it is named. A set
    # comparison discriminates where a membership loop cannot.
    #
    # ⚠️ THE LITERALS ARE SPELLED A SECOND TIME ON PURPOSE. Deriving `expected` from
    # REFUSAL_MARKERS rebuilds the tautology this branch exists to remove — it is exactly how
    # the notice became invertible: an anchor derived from the thing it checks.
    expected = {
        "DO NOT CLEAR THIS RED BY RECORDING A SCAN",
        "is REFUSED until rotation lands",
    }
    assert set( REFUSAL_MARKERS ) == expected, (
        f"REFUSAL_MARKERS is not the pinned set. missing={sorted( expected - set( REFUSAL_MARKERS ) )} "
        f"unexpected={sorted( set( REFUSAL_MARKERS ) - expected )}. A marker REMOVED narrows "
        "what 'still refuses' means. A marker ADDED is not automatically wrong — a real phrase "
        "from the notice genuinely strengthens this guard — but an empty or near-empty one is "
        "satisfied by any text at all and quietly takes the discrimination to zero. So widening "
        "is allowed and must be DELIBERATE: add it to the tuple AND to `expected`, in one edit" )
    assert len( REFUSAL_MARKERS ) == len( expected ), (
        f"REFUSAL_MARKERS has {len( REFUSAL_MARKERS )} entries against {len( expected )} pinned. "
        "The set comparison above is blind to a DUPLICATE, which would make a two-marker guard "
        "read as though it checked more than it does" )


def test_the_rescan_red_still_carries_the_two_shas_that_make_it_actionable():
    """
    Pins the SHAS, deliberately not the wording (Mr Radio, 2026-08-30).

    The prose in ROTATION_HELD_NOTICE can be rewritten freely and should be — it is
    documentation. What must survive every rewrite is the two identifiers a reader can
    CHECK: the held commit that already contains the re-scan, and the detector sha whose
    arrival in the fixture is refused before rotation. Assert the wording and this test
    becomes churn at rotation for no safety; assert the shas and it stays true through any
    rewrite that keeps the message useful.

    🔴 THE SECOND ASSERTION IS THE LOAD-BEARING ONE. A notice that exists but is never
    APPENDED to the failure message reaches nobody, and the first assertion alone cannot
    tell the difference — the constant would still contain both shas while the red printed
    without it. Tiberius's ec8627ad adds ~37 lines around that message region, so an edit
    dropping the append is a live possibility rather than a hypothetical.
    """
    import inspect

    # 🔴 LITERALS, NOT THE CONSTANTS. The first cut of this test asserted
    # `ROTATION_HELD_COMMIT in ROTATION_HELD_NOTICE`, which is a tautology: the notice is
    # built by interpolating that constant, so changing the constant changes both sides and
    # the assertion stays true. Mutation-proven — swapping the commit to "deadbeef" and the
    # detector sha to all-zeros both SURVIVED. Two values derived from each other cannot
    # discriminate a swap between them, whatever the assertion is named.
    assert "034e44ac" in ROTATION_HELD_NOTICE, (
        "the notice must name the HELD COMMIT 034e44ac — it is what a reader checks instead "
        "of re-deriving a credential judgement at 3am" )
    assert "8675ec7a1c0c677e56dc6e243be7af51ee2c715f17ec6a93e1a3c731c360633f" in ROTATION_HELD_NOTICE, (
        "the notice must name the detector sha whose arrival in the fixture is refused "
        "before rotation" )

    # 🔴 THE SHAS SAY WHAT THE NOTICE IS ABOUT. THEY DO NOT SAY IT STILL REFUSES.
    # Clayton 😎 measured exactly that: a notice naming both shas correctly, with its first
    # line rewritten to "it is probably fine to record a scan here", passed every check in
    # this file. Pinning identifiers and pinning a decision are different jobs.
    for marker in REFUSAL_MARKERS:
        assert marker in ROTATION_HELD_NOTICE, (
            f"the notice no longer contains {marker!r}, so it has stopped refusing. Rewrite "
            "the prose freely — but a rewrite that removes the refusal is an inversion, and "
            "this red is the only branch-level signal that the credential work is unfinished" )

    # 🔴 THE LEAD SENTENCE MUST STAY BEHIND ITS GATE, AND ONLY A RENDERED CHECK SEES IT.
    # Found by mutation rather than by reading, and it was the ONLY survivor of an eight-arm
    # sweep: replace `{_rescan_lead_sentence()}` in the rescan red with the literal text it
    # used to carry, and the gate is bypassed completely with every test still passing. The
    # notice has had a tripwire for exactly this shape since it was written; its own opening
    # sentence had none, and the tests that touch `_rescan_lead_sentence` all call it
    # directly — so nothing asked whether the RED still goes through it.
    #
    # Asserted on the rendered message, not on the call: what matters is that a reader under
    # a hold is never told to re-scan and record, whatever the code looks like.
    held = _render_every_red_under_a_hold()[ "test_a_detector_change_forces_a_full_rescan" ]
    assert "re-scan, triage the output, and record the result" not in held.lower(), (
        "the rescan red tells a reader to re-scan and record while the hold stands — the one "
        "action the notice in the same message REFUSES, and it is read first. The lead "
        "sentence has been inlined past _rescan_lead_sentence()" )

    source = inspect.getsource( test_a_detector_change_forces_a_full_rescan )
    assert "_rotation_held_notice" in source or "_rescan_red_message" in source, (
        "the rescan red no longer appends ROTATION_HELD_NOTICE, so the warning reaches "
        "nobody who hits it. Re-attach it to the assert message." )


def test_the_position_rule_is_measured_on_constructed_strings_not_only_on_the_real_message():
    """
    🔴 THE REAL MESSAGE EXERCISES ONE ROW OF THIS TABLE. That is the whole reason the rule
    was wrong twice: a check that only ever sees the shape it was written against agrees with
    itself. These five strings are the shapes, built by hand so the ordering is the only
    variable — Krishna 🦚's table, pinned rather than quoted, because a truth table in a DM
    is a claim and a truth table in a test is a control.

    Row 5 is the one that matters and the one neither of us saw first: a message MENTIONING
    the refusal early and also appending it properly at the end is CORRECTLY SERVED, and the
    guard rejected it while `.index` was on the left. Erring safe is not the same as being
    right, and this file's own comments condemn exactly that shape.
    """
    P, R = "rotation hold below", "🔴 DO NOT CLEAR"
    cases = [
        ( f"{P} ... {R}",              True,  "the ordinary case — one promise, refusal below" ),
        ( f"{P} ... {P} ... {R}",      True,  "two promises, refusal below both" ),
        ( f"{P} ... {R} ... {P}",      False, "a promise with nothing below it — the right-side bug" ),
        ( f"{R} ... {P}",              False, "refusal above the only promise" ),
        ( f"{R} ... {P} ... {R}",      True,  "mentioned above AND appended below — the left-side bug" ),
    ]
    for text, expected, why in cases:
        assert _refusal_lands_below_every_promise( text, P, R ) is expected, (
            f"the position rule got {why!r} wrong — expected {expected}" )

    assert _refusal_lands_below_every_promise( "no promise here at all", P, R ) is True, (
        "a message that makes no promise has nothing to point at, so it cannot point at "
        "nothing — this guard is about a broken promise, not about mandating one" )


def test_every_red_that_withholds_the_recipe_also_carries_the_notice():
    """
    🔴 THE GUARD ABOVE COVERED ONE RED OUT OF THREE, AND THE UNCOVERED ONE WAS BROKEN.

    `test_the_rescan_red_still_carries_the_two_shas_that_make_it_actionable` inspects
    exactly one function by name. Measured 2026-08-30: three reds print the withheld
    block, two appended the notice, and the third —
    `test_the_branch_we_commit_to_carries_no_untriaged_finding` — did not. The withheld
    block says "while the rotation hold BELOW is active", so that red pointed a reader at
    a hold that never appeared. A guard naming ONE site cannot see a second site going
    wrong, which is the same shape as every finding on this file tonight.

    ⚠️ AND A LIST OF NAMES WOULD ROT THE SAME WAY. This does not enumerate the reds; it
    DERIVES them — every function whose body renders `_clear_the_red_steps` into an
    assert message — so a fourth red added next month is covered on the day it is
    written, by nobody remembering anything.

    The helper tests that call `_clear_the_red_steps` to assert ON it are excluded by the
    same mechanical rule rather than by name: they inspect the returned block, they do not
    put it in front of a reader, so they have nothing to point at.

    Ensures:
        - every red rendering the withheld block also references `_rotation_held_notice`
        - the reds are derived from the source, never listed, so the check cannot go stale
        - it fails loudly if it finds NO reds at all, because a guard that silently
          measures an empty set is the failure mode this file already has three of
    """
    import ast, inspect

    module_src = inspect.getsource( sys.modules[ __name__ ] )
    reds       = []
    for node in ast.walk( ast.parse( module_src ) ):
        if not isinstance( node, ast.FunctionDef ): continue
        body = ast.get_source_segment( module_src, node ) or ""
        if "_clear_the_red_steps" not in body:  continue
        if not _renders_into_a_failure_message( node ): continue
        reds.append( node.name )

    assert reds, (
        "no red was found rendering the withheld block — either the reds were renamed or "
        "this derivation broke. An empty set passing is not a pass." )

    # 🔴 RENDER, DO NOT READ THE SOURCE — Maya 🌻, on Mr Radio 🦉's requirement, upgrading
    # the second half of this guard while keeping Clayton 😎's derivation above untouched.
    # **A call-shape assertion cannot see a missing referent.** The check here used to be
    # `"_rotation_held_notice" in body`, and it fails in BOTH directions:
    #
    #   FALSE PASS — measured. I wrote the same check myself and mutation-proved it blind to
    #   two of the four things it should catch: a red losing its notice, and the guard
    #   narrowing itself back to one subject. Both SURVIVED.
    #   FALSE FAIL — measured, one commit ago. Moving each message into a builder is a pure
    #   improvement, and the source check reddened on it because the notice was no longer
    #   spelled inside the red. A guard that punishes a refactor it should be indifferent to
    #   is measuring the wrong thing.
    #
    # THE INVARIANT IS A PROMISE ABOUT POSITION. The block says "the rotation hold BELOW is
    # active", so the refusal must be present AND below. A notice above the block passes any
    # `in` check and still leaves the reader looking downward at nothing.
    rendered = _render_every_red_under_a_hold()

    unrendered = sorted( set( reds ) - set( rendered ) )
    assert not unrendered, (
        f"{unrendered} print the withheld block and have no entry in "
        "_render_every_red_under_a_hold, so this guard cannot see what they say. A registry "
        "that silently covers less than the derivation is the staleness the derivation "
        "exists to prevent — add the red there, do not narrow the derivation" )

    promise    = "rotation hold below"
    # 🔴 THIS ANCHOR USED TO BE DERIVED FROM THE THING IT CHECKS, WHICH MADE IT A TAUTOLOGY.
    # It read `ROTATION_HELD_NOTICE.strip().splitlines()[ 0 ]`, and the message it is looked
    # for in is built by `_rotation_held_notice()`, which RETURNS that constant. Both sides
    # moved together, so no edit to the notice could ever make them disagree. Measured, and
    # reproduced independently by Clayton 😎 (sha `350540e02edf`): rewriting the first line to
    # "it is probably fine to record a scan here" left the file GREEN at 2 failed / 73 passed.
    # **The refusal could be INVERTED and nothing noticed.**
    #
    # My own note, written earlier tonight and then built into the guard meant to catch this
    # family: two values derived from each other cannot discriminate a swap between them,
    # whatever the assertion is named.
    first_line = REFUSAL_MARKERS[ 0 ]

    # 🔴 THE PROMISE MUST LIVE IN THE BLOCK, NOT MERELY SOMEWHERE IN THE MESSAGE.
    # Clayton 😎's survivor 2 is what exposed this, though not the way either of us first read
    # it. He measured that deleting "below" from the LEAD SENTENCE survives while deleting it
    # from the WITHHELD BLOCK is killed, and read that as "the block's copy is pinned". I
    # re-measured and he is right — arm 2 reddens, arm 1 does not — but the REASON is
    # incidental, and that is the finding:
    #
    #   the block is pinned ONLY because the branch-triage message has no lead sentence, so
    #   deleting the block's "below" leaves that message with no promise at all and trips the
    #   membership check. Add a lead sentence to that red — an ordinary, improving edit — and
    #   the block's promise silently becomes free in EVERY message.
    #
    # So the check below is scoped to the block itself. `promise in message` is satisfiable by
    # any other sentence that happens to say the same words, which makes the guard's subject a
    # coincidence of wording rather than the thing it means to protect.
    #
    # ⚠️ THE LEAD SENTENCE'S OWN COPY STAYS UNPINNED — right call, WRONG REASON, and Clayton
    # 😎 replaced the reason on review. I declined on the ground that it is prose carrying no
    # contract. It is not decoration: it is a DECOY. `promise in message` reads the whole
    # message, so the lead sentence's copy is what keeps that check GREEN when the block's copy
    # is gone — load-bearing in the test while reading as ornament in the file.
    #
    # ⇒ So the answer was never to pin the prose. It is to stop the guard READING the prose:
    #   the assert below asks the block itself, and the one at the top of the loop binds that
    #   block to the message. Pinning the wording would have been churn at rotation AND would
    #   have left the decoy doing its work.
    with _hold( True ):
        block = _clear_the_red_steps( _recorded_for_gate(), cu.get_project_root() )
    assert promise in block.lower(), (
        "the withheld block no longer says the hold is BELOW, so nothing in it points the "
        "reader anywhere. Every check under this one asks whether the refusal is below a "
        "promise; with no promise in the block they are satisfied by any sentence in the "
        "message that happens to use the same words" )

    for name in sorted( reds ):
        message = rendered[ name ]

        # 🔴 BIND THE BLOCK TO THE MESSAGE FIRST — Clayton 😎, reviewing 0cf9fdd5, and it is
        # the mirror of the hole that commit closed. My block-scoped assert above reads the
        # block from the HELPER; every check below reads the MESSAGE as text. Nothing bound
        # the two, so a red could stop rendering the block ENTIRELY and stay green: he
        # dropped `{steps}` from the rescan message and got 2 failed / 73 passed, because
        # `promise` was satisfied by the lead sentence, `first_line` by the notice at the
        # end, and the position check compared two things that were both still there. **The
        # whole guard passed a message that no longer withheld anything.**
        #
        # ⚠️ FIRST IN THE BODY, NOT AFTER THE PROMISE CHECK. An assert behind one that is
        # already failing is carried, not exercised, and the failing SET reads identically
        # either way — this file has been bitten by that once already.
        assert block in message, (
            f"{name} does not print the withheld block at all. Every check below reads the "
            "message for the block's WORDS, which any other sentence can supply" )

        assert promise in message.lower(), (
            f"{name} no longer prints the withheld block. If that is deliberate this guard "
            "should go with it; if not, the hold stopped being visible where somebody reads it" )
        for marker in REFUSAL_MARKERS:
            assert marker in message, (
                f"{name}'s notice no longer REFUSES — {marker!r} is gone. Prose here is free "
                "to be rewritten and should be; its MEANING is not. A notice that reads as "
                "permission is worse than no notice, because the reader acts on it" )

        assert first_line in message, (
            f"{name} prints the withheld block — which says the rotation hold is BELOW — and "
            "its message does not carry the refusal. The reader is pointed downward at "
            "nothing, which reads as a stale copy-paste and teaches them to discount the next "
            "refusal too" )
        assert _refusal_lands_below_every_promise( message, promise, first_line ), (
            f"{name} carries the refusal ABOVE the block that promises it BELOW. Present but "
            "misplaced still leaves the reader looking down at nothing — which is why this "
            "asserts a POSITION and not a membership" )


def _renders_into_a_failure_message( node ):
    """
    Does this function put `_clear_the_red_steps`'s output in front of a READER?

    The distinction the guard above turns on, and it is structural rather than nominal: a
    red interpolates the block into an assert's MESSAGE, while a helper test passes it to
    an assert's CONDITION to inspect it. Only the first has a reader to mislead.

    Requires:
        - node is an ast.FunctionDef

    Ensures:
        - True when some `assert`'s message mentions the steps variable or the helper
        - False otherwise, including for a function with no asserts at all
        - never raises
    """
    try:
        for inner in ast.walk( node ):
            if not isinstance( inner, ast.Assert ) or inner.msg is None: continue
            msg = ast.dump( inner.msg )
            if "steps" in msg or "_clear_the_red_steps" in msg: return True
        return False
    except Exception:
        return False


# ── the rotation-hold gate — BOTH branches, because one of them had no test ────────
#
# Rachel 🕊️, 2026-08-30: "the hold-CLEAR branch has no test." It did not. The hold-active
# path was exercised by every run of this file; the other one existed only in a manual
# control arm that was never committed, which is the same thing as untested.


def _recorded_for_gate():
    import json
    root = cu.get_project_root()
    return json.load( open( root + "/src/tests/unit/fixtures/secret_scan_last_full_scan.json" ) )


@contextlib.contextmanager
def _hold( active ):
    """
    Run a block with the rotation hold forced into a KNOWN position.

    🔴 RACHEL'S FINDING 2 — THE FLIP-DAY HALF, AND IT IS THE SAME DEFECT AS FINDING 1 ONE
    LEVEL UP. Finding 1 was two halves of the hold on two switches; this is a test asserting
    a BRANCH while reading the AMBIENT switch. Both tests below were written while the hold
    was active, so `_clear_the_red_steps` returned the withheld block without anybody asking
    for it, and the assertions passed on a state they never declared. The day somebody
    legitimately sets ROTATION_HOLD_ACTIVE False, they redden — not because the gate broke
    but because the test was measuring the flag instead of the branch. A red on rotation day
    is the worst possible red: it fires at the exact moment nobody has attention to spare for
    triage, and it trains the reader to discount the reds that mean something.

    THE FIX IS THE SAME SHAPE AS c21d1f60'S: ONE CONDITION, DECLARED, NOT A SECOND FLAG.
    Every test that asserts hold-active behaviour says so, every test that asserts
    hold-clear behaviour says so, and NONE of them consults the ambient value. The file then
    stands green with the flag in either position — Rachel's own acceptance shape, and the
    only version of this that can be verified before rotation day rather than during it.

    Patches `sys.modules[ __name__ ]`, never the dotted name. Tiberius measured that the
    dotted form resolves, does NOT trip raising=True, and patches a SECOND copy of the module
    while the running one keeps its old value — a patch that silently does nothing.

    Requires:
        - active is a bool: True forces the hold ON, False forces it OFF

    Ensures:
        - ROTATION_HOLD_ACTIVE is `active` inside the block, whatever it was outside
        - the prior value is restored on the way out, including on an exception
    """
    monkeypatch = pytest.MonkeyPatch()
    try:
        monkeypatch.setattr( sys.modules[ __name__ ], "ROTATION_HOLD_ACTIVE", active )
        yield
    finally:
        monkeypatch.undo()


def test_while_the_hold_stands_the_recipe_is_withheld_and_names_where_to_read_it():
    """
    Suppressed, not deleted — the reader must be able to find it.

    The hold is FORCED ON rather than assumed on: this asserts the hold-active branch, so it
    has to be the branch that runs, on rotation day as much as today. See `_hold`.
    """
    with _hold( True ):
        recorded = _recorded_for_gate()
        steps    = _clear_the_red_steps( recorded, cu.get_project_root() )
    assert "WITHHELD" in steps
    assert "_how_to_clear_the_red" in steps


def test_while_the_hold_stands_no_step_telling_anyone_to_update_the_record_is_printed():
    """
    The whole defect in one assertion. The recipe ends by telling you to update
    detector_sha256 and the counts; the hold refuses exactly that. While the hold stands,
    that instruction must not appear.

    The hold is FORCED ON rather than assumed on — see `_hold`.
    """
    with _hold( True ):
        recorded = _recorded_for_gate()
        steps    = _clear_the_red_steps( recorded, cu.get_project_root() )
    for step in recorded[ "_how_to_clear_the_red" ]:
        assert step not in steps


def test_once_the_hold_lifts_every_recorded_step_prints_again():
    """
    The half that had no test. A gate that never opens is indistinguishable from the
    deletion this was written to avoid, so the open state has to be asserted, not assumed.

    This one already declared its state; it now says so through the same helper as its
    mirror image above, so the two read as one pair rather than as one careful test and one
    that happened to agree with the flag. The live-module-object caveat that used to sit here
    lives in `_hold`.
    """
    with _hold( False ):
        recorded = _recorded_for_gate()
        steps    = _clear_the_red_steps( recorded, cu.get_project_root() )
    assert "WITHHELD" not in steps
    for step in recorded[ "_how_to_clear_the_red" ]:
        assert step in steps


def test_while_the_hold_stands_the_red_gives_no_instruction_to_re_scan_or_record():
    """
    THE SHARPEST ITEM IN THE SWEEP, AND IT IS AN ORDERING DEFECT AS MUCH AS A GATING ONE.
    Gating the recipe LIST left the sentence introducing it untouched, so the red opened
    "Re-scan, TRIAGE the output, and record the result" three lines above the WITHHELD block
    and eleven above the refusal. A reader acting on the first instruction found never
    reaches the eleventh line.

    Asserted as ABSENCE OF AN IMPERATIVE rather than as an exact string, because the prose
    should stay rewritable — the same call Mr Radio made for the notice's shas.
    """
    with _hold( True ):
        lead = _rescan_lead_sentence()
    lowered = lead.lower()
    for imperative in ( "re-scan,", "record the result", "triage the output" ):
        assert imperative not in lowered, (
            f"while the hold stands the red must not tell anyone to {imperative!r} — it is "
            "the one action the notice eleven lines below REFUSES, and it is read first" )


def test_once_the_hold_lifts_the_red_tells_you_what_to_do_again():
    """
    The other half, and it is not decoration: a gate that never opens is indistinguishable
    from having deleted the instruction. The recipe is CORRECT and becomes actionable the
    moment the credential is rotated.
    """
    with _hold( False ):
        lead = _rescan_lead_sentence()
    assert "Re-scan, TRIAGE the output, and record the result" in lead, (
        "once the hold lifts the instruction must come back in full — suppressing it "
        "permanently is the deletion this design was written to avoid" )


def test_the_unfakeable_fact_is_stated_in_BOTH_states():
    """
    The fingerprint cannot be filled in without scanning. That is true whatever the hold is
    doing, and it is what stops somebody pasting a value — so it survives the gate. Only the
    IMPERATIVE is suppressed, never the fact.
    """
    with _hold( True ):
        held = _rescan_lead_sentence()
    with _hold( False ):
        clear = _rescan_lead_sentence()
    for state, text in ( ( "held", held ), ( "clear", clear ) ):
        assert "cannot be filled in without scanning" in text, (
            f"the {state} sentence dropped the one fact that stops a paste" )


def test_the_withheld_block_does_not_send_the_reader_to_an_ungated_recipe():
    """
    🔴 THE GATE WAS A REDIRECT TO A CLEAN DESTINATION. The withheld block names
    `_how_to_clear_the_red` in the fixture as where to read the suppressed recipe — and that
    file is unrefused prose, so the reader arrives at exactly the instruction the block just
    refused. Suppressing a recipe and then pointing at an unsuppressed copy of it is not a
    gate, it is a detour.

    Both halves are asserted because either alone is satisfiable while the hole stays open:
    a pointer naming a key that does not exist is a lie, and a key nobody is pointed to is
    unread.
    """
    import json

    recorded = _recorded_for_gate()
    with _hold( True ):
        steps = _clear_the_red_steps( recorded, cu.get_project_root() )

    assert FIXTURE_HOLD_KEY in steps, (
        "the withheld block sends the reader to the record without naming the key that "
        "repeats the refusal there — the redirect must carry the hold with it" )
    assert FIXTURE_HOLD_KEY in recorded, (
        f"the withheld block names {FIXTURE_HOLD_KEY!r} in the record, and it is not there. "
        "A pointer to a key that does not exist is worse than no pointer" )


def test_the_records_own_annotation_leads_it_and_refuses_the_recipe_below():
    """
    The direct-reader hole, closed. A human who opens the fixture is reached by no render
    site — the gate suppresses the recipe where it is PRINTED, and this file is not printed.

    ⚠️ THE ANNOTATION IS AN ADDED KEY, NEVER AN EDIT TO A RECORDED STRING. Mr Radio's
    ruling: the record is evidence of what was scanned and what the then-owner said to do
    about it, so rewriting `_how_to_clear_the_red` to fix a display destroys evidence.
    Adding a key is annotation. That is why this test asserts the recipe is still INTACT.

    🔴 AND IT MUST LEAD THE RECORD, NOT MERELY APPEAR IN IT (Krishna 🦚, reviewing 01516300).
    I first placed it BESIDE the recipe, which reads as tidy and is **the defect this change
    exists to fix, wearing the fix's own clothes**: a reader acts on the first instruction
    they find. Placed there, the order was `_why` on line 2 — which ends "goes red until
    somebody re-scans and records the result here" — the six steps on 3 to 10, and the
    refusal on 11. The reader met the refused action twice before the refusal.

    🔴 THE ORDER IS ASSERTED, NOT JUST FIXED. Krishna found nothing pinning key order, and a
    fix nothing defends is one the next person re-breaks by adding a dict entry in the
    natural place — at the end. Position is load-bearing in a file whose failure mode is
    somebody acting too early.
    """
    recorded = _recorded_for_gate()
    hold     = recorded[ FIXTURE_HOLD_KEY ]

    assert list( recorded.keys() )[ 0 ] == FIXTURE_HOLD_KEY, (
        f"{FIXTURE_HOLD_KEY!r} must be the FIRST key in the record — it currently sits at "
        f"position {list( recorded.keys() ).index( FIXTURE_HOLD_KEY ) + 1}. A refusal the "
        "reader reaches AFTER the instruction it refuses is not a refusal, it is a footnote" )

    assert "034e44ac" in hold, (
        "the record's annotation must name the held commit carrying the finished re-scan — "
        "it is what a reader checks instead of re-deriving a credential judgement" )
    assert "DO NOT" in hold.upper(), (
        "the annotation must REFUSE, not advise. A refusal that reads as a caveat is a "
        "caveat, and this fleet has already learned that once" )

    # 🔴 THE RECIPE MUST STILL BE THERE, WHOLE. Annotation adds; it never edits.
    assert recorded[ "_how_to_clear_the_red" ], "the recipe was removed rather than annotated"
    assert any( "detector_sha256" in step for step in recorded[ "_how_to_clear_the_red" ] ), (
        "a recorded step was rewritten. The record is evidence — annotate beside it, never "
        "edit inside it" )


def test_the_hold_is_declared_not_derived_from_any_sha_or_scan():
    """
    Rachel's finding, pinned. The gate must take no arguments — a gate that accepts a root,
    a sha, or a scan is a gate somebody can key to a coordinate, and a coordinate moves for
    reasons that have nothing to do with an unrotated credential.
    """
    import inspect
    assert inspect.signature( _rotation_hold_is_active ).parameters == {}


def test_lifting_the_hold_silences_the_refusal_as_well_as_restoring_the_recipe():
    """
    ONE SWITCH, BOTH HALVES. Before this, the recipe-withholding was gated and the refusal
    was not, so flipping the flag restored the recipe while the notice kept insisting it was
    REFUSED — the contradiction the hold exists to remove, pointing the other way.

    🔴 THIS TEST ONLY MEANS SOMETHING IF IT CHECKS THE FLIPPED STATE. Asserting the notice is
    present today would pass against both the gated and the ungated version, since today the
    hold IS active. The discriminating case is the one nobody will run until rotation day.

    ⚠️ AND IT CARRIED FINDING 2 ITSELF, IN THE COMMIT THAT CLOSED FINDING 1. The first and
    last assertions read the AMBIENT flag — `!= ""` is the hold-ACTIVE answer, so both went
    red the day the flag flipped, in the very test written to prove flip day was safe. Fixing
    only the two tests Rachel named would have left this file red on rotation day anyway,
    which is the whole thing she asked for: green in EITHER position.

    The restore control is kept and made position-independent. Asserting the flag is True
    afterwards was never testing the restore — it was testing the flag; comparing against the
    value captured BEFORE the flip tests the restore in either position.
    """
    before = _rotation_hold_is_active()

    with _hold( True ):
        assert _rotation_held_notice() != "", "while the hold stands the refusal must be emitted"

    with _hold( False ):
        assert _rotation_held_notice() == "", (
            "once the hold lifts the refusal must go SILENT — otherwise the recipe returns "
            "while the notice still calls it refused, which is the same contradiction "
            "pointing the other way" )

    assert _rotation_hold_is_active() == before, (
        "the flag must be restored to whatever it was before the flip — comparing against the "
        "captured value, not against True, because True is only the right answer today" )


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

    steps = _clear_the_red_steps( recorded, root )
    assert not untriaged, _branch_triage_message( untriaged, steps, recorded )


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
