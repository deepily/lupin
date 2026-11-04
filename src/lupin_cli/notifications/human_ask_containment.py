"""
Refuses blocking human asks from inside a pytest run; the boundary sits at the ask.

Plain unit-tier runs once fired 33 real blocking yes/no prompts at the operator on the live
notification surface, seconds apart. Each prompt came from a separate test and named a
different fixture row, though the operator saw it as one prompt re-firing however he answered.

Two different tiers leaked, one of them from a correctly configured served checkout. The
stray `LUPIN_ROOT` in one process explained only the wrong `sender_id` stamp on later prompts.
So this was not one misconfigured seat. The people running the tiers did nothing wrong:
they ran the full tier, and the harness had no boundary.

Why the existing network guard could not catch this, and why that is correct:

`cosa.utils.unit_network_guard` blocks outbound dials in the unit tier. Its `is_loopback()`
returns True for `127.0.0.1` and `localhost`, because TestClient and the real-socket
tests bind loopback. In that module's own words, a guard that breaks legitimate tests gets
switched off, which is worse than no guard.

The human notification surface lives at `localhost:7999`, so the ask travels the one route
the network guard must leave open. Widening it would break every TestClient test. At the
network layer the harmful call and the legitimate ones look the same, so the boundary has to
sit at the ask. That is forced, not a preference.

Why not rely on each test stubbing the ask:

That lasts until the next unstubbed test. Containment that depends on every future test author
remembering to patch a seam is a convention, not a control. The offending tests had no stub
references at all, and nothing would tell the author of the next one.

The shape is borrowed from `_resolved_operator_attestation` (routers/tasks.py). That gate
refuses an accountless caller because `account_email` is None for every API-key seat, so it
needs no allowlist, no registry and nothing to remember. The ask path likewise reads a fact
the caller can neither forge nor forget. `PYTEST_CURRENT_TEST` is that fact: pytest sets it
itself for each test, so a test cannot escape detection by neglecting to opt in. It also
carries the node id, so the refusal names the test that tried.
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
    Whether the caller has explicitly waived containment for this process.

    Ensures:
        - True only for the string "1" (surrounding whitespace is ignored), so a stray
          empty or "0" value cannot silently open the door
        - never raises
    """
    return os.environ.get( ALLOW_ENV_VAR, "" ).strip() == "1"


def refusal_for_human_ask( question=None ):
    """
    The refusal message when a test tries to block on a human, or None when legitimate.

    Requires:
        - question is the spoken text of the ask, or None

    Ensures:
        - returns None when not running under pytest — the production path is untouched,
          and that is the case which must stay fast and silent
        - returns None when containment is explicitly waived
        - otherwise returns a non-empty message naming the test node id, so the refusal
          identifies the culprit rather than the victim
        - never raises

    It returns a message rather than raising, so the caller decides the failure mode. A
    module that raised from inside a notification helper would turn a containment breach
    into an exception in unrelated code that happened to trigger it. Only the caller
    knows whether it can degrade or must stop.
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
