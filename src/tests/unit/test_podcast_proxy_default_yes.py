"""
A podcast card waits one minute and silence is a yes; a yes may carry a typed comment.

Rick's ruling. His yes arrived as "yes [comment: …]" and the start door refused it as not_yes.
The card then defaulted to no after fifteen minutes. These tests pin the three pure functions
the ask and start doors read: `answer_word`, `default_yes_due` and the two judges built on them.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from cosa.rest import podcast_proxy as pp

NOW      = datetime( 2026, 10, 24, 17, 0, tzinfo=timezone.utc )
SESSION  = "binding-1"
OPERATOR = { "method": "jwt", "user_id": "u-1", "account_email": "rick@example.com" }


def card( state="delivered", default="yes", value=None, responded=False, expires_in=30, made_ago=10 ):
    """A podcast card row as the ask door writes it, with only the fields the judges read."""
    payload = { key: "x" for key in pp.PAYLOAD_KEYS }
    payload.update( kind=pp.CARD_KIND, command=pp.COMMAND, asked_by_session=SESSION )
    return SimpleNamespace(
        payload            = payload,
        response_requested = True,
        response_default   = default,
        response_value     = value,
        responded_at       = NOW if responded else None,
        state              = state,
        expires_at         = NOW + timedelta( seconds=expires_in ),
        created_at         = NOW - timedelta( seconds=made_ago ),
    )


@pytest.fixture( autouse=True )
def operator_login( monkeypatch ):
    monkeypatch.setattr( pp.promotion_gate, "answer_posted_by_the_operator", lambda who: who == OPERATOR )


# ── answer_word ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize( "value,word", [
    ( "yes", "yes" ),
    ( " Yes ", "yes" ),
    ( "yes [comment: go ahead]", "yes" ),
    ( "no [comment: yes, later]", "no" ),
    ( "neither", "neither" ),
    ( None, "" ),
    ( 1, "" ),
] )
def test_the_word_is_what_precedes_the_comment( value, word ):
    assert pp.answer_word( value ) == word


def test_the_ruling_is_one_minute_and_yes():
    assert pp.ASK_TIMEOUT_SECONDS == 60 and pp.RESPONSE_DEFAULT == "yes"
    assert "silence is a yes" in pp.UNANSWERED_MEANS and "REFUSED" not in pp.UNANSWERED_MEANS


# ── default_yes_due ──────────────────────────────────────────────────────────

def test_an_open_card_has_no_default_yet():
    assert pp.default_yes_due( card(), NOW ) is False


def test_a_card_past_its_expiry_takes_its_default_before_any_sweep():
    assert pp.default_yes_due( card( expires_in=-1 ), NOW ) is True


def test_a_card_the_sweep_expired_takes_its_default():
    assert pp.default_yes_due( card( state="expired" ), NOW ) is True


def test_a_card_settled_by_its_default_of_yes_qualifies():
    settled = card( state="expired", value={ "value": "yes", "source": "timeout_default" } )
    assert pp.default_yes_due( settled, NOW ) is True


def test_a_card_whose_stamped_default_is_not_yes_does_not_qualify():
    settled = card( state="expired", value={ "value": "no", "source": "timeout_default" } )
    assert pp.default_yes_due( settled, NOW ) is False


def test_a_persons_answer_beats_the_default():
    answered = card( state="responded", responded=True, expires_in=-1, value={ "value": "no", "source": "ui" } )
    assert pp.default_yes_due( answered, NOW ) is False


def test_an_old_card_asked_with_a_default_of_no_never_qualifies():
    assert pp.default_yes_due( card( default="no", state="expired" ), NOW ) is False


def test_an_expiry_never_set_is_not_passed():
    open_card = card()
    open_card.expires_at = None
    assert pp.default_yes_due( open_card, NOW ) is False


# ── start_refusal and card_state on the new paths ───────────────────────────

def test_an_expired_card_with_a_default_of_yes_starts():
    assert pp.start_refusal( card( state="expired" ), SESSION, NOW, 900 ) is None
    assert pp.card_state( card( state="expired" ), NOW ) == "yes"


def test_a_yes_with_a_comment_from_the_operator_starts():
    answered = card( state="responded", responded=True, value={ "value": "yes [comment: go]", "source": "ui", "answered_by": OPERATOR } )
    assert pp.start_refusal( answered, SESSION, NOW, 900 ) is None
    assert pp.card_state( answered, NOW ) == "yes"


def test_a_default_yes_still_answers_to_the_session_and_age_checks():
    assert pp.start_refusal( card( state="expired" ), "someone-else", NOW, 900 ).code == "wrong_session"
    assert pp.start_refusal( card( state="expired", made_ago=901 ), SESSION, NOW, 900 ).code == "too_old"


def test_an_open_card_is_not_answered():
    assert pp.start_refusal( card(), SESSION, NOW, 900 ).code == "not_answered"
    assert pp.card_state( card(), NOW ) == "waiting"


def test_an_old_cards_default_of_no_is_still_refused():
    settled = card( default="no", state="responded", responded=True, value={ "value": "no", "source": "timeout_default" } )
    assert pp.start_refusal( settled, SESSION, NOW, 900 ).code == "default_answer"
    assert pp.card_state( settled, NOW ) == "default_answer"
