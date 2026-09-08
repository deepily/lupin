"""
THE PRIORITY FIREWALL — who may set which priority, and on what evidence.

Rick's broadcast e254ec7d, 2026-09-07, quoted rather than paraphrased so the next
reader can check the rules against the source:

  - "the only way a ticket gets an upgrade from P5 to P4 through P1 is through a me
     or a manager. I can update them at any time."
  - "The only way a ticket will ever get upgraded to P0 is through me. Full stop. I
     don't give a fuck if the server is on fire I am the only person allowed to
     establish that a ticket is P0."
  - "workers can file tickets, but they can only file a P5 ticket. That's the only
     kind. If they want that to be a higher priority, they need to escalate through
     the manager who will petition me."

THREE RULES, AND THEY ARE THREE SEPARATE CHECKS — do not collapse them into one
predicate. Row b8205986 says so in its own body, and the reason is that they key on
different evidence:

  | # | rule                        | who                                        |
  |---|-----------------------------|--------------------------------------------|
  | 1 | set priority = P0           | Rick ONLY. No manager, no emergency path.  |
  | 2 | RAISE priority to P1-P4     | Rick or a manager.                         |
  | 3 | CREATE above P5             | Rick or a manager. A worker's create is P5,|
  |   |                             | whatever it asks for.                      |

  Rule 4 of the original four — "pull from holding must take the highest priority" —
  is SUPERSEDED and is deliberately absent from this module. Rick rescinded manager
  pulling entirely (broadcast c43a29c5, 2026-09-07 ~21:26): "I want to rescind the
  feature that allows you to pull from the holding area into the queue and it must
  default to NO." A highest-priority-first refusal now sits under a switch that is
  off, so building it here would be building to a shape that has already moved.
  `task_approval_settings.refusal_for_pull` owns that surface.

TWO SOURCES OF EVIDENCE, AND THE SECOND IS WHAT MAKES THE FIRST MEAN ANYTHING
-----------------------------------------------------------------------------
Rick ruled both hinges, separately, by keypress:

  ROLE     comes FROM THE PERSONA SESSION BRIDGE (2026-09-07 ~20:55). Not the
           User.roles column, which was the recommended option and which he declined.
  IDENTITY comes FROM A VALIDATED ACCOUNT (2026-09-07 ~21:47, "Close it — require a
           real account"). A typed `actor` string is not sufficient authorization.

⇒ They answer different questions and must never be summarised together. The bridge
  says WHAT ROLE a caller claims; the account says WHETHER THE CALLER IS WHO THEY SAY.

🔴 SO RULE 1 IS STRONG AND RULES 2-3 ARE ADVISORY-BY-CONSTRUCTION, AND THAT ASYMMETRY
IS DELIBERATE RATHER THAN AN OVERSIGHT. Build to it knowingly; the row's own warning
is that four checks on top of a partly-typed identity have the strength of that string.

  Rule 1 keys on `approver_persona_for_account( account_email )`, which resolves a
  SIGNATURE-VALIDATED token to a persona. A caller cannot forge it. This is the same
  door the PROMOTE path's ask exemption already uses, and it is the working shape —
  brought here rather than a new mechanism being invented.

  Rules 2-3 key on the bridge role, which the child session's own SessionStart writes.
  A session therefore DECLARES its own role, and this module cannot refuse a session
  that declares itself a manager. It stops mistakes and misroutes, not forgery.

⚠️ AND DO NOT TEST RULES 2-3 AS THOUGH THEY WERE A FIREWALL. A test asserting that a
worker's P1 is refused must drive the door with a bridge that SAYS worker; it cannot
prove refusal against an actor who says otherwise, and a test claiming that would be
asserting something this design does not deliver. Rule 1 is the one that can carry a
forgery claim, because its evidence is a validated account.

WHAT WOULD UPGRADE RULES 2-3, surveyed on row b8205986 and NOT built here: User.roles
is a JSONB column defaulting to ["user"] (postgres_models.py:93-97), has_role() and
is_admin() are already written (auth_middleware.py:289, :336), roles already ride in
the JWT (auth.py:202), and both auth paths resolve to a real user row. It needs two
new role VALUES — "manager" and "worker" — and nothing else. Short path, deliberately
not taken, because Rick chose the bridge knowing this consequence.
"""
from cosa.rest.task_approval_settings import (
    approver_persona_for_account,
    canonical_persona_key,
    UNCONDITIONAL_APPROVERS,
)


# The priority ladder, highest authority first. Ordering is what "raise" MEANS, so it
# lives here as data rather than being re-derived by string comparison at each site —
# "P1" < "P2" is true lexically and true by rank, which is a coincidence that stops
# holding the moment anybody adds a "P10".
PRIORITY_RANK = { "P0": 0, "P1": 1, "P2": 2, "P3": 3, "P4": 4, "P5": 5 }

# The floor a worker may file at. Rick: "they can only file a P5 ticket. That's the
# only kind."
WORKER_CREATE_PRIORITY = "P5"

# The one priority reserved to Rick personally.
OPERATOR_ONLY_PRIORITY = "P0"

# The bridge's own vocabulary for a manager seat. Named here rather than repeated as a
# literal at each call site.
BRIDGE_ROLE_MANAGER = "manager"


def normalize_priority( value ):
    """
    The canonical upper-case priority string, or None.

    Requires:
        - value is a priority string, or None

    Ensures:
        - returns the stripped upper-case form when it is a known priority
        - returns None for None, blank, non-string, and any unknown value
        - never raises

    ⚠️ AN UNKNOWN VALUE RETURNS None RATHER THAN RAISING, and the callers below treat
    None as "no priority stated". Rejecting an unknown value is `task_store_rules`'
    job (VALID_PRIORITIES), and doing it in two places means two rules that agree
    until they do not.
    """
    if not isinstance( value, str ): return None
    candidate = value.strip().upper()
    return candidate if candidate in PRIORITY_RANK else None


def caller_is_operator( account_email ):
    """
    Whether the caller is Rick himself, proven by a validated account.

    Requires:
        - account_email is the email on a VALIDATED access token, or None

    Ensures:
        - returns True only when the account maps to an unconditional approver
        - returns False for None/blank/unmapped, and for an API-key-only caller
        - never consults a caller-declared string
        - never raises

    🔴 THIS IS THE ONE PREDICATE IN THIS MODULE A CALLER CANNOT FORGE, and rule 1
    rests on it alone. `approver_persona_for_account` resolves a signature-validated
    token; there is deliberately no `actor` parameter here, so there is no typed-name
    path to leave open by accident.

    ⚠️ IT REUSES `UNCONDITIONAL_APPROVERS` RATHER THAN NAMING RICK AGAIN. He is
    already identified there as the standing authority the allowlist delegates from,
    and a second spelling of "who is Rick" is a second thing to keep in step.
    """
    persona = approver_persona_for_account( account_email )
    if persona is None: return False
    return canonical_persona_key( persona ) in [
        canonical_persona_key( p ) for p in UNCONDITIONAL_APPROVERS
    ]


def caller_is_manager( bridge_role, account_email=None ):
    """
    Whether the caller holds a manager seat, per the bridge role Rick ruled on.

    Requires:
        - bridge_role is the role string the caller's session bridge declares, or None
        - account_email is the email on a VALIDATED access token, or None

    Ensures:
        - returns True when the bridge role is "manager" (case/space-insensitive)
        - returns True for the operator, who outranks every manager check
        - returns False for None/blank/any other role
        - never raises

    ⚠️ THE BRIDGE IS SELF-DECLARED AND THIS FUNCTION CANNOT REFUSE A LIAR. Said out
    loud at the predicate rather than only in the module docstring, because this is
    the line somebody will read in isolation while writing a test. Rick chose this
    source with the consequence written into the option he clicked.

    ⚠️ `account_email` IS ACCEPTED AND USED ONLY FOR THE OPERATOR SHORT-CIRCUIT. It is
    NOT a second gate on manager-ness — adding one would quietly change who counts as
    a manager, which is a rule Rick has not been asked about.
    """
    if caller_is_operator( account_email ): return True
    if not isinstance( bridge_role, str ):  return False
    return canonical_persona_key( bridge_role ) == canonical_persona_key( BRIDGE_ROLE_MANAGER )


def session_id_from_actor( actor ):
    """
    The session id embedded in an `actor` string, or None.

    Requires:
        - actor is the caller-declared "persona words + session id" string, or None

    Ensures:
        - returns the LAST whitespace-separated token when it looks like a session id
          (hex-ish, 8 or more characters), else None
        - returns None for None/blank/non-string and for a bare persona name
        - never raises

    ⚠️ THE SESSION ID IS CALLER-DECLARED LIKE THE REST OF `actor`, so this buys a
    LOOKUP, not a proof. It is the input to the bridge read Rick ruled for, and the
    bridge is itself self-written — the chain is advisory end to end. Rule 1 does not
    touch any of this, which is why rule 1 is the one that can carry a forgery claim.

    ⚠️ IT TAKES THE LAST TOKEN, NOT A FIXED POSITION. A persona may be one word or
    three ("mr radio", "maria"), so counting from the front is an enumeration that
    goes wrong the first time somebody has a longer name.
    """
    if not isinstance( actor, str ) or not actor.strip(): return None
    tail = actor.strip().split()[ -1 ]
    if len( tail ) < 8: return None
    # A session id is hex with optional hyphens. Testing the character CLASS rather
    # than a length or a hyphen count, so a full UUID and an 8-char prefix both pass
    # and a persona name whose last word happens to be long does not.
    stripped = tail.replace( "-", "" )
    if not stripped or not all( c in "0123456789abcdefABCDEF" for c in stripped ): return None
    return tail


def caller_is_manager_by_bridge( actor, account_email=None, manager_fn=None ):
    """
    Whether the caller holds a manager seat, resolved through the session bridge.

    Requires:
        - actor is the caller-declared "persona + session id" string, or None
        - account_email is the email on a VALIDATED access token, or None
        - manager_fn is an injectable ( session_id ) -> bool, or None for the live one

    Ensures:
        - returns True for the operator, who outranks every manager check
        - returns True when the bridge says this session is a manager figure
        - returns False when no session id can be read out of `actor`
        - returns False rather than raising if the bridge cannot be read
        - never raises

    🔴 IT DELEGATES TO `is_manager_figure` RATHER THAN RE-DERIVING MANAGER-NESS. That
    predicate is the ratified one for exactly this question: it gates store WRITES,
    it is correct SERVER-SIDE (it reads the implicit flag stamped at registration,
    because the persona-chain env is empty server-side), and it fails CLOSED on any
    doubt. Writing a second manager rule here would be two pieces of code deciding one
    rule — they agree until they do not, and the copy is usually the one that is wrong.

    ⚠️ NOT TO BE CONFUSED WITH THE COUNTING PREDICATE. `fleet_size_cap` deliberately
    does NOT use `is_manager_figure`, because for a CAP the question is "how many
    seats exist" and the name rule mis-classifies there (measured 2026-09-04: Cheech
    carried role="author" with a lineage and counted as a manager while John carried
    the identical role and counted as a worker). For AUTHORIZATION the name rule is
    ratified and the fail-closed degrade is wanted. Same words, two questions.
    """
    if caller_is_operator( account_email ): return True

    session_id = session_id_from_actor( actor )
    if session_id is None: return False

    if manager_fn is None:
        try:
            from lupin_cli.claude_code.hooks.lib.manager_figure import is_manager_figure
            manager_fn = is_manager_figure
        except Exception:
            # An unimportable predicate is doubt, and doubt fails closed here for the
            # same reason it does inside is_manager_figure: this gates a write.
            return False
    try:
        return bool( manager_fn( session_id ) )
    except Exception:
        return False


def refusal_for_priority_change( current, requested, bridge_role=None, account_email=None,
                                 actor=None, manager_fn=None ):
    """
    Rules 1 and 2: may this caller move an EXISTING row to `requested`?

    Requires:
        - current is the row's present priority string, or None
        - requested is the priority being asked for, or None
        - bridge_role is the caller's declared session role, or None
        - account_email is the email on a VALIDATED access token, or None

    Ensures:
        - returns None (allowed) when `requested` is None or unknown — this module
          does not police values, only authority
        - returns None when the change is a LOWERING or a no-op, at any priority
        - RULE 1: returns a refusal for any non-operator setting P0, INCLUDING a
          manager, with no override and no emergency path
        - RULE 2: returns a refusal for a non-manager RAISING into P1-P4
        - the refusal string names the rule, the requested priority and what the
          caller was seen as
        - never raises

    🔴 RULE 1 IS CHECKED BEFORE RULE 2 AND THE ORDER IS LOAD-BEARING. A manager passes
    rule 2, so evaluating rule 2 first would let a manager set P0 — the exact thing
    Rick said "full stop" about. The P0 check is therefore unconditional on role and
    consults only the account.

    ⚠️ A LOWERING IS ALWAYS ALLOWED HERE, and that is a deliberate boundary rather
    than an omission. Rick ruled demotion separately ("it is me and me alone... that
    gets to promote and demote", 2026-09-08 ~11:58) and that rule lands on the
    admission path, not here. Two rules about priority in two modules would be two
    rules that disagree; this one owns RAISING.
    """
    wanted = normalize_priority( requested )
    if wanted is None: return None

    # A LOWERING OR A NO-OP NEEDS NO AUTHORITY FROM THIS MODULE, AND IT IS CHECKED
    # FIRST — including for P0.
    #
    # 🔴 THIS ORDER IS A CORRECTION, CAUGHT BY ITS OWN TEST. The first cut ran rule 1
    # before this check, so a caller re-sending P0 at a row that was ALREADY P0 was
    # refused. That is not what Rick ruled on: his sentence is about an UPGRADE — "the
    # only way a ticket will ever get UPGRADED to P0 is through me" — and a no-op
    # upgrades nothing. Refusing it would have made an idempotent retry fail, which is
    # the shape that taught callers to misread a failure as "it did not land" on row
    # 96cf5cec.
    #
    # ⚠️ AND IT DOES NOT WEAKEN RULE 1, because a LOWERING into P0 is impossible — P0
    # is the top of the ladder, so the only non-raise that reaches P0 is P0 -> P0.
    # Every genuine upgrade still falls through to the rule-1 check below.
    present = normalize_priority( current )
    if present is not None and PRIORITY_RANK[ wanted ] >= PRIORITY_RANK[ present ]: return None

    # RULE 1 — P0 is Rick's alone. Unconditional on role, on purpose, and BEFORE rule
    # 2: a manager passes rule 2, so evaluating rule 2 first would hand a manager the
    # one priority he said "full stop" about.
    if wanted == OPERATOR_ONLY_PRIORITY:
        if caller_is_operator( account_email ): return None
        return (
            f"Setting priority {OPERATOR_ONLY_PRIORITY} is reserved to the operator's own "
            f"account. Seen as: {_seen_as( bridge_role, account_email )}. "
            "A manager may petition for it; no manager, override or emergency path sets it "
            "directly (Rick, broadcast e254ec7d)."
        )

    # RULE 2 — raising into P1-P4 needs Rick or a manager.
    if _is_manager( bridge_role, account_email, actor, manager_fn ): return None
    return (
        f"Raising priority to {wanted} requires the operator or a manager. "
        f"Seen as: {_seen_as( bridge_role, account_email )}. "
        "A worker escalates through their manager, who petitions the operator "
        "(Rick, broadcast e254ec7d)."
    )


def refusal_for_priority_create( requested, bridge_role=None, account_email=None,
                                 actor=None, manager_fn=None ):
    """
    Rule 3: may this caller CREATE a row above the worker floor?

    Requires:
        - requested is the priority the create asks for, or None
        - bridge_role is the caller's declared session role, or None
        - account_email is the email on a VALIDATED access token, or None

    Ensures:
        - returns None when `requested` is None or unknown, or is at/below the worker
          floor — a worker filing P5 is the normal case and is never refused
        - RULE 1 still applies on create: only the operator creates at P0
        - returns a refusal when a non-manager asks to create above the floor
        - never raises

    ⚠️ THIS REFUSES RATHER THAN SILENTLY DOWNGRADING, and the choice is worth stating.
    Rick's wording — "they can only file a P5 ticket" — reads either way, and a quiet
    downgrade is the friendlier behaviour. It is also the one that lets a worker
    believe they filed a P1 for a week. A refusal is loud, and loud is what a rule
    about authority should be. If he wants the downgrade instead, that is a one-line
    change here and a NEW question for him, not a design choice to take quietly.
    """
    wanted = normalize_priority( requested )
    if wanted is None: return None

    if wanted == OPERATOR_ONLY_PRIORITY:
        if caller_is_operator( account_email ): return None
        return (
            f"Creating a ticket at {OPERATOR_ONLY_PRIORITY} is reserved to the operator's "
            f"own account. Seen as: {_seen_as( bridge_role, account_email )} "
            "(Rick, broadcast e254ec7d)."
        )

    if PRIORITY_RANK[ wanted ] >= PRIORITY_RANK[ WORKER_CREATE_PRIORITY ]: return None
    if _is_manager( bridge_role, account_email, actor, manager_fn ): return None
    return (
        f"Creating a ticket at {wanted} requires the operator or a manager; a worker files "
        f"{WORKER_CREATE_PRIORITY}. Seen as: {_seen_as( bridge_role, account_email )}. "
        "Escalate through your manager, who petitions the operator "
        "(Rick, broadcast e254ec7d)."
    )


def _is_manager( bridge_role, account_email, actor, manager_fn ):
    """
    Manager-ness from whichever source the caller supplied.

    Requires:
        - bridge_role is an explicitly-passed role string, or None
        - account_email is a validated account email, or None
        - actor is the caller-declared "persona + session id" string, or None
        - manager_fn is an injectable ( session_id ) -> bool, or None

    Ensures:
        - returns True if EITHER source says manager (an explicit role, or the bridge)
        - returns True for the operator via either source
        - returns False when neither source is supplied
        - never raises

    ⚠️ TWO SOURCES, OR'D, AND THE EXPLICIT ONE IS FOR TESTS. A door passes `actor` and
    the bridge answers; a unit test passes `bridge_role` and needs no bridge on disk.
    They are OR'd rather than ranked because there is no case where one should
    OVERRIDE the other — a caller supplies one or the other, never both in anger.

    🔴 THE EXPLICIT PATH IS WHY A TEST CANNOT PROVE THIS IS A FIREWALL. A test that
    passes bridge_role="manager" has SAID the caller is a manager; it has not shown
    that a real caller could not say the same. That limitation is the design's, not
    the test's — see this module's docstring.
    """
    if caller_is_manager( bridge_role, account_email ): return True
    if actor is not None:
        return caller_is_manager_by_bridge( actor, account_email, manager_fn )
    return False


def _seen_as( bridge_role, account_email ):
    """
    How the refusal describes the caller back to them.

    Requires:
        - bridge_role is a role string or None
        - account_email is a validated account email or None

    Ensures:
        - names the validated account when there is one, else says there is none
        - names the declared role when there is one, else says none was declared
        - never raises, and never echoes a caller-declared persona NAME

    ⚠️ IT DELIBERATELY DOES NOT ECHO THE `actor` STRING. A refusal that repeats a
    typed name back teaches the reader that the name was consulted, and here it was
    not — the account was. Saying "no login account (API-key caller)" is the sentence
    that tells somebody how to actually get through the door.
    """
    account = account_email if isinstance( account_email, str ) and account_email.strip() \
              else "no login account (API-key caller)"
    role    = bridge_role if isinstance( bridge_role, str ) and bridge_role.strip() \
              else "no declared role"
    return f"{account} / {role}"


def quick_smoke_test():
    """Exercise the three rules against both a permitted and a refused caller."""
    print( "task_priority_firewall smoke test" )
    print( "=================================" )

    # A caller with no account and no role — the worker case.
    assert refusal_for_priority_create( "P5" ) is None
    assert refusal_for_priority_create( "P1" ) is not None
    assert refusal_for_priority_create( "P0" ) is not None
    print( "  ✓ rule 3: a roleless caller files P5, and is refused above it" )

    # A manager by bridge role.
    assert refusal_for_priority_create( "P1", bridge_role="manager" ) is None
    assert refusal_for_priority_change( "P3", "P1", bridge_role="manager" ) is None
    print( "  ✓ rule 2: a manager raises into P1-P4" )

    # Rule 1 refuses even a manager, which is the whole point of checking it first.
    assert refusal_for_priority_change( "P1", "P0", bridge_role="manager" ) is not None
    assert refusal_for_priority_create( "P0", bridge_role="manager" ) is not None
    print( "  ✓ rule 1: a MANAGER is refused P0 — no override, no emergency path" )

    # A lowering needs nothing from this module.
    assert refusal_for_priority_change( "P1", "P4" ) is None
    assert refusal_for_priority_change( "P2", "P2" ) is None
    print( "  ✓ a lowering and a no-op are allowed at any role" )

    # An unknown value is not this module's to police.
    assert refusal_for_priority_change( "P1", "banana" ) is None
    assert refusal_for_priority_create( None ) is None
    print( "  ✓ unknown/absent values pass through to task_store_rules" )

    print( "\nAll task_priority_firewall smoke tests: ✓ passed" )


if __name__ == "__main__":
    quick_smoke_test()
