"""
The card features the split step compares, and the lookup that hands them to status.

A feature is a few plain facts about an ask: its response type, its notification type and the project of its sender.
A title or a message is never one, because it would tell any two episodes apart.
"""

from cosa.agents.prediction_engine.ask_family import PROJECT_PATTERN, UNKNOWN_PROJECT
from cosa.rest.postgres_models import Notification

NO_PROJECT = "none"


def card_features( row ):
    """
    List the card features of one ask.

    Requires:
        - row has sender_id, response_type and type, as a Notification or a query row of those columns does

    Ensures:
        - returns { response_type, type, project }; project is the sender's lower-case project name, or "none"
    """
    match   = PROJECT_PATTERN.search( row.sender_id or "" )
    project = match.group( 1 ).lower() if match and match.group( 1 ) != UNKNOWN_PROJECT else NO_PROJECT
    return { "response_type": row.response_type, "type": row.type, "project": project }


def feature_lookup( session, notification_ids ):
    """
    Build the function that gives the card features of an evidence row's ask.

    Requires:
        - session is an active SQLAlchemy session; notification_ids are notification ids

    Ensures:
        - returns features_of( notification_id ): the card features, or None when the ask is not found
        - one query for all ids; reads only
    """
    ids   = list( set( notification_ids ) )
    found = { row.id: card_features( row ) for row in session.query( Notification.id, Notification.sender_id, Notification.response_type, Notification.type )
              .filter( Notification.id.in_( ids ) ).all() } if ids else {}
    return lambda notification_id: found.get( notification_id )
