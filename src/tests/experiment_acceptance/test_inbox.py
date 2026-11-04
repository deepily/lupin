"""Notifications inbox: list, live arrival, senders, deletes, answers, priority filter."""
import re
import threading

import pytest
from playwright.sync_api import expect

OTHER_SENDER = "exp-other@lupin.deepily.ai"


def _open_inbox( page, server_url ):
    """Open the inbox and wait for the live channel to connect."""
    page.goto( f"{server_url}/app/notifications" )
    expect( page.get_by_text( "Connected", exact=True ) ).to_be_visible( timeout=10000 )
    return page.get_by_role( "region", name="Notifications" )


def _reload_inbox( page, server_url ):
    """Reload the inbox so the list comes from stored notifications, not live arrival."""
    page.reload()
    expect( page.get_by_text( "Connected", exact=True ) ).to_be_visible( timeout=10000 )
    return page.get_by_role( "region", name="Notifications" )


@pytest.mark.feature( "F09" )
def test_inbox_is_empty_for_a_new_user( signed_in, server_url ):
    inbox = _open_inbox( signed_in, server_url )
    expect( inbox.get_by_text( "No notifications yet" ) ).to_be_visible()


@pytest.mark.feature( "F09" )
def test_inbox_lists_notifications_newest_first_with_sender_and_priority( signed_in, server_url, account ):
    _open_inbox( signed_in, server_url )
    assert account.send( "first message", priority="urgent" ).status_code == 200
    assert account.send( "second message", priority="low" ).status_code == 200
    inbox = _reload_inbox( signed_in, server_url )
    rows = inbox.get_by_role( "listitem" )
    expect( rows ).to_have_count( 2 )
    expect( rows.nth( 0 ) ).to_contain_text( "second message" )
    expect( rows.nth( 0 ) ).to_contain_text( "low", ignore_case=True )
    expect( rows.nth( 0 ) ).to_contain_text( "exp-sender@lupin.deepily.ai" )
    expect( rows.nth( 1 ) ).to_contain_text( "first message" )
    expect( rows.nth( 1 ) ).to_contain_text( "urgent", ignore_case=True )


@pytest.mark.feature( "F10" )
def test_a_notification_sent_while_the_page_is_open_appears_without_reload( signed_in, server_url, account ):
    inbox = _open_inbox( signed_in, server_url )
    expect( inbox.get_by_text( "No notifications yet" ) ).to_be_visible()
    assert account.send( "arrived live" ).status_code == 200
    expect( inbox.get_by_text( "arrived live" ) ).to_be_visible( timeout=5000 )


@pytest.mark.feature( "F11" )
def test_senders_list_counts_and_filters( signed_in, server_url, account ):
    _open_inbox( signed_in, server_url )
    account.send( "from one a" )
    account.send( "from one b" )
    account.send( "from other", sender_id=OTHER_SENDER )
    inbox = _reload_inbox( signed_in, server_url )
    senders = signed_in.get_by_role( "list", name="Senders" )
    expect( senders.get_by_text( OTHER_SENDER ) ).to_be_visible()
    expect( senders.get_by_role( "listitem" ).filter( has_text=OTHER_SENDER ) ).to_contain_text( re.compile( r"\b1\b" ) )
    expect( senders.get_by_role( "listitem" ).filter( has_text="exp-sender@lupin.deepily.ai" ) ).to_contain_text( re.compile( r"\b2\b" ) )
    senders.get_by_text( OTHER_SENDER ).click()
    expect( inbox.get_by_text( "from other" ) ).to_be_visible()
    expect( inbox.get_by_text( "from one a" ) ).to_have_count( 0 )
    senders.get_by_text( "All senders" ).click()
    expect( inbox.get_by_text( "from one a" ) ).to_be_visible()


@pytest.mark.feature( "F12" )
def test_delete_removes_one_notification_for_good( signed_in, server_url, account ):
    _open_inbox( signed_in, server_url )
    account.send( "keep me" )
    account.send( "delete me" )
    inbox = _reload_inbox( signed_in, server_url )
    row = inbox.get_by_role( "listitem" ).filter( has_text="delete me" )
    row.get_by_role( "button", name="Delete" ).click()
    expect( inbox.get_by_text( "delete me" ) ).to_have_count( 0 )
    signed_in.reload()
    expect( _open_inbox( signed_in, server_url ).get_by_text( "keep me" ) ).to_be_visible()
    assert [ n[ "message" ] for n in account.inbox() ] == [ "keep me" ]


@pytest.mark.feature( "F12" )
def test_delete_conversation_removes_every_notification_from_that_sender( signed_in, server_url, account ):
    _open_inbox( signed_in, server_url )
    account.send( "other one", sender_id=OTHER_SENDER )
    account.send( "other two", sender_id=OTHER_SENDER )
    account.send( "stays" )
    inbox = _reload_inbox( signed_in, server_url )
    signed_in.get_by_role( "list", name="Senders" ).get_by_text( OTHER_SENDER ).click()
    signed_in.get_by_role( "button", name="Delete conversation" ).click()
    signed_in.get_by_role( "list", name="Senders" ).get_by_text( "All senders" ).click()
    expect( inbox.get_by_text( "stays" ) ).to_be_visible()
    expect( inbox.get_by_text( "other one" ) ).to_have_count( 0 )
    assert [ n[ "message" ] for n in account.inbox() ] == [ "stays" ]


@pytest.mark.feature( "F13" )
def test_a_yes_no_question_can_be_answered_and_stays_answered( signed_in, server_url, account ):
    result = {}
    inbox  = _open_inbox( signed_in, server_url )
    yes    = inbox.get_by_role( "button", name="Yes", exact=True )
    no     = inbox.get_by_role( "button", name="No", exact=True )
    sender = threading.Thread( target=lambda: result.update( response=account.send( "Deploy now?", response_requested="true", response_type="yes_no", timeout_seconds=60 ) ) )
    sender.start()
    expect( inbox.get_by_text( "Deploy now?" ) ).to_be_visible( timeout=10000 )
    assert "Deploy now?" in account.awaiting_response(), "an unanswered card is listed as awaiting a response"
    yes.click()
    expect( inbox.get_by_text( "Answered: yes" ) ).to_be_visible()
    expect( yes ).to_be_disabled()
    expect( no ).to_be_disabled()
    sender.join( timeout=30 )
    assert "yes" in result[ "response" ].text.lower()
    assert "Deploy now?" not in account.awaiting_response(), "an answered card is no longer awaiting"
    signed_in.reload()
    expect( _open_inbox( signed_in, server_url ).get_by_text( "Answered: yes" ) ).to_be_visible()


@pytest.mark.feature( "F14" )
def test_priority_filter_narrows_the_list_to_each_priority( signed_in, server_url, account ):
    _open_inbox( signed_in, server_url )
    for priority in ( "low", "medium", "high", "urgent" ): account.send( f"{priority} one", priority=priority )
    inbox = _reload_inbox( signed_in, server_url )
    picker = signed_in.get_by_role( "combobox", name="Priority" )
    for label, priority in ( ( "Low", "low" ), ( "Medium", "medium" ), ( "High", "high" ), ( "Urgent", "urgent" ) ):
        picker.select_option( label=label )
        expect( inbox.get_by_role( "listitem" ) ).to_have_count( 1 )
        expect( inbox.get_by_text( f"{priority} one" ) ).to_be_visible()
    picker.select_option( label="Any priority" )
    expect( inbox.get_by_role( "listitem" ) ).to_have_count( 4 )
