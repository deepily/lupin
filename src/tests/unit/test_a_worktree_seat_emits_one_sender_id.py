"""
Guard for row 6597cea9 — Rick's duplicate focus-bar rows.

THE INCIDENT, his words: "I'm seeing duplicate sessions created in the focus bar
that are directly related to your workers running inside of a work tree."

CAPTURED FROM THE LIVE HYDRATION PAYLOAD, not re-derived — five personas, two
rows each, SAME session hash, only the project segment differing:

    claude.code@lupin-wt-cc-author-maria-4.deepily.ai#950b26f1   count=180
    claude.code@lupin.deepily.ai#950b26f1                        count=9

The row's own decision rule: "same suffix + different project = a detection bug".
Same suffix. So it is the PROJECT segment, and the suffix hypothesis is refuted.

THE CAUSE. Two resolvers answer "which project is this session in":

    detect_project()                     -> "lupin"   worktree-aware
    _resolve_project_from_bridge_cwd()   -> "lupin-wt-…"  stops at the gitlink

`( parent / ".git" ).exists()` is True for a FILE, so the bridge resolver's walk
halts at the worktree root and takes its directory name. `detect_project()` has
carried a gitlink branch since the 2026-06-11 incident; the bridge resolver never
got it — while its docstring claims it "matches detect_project() semantics
exactly, just sourced from the bridge instead of live cwd."

⚠️ NOT A CANONICALISATION GAP. ~/.lupin/config maps [lupin], [plan],
[lupin-mobile] and has no [lupin-wt-*] section, and the canonicaliser returns an
unmapped name unchanged — so adding it would change nothing. The gap is
worktree-owner resolution.

⚠️ AND NOT A CLIENT BUG. SenderStore keys Map<sender_id, SenderRecord>, which is
correct given two genuinely distinct ids. Deduping there would hide a backend
minting two identities per seat.

Created 2026-09-04 — John, row 6597cea9.
"""

import json
import subprocess
from pathlib import Path

import pytest

from lupin_cli.claude_code.hooks.lib import session_bridge


def _real_worktree( tmp_path ):
    """
    Build a REAL git worktree on disk — not a hand-made gitlink.

    ⚠️ THE FIXTURE MUST GO THROUGH GIT. The resolver disambiguates a worktree
    from a submodule by asking git itself (`--git-common-dir`), so a hand-written
    `.git` file would exercise a path the real one never takes and could pass
    while the real case fails. This is the parser-fixture trap: a fixture authored
    on the parser's side of the boundary is tidier than what the world produces.

    Returns: ( main_repo_path, worktree_path )
    """
    main = tmp_path / "myrepo"
    main.mkdir()
    run = lambda *a: subprocess.run( a, cwd=main, check=True,
                                     capture_output=True, text=True )
    run( "git", "init", "-q", "-b", "main" )
    run( "git", "config", "user.email", "t@t.t" )
    run( "git", "config", "user.name", "t" )
    ( main / "f.txt" ).write_text( "x" )
    run( "git", "add", "-A" )
    run( "git", "commit", "-qm", "init" )

    wt = tmp_path / "myrepo-wt-somebody-1"
    run( "git", "worktree", "add", "--detach", "-q", str( wt ) )
    return main, wt


def _bridge_at( tmp_path, cwd_value ):
    """Point the resolver at a bridge file whose SessionStart cwd is `cwd_value`."""
    bridge = tmp_path / "cc-999.json"
    bridge.write_text( json.dumps( { "cwd": str( cwd_value ) } ) )
    return bridge


class TestAWorktreeSeatEmitsOneSenderId:

    def test_the_fixture_really_is_a_worktree( self, tmp_path ):
        """
        POSITIVE CONTROL, and it runs FIRST on purpose.

        Every assertion below is about what a resolver does with a worktree. If
        the fixture is not one, they all pass or fail for reasons that have
        nothing to do with the defect — the row's own warning, one level up from
        the strip: assert the thing exists before asserting what it does.
        """
        main, wt = _real_worktree( tmp_path )
        assert ( wt / ".git" ).is_file(), "not a gitlink — this is not a worktree"
        assert ( main / ".git" ).is_dir(), "the main repo is not a normal repo"
        common = subprocess.run(
            [ "git", "rev-parse", "--git-common-dir" ],
            cwd=wt, capture_output=True, text=True, check=True
        ).stdout.strip()
        assert Path( common ).name == ".git", (
            "git does not report this as a worktree, so the resolver's own "
            "disambiguator would not see one either"
        )

    def test_a_bridge_cwd_inside_a_worktree_resolves_to_the_MAIN_repo(
        self, tmp_path, monkeypatch
    ):
        """
        THE DEFECT. A worktree seat must emit the main repo's project segment,
        or one session gets two sender_ids and the focus bar renders two rows.

        Ensures:
            - the worktree DIRECTORY name is never returned
            - the answer is the main repo basename
        """
        main, wt = _real_worktree( tmp_path )
        bridge = _bridge_at( tmp_path, wt )
        monkeypatch.setattr(
            session_bridge, "_find_session_file", lambda: ( bridge, "test" )
        )

        got = session_bridge._resolve_project_from_bridge_cwd()

        assert got != wt.name.lower(), (
            f"the resolver returned the WORKTREE directory name {got!r} — this is "
            f"the second sender_id Rick sees as a duplicate row"
        )
        assert got == main.name.lower(), f"expected {main.name.lower()!r}, got {got!r}"

    def test_it_agrees_with_detect_project_from_the_same_place( self, tmp_path, monkeypatch ):
        """
        THE INVARIANT THE DOCSTRING ALREADY CLAIMS, now enforced.

        `_resolve_project_from_bridge_cwd` says it "matches detect_project()
        semantics exactly, just sourced from the bridge instead of live cwd."
        Two derivations of one value that agree only by circumstance diverge the
        day their inputs do — which is exactly what happened here. Pin the
        agreement so the next divergence reddens instead of shipping.
        """
        from cosa.agents.utils import sender_id as sid_mod

        main, wt = _real_worktree( tmp_path )
        bridge = _bridge_at( tmp_path, wt )
        monkeypatch.setattr(
            session_bridge, "_find_session_file", lambda: ( bridge, "test" )
        )
        monkeypatch.chdir( wt )

        from_bridge = session_bridge._resolve_project_from_bridge_cwd()
        from_cwd    = sid_mod.detect_project()

        assert from_bridge == from_cwd, (
            f"the two resolvers disagree about one seat — bridge {from_bridge!r} "
            f"vs cwd {from_cwd!r}. One session, two project segments, two rows."
        )

    def test_a_NORMAL_repo_is_unaffected( self, tmp_path, monkeypatch ):
        """
        THE DISCRIMINATING ARM. "Resolve to the main repo" must not become
        "always climb to the outermost repo" — a normal checkout still answers
        with its own basename, and a fix that broke this would repoint every
        non-worktree seat.
        """
        main, _wt = _real_worktree( tmp_path )
        bridge = _bridge_at( tmp_path, main )
        monkeypatch.setattr(
            session_bridge, "_find_session_file", lambda: ( bridge, "test" )
        )

        assert session_bridge._resolve_project_from_bridge_cwd() == main.name.lower()

    def test_a_subdirectory_of_a_worktree_still_resolves_to_the_MAIN_repo(
        self, tmp_path, monkeypatch
    ):
        """
        The bridge's cwd is wherever `claude` was launched, which is routinely a
        subdirectory. The walk must reach the worktree root and then resolve
        THROUGH it, not stop one level up.
        """
        main, wt = _real_worktree( tmp_path )
        deep = wt / "src" / "cosa"
        deep.mkdir( parents=True )
        bridge = _bridge_at( tmp_path, deep )
        monkeypatch.setattr(
            session_bridge, "_find_session_file", lambda: ( bridge, "test" )
        )

        assert session_bridge._resolve_project_from_bridge_cwd() == main.name.lower()
