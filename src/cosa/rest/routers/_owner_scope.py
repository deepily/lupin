#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Per-user read access to a person's own podcast files in the doc viewer.

`io/podcasts/<email>/` and `io/podcast-proxy/<card id>/` hold one person's files, so `lupin/.docview.yml`
cannot list them: a listed prefix is open to every signed-in user. This module adds the one folder a
request is entitled to, for that request only, to a copy of the scope. Every other guard of the viewer
(blocklists, the landing check, the credential check, the pinned open) then runs unchanged on that copy.
"""

import uuid
from dataclasses import replace
from urllib.parse import unquote

OWNED_SCOPE = "lupin"
EMAIL_ROOTS = ( "io/podcasts/", "io/deep-research/" )   # <root><email>/ : one person's files
PROXY       = "io/podcast-proxy/"


def card_is_owned_by( card_id, user_id ):
    """
    Say whether a podcast proxy card was made for this person.

    Requires:
        - card_id is a string; user_id is a string or None

    Ensures:
        - True only when the card has a row in the spent-cards table and the stored notification's
          recipient is user_id; started_by is not used, because it names the seat that asked
        - False for anything else, including a card id that is not a UUID

    Raises:
        - nothing
    """
    if not user_id: return False
    try:
        card_uuid = uuid.UUID( card_id )
    except ValueError:
        return False
    from cosa.rest.db.database import get_db
    from cosa.rest.db.repositories.notification_repository import NotificationRepository
    from cosa.rest.db.repositories.podcast_proxy_spent_repository import PodcastProxySpentRepository
    with get_db() as session:
        spent = PodcastProxySpentRepository( session ).get( card_uuid )
        card  = NotificationRepository( session ).get_by_id( card_uuid ) if spent is not None else None
        owned = card is not None and str( card.recipient_id ) == str( user_id )
    return owned


def owned_prefix( path, current_user, card_owner=card_is_owned_by ):
    """
    Name the folder this request may read beyond the whitelist, if any.

    Requires:
        - path is the raw `<project>/<rel>` string; current_user is the signed-in user dict ( email, uid )

    Ensures:
        - returns "io/podcasts/<email>/" or "io/deep-research/<email>/" when the path is in the caller's own folder
        - returns "io/podcast-proxy/<card id>/" when the path is in a card folder made for the caller
        - returns None otherwise, so another person's folder stays refused by the whitelist

    Raises:
        - nothing
    """
    decoded = unquote( path ).lstrip( "/" )
    if not decoded.startswith( OWNED_SCOPE + "/" ): return None
    rel = decoded[ len( OWNED_SCOPE ) + 1: ]
    email = current_user.get( "email" )
    if email:
        for root in EMAIL_ROOTS:
            if rel.startswith( root + email + "/" ): return root + email + "/"
    if rel.startswith( PROXY ):
        card_id = rel[ len( PROXY ): ].split( "/", 1 )[ 0 ]
        if card_id and card_owner( card_id, current_user.get( "uid" ) ): return PROXY + card_id + "/"
    return None


def registry_for( registry, path, current_user, card_owner=card_is_owned_by ):
    """
    Return the scope registry with the caller's own folder added, for this request only.

    Requires:
        - registry maps scope name to ScopeConfig; the lupin scope carries a manifest

    Ensures:
        - the input registry is not changed
        - when owned_prefix names a folder, the lupin entry is a copy whose manifest also allows it
        - otherwise the input registry is returned as it is

    Raises:
        - nothing
    """
    prefix = owned_prefix( path, current_user, card_owner )
    scope  = registry.get( OWNED_SCOPE )
    if prefix is None or scope is None or scope.manifest is None: return registry
    manifest = scope.manifest.model_copy( update={ "allowed_prefixes": list( scope.manifest.allowed_prefixes ) + [ prefix ] } )
    return { **registry, OWNED_SCOPE: replace( scope, manifest=manifest ) }
