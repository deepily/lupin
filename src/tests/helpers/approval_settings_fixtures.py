#!/usr/bin/env python3
"""
Writing an override-settings fixture that the STAMP will accept.

🔴 WHY THIS EXISTS. `_read_overrides` IGNORES every key in `STAMP_ENFORCED_KEYS` on a
file whose stamp does not verify — that is the whole point of the stamp, and it is
working. But every fixture written before the stamp landed writes a bare JSON body, so
each of them reads back as None and every assertion about `manager_pull_disabled` goes
red for a reason that has nothing to do with its subject.

⚠️ THE POPULATION WAS UNDER-REPORTED THE FIRST TIME, WHICH IS WHY THIS IS SHARED RATHER
THAN INLINED. The commit that parked the stamp named "16 fixtures" and had measured ONE
file. Running every file that names `task-approval-settings.json` — 17 of them — turned
up 25 failures across THREE files:

    test_a_falsy_string_does_not_switch_a_gate_on.py       16
    test_manager_pull_defaults_to_off.py                    8
    test_the_transition_door_calls_the_pull_toggle.py       1

⇒ A fourth file will be written eventually. It should find this helper rather than
rediscover the failure.

⚠️ IT DELEGATES TO THE MODULE'S OWN `_expected_stamp` AND DOES NOT REIMPLEMENT THE HMAC.
A fixture that computes the scheme itself agrees with the code until somebody changes the
scheme, and then it is a second opinion nobody asked for — the two-derivations-of-one-
value shape. Here there is exactly one derivation and the test rides it.

⚠️ AND IT IS NOT A WAY TO SOFTEN THE GUARD. The right fix for a red caused by the stamp is
to stamp the fixture, never to widen what the reader accepts: these tests' subject is the
boolean parse, and a stamped fixture leaves that subject exactly where it was.
"""
import json

import cosa.rest.task_approval_settings as approval


def stamped_json( body ):
    """
    `body` serialised as JSON, carrying the stamp the validated writer would have put on it.

    Requires:
        - body is a JSON-serialisable object. A non-dict is allowed on purpose — the
          reader has an arm for "the file is not an object" and it must still be able to
          write one

    Ensures:
        - returns a JSON string
        - a dict body carries `STAMP_KEY` when this process can compute one
        - a body that CANNOT be stamped is returned unchanged rather than raising. That
          covers two real cases and neither is an error: a non-dict body has nowhere to
          put a stamp, and a process with no `JWT_SECRET_KEY` cannot compute one. In the
          keyless case the reader's verdict is None — "cannot check", never "forged" — so
          it honours the key and the caller's arm measures what its name says anyway
        - does NOT touch the file or the module cache; the caller still owns both

    ⚠️ THE KEYLESS PATH IS NOT A SILENT PASS. It is the third state the stamp was
    deliberately given, and the reason `_stamp_is_valid` returns None rather than False:
    a dev box without a signing key must not read as an attack. Anything asserting the
    guard actually FIRES has to prove the secret is present in ITS process, not this one.
    """
    if isinstance( body, dict ):
        stamp = approval._expected_stamp( body )
        if stamp is not None: body = { **body, approval.STAMP_KEY: stamp }

    return json.dumps( body )
