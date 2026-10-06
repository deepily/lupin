"""
The priority firewall: who may set which priority, and on what evidence.

Only the operator or a manager may raise a ticket from P5 up through P1. Only the
operator may ever establish a ticket as P0. Workers may file tickets only at P5; a
worker who wants more escalates through a manager, who petitions the operator.

There are three rules and three separate checks. Never collapse them into one
predicate: they key on different evidence.

  1. Setting priority P0: the operator only. No manager, no emergency path.
  2. Raising priority to P1-P4: the operator or a manager.
  3. Creating above P5: the operator or a manager. A worker's create is P5,
     whatever it asks for.

A fourth rule, "pull from holding must take the highest priority", is superseded and
absent here. Manager pulling from holding was rescinded and defaults to off, so a
highest-priority-first refusal would target a shape that has moved.
`task_approval_settings.refusal_for_pull` owns that surface.

Two sources of evidence, ruled separately. Role comes from the persona session bridge,
not the User.roles column. Identity comes from a validated account; a typed `actor`
string is not sufficient authorization. The bridge says what role a caller claims; the
account says whether the caller is who they say.

Rule 1 is strong and rules 2-3 are advisory, and that asymmetry is intended. Rule 1
keys on `approver_persona_for_account( account_email )`, which resolves a
signature-validated token to a persona, so a caller cannot forge it. Rules 2-3 key on
the bridge role, which the child session's own SessionStart writes. A session declares
its own role, so this module cannot refuse one that claims to be a manager. It stops
mistakes and misroutes, not forgery.

Never test rules 2-3 as though they were a firewall. A test asserting that a worker's
P1 is refused must drive the door with a bridge that says worker. Only rule 1 can carry
a forgery claim, because its evidence is a validated account.

A stronger source for rules 2-3 was surveyed and not built. User.roles is a JSONB
column, has_role() and is_admin() exist, roles ride in the JWT, and both auth paths
resolve to a real user row. It needs two new role values, "manager" and "worker".
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

    An unknown value returns None rather than raising, and the callers below treat None
    as "no priority stated". Rejecting an unknown value is the job of `task_store_rules`
    (VALID_PRIORITIES); doing it in two places means two rules that agree until they
    do not.
    """
    if not isinstance( value, str ): return None
    candidate = value.strip().upper()
    return candidate if candidate in PRIORITY_RANK else None


def caller_is_operator( account_email ):
    """
    Whether the caller is Rick, proven by a validated account.

    Requires:
        - account_email is the email on a validated access token, or None

    Ensures:
        - returns True only when the account maps to an unconditional approver
        - returns False for None/blank/unmapped, and for an API-key-only caller
        - never consults a caller-declared string
        - never raises

    This is the one predicate in the module that a caller cannot forge, and rule 1
    rests on it alone. `approver_persona_for_account` resolves a signature-validated
    token. There is no `actor` parameter here, so no typed-name path can be left open
    by accident.

    It reuses `UNCONDITIONAL_APPROVERS` instead of naming Rick again. That list already
    identifies the standing authority the allowlist delegates from, and a second
    spelling of who the operator is would be a second thing to keep in step.
    """
    persona = approver_persona_for_account( account_email )
    if persona is None: return False
    return canonical_persona_key( persona ) in [
        canonical_persona_key( p ) for p in UNCONDITIONAL_APPROVERS
    ]


def caller_is_manager( bridge_role, account_email=None ):
    """
    Whether the caller holds a manager seat, per the bridge role.

    Requires:
        - bridge_role is the role string the caller's session bridge declares, or None
        - account_email is the email on a validated access token, or None

    Ensures:
        - returns True when the bridge role is "manager" (case/space-insensitive)
        - returns True for the operator, who outranks every manager check
        - returns False for None/blank/any other role
        - never raises

    The bridge is self-declared, so this function cannot refuse a liar. That is stated
    here, not only in the module docstring, because this is the line somebody reads in
    isolation while writing a test. The bridge was chosen as the source knowing this.

    `account_email` is accepted and used only for the operator short-circuit. It is not
    a second gate on manager-ness: adding one would quietly change who counts as a
    manager, a rule nobody has been asked about.
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
        - returns the last whitespace-separated token when it looks like a session id
          (hex-ish, 8 or more characters), else None
        - returns None for None/blank/non-string and for a bare persona name
        - never raises

    The session id is caller-declared like the rest of `actor`, so this buys a lookup,
    not a proof. It feeds the bridge read, and the bridge is itself self-written, so the
    chain is advisory end to end. Rule 1 touches none of this, which is why rule 1 is
    the one that can carry a forgery claim.

    It takes the last token, not a fixed position. A persona may be one word or three
    ("mr radio", "maria"), so counting from the front goes wrong for a longer name.
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
        - account_email is the email on a validated access token, or None
        - manager_fn is an injectable ( session_id ) -> bool, or None for the live one

    Ensures:
        - returns True for the operator, who outranks every manager check
        - returns True when the bridge says this session is a manager figure
        - returns False when no session id can be read out of `actor`
        - returns False rather than raising if the bridge cannot be read
        - never raises

    It delegates to `is_manager_figure` instead of re-deriving manager-ness. That
    predicate is the ratified one for this question: it gates store writes, it works
    server-side (it reads the implicit flag stamped at registration, because the
    persona-chain env is empty server-side), and it fails closed on any doubt. A second
    manager rule here would be two pieces of code deciding one rule, and they agree
    until they do not.

    This is not the counting predicate. `fleet_size_cap` does not use `is_manager_figure`,
    because a cap asks how many seats exist and the name rule mis-classifies there: one
    seat with role="author" and a lineage counted as a manager while another with the
    identical role counted as a worker. For authorization the name rule is ratified and
    the fail-closed degrade is wanted. Same words, two questions.
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
    Rules 1 and 2: whether the caller may move an existing row to `requested`.

    Requires:
        - current is the row's present priority string, or None
        - requested is the priority being asked for, or None
        - bridge_role is the caller's declared session role, or None
        - account_email is the email on a validated access token, or None

    Ensures:
        - returns None (allowed) when `requested` is None or unknown — this module
          does not police values, only authority
        - returns None when the change is a lowering or a no-op, at any priority
        - rule 1: returns a refusal for any non-operator setting P0, including a
          manager, with no override and no emergency path
        - rule 2: returns a refusal for a non-manager raising into P1-P4
        - the refusal string names the rule, the requested priority and what the
          caller was seen as
        - never raises

    Rule 1 is checked before rule 2 and the order matters. A manager passes rule 2, so
    evaluating rule 2 first would let a manager set P0, which only the operator may do.
    The P0 check therefore ignores role and consults only the account.

    A lowering is always allowed here. Demotion is ruled separately and lands
    on the admission path, not here. Two rules about priority in two modules would
    disagree, so this one owns raising.
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
    Rule 3: whether the caller may create a row above the worker floor.

    Requires:
        - requested is the priority the create asks for, or None
        - bridge_role is the caller's declared session role, or None
        - account_email is the email on a validated access token, or None

    Ensures:
        - returns None when `requested` is None or unknown, or is at/below the worker
          floor — a worker filing P5 is the normal case and is never refused
        - rule 1 still applies on create: only the operator creates at P0
        - returns a refusal when a non-manager asks to create above the floor
        - never raises

    A worker above the floor is refused rather than silently downgraded. The wording
    "they can only file a P5 ticket" reads either way, and a quiet downgrade is
    friendlier, but it lets a worker believe a P1 was filed for a week. A refusal is
    loud, which suits a rule about authority. Switching to a downgrade is a one-line
    change here and a new question for the operator, not a quiet design choice.
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


# ---------------------------------------------------------------------------
# THE PETITION — Rick's ruling 2026-09-09, row 9c26bf04
# ---------------------------------------------------------------------------
#
# 🔴 THE REFUSALS ABOVE STILL REFUSE. THIS GRANTS NOTHING. That is the entire safety
# argument and it is why this is a SEPARATE predicate rather than a third return state
# on `refusal_for_priority_create`. The firewall's answer to "may this caller set P0"
# is unchanged and is still NO. This answers a different question — "may this refusal
# be carried to Rick instead of returned to the caller" — and the door acts on both.
#
# ⚠️ `authority` IS CALLER-DECLARED AND THEREFORE PROVES NOTHING. It is not evidence
# and must never be read as any. Its only job is to ROUTE: to distinguish a caller
# claiming to relay an instruction from one exercising its own judgement, so the first
# gets asked and the second gets refused. THE CLAIM IS NEVER TRUSTED; IT IS ESCALATED.
#
# 🔴 IF A LATER CHANGE MAKES `authority` GRANT ANYTHING ON ITS OWN, ROW b8205986 IS
# REOPENED — that is the hole Rick closed on 2026-09-07 precisely because a
# caller-supplied actor string could name anyone. Nothing below returns a permission.
#
# WHY IT EXISTS AT ALL: the refusal this repo already emits promises a path that was
# never built — "A manager may petition for it; no manager, override or emergency path
# sets it directly." Every seat hitting that wall was told to do something it had no
# mechanism for. María 🌸 filed it (9c26bf04) after re-running her own create with
# authority="user_direct" and getting an identical 403, then reading at source that the
# refusal function does not take `authority` at all.
PETITIONABLE_AUTHORITY = "user_direct"

# WHAT A PETITION MINTS AT WHILE IT WAITS (María's ruling, 2026-09-09, superseding
# §4.1 of the design doc, which had the door answering 202 and minting nothing).
#
# The create SUCCEEDS at this priority and the petition is raised against the REAL
# row id. That ordering is the whole point: a decline is then a no-op — the row simply
# stays here — rather than a cleanup of something half-created. There is no window in
# which a petitioned row does not exist.
#
# 🔴 P1 IS NOT A CONSOLATION PRIZE, IT IS THE CEILING THE CALLER ALREADY HAD. A manager
# may set P1 directly today, so minting here grants NOTHING that was not already theirs.
# If this value were ever raised to P0 the petition would become the grant it is
# explicitly not, and row b8205986 would reopen.
PETITION_HOLDING_PRIORITY = "P1"


def petition_is_available( requested, authority, bridge_role=None, account_email=None,
                           actor=None, manager_fn=None ):
    """
    Whether a refused P0 may be carried to Rick as a petition instead of returned.

    Requires:
        - requested is the priority the call asks for, or None
        - authority is the caller-declared authority string, or None
        - bridge_role / account_email / actor / manager_fn are as `_is_manager` takes
          them

    Ensures:
        - returns False unless the requested priority is exactly OPERATOR_ONLY_PRIORITY —
          a petition exists to reach P0 and nothing else. P1-P4 already have a door
          (a manager sets them directly), so petitioning for one would be a second way
          to do something already permitted
        - returns False unless `authority` is exactly PETITIONABLE_AUTHORITY — a caller
          exercising its own judgement gets the flat refusal, unchanged. Only a caller
          claiming to relay the operator is escalated
        - returns False for a non-manager. A worker escalates through their manager,
          who petitions the operator, so the worker's escalation path is their manager
          and not this
        - returns False for the operator's own account — they are never refused in the
          first place, so there is nothing to petition
        - returns a bool, never a permission and never a token. The caller still has no
          authority it did not have; it has a route to somebody who does
        - never raises
    """
    wanted = normalize_priority( requested )
    if wanted != OPERATOR_ONLY_PRIORITY:                 return False
    if authority != PETITIONABLE_AUTHORITY:              return False
    # The operator is allowed outright by rule 1 and never reaches a refusal, so a
    # petition from that account would be a second path to a thing already permitted.
    if caller_is_operator( account_email ):              return False
    return _is_manager( bridge_role, account_email, actor, manager_fn )


def _is_manager( bridge_role, account_email, actor, manager_fn ):
    """
    Manager-ness from whichever source the caller supplied.

    Requires:
        - bridge_role is an explicitly-passed role string, or None
        - account_email is a validated account email, or None
        - actor is the caller-declared "persona + session id" string, or None
        - manager_fn is an injectable ( session_id ) -> bool, or None

    Ensures:
        - returns True if either source says manager (an explicit role, or the bridge)
        - returns True for the operator via either source
        - returns False when neither source is supplied
        - never raises

    There are two sources, combined by "or". A door passes `actor` and the bridge
    answers; a unit test passes `bridge_role` and needs no bridge on disk. They are
    combined rather than ranked because a caller supplies one or the other, so neither
    needs to override the other.

    The explicit path is why a test cannot prove this is a firewall. A test that passes
    bridge_role="manager" has said the caller is a manager; it has not shown that a real
    caller could not say the same. See the module docstring.
    """
    if caller_is_manager( bridge_role, account_email ): return True
    if actor is not None:
        return caller_is_manager_by_bridge( actor, account_email, manager_fn )
    return False


def _seen_as( bridge_role, account_email ):
    """
    Describes the caller back to them in a refusal message.

    Requires:
        - bridge_role is a role string or None
        - account_email is a validated account email or None

    Ensures:
        - names the validated account when there is one, else says there is none
        - names the declared role when there is one, else says none was declared
        - never raises, and never echoes a caller-declared persona name

    The `actor` string is never echoed. A refusal that repeats a typed name back suggests
    the name was consulted, and it was not; the account was. Saying "no login account (API-key caller)" tells the reader how to
    get through the door.
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
