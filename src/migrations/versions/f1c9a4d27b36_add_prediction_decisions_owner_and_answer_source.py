"""
Add prediction_decisions.owner_user_id and answer_source, and backfill them

Revision ID: f1c9a4d27b36
Revises: a7c3e91b5d20

A stored case carried no owner and no record of who or what produced its answer. So another
account's answer, a proxy's guess or a timed-out default could be retrieved as Rick's precedent.

This migration adds two nullable text columns and fills them for the rows that exist:

- `owner_user_id`: the account that answered, from `notifications.response_value.answered_by.user_id`
- `answer_source`: `human`, `proxy`, `timeout_default`, `test`, `hint_vote` or `unknown`

The backfill joins a case to its notification by `prediction_decisions.id = notifications.id::text`.
A hint-vote case has the id `hintvote-<notification id>`, so the join never matches it. It is
told apart by that id prefix and its answer is the forecast, not the user's answer. Derivation, in order:

1. id starts with `hintvote-`: `hint_vote`
2. no matching notification: `unknown`
3. `response_value.source` is `timeout_default`: `timeout_default`
4. `ratification_state` is one the decision proxy writes (`pending`, `autonomous`, `shadow`): `proxy`
5. `ratification_state` is one the engine's own path or a thumbs vote writes
   (`not_required`, `approved`, `rejected`) and `answered_by.user_id` is set: `human`
6. anything else, including a state it cannot place: `unknown`

A row it cannot classify is kept. It can still be retrieved as a neighbour, but it casts no
personal vote. The migration prints the count per `ratification_state` and per derived value.
`answered_by.method` is not used: it records the auth method, not who answered.

The migration is idempotent. A column is added only when missing, and only rows whose
`answer_source` is still NULL are filled, so a second run changes nothing. A fresh database built
from the current models already has the columns, so there is nothing to add and no row to fill.
"""
import json
from collections import Counter
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = 'f1c9a4d27b36'
down_revision: Union[str, Sequence[str], None] = 'a7c3e91b5d20'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE_NAME          = "prediction_decisions"
NOTIFICATIONS_TABLE = "notifications"
COLUMN_NAMES        = ( "owner_user_id", "answer_source" )
HINT_VOTE_PREFIX    = "hintvote-"
PROXY_STATES        = frozenset( { "pending", "autonomous", "shadow" } )
HUMAN_STATES        = frozenset( { "not_required", "approved", "rejected" } )
LOOKUP_CHUNK        = 500


def _column_names( inspector ) -> set:
    return { column[ "name" ] for column in inspector.get_columns( TABLE_NAME ) }


def derive_answer_source( case_id, ratification_state, response_value ):
    """
    The ( owner_user_id, answer_source ) of one stored case.

    Requires:
        - case_id is the case's primary key
        - ratification_state is the case's stored state, or None
        - response_value is the matching notification's answer as a dict, or None when none matches

    Ensures:
        - follows the derivation order in the module docstring
        - returns an owner only when the notification names one
    """
    if case_id.startswith( HINT_VOTE_PREFIX ): return ( None, "hint_vote" )
    if response_value is None:                 return ( None, "unknown" )

    owner = ( response_value.get( "answered_by" ) or { } ).get( "user_id" )
    if response_value.get( "source" ) == "timeout_default": return ( owner, "timeout_default" )
    if ratification_state in PROXY_STATES:                  return ( owner, "proxy" )
    if ratification_state in HUMAN_STATES and owner:        return ( owner, "human" )
    return ( owner, "unknown" )


def _as_dict( value ):
    """A notification's response_value as a dict, from a dict or a JSON string."""
    if isinstance( value, str ): value = json.loads( value )
    return value if isinstance( value, dict ) else None


def _answers_by_case_id( bind, case_ids ) -> dict:
    """The matching notification's answer for each case id, by the inventory's own join key."""
    if NOTIFICATIONS_TABLE not in inspect( bind ).get_table_names(): return { }
    answers = { }
    statement = sa.text( f"SELECT CAST( id AS TEXT ) AS key, response_value FROM {NOTIFICATIONS_TABLE} "
                         f"WHERE CAST( id AS TEXT ) IN :ids" ).bindparams( sa.bindparam( "ids", expanding=True ) )
    for start in range( 0, len( case_ids ), LOOKUP_CHUNK ):
        for key, response_value in bind.execute( statement, { "ids": case_ids[ start:start + LOOKUP_CHUNK ] } ):
            answers[ key ] = _as_dict( response_value )
    return answers


def backfill( bind ) -> dict:
    """
    Fill owner_user_id and answer_source for every row whose answer_source is still NULL.

    Requires:
        - both columns exist on prediction_decisions

    Ensures:
        - fills only rows with a NULL answer_source, so a repeat run changes nothing
        - returns { "states": Counter by ratification_state, "derived": Counter by answer_source }
    """
    rows = bind.execute( sa.text( f"SELECT id, ratification_state FROM {TABLE_NAME} WHERE answer_source IS NULL" ) ).all()
    answers = _answers_by_case_id( bind, [ row[ 0 ] for row in rows ] )
    states, derived = Counter(), Counter()
    for case_id, state in rows:
        owner, source = derive_answer_source( case_id, state, answers.get( case_id ) )
        states[ state ] += 1
        derived[ source ] += 1
        bind.execute( sa.text( f"UPDATE {TABLE_NAME} SET owner_user_id = :owner, answer_source = :source WHERE id = :id" ),
                      { "owner": owner, "source": source, "id": case_id } )
    return { "states": states, "derived": derived }


def upgrade() -> None:
    """
    Add owner_user_id and answer_source, then fill them from each case's notification.

    Ensures:
        - no-op when prediction_decisions is absent
        - each column is added only when missing (re-run safe)
        - prints the count per ratification_state and per derived answer_source
        - a row it cannot classify is kept and marked unknown
    """
    bind      = op.get_bind()
    inspector = inspect( bind )
    if TABLE_NAME not in inspector.get_table_names():
        return

    present = _column_names( inspector )
    if "owner_user_id" not in present:
        op.add_column( TABLE_NAME, sa.Column( "owner_user_id", sa.Text(), nullable=True ) )
    if "answer_source" not in present:
        op.add_column( TABLE_NAME, sa.Column( "answer_source", sa.Text(), nullable=True ) )

    counts = backfill( bind )
    print( f"[{revision}] prediction_decisions rows filled by ratification_state: {dict( counts[ 'states' ] )}" )
    print( f"[{revision}] prediction_decisions rows filled by answer_source: {dict( counts[ 'derived' ] )}" )


def downgrade() -> None:
    """
    Drop the two columns.

    Ensures:
        - no-op when prediction_decisions is absent
        - each drop is guarded, so a partial upgrade downgrades cleanly
    """
    inspector = inspect( op.get_bind() )
    if TABLE_NAME not in inspector.get_table_names():
        return

    present = _column_names( inspector )
    for name in COLUMN_NAMES:
        if name in present:
            op.drop_column( TABLE_NAME, name )
