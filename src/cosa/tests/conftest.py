"""
Collection-time config floor for the CoSA test tree — store row 5bf28e07.

WHY THIS FILE EXISTS
--------------------
`src/cosa/tests/**` is the 412-file tree that no gate references (row 5bf28e07,
measured under d97b024e). Surveying it — the first step of the WIRE-or-RULE-OUT
decision — died before it began: **9 files failed at COLLECTION with
`ValueError: [LUPIN_CONFIG_MGR_CLI_ARGS] is NOT set`**, which reads like nine broken
test files and is nothing of the sort.

Measured 2026-07-25, with a control in both directions:

    without this floor : 8,501 collected, 9 collection ERRORS
    with it            : 8,788 collected, 0 errors

⇒ **The 9 were an environment gap, not test rot**, and the 287-test difference is what
those 9 files contain. A survey that reported "9 files are broken" would have been a
measurement of this repo's env, dressed as a measurement of CoSA's tests.

THIS IS BUG 9fe8b80f's OWN FIX, NEVER APPLIED TO THIS TREE
----------------------------------------------------------
`src/tests/conftest.py` carries an identical floor and states the mechanism exactly:
modules like `cosa/rest/jwt_service.py` instantiate `ConfigurationManager` at
MODULE-IMPORT time, so a file that imports one needs the env var at COLLECTION time —
BEFORE any fixture runs. The wired tree hit this ("4 unit + 1 smoke file died at
collection") and fixed it there. **The CoSA tree has no root conftest at all**, so the
same defect sat here undisturbed — invisible, because nothing ever collected this tree.

⇒ That is row 5bf28e07's own thesis in miniature: **a suite no gate references cannot go
red, and a suite that cannot go red is indistinguishable from a suite that passes.** The
env gap survived precisely because nobody was looking.

WHAT THIS FILE DOES *NOT* DO
----------------------------
It does not wire this tree into any gate, runner, INI key or `test_type`. **Rick's
WIRE-or-RULE-OUT decision on 5bf28e07 is untouched.** This only removes a spurious
blocker so the decision is made about the tests' actual content rather than about an
unset environment variable.

`setdefault`, NOT a hard set — a FLOOR only. An explicit export (CI, the container, the
integration/e2e conftests that pin `config_block_id=Lupin:+Testing`) still WINS.

⚠️ DO NOT REFACTOR THIS INTO A FIXTURE. Fixtures run at EXECUTION time, after the
collection-time imports that need it. Moving it would re-break bare collection — the
warning `src/tests/conftest.py` already carries, repeated here because a reader arriving
in this tree will not have seen it.

The path is ROOT-RELATIVE (`/src/conf/...`) because `ConfigurationManager` prepends the
project root itself; an absolute host path would be doubled.
"""

import os
import secrets
import sys

# ── Bootstrap: make `cosa` importable before anything imports it ──────────────
# Mirrors src/tests/conftest.py. Per the PATH MANAGEMENT mandate, conftest is one
# of the named bootstrap exceptions that may touch sys.path directly.
lupin_root = os.environ.get( "LUPIN_ROOT" )
if lupin_root is None:
    lupin_root = os.path.abspath( os.path.join( os.path.dirname( __file__ ), "..", "..", ".." ) )
    os.environ.setdefault( "LUPIN_ROOT", lupin_root )

src_path = os.path.join( lupin_root, "src" )
if src_path not in sys.path:
    sys.path.insert( 0, src_path )

# ── Collection-time config floor (bug 9fe8b80f, applied to this tree) ─────────
os.environ.setdefault(
    "LUPIN_CONFIG_MGR_CLI_ARGS",
    "config_path=/src/conf/lupin-app.ini splainer_path=/src/conf/lupin-app-splainer.ini config_block_id=Lupin:+Development",
)

# ── Collection-time JWT secret floor (row adce3547) ───────────────────────────
# cosa/rest/jwt_service.py has no default signing secret — unset JWT_SECRET_KEY raises at
# MODULE IMPORT, which for a test file means at COLLECTION time, before any fixture runs.
# That is the point of the change; it also means a bare pytest run needs a value seeded
# here, exactly like the LUPIN_CONFIG_MGR_CLI_ARGS floor above.
#
# The value is GENERATED PER RUN, never a literal in this file. A fixed test secret checked
# into the repo would be the same shared-constant defect the application-side change exists
# to remove, only wearing a test costume. Subprocesses spawned by tests inherit it through
# os.environ, so a parent and a spawned server still agree on the signature.
#
# setdefault (NOT a hard set): an explicit export — CI, the container, or a test that pins
# its own secret before importing jwt_service — still WINS.
#
# DO NOT refactor this into a fixture: fixtures run at execution time, after the
# collection-time import that needs it.
os.environ.setdefault( "JWT_SECRET_KEY", "test-only-generated-per-run-" + secrets.token_urlsafe( 32 ) )
