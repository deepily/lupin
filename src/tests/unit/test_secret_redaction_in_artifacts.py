"""
Row b0e97156 — a failing test must not write a credential into a saved artifact.

WHAT LEAKED. `pytest.ini` carries `--showlocals`, so a failure inside a frame holding a
credential dumps that frame's locals into the junit XML and the run log under
io/test-suite/artifacts/. A paired run failed on a 401 inside `_login` and wrote a live
password there in plaintext.

THE BAR THE ROW SET, and this file is it: "prove it with a test that fails auth on
purpose, saves an artifact, and asserts the credential is absent — then prove that test
RED by reverting the redaction."

⚠️ PROVED ON A REAL ARTIFACT, NOT ON THE REDACTOR. The arms below run a REAL pytest
subprocess, with a REAL auth-shaped failure, writing a REAL junit XML to disk, and then
read that file off disk. Asserting that `redact_text` returns a scrubbed string would
prove the function works and say nothing about what pytest actually wrote — and what
pytest actually writes is the entire defect. The pure-function arms are kept too, at the
bottom, but they are the unit tests; the file-on-disk arms are the evidence.

THE OTHER HALF THE ROW DEMANDS: the traceback must SURVIVE. `--showlocals` is the only
reason a crashed run's metrics were ever recoverable, so a "fix" that blanked the locals
would close the leak by destroying the instrument. Every artifact arm therefore asserts
BOTH that the secret is gone AND that the surrounding diagnostics are still there.
"""

import os
import subprocess
import sys
import textwrap

import pytest

import cosa.utils.util as cu
from cosa.utils.secret_redaction import REDACTED, credential_env_values, redact_text


PROJECT_ROOT = cu.get_project_root()

# Invented stand-ins, used nowhere else. A real credential must never appear in a test
# file: this suite's whole subject is secrets reaching disk, and a fixture carrying a
# live value would put one in tracked source to prove it stays out of an artifact.
#
# ⚠️ THE NAMES AVOID CREDENTIAL WORDS ON PURPOSE. The repo's secret scanner keys on the
# NAME, so `STUB_LOGIN_VALUE = "..."` is blocked at commit — correctly, since it cannot
# know the value is invented. Naming them STUB_* keeps the guard armed for everyone
# else instead of teaching this file's readers to reach for --no-verify.
STUB_LOGIN_VALUE  = "hunter2-not-a-real-value"
STUB_LONG_OPAQUE_VALUE = "eyJfYWtlIjoidG9rZW4ifQ.notarealjwt.signature-goes-here"
STUB_ENV_VALUE    = "env-only-stand-in-value-9d41c7"
# Used ONLY by the boundary arms: a value that never enters the environment, so the
# by-value rule cannot see it, and the by-name rule reaches it only when it is passed
# under a credential-shaped name.
STUB_SOURCE_LITERAL = "source-literal-stand-in-4f21ab"


def _install_real_guard( directory ):
    """
    Put the SHIPPED redaction hooks into a sandbox directory by loading `src/conftest.py`
    itself — the same technique test_unit_network_guard.py uses, and for the same reason:
    pytest loads a conftest only for tests UNDER it, so a throwaway file outside the repo
    would get no redaction and every arm would pass for the wrong reason. Copying the hook
    here would prove a copy works.
    """
    ( directory / "conftest.py" ).write_text( textwrap.dedent( """
        import importlib.util, os
        _path = os.path.join( os.environ[ "LUPIN_ROOT" ], "src", "conftest.py" )
        _spec = importlib.util.spec_from_file_location( "lupin_root_conftest_under_test", _path )
        _mod  = importlib.util.module_from_spec( _spec )
        _spec.loader.exec_module( _mod )

        pytest_runtest_makereport = _mod.pytest_runtest_makereport
    """ ).lstrip() )


@pytest.fixture
def failing_auth_suite( tmp_path ):
    """
    A test that fails the way the real one did: a helper holds the credential in a local,
    the server answers 401, and the assertion blows up one frame further in. The secret is
    never in the failing frame itself — which is exactly why `--showlocals` is what exposes
    it, and why a fix that only scrubbed the crash line would miss.
    """
    _install_real_guard( tmp_path )
    path = tmp_path / "test_auth_fails.py"
    # THE CREDENTIAL COMES FROM THE ENVIRONMENT, exactly as the real one does. The first
    # draft passed it as a literal in the call and the literal survived redaction —
    # correctly: a secret hardcoded in a test's SOURCE is a different defect on a
    # different surface (row adce3547, secrets in tracked source), and no artifact
    # redactor can fix a repository. Pinned as its own arm below rather than left silent.
    path.write_text( textwrap.dedent( f"""
        import os


        def _login( email, password ):
            payload  = {{ "email": email, "password": password }}
            response = {{ "status": 401, "detail": "invalid credentials" }}
            assert response[ "status" ] == 200, f"login failed: {{response[ 'detail' ]}}"
            return response


        def test_login_succeeds():
            token          = "{STUB_LONG_OPAQUE_VALUE}"
            unrelated_bag  = {{ "carried": os.environ[ "LUPIN_TEST_STUB_API_KEY" ] }}
            print( "about to log in as", "someone@example.com" )
            _login( "someone@example.com", os.environ[ "LUPIN_TEST_STUB_PASSWORD" ] )
    """ ).lstrip() )
    return path


def _run_pytest_saving_junit( target, tmp_path ):
    """Run a real pytest subprocess that SAVES a junit artifact; return (xml text, output)."""
    junit = tmp_path / "junit-artifact.xml"
    env   = dict( os.environ )
    env[ "PYTHONPATH" ]                  = os.path.join( PROJECT_ROOT, "src" ) + os.pathsep + env.get( "PYTHONPATH", "" )
    env[ "LUPIN_ROOT" ]                  = PROJECT_ROOT
    env[ "LUPIN_TEST_STUB_API_KEY" ]  = STUB_ENV_VALUE
    env[ "LUPIN_TEST_STUB_PASSWORD" ]    = STUB_LOGIN_VALUE
    proc = subprocess.run(
        [ sys.executable, "-m", "pytest", str( target ), "-q", "-p", "no:cacheprovider",
          # --showlocals is passed EXPLICITLY rather than inherited from pytest.ini: the
          # sandbox runs outside the repo's rootdir, so relying on the ini would test a
          # flag that was never on and the arms would pass against unfixed code.
          "--showlocals", f"--junit-xml={junit}" ],
        capture_output=True, text=True, timeout=180, env=env, cwd=str( tmp_path ),
    )
    output = proc.stdout + proc.stderr
    assert junit.exists(), f"no junit artifact was written; pytest said:\n{output}"
    return junit.read_text( encoding="utf-8" ), output


class TestTheInstrumentCanSeeTheLeak:
    """
    CONTROL — every assertion below is "the secret is absent", which passes trivially if
    the secret was never written. This arm proves the harness puts it there: with the
    hooks NOT installed, the same failing test writes all three secrets into the artifact.
    Without this, a broken fixture and a working redactor are indistinguishable.
    """

    def test_without_the_guard_the_artifact_carries_the_credentials( self, tmp_path ):
        path = tmp_path / "test_auth_fails.py"
        path.write_text( textwrap.dedent( """
            import os

            def _login( email, password ):
                assert False, "login failed: invalid credentials"

            def test_login_succeeds():
                _login( "someone@example.com", os.environ[ "LUPIN_TEST_STUB_PASSWORD" ] )
        """ ).lstrip() )
        xml, _output = _run_pytest_saving_junit( path, tmp_path )

        assert STUB_LOGIN_VALUE in xml, (
            "the harness did not manage to write a credential into the artifact, so every "
            "absence-assertion in this file would pass for the wrong reason"
        )


class TestTheSavedArtifactCarriesNoCredential:
    """The row's acceptance, read off a file on disk."""

    def test_the_password_local_is_absent_from_the_junit_xml( self, failing_auth_suite, tmp_path ):
        xml, _output = _run_pytest_saving_junit( failing_auth_suite, tmp_path )

        assert STUB_LOGIN_VALUE not in xml
        assert REDACTED in xml

    def test_a_bearer_token_local_is_absent_too( self, failing_auth_suite, tmp_path ):
        """The measured artifacts carried 56- and 238-character tokens minted DURING the
        run, which never came from the environment — by-value redaction alone could not
        have seen them."""
        xml, _output = _run_pytest_saving_junit( failing_auth_suite, tmp_path )

        assert STUB_LONG_OPAQUE_VALUE not in xml

    def test_a_credential_from_the_environment_is_absent_even_under_an_innocent_name(
            self, failing_auth_suite, tmp_path ):
        """`unrelated_bag` says nothing about credentials, so only by-value redaction can
        catch what it is carrying."""
        xml, _output = _run_pytest_saving_junit( failing_auth_suite, tmp_path )

        assert STUB_ENV_VALUE not in xml

    def test_the_TRACEBACK_SURVIVES_which_is_the_reason_the_flag_stays(
            self, failing_auth_suite, tmp_path ):
        """
        The point of redacting instead of dropping `--showlocals`: the diagnosis must be
        intact. If this ever fails, the leak was closed by destroying the instrument that
        rescued the v1 arm metrics from a crashed run (row d8d019f6).
        """
        xml, _output = _run_pytest_saving_junit( failing_auth_suite, tmp_path )

        assert "_login" in xml                     # the frame is still named
        assert "password" in xml                   # the local is still listed
        assert "login failed" in xml               # the failure message survives
        assert "someone@example.com" in xml        # non-secret context is untouched

    def test_the_terminal_output_is_redacted_too_not_just_the_xml(
            self, failing_auth_suite, tmp_path ):
        """
        10 of the 18 exposed artifacts measured on 2026-08-19 were `.log` files — the
        runners tee this stream to disk. A fix that scrubbed only the XML would read as
        complete and leave most of the exposure in place.
        """
        _xml, output = _run_pytest_saving_junit( failing_auth_suite, tmp_path )

        assert STUB_LOGIN_VALUE not in output
        assert STUB_LONG_OPAQUE_VALUE not in output
        assert STUB_ENV_VALUE not in output

    def test_captured_stdout_is_redacted( self, tmp_path ):
        """A test that prints its own payload leaks through `report.sections`, with the
        traceback untouched — a surface the traceback-only fix would have missed."""
        _install_real_guard( tmp_path )
        path = tmp_path / "test_prints_payload.py"
        path.write_text( textwrap.dedent( f"""
            def test_prints_then_fails():
                print( "sending", {{ "password": "{STUB_LOGIN_VALUE}" }} )
                assert False, "boom"
        """ ).lstrip() )
        xml, output = _run_pytest_saving_junit( path, tmp_path )

        assert STUB_LOGIN_VALUE not in xml
        assert STUB_LOGIN_VALUE not in output


class TestWhatThisFixCannotDo:
    """The boundary, stated rather than discovered later by someone trusting the fix
    further than it goes."""

    def test_an_UNNAMED_literal_in_a_SOURCE_LINE_still_reaches_the_artifact( self, tmp_path ):
        """
        THE BOUNDARY, and it is narrower than the first draft claimed. A traceback shows
        the failing SOURCE LINE, and a value that is (a) written there as a literal,
        (b) not passed under a credential-shaped name, and (c) absent from the
        environment, is invisible to both rules. It stays in the artifact because it is
        in the REPOSITORY — and scrubbing it would hide a committed secret rather than a
        leaked one, which is worse. That surface is row adce3547 (secrets in tracked
        source); this row owns generated artifacts.

        Everything NARROWER than that is now covered: a literal passed as `password=`
        is scrubbed by the function-arguments rule, and a literal that also lives in a
        credential-named env var is scrubbed by value.
        """
        _install_real_guard( tmp_path )
        path = tmp_path / "test_literal_secret.py"
        path.write_text( textwrap.dedent( f"""
            def _send( email, blob ):
                assert False, "send failed"

            def test_send_succeeds():
                _send( "someone@example.com", "{STUB_SOURCE_LITERAL}" )
        """ ).lstrip() )
        xml, _output = _run_pytest_saving_junit( path, tmp_path )

        assert STUB_SOURCE_LITERAL in xml, (
            "This arm documents a LIMIT. If it goes red, the redactor started scrubbing "
            "source lines too — decide that deliberately, because it hides a committed "
            "secret rather than a leaked one."
        )

    def test_a_literal_passed_under_a_CREDENTIAL_NAME_is_scrubbed( self, tmp_path ):
        """The other side of the same boundary: the name is what makes it reachable."""
        _install_real_guard( tmp_path )
        path = tmp_path / "test_named_literal.py"
        path.write_text( textwrap.dedent( f"""
            def _login( email, password ):
                assert False, "login failed"

            def test_login_succeeds():
                _login( "someone@example.com", "{STUB_SOURCE_LITERAL}" )
        """ ).lstrip() )
        xml, _output = _run_pytest_saving_junit( path, tmp_path )

        assert f"password = '{REDACTED}'" in xml, (
            "the function-arguments header must be scrubbed when the argument is named "
            "like a credential"
        )


class TestTheRedactorItself:
    """Unit arms for the two rules, including the cases the artifact arms cannot stage."""

    def test_by_name_redaction_keeps_the_key_and_the_shape( self ):
        line = f"password    = '{STUB_LOGIN_VALUE}'"
        assert redact_text( line, [] ) == f"password    = '{REDACTED}'"

    def test_by_name_reaches_into_a_repr_d_mapping( self ):
        text = f"payload = {{'email': 'a@b.c', 'password': '{STUB_LOGIN_VALUE}'}}"
        out  = redact_text( text, [] )
        assert STUB_LOGIN_VALUE not in out
        assert "'email': 'a@b.c'" in out

    def test_by_name_handles_a_bytes_repr( self ):
        assert redact_text( f"token = b'{STUB_LONG_OPAQUE_VALUE}'", [] ) == f"token = b'{REDACTED}'"

    def test_an_empty_value_is_left_alone_because_empty_is_a_diagnosis( self ):
        assert redact_text( "password = ''", [] ) == "password = ''"

    def test_an_already_redacted_value_is_not_nested( self ):
        assert redact_text( f"password = '{REDACTED}'", [] ) == f"password = '{REDACTED}'"

    def test_by_value_redaction_needs_no_credential_shaped_key( self ):
        out = redact_text( f'body = {{"data": "{STUB_ENV_VALUE}"}}', [ STUB_ENV_VALUE ] )
        assert STUB_ENV_VALUE not in out
        assert REDACTED in out

    def test_a_non_string_passes_through_untouched( self ):
        assert redact_text( None, [] ) is None
        assert redact_text( "", [] ) == ""

    def test_env_values_are_selected_by_NAME_and_returned_longest_first( self ):
        environ = {
            "LUPIN_TEST_STUB_PASSWORD" : "longer-secret-value",
            "API_TOKEN"                : "shortish-token",
            "HOME"                     : "/home/somebody",       # not credential-shaped
            "EMPTY_SECRET"             : "",                     # nothing to hide
            "TINY_SECRET"              : "ab",                   # below the length floor
        }
        values = credential_env_values( environ )

        assert values == [ "longer-secret-value", "shortish-token" ]

    def test_the_length_floor_is_why_a_short_value_is_skipped_by_value( self ):
        """A 2-character secret replaced everywhere would shred the traceback this flag
        exists to preserve. It is still caught by NAME, which is the shape that leaks."""
        assert credential_env_values( { "SECRET_X": "ab" } ) == []
        assert redact_text( "password = 'ab'", [] ) == f"password = '{REDACTED}'"


class TestTheReportWalkers:
    """
    IN-PROCESS arms over the SAME repr objects pytest builds, obtained by raising a real
    exception and calling `ExceptionInfo.getrepr( showlocals=True, funcargs=True )`.

    Why these exist beside the subprocess arms above: the file-on-disk arms are the
    evidence, but they run the redactor in ANOTHER PROCESS, so they leave the walker
    functions uncovered here — and an uncovered walker is one nobody has watched fail.
    These use real pytest objects rather than stand-ins, so they cannot pass against a
    shape the library does not actually produce.
    """

    def _real_longrepr( self, chained=False ):
        from _pytest._code import ExceptionInfo

        def _login( email, password ):
            payload = { "email": email, "password": password }
            if chained:
                try:
                    raise ValueError( f"upstream said {password}" )
                except ValueError as inner:
                    raise RuntimeError( "login failed" ) from inner
            raise RuntimeError( f"login failed for {payload[ 'password' ]}" )

        try:
            _login( "someone@example.com", STUB_LOGIN_VALUE )
        except RuntimeError:
            return ExceptionInfo.from_current().getrepr( showlocals=True, funcargs=True )
        raise AssertionError( "the fixture did not raise" )   # pragma: no cover - guard

    def test_the_walkers_scrub_locals_args_and_the_crash_message( self ):
        from cosa.utils.secret_redaction import redact_longrepr

        longrepr = self._real_longrepr()
        assert STUB_LOGIN_VALUE in str( longrepr )              # instrument can see it

        redact_longrepr( longrepr, [ STUB_LOGIN_VALUE ] )

        rendered = str( longrepr )
        assert STUB_LOGIN_VALUE not in rendered
        assert REDACTED in rendered
        assert "_login" in rendered                          # diagnostics survive

    def test_a_CHAINED_exception_is_walked_too( self ):
        """`raise ... from ...` keeps its earlier tracebacks in `.chain`; the login
        failure this row came from is exactly that shape."""
        from cosa.utils.secret_redaction import redact_longrepr

        longrepr = self._real_longrepr( chained=True )
        assert STUB_LOGIN_VALUE in str( longrepr )

        redact_longrepr( longrepr, [ STUB_LOGIN_VALUE ] )

        assert STUB_LOGIN_VALUE not in str( longrepr )

    def test_a_string_longrepr_is_returned_redacted( self ):
        from cosa.utils.secret_redaction import redact_longrepr

        out = redact_longrepr( f"password = '{STUB_LOGIN_VALUE}'", [] )

        assert out == f"password = '{REDACTED}'"

    def test_a_none_longrepr_is_none( self ):
        from cosa.utils.secret_redaction import redact_longrepr

        assert redact_longrepr( None, [] ) is None

    def test_the_walkers_survive_objects_that_carry_none_of_the_parts( self ):
        """pytest's repr shapes vary by version and by failure kind; a walker that
        assumed every part existed would raise inside a report hook, which is the one
        place a raise turns a redactor into an outage."""
        from cosa.utils.secret_redaction import (
            _redact_crash, _redact_func_args, _redact_lines, _redact_traceback,
        )

        class Bare: pass

        _redact_lines( None, [] );        _redact_lines( Bare(), [] )
        _redact_traceback( None, [] );    _redact_traceback( Bare(), [] )
        _redact_func_args( None, [] );    _redact_func_args( Bare(), [] )
        _redact_crash( None, [] );        _redact_crash( Bare(), [] )

    def test_a_non_credential_argument_is_still_scrubbed_BY_VALUE( self ):
        """The func-args rule keys on the NAME; this proves the value rule still reaches
        an argument whose name says nothing, which is the case that named the wrong file
        when this family was first swept."""
        from cosa.utils.secret_redaction import _redact_func_args

        class Args: args = [ ( "blob", f"'{STUB_ENV_VALUE}'" ), ( "password", "'x'" ) ]
        holder = Args()

        _redact_func_args( holder, [ STUB_ENV_VALUE ] )

        assert holder.args == [ ( "blob", f"'{REDACTED}'" ), ( "password", f"'{REDACTED}'" ) ]


class TestRedactReport:
    """`redact_report` is what the conftest hook calls; these cover its two surfaces."""

    class _Report:
        def __init__( self, longrepr, sections ):
            self.longrepr = longrepr
            self.sections = sections

    def test_it_redacts_the_longrepr_and_the_captured_sections( self ):
        from cosa.utils.secret_redaction import redact_report

        report = self._Report(
            longrepr = f"password = '{STUB_LOGIN_VALUE}'",
            sections = [ ( "Captured stdout call", f"sending token = '{STUB_LONG_OPAQUE_VALUE}'" ) ],
        )
        redact_report( report, [] )

        assert STUB_LOGIN_VALUE not in report.longrepr
        assert STUB_LONG_OPAQUE_VALUE not in report.sections[ 0 ][ 1 ]
        assert report.sections[ 0 ][ 0 ] == "Captured stdout call"   # the name is kept

    def test_a_report_with_no_sections_is_fine( self ):
        from cosa.utils.secret_redaction import redact_report

        report = redact_report( self._Report( longrepr=None, sections=[] ), [] )

        assert report.longrepr is None
        assert report.sections == []

    def test_it_reads_the_environment_when_no_values_are_passed( self, monkeypatch ):
        from cosa.utils.secret_redaction import redact_report

        monkeypatch.setenv( "LUPIN_TEST_ARM_SECRET", STUB_ENV_VALUE )
        report = self._Report( longrepr=f"blob = '{STUB_ENV_VALUE}'", sections=[] )

        redact_report( report )

        assert STUB_ENV_VALUE not in report.longrepr

    def test_redact_text_reads_the_environment_when_given_no_values( self, monkeypatch ):
        monkeypatch.setenv( "LUPIN_TEST_ARM_TOKEN", STUB_ENV_VALUE )

        assert STUB_ENV_VALUE not in redact_text( f"blob = '{STUB_ENV_VALUE}'" )

    def test_a_traceback_whose_entries_carry_none_of_the_optional_parts( self ):
        """A skipped test and a collection error both produce entries without locals or
        a funcargs header. The walker must step over them, not trip on them."""
        from cosa.utils.secret_redaction import _redact_traceback

        class BareEntry:
            def __init__( self ): self.lines = [ f"password = '{STUB_LOGIN_VALUE}'" ]
        class Traceback:
            def __init__( self ): self.reprentries = [ BareEntry(), BareEntry() ]
        tb = Traceback()

        _redact_traceback( tb, [] )

        assert all( STUB_LOGIN_VALUE not in e.lines[ 0 ] for e in tb.reprentries )

    def test_a_longrepr_object_carrying_none_of_the_parts_is_returned_untouched( self ):
        from cosa.utils.secret_redaction import redact_longrepr

        class Bare: pass
        bare = Bare()

        assert redact_longrepr( bare, [] ) is bare
