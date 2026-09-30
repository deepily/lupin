"""
Who the audit trail SAYS did it, when the server knows who actually did.

🔴 THE CLAIM THIS MODULE EXISTS TO MAKE TRUE. `task_approval_settings`'s docstring
says, of the caller-declared actor: "The authenticated user id IS recorded alongside,
so a false claim is attributable after the fact — accountability rather than
prevention." **That was false when written.** Measured 2026-09-04 at `3862c0b9`:
`authenticated_user_id` is bound in `routers/tasks.py` TWELVE times and appears in no
function body — bound everywhere, read nowhere. (Verified with a positive control: the
same search shape finds three real uses in `routers/commons.py`, so the empty result is
a true zero rather than a broken search.)

⇒ Nothing was recorded alongside anything. The store's entire accountability story
rested on a sentence, and a sentence is not a control. This module is the record.

WHAT IT DOES NOT DO, AND THE LINE IS RICK'S TO MOVE, NOT MINE. It REFUSES NOBODY.
María's ruling, 2026-09-04: "Correct the attribution so the edit door records the real
identity the P0 mechanism establishes. Leave the 404 behavior exactly as it is." A gate
on the edit door would be new policy — who may reassign somebody else's work — and this
row is filed as a bug. Attribution is the bug; refusal is a proposal, and it is written
up as one rather than smuggled in here.

THE FORMAT, AND WHY THE IDENTITY GOES FIRST.

    rick (operator foolish goat)
    somebody@example.com (operator wise penguin)

Two properties earn that order, and neither is cosmetic:

  1. THE EXISTING ALLOWLIST STILL PARSES IT. `is_approver` walks progressively shorter
     LEADING word-runs, so "rick (operator foolish goat)" matches "rick" on the first
     take. An identity appended at the END would be invisible to every reader that
     already exists.
  2. THE DECLARED STRING SURVIVES, which is the repo's add-never-overwrite rule. The
     session id in "operator foolish goat" is the only thing that says WHICH tab; the
     email is the only thing that says WHICH PERSON. Discarding either loses a fact
     nothing else carries.

⚠️ AN API-KEY CALLER IS UNCHANGED, DELIBERATELY. Every seat in the fleet authenticates
by API key and has no login account, so `account_email` is None for them and the
declared actor is returned untouched. A change that rewrote every seat's audit actor
would be a migration wearing a bug fix's clothes.
"""

from cosa.rest.task_approval_settings import approver_persona_for_account

# `task_events.actor` is String(255) in postgres, and the request models already cap a
# declared actor at exactly 255 — so ANY prefix can overflow. Named here rather than
# spelled inline twice, because the two must not be able to drift apart.
ACTOR_COLUMN_LIMIT = 255

# What replaces the declared actor when it cannot fit beside the identity. It says a
# thing was DROPPED, which a silent truncation does not — a reader seeing a clipped
# string has no way to tell it from an actor somebody typed that way.
ELIDED_MARKER = "(declared actor elided — too long)"


def identity_for_account( account_email ):
    """
    The name an authenticated account should be recorded under, or None.

    Requires:
        - account_email is the email off a VALIDATED access token, or None

    Ensures:
        - returns the mapped approver PERSONA when the account has one — the store
          speaks personas, and "rick" is more use to a reader than a UUID or an address
        - otherwise returns the EMAIL itself for any non-blank account, so an ordinary
          logged-in user is still named. Attribution is not a privilege: an account
          that cannot approve anything is exactly the one whose edits you most want
          traceable
        - returns None for None/blank/non-string — an API-key caller has no account
        - never raises
    """
    if not isinstance( account_email, str ) or not account_email.strip(): return None
    persona = approver_persona_for_account( account_email )
    return persona if persona is not None else account_email.strip()


def recorded_actor( declared_actor, account_email ):
    """
    The actor string to WRITE, given what the caller claimed and who they really are.

    Requires:
        - declared_actor is the caller's `payload.actor` (a non-empty string per the
          request models)
        - account_email is the email off a VALIDATED access token, or None

    Ensures:
        - with NO account (API-key caller): returns `declared_actor` UNCHANGED. This is
          today's behaviour written down, and it is why the whole fleet is untouched
        - with an account: returns "<identity> (<declared>)", identity FIRST so leading
          word-run matchers still resolve it
        - NEVER exceeds ACTOR_COLUMN_LIMIT, and when it must cut, it cuts the DECLARED
          half and SAYS SO — the identity is the load-bearing part and is never the
          thing dropped
        - returns `declared_actor` unchanged if the identity alone cannot fit, because
          a truncated identity is worse than an honest un-upgraded one: it would name
          a person who does not exist
        - never raises
    """
    identity = identity_for_account( account_email )
    if identity is None: return declared_actor

    combined = f"{identity} ({declared_actor})"
    if len( combined ) <= ACTOR_COLUMN_LIMIT: return combined

    # The declared half does not fit. Drop it VISIBLY rather than clipping it — a
    # clipped string is indistinguishable from one somebody typed that way.
    elided = f"{identity} {ELIDED_MARKER}"
    if len( elided ) <= ACTOR_COLUMN_LIMIT: return elided

    # Even the identity plus a marker does not fit, so there is nothing honest left to
    # write. Fail BACKWARD to the caller's own string rather than inventing a truncated
    # name — this repo's rule is that a step which cannot finish declines rather than
    # half-finishing and returning something the caller reads as success.
    return declared_actor
