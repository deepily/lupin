"""
THE SWORD OF DAMOCLES: which deletion ticket an admit request may pledge (row ab8c5728).

Rick, 2026-09-14 ~22:32 EDT: a manager asking him to admit one row must name one ticket of
their own to delete — "tit for tat" — and the rule is switchable at runtime
(`sword_of_damocles_active`). Plan: src/rnd/2026.09.14-sword-of-damocles-enforcement-plan.md.

⚠️ WHY THIS IS NOT IN `task_request_lifecycle`. That module is structurally forbidden from
accepting a ticket or a row (`test_nothing_in_this_module_can_touch_a_ticket`), so a denial
routed through it can never dispose of work. A pledge IS a row, so its rules live here and
that guard stays whole.

Pure: no database, no bridge, no I/O. The router hands it facts read under the lock.
"""
from cosa.rest.task_approval_settings import MOVE_ADMIT
from cosa.rest.task_request_lifecycle import REQUEST_PENDING
from cosa.rest.task_store_rules       import TERMINAL_STATUSES
from lupin_mcp.persona_normalization  import canonical_persona_key


def refusal_for_pledge( move, switch_on, target_id, pledge_id, pledge_row, requester_persona, pledged_on ):
    """
    Why an admit request may not carry this deletion ticket — the Sword of Damocles rule.

    Rick, 2026-09-14 ~22:32 EDT (row ab8c5728): "if you're asking to add 1 the method for
    requesting 1 of me then requires that you pass in A ticket ID that belongs to you".
    Rulings on the plan's open questions (Mr. Radio, 22:39): demote is exempt; no
    peer-manager agreement. Plan: src/rnd/2026.09.14-sword-of-damocles-enforcement-plan.md §3.2.

    Requires:
        - move is the requested move; switch_on is `get_sword_of_damocles_active()`
        - target_id / pledge_id are the row ids as strings, pledge_id None when not sent
        - pledge_row is the pledged row READ UNDER THE LOCK (anything with `owner_persona`
          and `status`), or None when no such row exists
        - requester_persona is what the SESSION BRIDGE resolved for the caller — never the
          typed actor name — or None/blank when it resolved nothing
        - pledged_on is the id of another row whose PENDING admit already names this
          pledge, or None

    Ensures:
        - returns None when the request may be filed, else ( status_code, detail )
        - a pledge on a demote is refused, not ignored — a field ignored in silence reads
          as a switch that does not work
        - with the switch OFF a pledge is optional, but a pledge that IS sent passes every
          check it would with the switch on
        - an unresolved requester is refused 403; there is no fallback to the typed name
          (María, 2026-09-14 22:41 — that name is row b8205986's hole)
        - never raises
    """
    if move != MOVE_ADMIT:
        if pledge_id is None: return None
        return ( 422, f"a '{move}' request names no deletion ticket. Only an admit asks Rick to "
                      f"add a row, so only an admit pays for one — drop `deletion_task_id`." )

    if pledge_id is None:
        if not switch_on: return None
        return ( 422, "an admit request must name `deletion_task_id`: one live ticket of your own, "
                      "dropped when Rick approves (row ab8c5728). Rick switches this rule with "
                      "`sword_of_damocles_active` in the approval settings." )

    if pledge_id == target_id:
        return ( 422, "a row cannot pledge itself to pay for its own admission — name a different ticket of yours to delete." )

    if pledge_row is None:
        return ( 422, f"deletion ticket {pledge_id} does not exist. Name a live ticket you own." )

    if requester_persona is None or not requester_persona.strip():
        return ( 403, "your persona could not be read from your session bridge, so nobody can tell "
                      "whether the deletion ticket is yours. The request is refused rather than "
                      "trusting the typed actor name." )

    owner = canonical_persona_key( pledge_row.owner_persona or "" )
    if owner != canonical_persona_key( requester_persona ):
        return ( 403, f"deletion ticket {pledge_id} belongs to '{pledge_row.owner_persona}', not to you. "
                      f"The ticket you pledge must be your own." )

    if pledge_row.status in TERMINAL_STATUSES:
        return ( 409, f"deletion ticket {pledge_id} is already '{pledge_row.status}'. A finished row is a "
                      f"close, not a deletion — pledge a live ticket." )

    if pledged_on is not None:
        return ( 409, f"deletion ticket {pledge_id} is already pledged on the pending admit request for "
                      f"row {pledged_on}. One pledge pays for one admit." )

    return None


def pledge_is_dead( pledge_status ):
    """
    Whether a pledged row can no longer be dropped to pay for an admit.

    Requires:
        - pledge_status is the pledged row's status, or None when the row does not exist

    Ensures:
        - True when the row is gone or already terminal (done, dropped, wont_fix)
        - False for every live status, the holding area included
        - never raises
    """
    return pledge_status is None or pledge_status in TERMINAL_STATUSES


def pledge_changed_hands( pledge_owner, pledged_by ):
    """
    Whether the pledged row is no longer owned by the manager who pledged it.

    RB-2 (María's review of 06b5a057, 2026-09-15): a pledge admitted at filing and then
    REASSIGNED was still dropped at the verdict, so approving one manager's admit deleted a
    ticket another persona now owned. The ownership check ran once, at filing, and nothing
    re-asked it when the row was dropped. The filing door now records who pledged
    (`request_pledged_by`), and this compares that to the row's owner at the moment it
    would be consumed.

    Requires:
        - pledge_owner is the pledged row's `owner_persona` as read now, or None
        - pledged_by is the request's `request_pledged_by`, or None

    Ensures:
        - True when pledged_by is None or blank — a pledge with no recorded pledger cannot
          show it is still the pledger's, so it FAILS CLOSED rather than being assumed theirs
        - True when the canonical persona keys differ; False when they match
        - never raises
    """
    if pledged_by is None or not pledged_by.strip(): return True
    return canonical_persona_key( pledge_owner or "" ) != canonical_persona_key( pledged_by )


def request_is_stranded_by_its_pledge( request_state, request_move, pledge_id, pledge_status, pledge_owner, pledged_by ):
    """
    Whether a pending admit request may be re-filed because its pledge can no longer pay for it.

    Mr. Radio's Q2 ruling (2026-09-14 22:40): an approval over a dead pledge is refused 409
    and the request stays pending, so the manager must be able to re-file it with a live
    pledge. Without this, the one-request-per-row rule would leave that request stuck on
    Rick's board with no way to answer it and no way to replace it. RB-2 adds the second way
    a pledge stops paying — it changed hands — and it strands the request the same way.

    Requires:
        - request_state / request_move are the row's request columns
        - pledge_id is the row's request_deletion_id (None when it has none)
        - pledge_status / pledge_owner are that pledged row's status and owner, both None
          when it does not exist
        - pledged_by is the row's request_pledged_by

    Ensures:
        - True only for a PENDING ADMIT that carries a pledge which `pledge_is_dead` or
          `pledge_changed_hands`
        - False for a grandfathered admit with no pledge, a demote, or any answered request
        - never raises
    """
    if request_state != REQUEST_PENDING or request_move != MOVE_ADMIT or pledge_id is None: return False
    return pledge_is_dead( pledge_status ) or pledge_changed_hands( pledge_owner, pledged_by )


def refusal_for_consuming_pledge( move, pledge_id, pledge_status, pledge_owner, pledged_by ):
    """
    Why Rick's approval cannot drop the row this request pledged.

    Q2 ruling: approve admits the target AND drops the pledge in one transaction, or neither
    happens. A pledge that died after filing cannot be dropped, so the approval is refused
    rather than admitting a row nobody paid for. RB-2: neither can a pledge that changed
    hands after filing, or the approval would delete a ticket its new owner never offered.

    Requires:
        - move is the request's move; pledge_id its request_deletion_id (None when none)
        - pledge_status / pledge_owner are the pledged row's status and owner READ UNDER THE
          LOCK, both None when absent
        - pledged_by is the request's request_pledged_by

    Ensures:
        - None for a demote, or an admit with no pledge (filed before the switch — María,
          2026-09-14 22:41, grandfathered), or a live pledge still owned by its pledger
        - ( 409, detail ) when the pledge is dead or changed hands; the detail says the
          request stays pending and the manager re-files with a live ticket of their own
        - a dead pledge is reported as dead even if it also changed hands
        - never raises
    """
    if move != MOVE_ADMIT or pledge_id is None: return None

    if pledge_is_dead( pledge_status ):
        state = "no longer exists" if pledge_status is None else f"is already '{pledge_status}'"
        return ( 409, f"this admit request pledged ticket {pledge_id} for deletion, and that ticket {state}, "
                      f"so approving it would admit a row nobody paid for. Nothing was changed: the request "
                      f"stays pending, and the manager may re-file it with a live ticket of their own." )

    if pledge_changed_hands( pledge_owner, pledged_by ):
        return ( 409, f"this admit request pledged ticket {pledge_id} for deletion on behalf of '{pledged_by}', "
                      f"and that ticket now belongs to '{pledge_owner}', so approving it would delete a ticket "
                      f"its owner never offered. Nothing was changed: the request stays pending, and the "
                      f"manager may re-file it with a live ticket of their own." )

    return None
