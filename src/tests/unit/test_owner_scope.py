"""
Unit tests for the per-user read rule of the doc viewer.

io/podcasts/<email>/, io/deep-research/<email>/ and io/podcast-proxy/<card id>/ hold one person's files.
The viewer serves a folder to its owner only, by adding that one folder to the lupin scope for that request.
The scope is built under pytest's tmp_path; the card-owner lookup is a stub except in the TestCardOwner class.

Tier: :7999-eligible unit ( no server, no persistent state ).
"""

import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

import cosa.rest.routers._owner_scope as owner_scope
import cosa.rest.routers.docs_files as docs_files
from cosa.config.docview_manifest import DocviewManifest
from cosa.rest.routers._scope_registry import ScopeConfig

ME     = { "email": "me@x.com", "uid": "user-me" }
OTHER  = { "email": "you@x.com", "uid": "user-you" }
CARD   = str( uuid.uuid4() )


def _owner_of_card( card_id, user_id ):
    return card_id == CARD and user_id == "user-me"


@pytest.fixture
def lupin_root( tmp_path ):
    root = tmp_path / "lupin"
    for rel, text in (
        ( "src/notes.md",                              "# note\n" ),
        ( "io/podcasts/me@x.com/s-script.md",           "# my script\n" ),
        ( "io/podcasts/you@x.com/s-script.md",          "# your script\n" ),
        ( "io/deep-research/me@x.com/report.md",        "# my report\n" ),
        ( f"io/podcast-proxy/{CARD}/doc.md",            "# proxy doc\n" ),
        ( "io/podcast-proxy/other-card/doc.md",         "# not mine\n" ),
        ( "io/podcasts/me@x.com/key-credentials.md",    "# named like a secret\n" ),
    ):
        path = root / rel
        path.parent.mkdir( parents=True, exist_ok=True )
        path.write_text( text )
    ( root / "io" / "podcasts" / "me@x.com" / "to-yours.md" ).symlink_to( root / "io" / "podcasts" / "you@x.com" / "s-script.md" )
    return root


@pytest.fixture
def registry( lupin_root, monkeypatch ):
    manifest = DocviewManifest( allowed_prefixes=[ "src/" ] )
    reg      = { "lupin": ScopeConfig( name="lupin", root=str( lupin_root ), allowed_prefixes=(), manifest=manifest ) }
    monkeypatch.setattr( docs_files, "_get_scope_registry", lambda: reg )
    monkeypatch.setattr( docs_files, "owner_registry", lambda r, p, u: owner_scope.registry_for( r, p, u, _owner_of_card ) )
    return reg


def _get( path, user=ME ):
    return asyncio.run( docs_files.get_docs_file( path=path, scope=None, current_user=user ) )


def _refusal( path, user=ME ):
    with pytest.raises( HTTPException ) as raised:
        _get( path, user )
    return raised.value


class TestOwnedPrefix:

    def test_own_podcasts_folder( self ):
        assert owner_scope.owned_prefix( "lupin/io/podcasts/me@x.com/a.md", ME, _owner_of_card ) == "io/podcasts/me@x.com/"

    def test_own_deep_research_folder( self ):
        assert owner_scope.owned_prefix( "lupin/io/deep-research/me@x.com/a.md", ME, _owner_of_card ) == "io/deep-research/me@x.com/"

    def test_url_encoded_email_is_decoded( self ):
        assert owner_scope.owned_prefix( "lupin/io/podcasts/me%40x.com/a.md", ME, _owner_of_card ) == "io/podcasts/me@x.com/"

    def test_someone_elses_folder_gets_none( self ):
        assert owner_scope.owned_prefix( "lupin/io/podcasts/you@x.com/a.md", ME, _owner_of_card ) is None

    def test_an_email_that_only_starts_with_mine_gets_none( self ):
        assert owner_scope.owned_prefix( "lupin/io/podcasts/me@x.com.evil/a.md", ME, _owner_of_card ) is None

    def test_user_without_an_email_gets_none( self ):
        assert owner_scope.owned_prefix( "lupin/io/podcasts/None/a.md", { "uid": "user-me" }, _owner_of_card ) is None

    def test_other_project_gets_none( self ):
        assert owner_scope.owned_prefix( "claude-plans/io/podcasts/me@x.com/a.md", ME, _owner_of_card ) is None

    def test_my_proxy_card( self ):
        assert owner_scope.owned_prefix( f"lupin/io/podcast-proxy/{CARD}/doc.md", ME, _owner_of_card ) == f"io/podcast-proxy/{CARD}/"

    def test_someone_elses_proxy_card_gets_none( self ):
        assert owner_scope.owned_prefix( f"lupin/io/podcast-proxy/{CARD}/doc.md", OTHER, _owner_of_card ) is None

    def test_the_bare_proxy_folder_gets_none( self ):
        assert owner_scope.owned_prefix( "lupin/io/podcast-proxy/", ME, _owner_of_card ) is None


class TestRegistryFor:

    def test_adds_the_prefix_to_a_copy_only( self, registry ):
        out = owner_scope.registry_for( registry, "lupin/io/podcasts/me@x.com/a.md", ME, _owner_of_card )
        assert "io/podcasts/me@x.com/" in out[ "lupin" ].manifest.allowed_prefixes
        assert registry[ "lupin" ].manifest.allowed_prefixes == [ "src/" ], "the shared registry is not changed"

    def test_no_prefix_returns_the_same_registry( self, registry ):
        assert owner_scope.registry_for( registry, "lupin/src/notes.md", ME, _owner_of_card ) is registry

    def test_no_lupin_scope_returns_the_same_registry( self ):
        reg = { "other": SimpleNamespace( manifest=None ) }
        assert owner_scope.registry_for( reg, "lupin/io/podcasts/me@x.com/a.md", ME, _owner_of_card ) is reg

    def test_lupin_scope_without_a_manifest_returns_the_same_registry( self ):
        reg = { "lupin": SimpleNamespace( manifest=None ) }
        assert owner_scope.registry_for( reg, "lupin/io/podcasts/me@x.com/a.md", ME, _owner_of_card ) is reg


class TestTheViewerServesTheOwnerOnly:

    def test_owner_reads_own_script( self, registry ):
        assert _get( "lupin/io/podcasts/me@x.com/s-script.md" ).body.decode() == "# my script\n"

    def test_owner_reads_own_report( self, registry ):
        assert _get( "lupin/io/deep-research/me@x.com/report.md" ).body.decode() == "# my report\n"

    def test_owner_reads_own_proxy_card( self, registry ):
        assert _get( f"lupin/io/podcast-proxy/{CARD}/doc.md" ).body.decode() == "# proxy doc\n"

    def test_another_user_is_refused_my_script( self, registry ):
        assert _refusal( "lupin/io/podcasts/me@x.com/s-script.md", OTHER ).status_code == 400

    def test_owner_is_refused_another_users_script( self, registry ):
        assert "whitelist" in _refusal( "lupin/io/podcasts/you@x.com/s-script.md" ).detail

    def test_owner_is_refused_a_card_made_for_someone_else( self, registry ):
        assert "whitelist" in _refusal( "lupin/io/podcast-proxy/other-card/doc.md" ).detail

    def test_dot_dot_into_another_users_folder_is_refused( self, registry ):
        assert _refusal( "lupin/io/podcasts/me@x.com/../you@x.com/s-script.md" ).status_code == 400

    def test_a_symlink_into_another_users_folder_is_refused_where_it_lands( self, registry ):
        assert _refusal( "lupin/io/podcasts/me@x.com/to-yours.md" ).status_code == 400

    def test_the_secrets_blocklist_still_applies_inside_my_folder( self, registry ):
        assert "secrets" in _refusal( "lupin/io/podcasts/me@x.com/key-credentials.md" ).detail

    def test_the_rest_of_io_stays_closed( self, registry ):
        assert "whitelist" in _refusal( "lupin/io/write-ups-not/x.md" ).detail

    def test_my_folder_lists_for_me( self, registry ):
        import json
        names = [ e[ "name" ] for e in json.loads( _get( "lupin/io/podcasts/me@x.com/" ).body )[ "entries" ] ]
        assert "s-script.md" in names

    def test_upload_does_not_use_the_owner_rule( self ):
        import inspect
        assert "owner_registry" not in inspect.getsource( docs_files.upload_docs_file )
        assert "owner_registry" in inspect.getsource( docs_files.get_docs_file )


class TestCardOwner:

    def _db( self, spent, card ):
        session = MagicMock()
        ctx     = MagicMock()
        ctx.__enter__.return_value = session
        spent_repo = MagicMock()
        spent_repo.get.return_value = spent
        note_repo = MagicMock()
        note_repo.get_by_id.return_value = card
        return ctx, spent_repo, note_repo

    def _run( self, spent, card, user_id="user-me", card_id=None ):
        ctx, spent_repo, note_repo = self._db( spent, card )
        with patch( "cosa.rest.db.database.get_db", return_value=ctx ), \
             patch( "cosa.rest.db.repositories.podcast_proxy_spent_repository.PodcastProxySpentRepository", return_value=spent_repo ), \
             patch( "cosa.rest.db.repositories.notification_repository.NotificationRepository", return_value=note_repo ):
            return owner_scope.card_is_owned_by( card_id or CARD, user_id )

    def test_spent_card_made_for_the_user_is_owned( self ):
        assert self._run( object(), SimpleNamespace( recipient_id="user-me" ) ) is True

    def test_spent_card_made_for_someone_else_is_not( self ):
        assert self._run( object(), SimpleNamespace( recipient_id="user-you" ) ) is False

    def test_card_with_no_spent_row_is_not_owned( self ):
        assert self._run( None, SimpleNamespace( recipient_id="user-me" ) ) is False

    def test_spent_row_without_a_stored_card_is_not_owned( self ):
        assert self._run( object(), None ) is False

    def test_card_id_that_is_not_a_uuid_is_not_owned( self ):
        assert owner_scope.card_is_owned_by( "not-a-uuid", "user-me" ) is False

    def test_no_user_is_not_owned( self ):
        assert owner_scope.card_is_owned_by( CARD, None ) is False
