"""
Coverage ramp for `src/scripts/init_test_database.py` — a straggler at zero on the
coverage-gate frame (unit + cosa, one data file), claimed in
`src/rnd/v0.2.1/2026.08.30-coverage-straggler-claim-ledger.md`.

🔴 THIS SCRIPT CREATES A DATABASE, AND THE WRONG ONE IS ONE ENVIRONMENT VARIABLE AWAY.
`init_auth_database()` writes a real auth schema at whatever `get_auth_db_path()` resolves
to, and a host shell inherits the *Development* config block — the exact trap CLAUDE.md
§ TESTING VENUES documents, where a query aimed at `lupin_db_test` silently answers from
`lupin_db_dev`. Nothing in this file may reach either. Three independent controls, because
each one covers a different way out of the process:

  1. `get_auth_db_path` and `init_auth_database` are stopped at the MODULE attribute, so a
     missed patch surfaces as an error rather than as a schema written somewhere real.
  2. `ConfigurationManager` is stopped the same way. Constructing the real one reads the INI
     and would make these tests depend on which block the runner's environment selected.
  3. A PLUGIN-LEVEL TRIPWIRE on `subprocess.run`, installed autouse for the whole module,
     with its own test proving it BITES. This one is not optional bookkeeping: the script
     does `import subprocess` INSIDE `main()`, so the name is a function local and there is
     no `mod.subprocess` attribute to patch. The real module's `run` is the only seam, and
     an unpatched call would execute `create_api_keys_table.py` for real — a second script,
     in a second process, against a real database.

⚠️ THE SUBPROCESS IS SOMEBODY ELSE'S SCRIPT. `create_api_keys_table.py` is covered on its own
row; what belongs here is only the CONTRACT between the two — that it is invoked with this
interpreter, by absolute path under `lupin_root`, with output captured, and that a non-zero
return code fails the whole run instead of being printed and walked past.

LOAD MECHANISM: by-path `importlib.util.spec_from_file_location`. The filename is already an
identifier, but by-path load is what makes the module RE-loadable, which is the only way to
reach the `LUPIN_ROOT` bootstrap branch that has already run before any test starts.
"""

import importlib.util
import os
import subprocess
import sys

import pytest


_ROOT = os.environ.get( "LUPIN_ROOT", os.getcwd() )
_PATH = os.path.join( _ROOT, "src", "scripts", "init_test_database.py" )
_NAME = "init_test_database_under_test"


def _load():
    """Import the script by path and return its namespace."""
    spec   = importlib.util.spec_from_file_location( _NAME, _PATH )
    module = importlib.util.module_from_spec( spec )
    sys.modules[ _NAME ] = module
    spec.loader.exec_module( module )
    return module


class EscapedToASubprocess( AssertionError ):
    """Raised when a test would have run the real api-keys script against a real database."""


@pytest.fixture( autouse=True )
def _no_subprocess( monkeypatch ):
    def _tripwire( *a, **k ):
        raise EscapedToASubprocess(
            f"a test reached subprocess.run{a!r} — this script shells create_api_keys_table.py, "
            "which writes to a real database"
        )
    monkeypatch.setattr( subprocess, "run", _tripwire )


@pytest.fixture
def mod( monkeypatch ):
    monkeypatch.setenv( "LUPIN_ROOT", _ROOT )
    return _load()


# ── doubles ───────────────────────────────────────────────────────────────────

class _Config:
    """`ConfigurationManager` stopped at the module attribute; records how it was asked."""

    def __init__( self, testing=True ):
        self.testing = testing
        self.gets    = [ ]
        self.env_var = None

    def __call__( self, env_var_name=None ):
        self.env_var = env_var_name
        return self

    def get( self, key, default=None, return_type=None ):
        self.gets.append( ( key, default, return_type ) )
        return self.testing


class _Completed:
    """The shape `subprocess.run( …, capture_output=True, text=True )` hands back."""

    def __init__( self, returncode=0, stdout="api_keys table created", stderr="" ):
        self.returncode = returncode
        self.stdout     = stdout
        self.stderr     = stderr


def _raise( error ):
    """A stand-in that raises when called — the failure injected at a module seam."""
    def _boom( *a, **k ): raise error
    return _boom


DB_PATH = "/nonexistent/test-only/lupin_auth_test.db"


@pytest.fixture
def wired( mod, monkeypatch ):
    """
    Every write seam stopped, plus a recording `subprocess.run` that replaces the tripwire for
    the tests that legitimately reach it.
    """
    state = { "config": _Config(), "init_calls": 0, "runs": [ ],
              "result": _Completed() }

    def _init_auth_database():
        state[ "init_calls" ] += 1

    def _run( argv, capture_output=None, text=None ):
        state[ "runs" ].append( { "argv": argv, "capture_output": capture_output, "text": text } )
        return state[ "result" ]

    monkeypatch.setattr( mod, "ConfigurationManager", state[ "config" ] )
    monkeypatch.setattr( mod, "get_auth_db_path",  lambda: DB_PATH )
    monkeypatch.setattr( mod, "init_auth_database", _init_auth_database )
    monkeypatch.setattr( subprocess, "run", _run )
    return state


# ── Module bootstrap ──────────────────────────────────────────────────────────

class TestBootstrap:

    def test_missing_lupin_root_refuses_at_import_with_the_export_in_the_message( self, monkeypatch ):
        monkeypatch.delenv( "LUPIN_ROOT", raising=False )
        with pytest.raises( RuntimeError ) as excinfo:
            _load()

        message = str( excinfo.value )
        assert "export LUPIN_ROOT"      in message
        assert "init_test_database.py"  in message

    def test_a_path_without_src_gets_it_inserted_at_the_front( self, monkeypatch ):
        """`insert( 0, … )`, not append — src must win over anything already on the path."""
        monkeypatch.setenv( "LUPIN_ROOT", _ROOT )
        src = os.path.join( _ROOT, "src" )
        monkeypatch.setattr( sys, "path", [ p for p in sys.path if p != src ] )

        _load()

        assert sys.path[ 0 ] == src

    def test_reloading_with_src_already_present_does_not_duplicate_it( self, monkeypatch ):
        """The guard's FALSE half — an unconditional insert would grow sys.path per import."""
        monkeypatch.setenv( "LUPIN_ROOT", _ROOT )
        src    = os.path.join( _ROOT, "src" )
        before = sys.path.count( src )
        assert before >= 1, "precondition: this test session already put src on the path"

        _load()

        assert sys.path.count( src ) == before


class TestTheTripwireItself:
    """
    A control that has never been seen to fire is indistinguishable from no control. This is
    the arm that proves the other tests' silence means something.
    """

    def test_running_a_subprocess_raises_rather_than_touching_a_real_database( self ):
        with pytest.raises( EscapedToASubprocess ):
            subprocess.run( [ sys.executable, "-c", "pass" ] )


# ── The test-mode gate ────────────────────────────────────────────────────────

class TestTestModeGate:

    def test_a_non_testing_config_block_refuses_before_writing_anything( self, mod, wired, capsys ):
        """
        The gate that stops this creating a schema in `lupin_db_dev`. It must return BEFORE
        `init_auth_database`, not merely warn — a warning plus a write is a write.
        """
        wired[ "config" ].testing = False

        assert mod.main() == 1
        assert wired[ "init_calls" ] == 0
        assert wired[ "runs" ]       == [ ]

    def test_the_refusal_names_the_environment_variable_that_fixes_it( self, mod, wired, capsys ):
        wired[ "config" ].testing = False

        mod.main()

        out = capsys.readouterr().out
        assert "Not in test mode"           in out
        assert "LUPIN_CONFIG_MGR_CLI_ARGS"  in out
        assert "Lupin:+Testing"             in out

    def test_test_mode_is_read_as_a_boolean_and_defaults_to_refusing( self, mod, wired ):
        """
        `default=False` is the safe direction: a config missing the key must NOT be treated as
        test mode. `return_type="boolean"` matters because the INI value arrives as a string,
        and the string "false" is truthy.
        """
        mod.main()

        assert wired[ "config" ].gets == [ ( "app testing", False, "boolean" ) ]

    def test_the_config_is_read_from_the_cli_args_environment_variable( self, mod, wired ):
        mod.main()
        assert wired[ "config" ].env_var == "LUPIN_CONFIG_MGR_CLI_ARGS"


# ── The happy path ────────────────────────────────────────────────────────────

class TestSuccessfulInitialization:

    def test_a_clean_run_initializes_the_schema_once_and_exits_0( self, mod, wired ):
        assert mod.main() == 0
        assert wired[ "init_calls" ] == 1

    def test_it_reports_the_database_it_actually_wrote_to( self, mod, wired, capsys ):
        """
        The resolved path is printed twice on purpose — before the write and in the summary.
        Which database this touched is the single fact an operator most needs, and the one a
        wrong config block gets wrong silently.
        """
        mod.main()

        out = capsys.readouterr().out
        assert out.count( DB_PATH ) == 2
        assert "SUCCESS" in out

    def test_the_summary_points_at_the_integration_suite_this_database_is_for( self, mod, wired, capsys ):
        mod.main()
        assert "run-integration-tests.sh" in capsys.readouterr().out


class TestTheApiKeysSubprocess:

    def test_the_second_script_is_run_with_this_interpreter_by_absolute_path( self, mod, wired ):
        """
        `sys.executable`, not `"python"` — the venv's interpreter is the one with the
        dependencies, and a bare name would take whatever is first on PATH.
        """
        mod.main()

        argv = wired[ "runs" ][ 0 ][ "argv" ]
        assert argv[ 0 ] == sys.executable
        assert os.path.isabs( argv[ 1 ] )
        assert argv[ 1 ] == os.path.join( _ROOT, "src", "scripts", "create_api_keys_table.py" )

    def test_the_child_path_is_built_from_lupin_root_not_from_the_working_directory( self, mod, wired ):
        """A cwd-relative path would silently run a different repo's copy of that script."""
        mod.main()
        assert wired[ "runs" ][ 0 ][ "argv" ][ 1 ].startswith( mod.lupin_root )

    def test_the_childs_output_is_captured_as_text_and_relayed( self, mod, wired, capsys ):
        wired[ "result" ] = _Completed( stdout="created 1 table" )

        mod.main()

        assert wired[ "runs" ][ 0 ][ "capture_output" ] is True
        assert wired[ "runs" ][ 0 ][ "text" ]           is True
        assert "created 1 table" in capsys.readouterr().out

    def test_a_failing_child_fails_the_whole_run_rather_than_being_printed_and_passed( self, mod, wired, capsys ):
        """
        Half a schema is worse than none: the integration suite would then fail on a missing
        `api_keys` table rather than on the initialization that actually broke.
        """
        wired[ "result" ] = _Completed( returncode=1, stdout="", stderr="no such table: users" )

        assert mod.main() == 1

        out = capsys.readouterr().out
        assert "api_keys table creation failed" in out
        assert "no such table: users"           in out
        assert "SUCCESS"                    not in out


# ── The failure envelope ──────────────────────────────────────────────────────

class TestFailuresAreReportedNotSwallowed:

    def test_a_failure_inside_schema_creation_exits_1_with_the_message_and_a_traceback( self, mod, wired, monkeypatch, capsys ):
        """
        The bare `except Exception` is deliberate for a setup script, but only because it
        re-emits the detail. Swallowing the traceback would leave an operator with an exit
        code and no cause.
        """
        monkeypatch.setattr( mod, "init_auth_database", _raise( RuntimeError( "database is locked" ) ) )

        assert mod.main() == 1

        captured = capsys.readouterr()
        assert "FATAL ERROR"        in captured.out
        assert "database is locked" in captured.out
        # `traceback.print_exc()` writes to stderr, so the cause and the trace land on two
        # different streams. A test that looked for both in stdout would pass only if the
        # trace were missing entirely — which is the thing being pinned.
        assert "Traceback"          in captured.err

    def test_a_failure_while_resolving_the_database_path_is_caught_too( self, mod, wired, monkeypatch, capsys ):
        """The try opens before the path lookup — a misconfigured block must not raise raw."""
        monkeypatch.setattr( mod, "get_auth_db_path", _raise( KeyError( "auth db path" ) ) )

        assert mod.main() == 1
        assert "FATAL ERROR" in capsys.readouterr().out

    def test_a_failure_constructing_the_config_manager_is_caught_too( self, mod, wired, monkeypatch, capsys ):
        """The earliest thing inside the try — a missing INI must exit 1, not traceback out."""
        monkeypatch.setattr( mod, "ConfigurationManager", _raise( FileNotFoundError( "lupin-app.ini" ) ) )

        assert mod.main() == 1
        assert "FATAL ERROR" in capsys.readouterr().out

    def test_a_failure_in_the_subprocess_call_itself_is_caught_rather_than_escaping( self, mod, wired, monkeypatch, capsys ):
        """`subprocess.run` can raise before it ever returns — a missing interpreter, say."""
        monkeypatch.setattr( subprocess, "run", _raise( OSError( "no such interpreter" ) ) )

        assert mod.main() == 1
        assert "no such interpreter" in capsys.readouterr().out
