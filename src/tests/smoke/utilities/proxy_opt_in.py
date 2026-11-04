"""
One skip gate for smoke entries that need a notification proxy answering their gates.

Under pytest `pre_run_hook` never fires, so a proxy exists only when the run passes --auto-proxy
(the conftest fixture `_auto_proxy_for_module` starts it). The :7999 smoke tier passes none, and
these entries spend real LLM tokens or time out, so they belong to the :8000 scheduled tier.
"""
import os

import pytest


def skip_unless_proxy_opt_in( request ):
    """
    Skip the calling pytest entry unless the run opted in to a live proxy.

    Requires:
        - request is the pytest request fixture

    Ensures:
        - skips with the reason when --auto-proxy is absent
        - skips with the reason when LUPIN_INTERACTIVE_TESTS is not "true" (case-insensitive)
        - otherwise returns None and the caller runs its real checks

    Raises:
        - pytest.skip.Exception on either missing opt-in
    """
    if not request.config.getoption( "--auto-proxy", default=False ):
        pytest.skip( "needs a notification proxy: run with --auto-proxy (see the module docstring for the :8000 venue)" )
    if os.environ.get( "LUPIN_INTERACTIVE_TESTS", "" ).lower() != "true":
        pytest.skip( "needs LUPIN_INTERACTIVE_TESTS=true" )
