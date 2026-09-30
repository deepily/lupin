"""
A TEST CANNOT ASK A HUMAN. The boundary, and why it is here rather than anywhere more
obvious.

🔴 THE INCIDENT (row e625e608, 2026-09-04). Plain `pytest src/tests/unit/ -q` runs fired
**33 REAL blocking yes/no prompts at Rick** on the live notification surface, between
18:33:24 and 18:48:36. He experienced it as one permission prompt re-firing however he
answered — it was never one prompt retrying, it was SEPARATE TESTS EACH FIRING A SEPARATE
ASK, seconds apart, each naming a different fixture row.

⚠️ **TWO DIFFERENT TIERS LEAKED, AND ONE RAN FROM A PROPERLY CONFIGURED SERVED CHECKOUT.**
This matters because the first report of the incident emphasised that one offending
process had `LUPIN_ROOT` pointing into `/tmp`. That explained only the
`sender_id: claude.code@unknown.deepily.ai` stamp on the later prompts — it never
explained the leak. Do not read this as one misconfigured seat: it is every unit tier,
including correct ones. (A third tier ran continuously throughout and produced none, so it
is not "any tier at any time" either — it is which tests get collected and reached.)

⚠️ THE PEOPLE WHO RAN THE TIERS DID NOTHING WRONG. They were told to run the FULL tier
rather than a hand-picked population, and they did. The harness had no boundary.

=== WHY THE EXISTING NETWORK GUARD COULD NOT CATCH THIS, AND WHY THAT IS CORRECT ===

`cosa.utils.unit_network_guard` already blocks outbound dials in the unit tier. It did not
fire, and it *should* not have: its `is_loopback()` deliberately returns True for
`127.0.0.1` / `localhost`, because TestClient and the real-socket arms bind loopback on
purpose, and — in that module's own words — "a guard that breaks legitimate tests gets
switched off, which is worse than no guard."

⇒ **The human notification surface lives at `localhost:7999`.** So the ask travels the one
route the network guard is REQUIRED to leave open. Widening that guard to catch it would
break every TestClient test in the repo.

⇒ **THEREFORE THE BOUNDARY BELONGS AT THE ASK, NOT AT THE SOCKET.** That is not a
preference; it is forced, because at the network layer the harmful call and the legitimate
ones are indistinguishable.

=== WHY NOT "THAT TEST SHOULD HAVE STUBBED IT" ===

Because it lasts exactly until the next unstubbed test. Containment that depends on every
future test author remembering to patch a seam is a convention, not a control, and this
repo's standing position is that a rule which depends on remembering is not installed. The
offending tests had ZERO stub references; the next test written will not have any either,
and nothing would tell its author.

=== THE SHAPE, BORROWED FROM A GATE THAT ALREADY WORKS ===

`_resolved_operator_attestation` (routers/tasks.py) refuses an accountless caller because
`account_email` is None for every API-key seat — no allowlist, no registry, nothing to
remember, and no way to type past it. This is the same move one layer down: the ask path
reads a fact the caller can neither forge nor forget, and refuses.

`PYTEST_CURRENT_TEST` is that fact. **pytest sets it itself, per test, with no cooperation
from anyone** — so a test cannot escape detection by neglecting to opt in, which is the
whole failure mode being closed. It also carries the node id, so the refusal NAMES the
test that tried.
"""
import os

# pytest exports this for the duration of each test. Nobody sets it by hand; that is the
# entire point — see the module docstring.
PYTEST_NODE_ENV_VAR = "PYTEST_CURRENT_TEST"

# The deliberate escape, spelled the way this repo already spells them
# (`LUPIN_ALLOW_GIT_STASH`, `LUPIN_ALLOW_MERGE_COMMIT`): loud, explicit, greppable. It
# exists for the tests OF the ask path itself, which must reach the real function to test
# it. An ordinary test never needs this and should never set it.
ALLOW_ENV_VAR = "LUPIN_ALLOW_HUMAN_ASK_IN_TESTS"


def test_node_id():
    """
    The pytest node id currently in flight, or None outside a test.

    Ensures:
        - returns the node id string when running under pytest
        - returns None when not, and for a blank or non-string value
        - never raises
    """
    raw = os.environ.get( PYTEST_NODE_ENV_VAR )
    if not isinstance( raw, str ) or not raw.strip(): return None
    # pytest's value is "<node id> (setup|call|teardown)". The node id is the useful half.
    return raw.strip().split( " " )[ 0 ]


def containment_is_waived():
    """
    Whether the caller has EXPLICITLY waived containment for this process.

    Ensures:
        - True only for the exact string "1", so a stray empty or "0" value cannot
          silently open the door
        - never raises
    """
    return os.environ.get( ALLOW_ENV_VAR, "" ).strip() == "1"


def refusal_for_human_ask( question=None ):
    """
    The refusal when a TEST tries to block on a human, or None when the call is legitimate.

    Requires:
        - question is the spoken text of the ask, or None

    Ensures:
        - returns None when not running under pytest — the production path is untouched,
          and that is the case which must stay fast and silent
        - returns None when containment is explicitly waived
        - otherwise returns a non-empty message NAMING the test node id, so the refusal
          identifies the culprit rather than the victim
        - never raises

    ⚠️ RETURNS A MESSAGE RATHER THAN RAISING, so the caller decides the failure mode. A
    module that raised from inside a notification helper would turn a containment breach
    into an exception in whatever unrelated code happened to trigger it, and the caller is
    the only place that knows whether it can degrade or must stop.
    """
    node = test_node_id()
    if node is None:            return None
    if containment_is_waived(): return None

    asked = f" ({question!r})" if question else ""
    return (
        f"A TEST TRIED TO BLOCK ON A HUMAN{asked} — refused (row e625e608).\n"
        f"  test    : {node}\n"
        f"  Unit tiers fired 33 real prompts at Rick on 2026-09-04 because nothing "
        f"stopped them. The network guard cannot: the human surface is on localhost, "
        f"which that guard must leave open for TestClient.\n"
        f"  FIX THE TEST, NOT THIS GUARD: inject the seam — `approval_for_promotion` "
        f"takes `ask_fn`, so pass a fake. If a test genuinely must reach the real ask "
        f"path, set {ALLOW_ENV_VAR}=1 for that test alone and say why in the test."
    )
