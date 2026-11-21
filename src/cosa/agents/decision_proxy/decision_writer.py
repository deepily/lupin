#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
The one writer for a proxy_decisions row, shared by the responder and the SWE team.

Both callers choose between a shadow row and a decision row on the result's action. Only the
fields around that choice differ, so the choice lives here and the differences are arguments.
"""


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
        - whatever the database session or the repository raises; the callers treat the write as
          non-fatal and catch it
    """
    from cosa.rest.db.database import get_db
    from cosa.rest.db.repositories.proxy_decision_repository import ProxyDecisionRepository

    extra = extra if extra is not None else {}

    with get_db() as session:
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
