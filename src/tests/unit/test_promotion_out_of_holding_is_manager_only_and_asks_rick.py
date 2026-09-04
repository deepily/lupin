"""
Rick's ruling 2026-09-04: promotion out of the holding area is manager-only, and
the method asks him from inside itself.

Spec: src/rnd/2026.09.04-gated-promotion-out-of-the-holding-area.md

⚠️ THE ASK LIVING INSIDE THE METHOD IS THE WHOLE DESIGN. Not "the manager should
ask Rick" but "the promotion cannot happen without Rick being asked" — so these
arms exist to prove there is NO path that quietly skips him. An arm that never
fails is not a guard; each control here is deleted in the mutation pass and the
named arm below must go red.
"""
import pytest

from cosa.rest import task_promotion_gate as gate


# ── 1. THE CREDENTIAL CHECK ──────────────────────────────────────────────────

def test_a_worker_is_refused_and_the_reason_names_the_credential():
    refusal = gate.manager_refusal( session_id="worker-sid", actor="Pocholo 5bd424ca",
                                    is_manager_fn=lambda sid, **kw: False )
    assert refusal is not None
    # "a promote that fails without saying why sends someone hunting a bug that
    # does not exist" — the refusal must NAME the credential, not merely 403.
    assert "manager" in refusal.lower()
    assert "Pocholo 5bd424ca" in refusal


def test_a_manager_is_not_refused_on_credentials():
    assert gate.manager_refusal( session_id="mgr-sid", actor="María 4f98d12f",
                                 is_manager_fn=lambda sid, **kw: True ) is None


# ── 2. THE ASK, FROM INSIDE THE METHOD ───────────────────────────────────────

def test_a_manager_causes_rick_to_be_asked():
    fired = []
    def ask( **kwargs ):
        fired.append( kwargs )
        return gate.AskOutcome( answer="yes", default_used=False )

    result = gate.approval_for_promotion(
        session_id="mgr-sid", actor="María 4f98d12f", task_id="8af64f5a",
        title="the row", is_manager_fn=lambda sid, **kw: True, ask_fn=ask )

    assert len( fired ) == 1, "Rick was not asked — the ask must fire from inside the method"
    assert result.allowed is True


def test_the_ask_is_not_fired_for_a_worker_who_was_already_refused():
    """Credentials first, ask second — Rick is not bothered by a caller who cannot promote."""
    fired = []
    def ask( **kwargs ):
        fired.append( kwargs )
        return gate.AskOutcome( answer="yes", default_used=False )

    result = gate.approval_for_promotion(
        session_id="worker-sid", actor="Pocholo 5bd424ca", task_id="8af64f5a",
        title="the row", is_manager_fn=lambda sid, **kw: False, ask_fn=ask )

    assert result.allowed is False
    assert fired == [], "a refused worker must not put a question in front of Rick"


def test_a_real_no_from_rick_blocks_the_promotion():
    result = gate.approval_for_promotion(
        session_id="mgr-sid", actor="María 4f98d12f", task_id="8af64f5a", title="the row",
        is_manager_fn=lambda sid, **kw: True,
        ask_fn=lambda **kw: gate.AskOutcome( answer="no", default_used=False ) )
    assert result.allowed is False
    assert "no" in ( result.refusal or "" ).lower()


def test_the_ask_defaults_to_yes_so_an_absent_rick_is_not_a_blocker():
    kw = gate.promotion_ask_kwargs( actor="María 4f98d12f", task_id="8af64f5a", title="the row" )
    assert kw[ "response_default" ] == "yes"


# ── 3. KEYPRESS vs TIMED-OUT DEFAULT ─────────────────────────────────────────

def test_a_keypress_and_a_default_do_not_look_identical_on_the_row():
    press = gate.approval_for_promotion(
        session_id="m", actor="María", task_id="t", title="x",
        is_manager_fn=lambda sid, **kw: True,
        ask_fn=lambda **kw: gate.AskOutcome( answer="yes", default_used=False ) )
    timed = gate.approval_for_promotion(
        session_id="m", actor="María", task_id="t", title="x",
        is_manager_fn=lambda sid, **kw: True,
        ask_fn=lambda **kw: gate.AskOutcome( answer="yes", default_used=True ) )

    assert press.allowed is timed.allowed is True
    assert press.approval_source == gate.APPROVAL_KEYPRESS
    assert timed.approval_source == gate.APPROVAL_DEFAULT
    # the whole requirement: they must be TELLABLE APART afterwards
    assert press.approval_source != timed.approval_source
    assert press.authority_suffix() != timed.authority_suffix()


def test_the_authority_suffix_says_which_way_the_answer_came():
    timed = gate.approval_for_promotion(
        session_id="m", actor="María", task_id="t", title="x",
        is_manager_fn=lambda sid, **kw: True,
        ask_fn=lambda **kw: gate.AskOutcome( answer="yes", default_used=True ) )
    # a reader of the row must be able to see it WITHOUT knowing this module's constants
    assert "default" in timed.authority_suffix().lower()


# ── 4. THE ASK IS HUMAN-ONLY ─────────────────────────────────────────────────

def test_the_auto_answer_proxy_cannot_approve_a_promotion_on_ricks_behalf():
    """
    `human_only` is load-bearing, not decoration — the same reason self_respin
    carries it (row 804afce6). Without it a proxy answers for Rick and the gate
    he asked for becomes a gate answered by a robot.
    """
    kw = gate.promotion_ask_kwargs( actor="María", task_id="t", title="x" )
    assert kw[ "human_only" ] is True


# ── 5. STRICTNESS: FAIL CLOSED, BUT SAY WHICH FAILURE IT IS ──────────────────
#
# María's ruling 2026-09-03: an unreadable bridge fails CLOSED. "Falling back to
# the allowlist there means the gate opens widest exactly when it knows least."
# She required both guards below to be BUILT, not noted.

def test_an_unreadable_bridge_is_refused_not_waved_through():
    """The strictness itself. Fail-open here would open the gate at the moment it
       knows least about who is asking."""
    refusal = gate.manager_refusal(
        session_id="stale-sid", actor="María 4f98d12f",
        is_manager_fn=lambda sid, **kw: False,
        classify_fn=lambda sid, **kw: gate.DENIAL_STALE_BRIDGE )
    assert refusal is not None


def test_an_unreadable_bridge_does_not_read_as_a_permissions_denial():
    """
    Guard 1 — the refusal NAMES THE CAUSE. A locked-out manager who cannot tell a
    permissions problem from a broken bridge goes hunting the wrong thing; this
    whole evening was spent proving what a mislabelled failure costs.
    """
    stale = gate.manager_refusal(
        session_id="stale-sid", actor="María 4f98d12f",
        is_manager_fn=lambda sid, **kw: False,
        classify_fn=lambda sid, **kw: gate.DENIAL_STALE_BRIDGE )
    denied = gate.manager_refusal(
        session_id="worker-sid", actor="Pocholo 5bd424ca",
        is_manager_fn=lambda sid, **kw: False,
        classify_fn=lambda sid, **kw: gate.DENIAL_DENIED )

    assert stale != denied, "an unreadable bridge and a real denial must not read alike"
    assert "could not be read" in stale
    assert "could not be read" not in denied


def test_the_refusal_tells_a_locked_out_manager_how_to_recover():
    """
    Guard 2 — the RECOVERY is at the check, not only in a doc. Tonight four of
    seven live seats served stale modules; if bridges go unreadable in bulk every
    manager loses promotion at once, and the message is where they will look.
    """
    stale = gate.manager_refusal(
        session_id="stale-sid", actor="María 4f98d12f",
        is_manager_fn=lambda sid, **kw: False,
        classify_fn=lambda sid, **kw: gate.DENIAL_STALE_BRIDGE )
    assert "re-spin" in stale.lower() or "restart" in stale.lower()


def test_a_missing_session_id_is_its_own_cause_too():
    nosid = gate.manager_refusal(
        session_id=None, actor="somebody 9999",
        is_manager_fn=lambda sid, **kw: False )
    assert "no session id" in nosid.lower()


# ── 6. THE TIMEOUT IS A DIAL, NOT A CONSTANT ─────────────────────────────────
#
# María's ruling 2026-09-03: an INI key, read at call time, so an operator's edit
# lands on the next promotion rather than the next deploy.

def test_the_ask_timeout_is_read_from_config_not_frozen_at_import( monkeypatch ):
    """
    A constant would freeze at import and a change would need a restart — the exact
    asymmetry Rick objected to in the ratio gate.
    """
    seen = {}
    def fake_ini( key, return_type, fallback ):
        seen[ "key" ] = key
        return 7
    monkeypatch.setattr( gate, "_ini_value", fake_ini )
    kw = gate.promotion_ask_kwargs( actor="María", task_id="t", title="x" )
    assert kw[ "timeout_seconds" ] == 7, "the ask is not reading the configured value"
    assert seen[ "key" ] == gate.INI_KEY_ASK_TIMEOUT


def test_an_unreadable_config_falls_back_rather_than_raising( monkeypatch ):
    monkeypatch.setattr( gate, "_ini_value",
                         lambda k, rt, fb: fb )   # the reader's own never-raise contract
    kw = gate.promotion_ask_kwargs( actor="María", task_id="t", title="x" )
    assert kw[ "timeout_seconds" ] == gate.FALLBACK_ASK_TIMEOUT_SECONDS


def test_the_timeout_dial_cannot_skip_the_ask():
    """
    The dial says how long, never whether. A reader who thinks 0 disables the gate
    would be turning a dial that does something other than what they intend.
    """
    fired = []
    result = gate.approval_for_promotion(
        session_id="m", actor="María", task_id="t", title="x",
        is_manager_fn=lambda sid, **kw: True,
        ask_fn=lambda **kw: ( fired.append( kw ), gate.AskOutcome( answer="yes", default_used=True ) )[ 1 ] )
    assert len( fired ) == 1
    assert result.allowed is True


# ──────────────────────────────────────────────────────────────────────────────
# THE TWO ARMS FOR MAYA'S REVIEW FINDINGS (2026-09-03, at 47cff912).
#
# Both are BEHAVIOUR CHANGES, so neither is covered by anything above and both
# need their own arm. She found the third — the import defect — and her own guard
# covers that one; it deliberately does not inject `ask_fn`, which is the whole
# reason it could see what 25 injected tests could not.
# ──────────────────────────────────────────────────────────────────────────────

def test_an_ask_that_BLOWS_UP_is_a_refusal_not_a_500():
    """
    The docstring used to promise "never raises" and the function raised.

    That is how the import defect reached a caller as a 500 rather than as a
    refusal: any exception from `ask_fn` propagated through the door untouched. A
    promotion that fails with a stack trace tells the manager nothing about what
    to do, and tells nobody at all that Rick was never asked.

    🔨 IT REFUSES RATHER THAN ALLOWS, and that is the arguable half. An ABSENT
    Rick must not be a blocker — that is the timed-out default, and it still
    allows. A BROKEN ask is a different claim: not "he did not answer" but "we do
    not know whether he was asked". The gate must not open widest when it knows
    least.
    """
    def _explodes( **kw ):
        raise ModuleNotFoundError( "No module named 'lupin_cli.notifications.models'" )

    result = gate.approval_for_promotion(
        session_id="m", actor="María", task_id="t-99", title="x",
        is_manager_fn=lambda sid, **kw: True, ask_fn=_explodes )

    assert result.allowed is False
    assert "ModuleNotFoundError" in result.refusal, result.refusal
    assert "t-99" in result.refusal
    # The three causes must not read alike — a broken ask is neither a permissions
    # problem nor a no from Rick, and a manager chasing the wrong one loses an hour.
    assert "NOT a permissions problem" in result.refusal
    assert "NOT a no from Rick"        in result.refusal


def test_an_UNRECOGNISED_answer_is_never_recorded_as_ricks_keypress():
    """
    Maya flagged this as HARDENING rather than a defect, and it is filed that way:
    she did not establish that a YES_NO response can carry anything but yes or no,
    and neither did I. Nobody has shown this can happen.

    What made it worth closing anyway is not the allowing, it is the ATTRIBUTION.
    The old code allowed every answer that did not start with "no" AND stamped it
    `rick-approved (keypress)` — so a malformed or empty response would have gone
    onto the row as Rick's own keypress. The one thing this gate must never do is
    put his name on a decision he did not make.

    ⚠️ THE TIMED-OUT DEFAULT IS EXPLICITLY NOT AFFECTED, and the last case is what
    proves it: a default still allows, and is still stamped as a default rather
    than as a keypress. Closing this must not turn an absent Rick into a blocker.
    """
    def _answers( text, default_used=False ):
        return gate.approval_for_promotion(
            session_id="m", actor="María", task_id="t-42", title="x",
            is_manager_fn=lambda sid, **kw: True,
            ask_fn=lambda **kw: gate.AskOutcome( answer=text, default_used=default_used ) )

    for junk in [ "", "   ", "maybe", "y", "sure", "affirmative" ]:
        r = _answers( junk )
        assert r.allowed is False, f"{junk!r} was allowed"
        assert "not recognised" in r.refusal, r.refusal
        assert r.authority_suffix() == "", f"{junk!r} still produced an authority stamp"

    yes = _answers( "yes" )
    assert yes.allowed is True
    assert yes.approval_source == gate.APPROVAL_KEYPRESS

    # The negative control, and the reason it is here: a rule that refused an
    # unrecognised answer WITHOUT this exemption would silently make an absent
    # Rick a blocker, which is the one thing his standing ruling forbids.
    timed_out = _answers( "yes", default_used=True )
    assert timed_out.allowed is True
    assert timed_out.approval_source == gate.APPROVAL_DEFAULT
    assert "default" in timed_out.authority_suffix()
