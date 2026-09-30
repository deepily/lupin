"""
The email smoke test must not report a STRUCTURAL DEFECT as a normal development condition.

WHY THIS FILE EXISTS. `test_email_configuration()` wrapped everything in
`except Exception -> return False`, and `quick_smoke_test()` read any False as "SMTP is
not configured", printed *"This is normal in development environment"*, and
RETURNED TRUE.

So when `return_type="bool"` raised `ValueError` — a defect in the code, not in the
environment — the observed behaviour was:

    ✗ Email configuration invalid: Return type [bool] is invalid.
    ⚠ Email configuration test failed (expected if SMTP not configured)
      This is normal in development environment
    quick_smoke_test() -> True

The error text was on screen the whole time and read as expected noise.

🔴 AND THAT SHAPE IS A SEPARATE DEFECT FROM THE TYPE STRING. Fixing `"bool"` ->
`"boolean"` closes one instance and leaves this alive for the next config-shaped
failure. It is this repo's § A CLEAN EXIT IS NOT EVIDENCE THE WORK HAPPENED arriving on
a smoke test: the run completes, says something, and hands the caller a green that
nothing supports.

⚠️ THE TWIN BELOW IS NOT OPTIONAL. "The smoke test fails on a defect" is satisfied
perfectly by a smoke test that fails on EVERYTHING, and an unconfigured SMTP genuinely
is normal here. Only the pair says the two are told apart.
"""

from unittest.mock import patch

import pytest

import cosa.rest.email_service as email_service


def test_a_CONFIG_SHAPED_failure_fails_the_smoke_test_and_is_never_called_normal( capsys ):
    """
    A bad `return_type` reaches the dispatcher as ValueError. That is a defect in this
    code, and the smoke test must say so.

    THE ARM: with the config manager raising ValueError, `quick_smoke_test()` must
    return False and must NOT print the development-is-fine reassurance.
    """
    with patch( "cosa.rest.email_service.config_mgr" ) as mock_cfg:
        mock_cfg.get.side_effect = ValueError( "Return type [bool] is invalid." )

        result = email_service.quick_smoke_test()

    printed = capsys.readouterr().out

    assert result is False, (
        "quick_smoke_test() returned True on a ValueError from the config dispatcher. "
        "A structural defect was reported as a passing smoke test — which is how "
        "return_type='bool' survived in two call sites."
    )
    assert "normal in development" not in printed, (
        "the smoke test described a code defect as a normal development condition. "
        f"Output was:\n{printed}"
    )


def test_a_CONNECTION_failure_is_STILL_normal_and_still_passes( capsys ):
    """
    🔴 THE DISCRIMINATING TWIN, and without it the arm above is satisfied by a smoke
    test that fails on everything.

    An unconfigured or unreachable SMTP host is genuinely expected on a dev box. That
    case must keep its reassurance and must keep passing — the fix separates a defect
    from an environment, it does not turn every absence into a failure.
    """
    with patch( "cosa.rest.email_service.config_mgr" ) as mock_cfg, \
         patch( "cosa.rest.email_service.smtplib" ) as mock_smtplib:

        mock_cfg.get.side_effect          = lambda key, default=None, **kw: default
        mock_smtplib.SMTP.side_effect     = OSError( "Connection refused" )

        result = email_service.quick_smoke_test()

    printed = capsys.readouterr().out

    assert result is True, (
        "an unreachable SMTP host is a normal dev condition and must not fail the "
        "smoke test — the fix must separate a DEFECT from an ENVIRONMENT, not report "
        "both as failures."
    )
    assert "normal in development" in printed, (
        f"the connection case lost its reassurance. Output was:\n{printed}"
    )


def test_the_config_shaped_failure_reaches_the_caller_of_test_email_configuration():
    """
    The seam the fix actually moves: `test_email_configuration()` must let a
    config-shaped error OUT rather than flattening it into False.

    Asserted separately from the smoke test above because a test placed behind another
    assertion is carried, not exercised — and because these are two different claims:
    one about what the checker does, one about what the smoke test makes of it.
    """
    with patch( "cosa.rest.email_service.config_mgr" ) as mock_cfg:
        mock_cfg.get.side_effect = ValueError( "Return type [bool] is invalid." )

        with pytest.raises( ValueError ):
            email_service.test_email_configuration()


def test_a_CONNECTION_failure_still_returns_False_from_test_email_configuration():
    """
    POSITIVE CONTROL for the arm directly above. Without it, a checker that raised on
    EVERYTHING would satisfy the `pytest.raises` perfectly.
    """
    with patch( "cosa.rest.email_service.config_mgr" ) as mock_cfg, \
         patch( "cosa.rest.email_service.smtplib" ) as mock_smtplib:

        mock_cfg.get.side_effect      = lambda key, default=None, **kw: default
        mock_smtplib.SMTP.side_effect = OSError( "Connection refused" )

        assert email_service.test_email_configuration() is False
