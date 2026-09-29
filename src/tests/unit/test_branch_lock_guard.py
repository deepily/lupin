"""
Unit tests for the branch-lock guard (row 3a592920).

The guard denies the four routes around the branch-lock reference-transaction hook:
setting BRANCH_GUARD_ALLOW, changing core.hooksPath, writing into the hooks directory,
and unsetting CLAUDECODE. Each route has its own class, so a mutant that disables one
check reddens that class by name.

The ALLOW cases are not decoration. Every one was taken from a real fleet command
(transcripts 2026-09-15..29) that mentions the lock without routing around it; a guard
that refuses those gets switched off, and then it guards nothing.

Coverage target is 100% lines AND branches on branch_lock_guard.py. The one exclusion is
the fail-open `except Exception` backstop in branch_lock_deny_reason, which carries a
same-line pragma explaining why it is unreachable.
"""
import subprocess
from types import SimpleNamespace

import pytest

from lupin_cli.claude_code.hooks.lib import branch_lock_guard as blg
from lupin_cli.claude_code.hooks.lib.branch_lock_guard import (
    DENY_ALLOW_FLAG,
    DENY_CLAUDECODE,
    DENY_HOOKSPATH,
    DENY_HOOKS_WRITE,
    branch_lock_deny_reason,
    build_branch_lock_deny_response,
    configured_hooks_dirs,
)


def _deny( command, **kw ):
    """Run the guard over one Bash command, forced ON, with no configured hooks dir."""
    kw.setdefault( "enabled", True )
    kw.setdefault( "hooks_dirs", [] )
    return branch_lock_deny_reason( "Bash", { "command": command }, **kw )


def _route( command, **kw ):
    """The first line of the deny reason: which route was refused, or None."""
    reason = _deny( command, **kw )
    return reason.split( "\n", 1 )[ 0 ] if reason else None


# ─── Route 1: BRANCH_GUARD_ALLOW ────────────────────────────────────────────────────

class TestRouteOneBranchGuardAllow:

    @pytest.mark.parametrize( "command", [
        "BRANCH_GUARD_ALLOW=x git branch foo",
        "export BRANCH_GUARD_ALLOW=reaper; git branch foo",
        "env BRANCH_GUARD_ALLOW=1 git switch -c foo",
        'BRANCH_GUARD_ALLOW="me" git branch foo',
        "echo ${BRANCH_GUARD_ALLOW:=x}",
        "declare -x BRANCH_GUARD_ALLOW",
        """python3 -c 'import os; os.environ["BRANCH_GUARD_ALLOW"]="x"'""",
        """python3 -c 'import os; os.environ.setdefault("BRANCH_GUARD_ALLOW", "x")'""",
        """python3 -c 'import os; os.putenv("BRANCH_GUARD_ALLOW", "x")'""",
        "python3 - <<'PY'\nimport os\nos.environ['BRANCH_GUARD_ALLOW'] = 'x'\nPY",
        "bash -c 'BRANCH_GUARD_ALLOW=x git branch foo'",
    ] )
    def test_setting_the_pass_is_denied( self, command ):
        assert _route( command ) == DENY_ALLOW_FLAG

    @pytest.mark.parametrize( "command", [
        "grep -rn BRANCH_GUARD_ALLOW src",
        'echo "$BRANCH_GUARD_ALLOW"',
        'git commit -m "the reaper sets BRANCH_GUARD_ALLOW=reaper"',
        "cat > notes.md <<'EOF'\nthe reaper sets BRANCH_GUARD_ALLOW=reaper\nEOF",
        "python3 -c 'import os; print( os.environ.get( \"BRANCH_GUARD_ALLOW\" ) )'",
        "LUPIN_BRANCH_GUARD_ALLOW=1 true",
    ] )
    def test_reading_or_writing_about_it_is_allowed( self, command ):
        assert _deny( command ) is None


# ─── Route 2: core.hooksPath ─────────────────────────────────────────────────────────

class TestRouteTwoHooksPath:

    @pytest.mark.parametrize( "command", [
        "git -c core.hooksPath=/dev/null branch foo",
        "git -c 'core.hooksPath=/dev/null' branch foo",
        'git -c "core.hooksPath=/tmp/x" checkout -b foo',
        "git -c CORE.HOOKSPATH=/x branch foo",
        "git config core.hooksPath /tmp/nohooks",
        "git config --global core.hooksPath /tmp/nohooks",
        "git config --file .git/config core.hooksPath /tmp/x",
        "git config --add core.hooksPath /tmp/x",
        "git config set core.hooksPath /tmp/x",
        "/usr/bin/git config core.hooksPath /tmp/x",
        "GIT_CONFIG_KEY_0=core.hooksPath GIT_CONFIG_VALUE_0=/x GIT_CONFIG_COUNT=1 git branch z",
        "GIT_CONFIG_PARAMETERS=core.hooksPath=/x git branch z",
    ] )
    def test_changing_it_is_denied( self, command ):
        assert _route( command ) == DENY_HOOKSPATH

    @pytest.mark.parametrize( "command", [
        "git config core.hooksPath",
        "git config --get core.hooksPath",
        "git config --show-origin --get core.hooksPath",
        "git config --unset core.hooksPath",
        "git config set core.hooksPath",
        "git config user.name",
        "git config --file .git/config user.name",
        "git config --list",
        'hp=$(git config core.hooksPath); ls -la "$hp"/reference-transaction',
        'for r in a b; do echo "$r hooksPath=$(git -C $r config core.hooksPath)"; done',
        'grep -rn "BRANCH_GUARD\\|core.hooksPath" src/lupin_cli/claude_code/hooks/',
        "cat > t.py <<'EOF'\n_run( 'git', '-c', 'core.hooksPath=/dev/null', 'branch', 'x' )\nEOF",
    ] )
    def test_reading_it_is_allowed( self, command ):
        assert _deny( command ) is None


# ─── Route 3: writing into the hooks directory ───────────────────────────────────────

class TestRouteThreeHooksDirectoryWrites:

    @pytest.mark.parametrize( "command", [
        "cp /tmp/x .git/hooks/reference-transaction",
        "rm .git/hooks/reference-transaction",
        "mv .git/hooks/reference-transaction /tmp/off",
        "chmod -x .git/hooks/reference-transaction",
        "ln -sf ../../src/scripts/pre-commit-chain.sh .git/hooks/pre-commit",
        "sudo cp x /repo/.git/hooks/pre-commit",
        "cp x .git/worktrees/seat-a/hooks/pre-commit",
        "echo 'exit 0' > .git/hooks/reference-transaction",
        "echo x >> .git/hooks/reference-transaction",
        'echo "exit 0" > "$LUPIN_ROOT/.git/hooks/reference-transaction"',
        "printf x | tee .git/hooks/reference-transaction",
        "sed -i 's/exit $status/exit 0/' .git/hooks/reference-transaction",
        "perl -pi -e 's/1/0/' .git/hooks/reference-transaction",
        "find .git/hooks -name 'ref*' -delete",
        "cd .git/hooks && mv reference-transaction rt.off",
        "cd .git/hooks; echo x > reference-transaction",
        "bash -c 'rm .git/hooks/reference-transaction'",
        "sh <<'EOF'\nrm .git/hooks/reference-transaction\nEOF",
    ] )
    def test_writing_there_is_denied( self, command ):
        assert _route( command ) == DENY_HOOKS_WRITE

    @pytest.mark.parametrize( "command", [
        "ls .git/hooks | grep -v sample",
        "ls -la .git/hooks",
        "head -20 .git/hooks/pre-commit",
        "cat .git/hooks/reference-transaction",
        "sed -n 1,20p .git/hooks/reference-transaction",
        "find .git/hooks -name 'ref*'",
        "ls .git/hooks > /tmp/list.txt",
        "echo 'see .git/hooks/pre-commit' > notes.md",
        "echo 'cp x > .git/hooks/y'",
        "cd .git/hooks && ls; cd /tmp && echo hi > x.txt",
        "cd /tmp && echo hi > x.txt",
        "git status 2>&1 | tail -3",
        "cp a .git/hooksmith/b",
    ] )
    def test_reading_there_is_allowed( self, command ):
        assert _deny( command ) is None

    def test_a_configured_hooks_directory_is_guarded_too( self ):
        """core.hooksPath can point anywhere; a write there disables the lock just the same."""
        command = "cp x /srv/shared-hooks/reference-transaction"
        assert _deny( command ) is None
        assert _route( command, hooks_dirs=[ "/srv/shared-hooks" ] ) == DENY_HOOKS_WRITE


# ─── Route 4: CLAUDECODE ─────────────────────────────────────────────────────────────

class TestRouteFourClaudeCode:

    @pytest.mark.parametrize( "command", [
        "env -u CLAUDECODE git branch foo",
        "env -u CLAUDECODE -u OTHER git branch foo",
        "env --unset=CLAUDECODE git branch foo",
        "unset CLAUDECODE; git branch foo",
        "unset -v CLAUDECODE",
        "export -n CLAUDECODE",
        "CLAUDECODE= git branch foo",
        "CLAUDECODE=0 git branch foo",
        'CLAUDECODE="" git branch foo',
        "env -i PATH=/usr/bin git branch foo",
        "env --ignore-environment git branch foo",
        "env -i HOME=$HOME sh -c 'git branch foo'",
        """python3 -c 'import os; os.environ.pop("CLAUDECODE")'""",
        """python3 -c 'import os; del os.environ["CLAUDECODE"]'""",
        """python3 -c 'import os; os.environ["CLAUDECODE"] = "0"'""",
        """python3 -c 'import os; os.unsetenv("CLAUDECODE")'""",
        "bash -c 'unset CLAUDECODE; git branch x'",
        "bash <<'EOF'\nunset CLAUDECODE\ngit branch x\nEOF",
        "python3 - <<'PY'\nimport os\ndel os.environ['CLAUDECODE']\nPY",
    ] )
    def test_hiding_it_is_denied( self, command ):
        assert _route( command ) == DENY_CLAUDECODE

    @pytest.mark.parametrize( "command", [
        "CLAUDECODE=1 claude -p hi",
        "echo $CLAUDECODE",
        'echo "CLAUDECODE=0"',
        "env -i HOME=$HOME PATH=/usr/bin:/bin sh -c \"$PREFIX python3 /tmp/probe.py\"",
        "env | grep CLAUDE",
        "cat > f.py <<'EOF'\nos.environ.pop( 'CLAUDECODE' )\nEOF",
        "python3 - <<'PY'\nimport os\nprint( os.environ.get( 'CLAUDECODE' ) )\nPY",
    ] )
    def test_reading_it_is_allowed( self, command ):
        assert _deny( command ) is None


# ─── The switches ────────────────────────────────────────────────────────────────────

class TestTheSwitches:

    ROUTE = "cp x .git/hooks/pre-commit"

    def test_the_control_the_route_is_denied_when_armed( self ):
        assert _deny( self.ROUTE ) is not None

    @pytest.mark.parametrize( "value", [ "1", "true", "ON", "yes" ] )
    def test_the_hatch_in_the_environment_disables_it( self, value ):
        assert branch_lock_deny_reason( "Bash", { "command": self.ROUTE },
                                        env={ "LUPIN_ALLOW_BRANCH_LOCK_BYPASS": value },
                                        hooks_dirs=[] ) is None

    def test_a_falsy_hatch_in_the_environment_does_not( self ):
        assert branch_lock_deny_reason( "Bash", { "command": self.ROUTE },
                                        env={ "LUPIN_ALLOW_BRANCH_LOCK_BYPASS": "0" },
                                        hooks_dirs=[] ) is not None

    def test_the_hatch_written_in_the_command_disables_it( self ):
        assert _deny( "LUPIN_ALLOW_BRANCH_LOCK_BYPASS=1 " + self.ROUTE ) is None

    @pytest.mark.parametrize( "value", [ "", "0", "no" ] )
    def test_a_falsy_hatch_in_the_command_does_not( self, value ):
        assert _deny( f"LUPIN_ALLOW_BRANCH_LOCK_BYPASS={value} " + self.ROUTE ) is not None

    def test_reading_the_hatch_is_not_setting_it( self ):
        assert _deny( "echo $LUPIN_ALLOW_BRANCH_LOCK_BYPASS=1; " + self.ROUTE ) is not None

    def test_enabled_false_disables_it( self ):
        assert _deny( self.ROUTE, enabled=False ) is None

    def test_the_process_environment_is_read_when_none_is_injected( self, monkeypatch ):
        monkeypatch.setenv( "LUPIN_ALLOW_BRANCH_LOCK_BYPASS", "1" )
        assert branch_lock_deny_reason( "Bash", { "command": self.ROUTE }, hooks_dirs=[] ) is None
        monkeypatch.delenv( "LUPIN_ALLOW_BRANCH_LOCK_BYPASS" )
        assert branch_lock_deny_reason( "Bash", { "command": self.ROUTE }, hooks_dirs=[] ) is not None


class TestInputsItIgnores:

    @pytest.mark.parametrize( "tool_name, tool_input", [
        ( "Write", { "command": "cp x .git/hooks/pre-commit" } ),
        ( "Bash",  "cp x .git/hooks/pre-commit" ),
        ( "Bash",  { "command": "" } ),
        ( "Bash",  { "command": None } ),
        ( "Bash",  {} ),
    ] )
    def test_anything_but_a_bash_command_passes( self, tool_name, tool_input ):
        assert branch_lock_deny_reason( tool_name, tool_input, enabled=True, hooks_dirs=[] ) is None

    def test_nesting_deeper_than_the_cap_is_not_followed( self ):
        """The cap keeps a pathological command from recursing forever."""
        inner = "rm .git/hooks/pre-commit"
        assert blg._check_text( inner, blg._hooks_dir_re( [] ), depth=blg._MAX_DEPTH + 1 ) is None
        assert blg._check_text( inner, blg._hooks_dir_re( [] ), depth=blg._MAX_DEPTH ) == DENY_HOOKS_WRITE

    def test_a_segment_with_no_program_is_skipped( self ):
        assert blg._segment_program( "   " ) is None
        assert _deny( "X=1; ;" ) is None


class TestTheDenyText:

    def test_it_names_the_route_the_reason_and_the_way_out( self ):
        reason = _deny( "env -u CLAUDECODE git branch x" )
        assert reason.startswith( DENY_CLAUDECODE )
        assert "0a9b1d68" in reason and "3a592920" in reason
        assert "detached HEAD" in reason
        assert "LUPIN_ALLOW_BRANCH_LOCK_BYPASS=1" in reason

    def test_the_envelope_is_a_pretooluse_deny( self ):
        assert build_branch_lock_deny_response( "why" ) == {
            "hookSpecificOutput": {
                "hookEventName"            : "PreToolUse",
                "permissionDecision"       : "deny",
                "permissionDecisionReason" : "why",
            }
        }


# ─── Reading core.hooksPath ──────────────────────────────────────────────────────────

def _runner( stdout="", returncode=0, calls=None, raises=None ):
    def run( args, **kw ):
        if calls is not None:
            calls.append( ( args, kw ) )
        if raises:
            raise raises
        return SimpleNamespace( stdout=stdout, returncode=returncode )
    return run


class TestConfiguredHooksDirs:

    def test_unset_returns_nothing( self ):
        assert configured_hooks_dirs( "/r", runner=_runner( "", returncode=1 ) ) == []

    def test_the_default_directory_returns_nothing_because_the_default_pattern_covers_it( self ):
        assert configured_hooks_dirs( "/r", runner=_runner( "/r/.git/hooks\n" ) ) == []

    def test_a_custom_directory_is_returned_with_its_realpath( self, tmp_path ):
        real = tmp_path / "real-hooks"
        real.mkdir()
        link = tmp_path / "hooks-link"
        link.symlink_to( real )
        got = configured_hooks_dirs( "/r", runner=_runner( f"{link}/\n" ) )
        assert got == [ str( link ), str( real ) ]

    def test_a_custom_directory_that_is_already_real_is_listed_once( self, tmp_path ):
        got = configured_hooks_dirs( "/r", runner=_runner( f"{tmp_path}\n" ) )
        assert got == [ str( tmp_path ) ]

    def test_it_asks_git_in_the_session_directory_with_a_timeout( self ):
        calls = []
        configured_hooks_dirs( "/some/tree", runner=_runner( calls=calls ) )
        args, kw = calls[ 0 ]
        assert args == [ "git", "-C", "/some/tree", "config", "--get", "core.hooksPath" ]
        assert kw[ "timeout" ] == blg._GIT_CONFIG_TIMEOUT_SECONDS

    def test_without_a_directory_it_asks_git_where_it_stands( self ):
        calls = []
        configured_hooks_dirs( None, runner=_runner( calls=calls ) )
        assert calls[ 0 ][ 0 ] == [ "git", "config", "--get", "core.hooksPath" ]

    def test_a_timeout_fails_open( self ):
        boom = subprocess.TimeoutExpired( "git", 2 )
        assert configured_hooks_dirs( "/r", runner=_runner( raises=boom ) ) == []

    def test_the_real_runner_is_used_by_default( self, monkeypatch ):
        calls = []
        monkeypatch.setattr( blg.subprocess, "run", _runner( calls=calls ) )
        configured_hooks_dirs( "/r" )
        assert calls

    def test_the_guard_resolves_it_when_none_is_injected( self, monkeypatch ):
        monkeypatch.setattr( blg, "configured_hooks_dirs", lambda cwd: [ "/srv/hooks" ] )
        reason = branch_lock_deny_reason( "Bash", { "command": "rm /srv/hooks/x" },
                                          enabled=True, cwd="/r" )
        assert reason.startswith( DENY_HOOKS_WRITE )
