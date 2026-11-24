#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
The one writer for a proxy_decisions row, shared by the responder and the SWE team.

Both callers choose between a shadow row and a decision row on the result's action. Only the
fields around that choice differ, so the choice lives here and the differences are arguments.
A test run may write only to a scratch database; the guard below refuses any other write.
"""

from lupin_cli.notifications.human_ask_containment import test_node_id


def refuse_non_scratch_database_under_pytest( session ):
    """
    Refuse a test's proxy_decisions write to any database that is not a scratch one.

    Requires:
        - session is the database session the write will use

    Ensures:
        - returns None outside pytest
        - under pytest, returns None when the session's bind names a scratch database: one that
          prediction_decision_repository.TEST_DATABASE_NAME matches, a "test" word as in lupin_db_test
        - under pytest, returns None when the bind names no string at all (a faked session, or an in-memory database)
        - under pytest, raises when the bind names any other database, dev, production or a stranger, naming the test that tried
        - the check reads the session's own bind, so a test that fakes the session is not refused

    Raises:
        - RuntimeError when pytest is running and the session is bound to a named database that is not a scratch one
    """
    node = test_node_id()
    if node is None: return
    from cosa.rest.db.repositories.prediction_decision_repository import TEST_DATABASE_NAME
    database = session.get_bind().url.database
    if not isinstance( database, str ) or TEST_DATABASE_NAME.search( database ): return
    raise RuntimeError( f"test {node} tried to write a proxy_decisions row to {database}, which is not a scratch database; bind one with a test word in its name or fake the session" )


def write_proxy_decision( result, notification_id, domain, question, sender_id, requires_ratification,
                          shadow_reason_default, shadow_decision_value, extra=None, commit=False ):
    """
    Write one proxy_decisions row: a shadow row for a shadow result, a decision row otherwise.

    Requires:
        - result has action, value, category, confidence, trust_level and reason
        - notification_id, domain, question and sender_id are strings
        - requires_ratification is a bool, used only for a non-shadow row
        - shadow_reason_default is the text stored when a shadow result has no reason
        - shadow_decision_value is the value a shadow row stores; the caller decides it, since
          whether a shadow row records a forecast is the caller's switch to read
        - extra is None or a dict of further repository keyword arguments, such as
          metadata_json, data_origin and rule_agreement

    Ensures:
        - exactly one repository call is made, log_shadow for action "shadow", log_decision otherwise
        - the question is cut to 500 characters
        - a non-shadow row stores result.reason or "", and result.value as its decision value
        - the session is committed only when commit is True
        - extra reaches the repository call unchanged

    Raises:
        - RuntimeError from refuse_non_scratch_database_under_pytest when a test is bound to a named database that is not a scratch one
        - whatever the database session or the repository raises; the callers treat the write as
          non-fatal and catch it
    """
    from cosa.rest.db.database import get_db
    from cosa.rest.db.repositories.proxy_decision_repository import ProxyDecisionRepository

    extra = extra if extra is not None else {}

    with get_db() as session:
        refuse_non_scratch_database_under_pytest( session )
        repo = ProxyDecisionRepository( session )

        if result.action == "shadow":
            repo.log_shadow(
                notification_id = notification_id,
                domain          = domain,
                category        = result.category,
                question        = question[ :500 ],
                sender_id       = sender_id,
                confidence      = result.confidence,
                trust_level     = result.trust_level,
                reason          = result.reason or shadow_reason_default,
                decision_value  = shadow_decision_value,
                **extra
            )
        else:
            repo.log_decision(
                notification_id       = notification_id,
                domain                = domain,
                category              = result.category,
                question              = question[ :500 ],
                action                = result.action,
                decision_value        = result.value,
                sender_id             = sender_id,
                confidence            = result.confidence,
                trust_level           = result.trust_level,
                reason                = result.reason or "",
                requires_ratification = requires_ratification,
                **extra
            )

        if commit: session.commit()
