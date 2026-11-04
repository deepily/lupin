"""
Who the audit trail says did it, when the server knows who actually did.

The caller-declared actor can be false. `task_approval_settings` relies on the authenticated
user id being recorded alongside it, so a false claim is attributable afterwards. That only
holds if something writes the identity down, and this module is that record.

It refuses nobody. The edit door keeps its 404 behaviour exactly as it is, and only the
attribution is corrected. A gate on the edit door would be new policy about who may
reassign somebody else's work. Refusal is a separate proposal, not made here.

The format puts the identity first:

    rick (operator foolish goat)
    somebody@example.com (operator wise penguin)

Two properties earn that order.

  1. The existing allowlist still parses it. `is_approver` walks progressively shorter
     leading word-runs, so "rick (operator foolish goat)" matches "rick" on the first
     take. An identity appended at the end would be invisible to every existing reader.
  2. The declared string survives, following the repo's add-never-overwrite rule. The
     session id in "operator foolish goat" is the only thing that says which tab; the
     email is the only thing that says which person. Discarding either loses a fact
     nothing else carries.

An API-key caller is unchanged. Every seat in the fleet authenticates by API key.
Seats have no login account, so `account_email` is None for them and the declared
actor is returned untouched. Rewriting every seat's audit actor would be a migration, not a bug fix.
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
        - account_email is the email off a validated access token, or None

    Ensures:
        - returns the mapped approver persona when the account has one — the store
          speaks personas, and "rick" is more use to a reader than a UUID or an address
        - otherwise returns the email itself for any non-blank account, so an ordinary
          logged-in user is still named. Attribution is not a privilege: an account
          that cannot approve anything is the one whose edits most need to be traceable
        - returns None for None/blank/non-string — an API-key caller has no account
        - never raises
    """
    if not isinstance( account_email, str ) or not account_email.strip(): return None
    persona = approver_persona_for_account( account_email )
    return persona if persona is not None else account_email.strip()


def recorded_actor( declared_actor, account_email ):
    """
    The actor string to write, given what the caller claimed and who they really are.

    Requires:
        - declared_actor is the caller's `payload.actor` (a non-empty string per the
          request models)
        - account_email is the email off a validated access token, or None

    Ensures:
        - with no account (API-key caller): returns `declared_actor` unchanged. This is
          the existing behaviour, and it is why the whole fleet is untouched
        - with an account: returns "<identity> (<declared>)", identity first so leading
          word-run matchers still resolve it
        - never exceeds ACTOR_COLUMN_LIMIT, and when it must cut, it cuts the declared
          half and says so — the identity is the part that must survive and is never the
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
