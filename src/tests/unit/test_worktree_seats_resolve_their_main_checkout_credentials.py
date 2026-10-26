"""
A seat standing in a git WORKTREE must resolve its repo's credentials.

🔴 THE INCIDENT (2026-09-04). `session_bridge.resolve_project_name()` walks the
bridge `cwd` to the nearest `.git` and tests `( parent / ".git" ).exists()`. A
linked worktree's `.git` is a FILE, so the test passes on the WORKTREE itself and
the project resolves to the worktree's own directory name —
`lupin-wt-cc-author-maria-1`. `~/.lupin/config` carries one section per REPO, so
that name never matches, `get_hook_credentials()` raised, and the CC notification
listener called `sys.exit( 1 )` roughly 0.1s into startup — before its first log
line and before its log file was opened. Every worktree seat ran DEAF. The shared
centralized log carried 33 such deaths.

WHERE THE FIX SITS, AND WHY IT IS NOT SHARED. The collapse lives in
`hook_credentials`, not in a common helper. `memento_io` performs the same
collapse and there it is the BUG — writer to the main slot, reader on the
worktree slot. Credentials want the MAIN checkout; mementos want the SEAT. One
shared helper would fix this caller and cement that one. (María's ruling.)

ARMS — the second and third are what make the first mean anything:
    1. worktree cwd, section only for the main checkout -> resolves
    2. ORDINARY checkout                                -> unchanged
    3. no section anywhere                              -> still raises
                                                           (fails CLOSED, so the
                                                           fix is not "always
                                                           succeed")
    4. the mechanism, pinned directly: a worktree's `.git` is a FILE whose
       `.exists()` is True — the reason the resolver named the worktree at all
    5. the credential failure is written to STDERR, not stdout — the part-2
       change, without which the death stays unattributable in a shared log
"""

import sys
import types

import pytest

from lupin_cli.claude_code.hooks.lib import hook_credentials


def _config( tmp_path, *sections ):
    """Write a config carrying exactly the named sections."""
    path = tmp_path / "config"
    body = ""
    for name in sections:
        body += f"[{name}]\nemail = claude.code@{name}.example\npassword = pw-{name}\n\n"
    path.write_text( body )
    return path


def _worktree( tmp_path ):
    """A linked worktree: `.git` is a FILE pointing into the main checkout."""
    main = tmp_path / "mainrepo"
    ( main / ".git" / "worktrees" / "wt1" ).mkdir( parents=True )
    wt = tmp_path / "mainrepo-wt-seat-1"
    wt.mkdir()
    ( wt / ".git" ).write_text( f"gitdir: {main}/.git/worktrees/wt1\n" )
    return main, wt


def test_a_worktree_seat_gets_its_main_checkouts_credentials( tmp_path, monkeypatch ):
    main, wt = _worktree( tmp_path )
    monkeypatch.setattr( hook_credentials, "CREDENTIALS_FILE", _config( tmp_path, "mainrepo" ) )
    monkeypatch.setattr( hook_credentials, "resolve_project_name", lambda: wt.name.lower() )
    monkeypatch.chdir( wt )

    email, password = hook_credentials.get_hook_credentials()

    assert email == "claude.code@mainrepo.example"
    assert password == "pw-mainrepo"


def test_an_ordinary_checkout_is_unchanged( tmp_path, monkeypatch ):
    """
    Positive control. The collapse must not alter the path that already worked —
    without this arm, a change that simply returned the first section in the file
    would satisfy the test above.
    """
    repo = tmp_path / "mainrepo"
    ( repo / ".git" ).mkdir( parents=True )
    monkeypatch.setattr( hook_credentials, "CREDENTIALS_FILE", _config( tmp_path, "mainrepo", "other" ) )
    monkeypatch.setattr( hook_credentials, "resolve_project_name", lambda: "mainrepo" )
    monkeypatch.chdir( repo )

    email, _password = hook_credentials.get_hook_credentials()

    assert email == "claude.code@mainrepo.example"


def test_an_unknown_project_still_fails_closed( tmp_path, monkeypatch ):
    """
    The fix must not become 'find some credentials'. A worktree whose MAIN
    checkout has no section is still an error — the same error as before.
    """
    main, wt = _worktree( tmp_path )
    monkeypatch.setattr( hook_credentials, "CREDENTIALS_FILE", _config( tmp_path, "somebody-else" ) )
    monkeypatch.setattr( hook_credentials, "resolve_project_name", lambda: wt.name.lower() )
    monkeypatch.chdir( wt )

    with pytest.raises( ValueError ) as exc:
        hook_credentials.get_hook_credentials()

    assert wt.name.lower() in str( exc.value ), "the error must still name what was actually looked up"


def test_the_mechanism_a_worktree_dot_git_is_a_file_that_exists( tmp_path ):
    """
    Pinned directly, because it is the whole reason the resolver named the
    worktree: the ancestor walk asks `.exists()`, and a worktree's `.git`
    answers True while being a FILE.
    """
    main, wt = _worktree( tmp_path )

    assert ( wt / ".git" ).exists()
    assert ( wt / ".git" ).is_file()
    assert hook_credentials._main_checkout_name( wt ) == "mainrepo"
    assert hook_credentials._main_checkout_name( main ) == "mainrepo"


def test_credential_failure_is_written_to_stderr_not_stdout( capsys, monkeypatch, tmp_path ):
    """
    Part 2. The spawning hook sends listener STDOUT to the SHARED centralized log
    and STDERR to a per-session file named by session hash. This message carries no
    logger prefix and no timestamp — on stdout it was unattributable, and 33 of them
    accumulated in that log unnoticed, one of them directly beneath the previous
    session's clean shutdown banner.
    """
    from lupin_cli.claude_code.hooks.lib import cc_notification_listener as listener

    monkeypatch.setattr( hook_credentials, "CREDENTIALS_FILE", tmp_path / "does-not-exist" )
    args = types.SimpleNamespace( email=None, password=None )

    with pytest.raises( SystemExit ) as exc:
        listener._resolve_credentials( args )

    captured = capsys.readouterr()
    assert exc.value.code == 1
    assert "Credential resolution failed" in captured.err
    assert "Credential resolution failed" not in captured.out, \
        "on stdout this lands unattributed in the shared centralized log"


# ── the walk's refusal arms and the search-root generator ─────────

class TestMainCheckoutNameRefusals:

    def test_an_unresolvable_start_yields_none( self, monkeypatch ):
        from pathlib import Path
        monkeypatch.setattr( Path, "resolve", lambda self, *a, **k: ( _ for _ in () ).throw( OSError( "loop" ) ) )
        assert hook_credentials._main_checkout_name( "/anywhere" ) is None

    def test_a_tree_with_no_dot_git_anywhere_yields_none( self, tmp_path ):
        # tmp_path sits under /tmp, which has no .git ancestor.
        assert hook_credentials._main_checkout_name( tmp_path / "plain" ) is None

    def test_an_ordinary_checkout_names_its_own_directory( self, tmp_path ):
        repo = tmp_path / "MyRepo"
        ( repo / ".git" ).mkdir( parents=True )
        assert hook_credentials._main_checkout_name( repo ) == "myrepo"

    def test_an_unreadable_dot_git_file_yields_none( self, tmp_path, monkeypatch ):
        from pathlib import Path
        wt = tmp_path / "wt"; wt.mkdir()
        ( wt / ".git" ).write_text( "gitdir: /x/.git/worktrees/wt" )
        monkeypatch.setattr( Path, "read_text", lambda self, *a, **k: ( _ for _ in () ).throw( OSError( "denied" ) ) )
        assert hook_credentials._main_checkout_name( wt ) is None

    def test_a_dot_git_file_not_in_gitdir_form_yields_none( self, tmp_path ):
        wt = tmp_path / "wt"; wt.mkdir()
        ( wt / ".git" ).write_text( "something else entirely" )
        assert hook_credentials._main_checkout_name( wt ) is None

    def test_a_gitdir_without_the_worktrees_marker_yields_none( self, tmp_path ):
        # a submodule's gitdir points at <super>/.git/modules/<name>, not .git/worktrees/
        wt = tmp_path / "sub"; wt.mkdir()
        ( wt / ".git" ).write_text( "gitdir: /super/.git/modules/sub" )
        assert hook_credentials._main_checkout_name( wt ) is None


class TestCredentialSearchRoots:

    def test_the_bridge_cwd_comes_first_then_the_live_cwd( self, tmp_path, monkeypatch ):
        import json
        from pathlib import Path
        bridge = tmp_path / "cc-x.json"
        bridge.write_text( json.dumps( { "cwd": "/bridge/cwd" } ) )
        monkeypatch.setattr( "lupin_cli.claude_code.hooks.lib.session_bridge._find_session_file",
                             lambda: ( bridge, "pid" ) )
        roots = list( hook_credentials._credential_search_roots() )
        assert roots == [ "/bridge/cwd", Path.cwd() ]

    def test_a_bridge_without_a_cwd_yields_only_the_live_cwd( self, tmp_path, monkeypatch ):
        import json
        from pathlib import Path
        bridge = tmp_path / "cc-x.json"
        bridge.write_text( json.dumps( { "cwd": "" } ) )
        monkeypatch.setattr( "lupin_cli.claude_code.hooks.lib.session_bridge._find_session_file",
                             lambda: ( bridge, "pid" ) )
        assert list( hook_credentials._credential_search_roots() ) == [ Path.cwd() ]

    def test_a_broken_bridge_lookup_is_swallowed( self, monkeypatch ):
        from pathlib import Path
        def boom(): raise RuntimeError( "bridge dir gone" )
        monkeypatch.setattr( "lupin_cli.claude_code.hooks.lib.session_bridge._find_session_file", boom )
        assert list( hook_credentials._credential_search_roots() ) == [ Path.cwd() ]

    def test_a_vanished_cwd_yields_nothing_rather_than_raising( self, monkeypatch ):
        from pathlib import Path
        monkeypatch.setattr( "lupin_cli.claude_code.hooks.lib.session_bridge._find_session_file", lambda: None )
        monkeypatch.setattr( Path, "cwd", classmethod( lambda cls: ( _ for _ in () ).throw( FileNotFoundError( "gone" ) ) ) )
        assert list( hook_credentials._credential_search_roots() ) == [ ]
