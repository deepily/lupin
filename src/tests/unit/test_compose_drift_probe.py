#!/usr/bin/env python3
"""
Row 92374685 — compose_drift_probe.py decides whether bounce-dev-server.sh may RESTART a
container or must RECREATE it, because a restart never applies a changed tmpfs, mount or
environment value.

THE FIXTURES ARE REAL. fixtures/compose_drift/ holds `docker compose config --format json
lupin-rest-dev` and `docker inspect lupin-rest-dev`, captured 2026-09-15 16:40 EDT from the
live dev container right after it had been recreated, so the two agree. Every environment
VALUE is replaced on both sides: REDACTED-<key>, or empty for a secret-named key (the commit
credential guard flags any value there); keys, mounts,
tmpfs and labels are verbatim. Each drift test starts from that agreeing pair and changes
exactly one thing, so a verdict can only come from the thing changed.

The first run of this probe against the live containers reported drift on BOTH of them,
on a named volume: compose calls it "claude-creds-dev", docker "lupin_claude-creds-dev".
The real fixture is what reproduces that, and test_a_named_volume_is_compared_by_its_
project_prefixed_name pins it.
"""
import json
import os
import subprocess
import sys
import unittest
from unittest.mock import patch

import cosa.utils.util as cu

sys.path.insert( 0, cu.get_project_root() + "/src/scripts" )
import compose_drift_probe as probe_module  # noqa: E402

_FIXTURES = cu.get_project_root() + "/src/tests/unit/fixtures/compose_drift"
SERVICE   = "lupin-rest-dev"


def _load( name ):
    with open( os.path.join( _FIXTURES, name ) ) as f:
        return json.load( f )


def _pair():
    return _load( "compose-config-lupin-rest-dev.json" ), _load( "inspect-lupin-rest-dev.json" )


def _runner_for( rendered, inspected, calls=None, envs=None ):
    """A runner that answers the two commands the probe issues, and records them and their env."""
    def runner( argv, env=None ):
        if calls is not None: calls.append( argv )
        if envs is not None: envs.append( env )
        if argv[ :2 ] == [ "docker", "inspect" ]: return inspected
        if argv[ :2 ] == [ "docker", "compose" ]: return rendered
        raise AssertionError( f"unexpected command {argv}" )
    return runner


def _verdict( rendered, inspected ):
    return probe_module.probe( SERVICE, runner=_runner_for( rendered, inspected ) )[ :2 ]


class TestTheRealPairAgrees( unittest.TestCase ):

    def test_the_captured_pair_has_no_drift( self ):
        rendered, inspected = _pair()
        self.assertEqual( _verdict( rendered, inspected ), ( probe_module.EXIT_NO_DRIFT, [ ] ) )

    def test_the_fixture_is_not_empty_so_agreement_means_something( self ):
        rendered, inspected = _pair()
        service = rendered[ "services" ][ SERVICE ]
        self.assertGreater( len( service[ "volumes" ] ), 20 )
        self.assertGreater( len( service[ "environment" ] ), 10 )
        self.assertEqual( len( service[ "tmpfs" ] ), 1 )

    def test_the_probe_renders_the_service_its_own_labels_name( self ):
        rendered, inspected = _pair()
        calls = [ ]
        probe_module.probe( SERVICE, runner=_runner_for( rendered, inspected, calls ) )
        labels = inspected[ 0 ][ "Config" ][ "Labels" ]
        self.assertEqual( calls[ 0 ], [ "docker", "inspect", SERVICE ] )
        self.assertEqual( calls[ 1 ], [ "docker", "compose",
                                        "--project-name", labels[ probe_module.LABEL_PROJECT ],
                                        "--project-directory", labels[ probe_module.LABEL_WORKING_DIR ],
                                        "-f", labels[ probe_module.LABEL_CONFIG_FILES ],
                                        "config", "--format", "json", labels[ probe_module.LABEL_SERVICE ] ] )


class TestTheRecreateUsesTheTreeThatWasCompared( unittest.TestCase ):
    """
    María's review of 34a2764a: the bounce script recreated from $LUPIN_ROOT while the probe
    compared the container's own compose tree. The probe now returns the recreate argv, built
    from the same labels, and the script runs exactly that.
    """

    def test_the_recreate_argv_is_the_compared_prefix_plus_up( self ):
        rendered, inspected = _pair()
        calls = [ ]
        code, fields, recreate = probe_module.probe( SERVICE, runner=_runner_for( rendered, inspected, calls ) )
        config_prefix = calls[ 1 ][ :calls[ 1 ].index( "config" ) ]
        self.assertEqual( recreate, config_prefix + [ "up", "-d", "--force-recreate", "--no-deps", SERVICE ] )
        self.assertIn( "/mnt/DATA01/include/www.deepily.ai/projects/lupin", recreate,
                       "the fixture's working_dir label should be the recreate's project directory" )

    def test_a_container_without_a_project_label_is_unknown_with_no_recreate( self ):
        rendered, inspected = _pair()
        del inspected[ 0 ][ "Config" ][ "Labels" ][ probe_module.LABEL_PROJECT ]
        code, fields, recreate = probe_module.probe( SERVICE, runner=_runner_for( rendered, inspected ) )
        self.assertEqual( ( code, recreate ), ( probe_module.EXIT_UNKNOWN, [ ] ) )
        self.assertIn( "com.docker.compose.project", fields[ 0 ] )

    def test_main_prints_one_recreate_line_per_argument_only_on_drift( self ):
        rendered, inspected = _pair()
        with patch( "sys.stdout" ) as out:
            probe_module.main( [ SERVICE ], runner=_runner_for( rendered, inspected ) )
        clean = "".join( c.args[ 0 ] for c in out.write.call_args_list )
        self.assertNotIn( probe_module.RECREATE_ARG_PREFIX, clean )
        inspected[ 0 ][ "HostConfig" ][ "Tmpfs" ] = { }
        with patch( "sys.stdout" ) as out:
            probe_module.main( [ SERVICE ], runner=_runner_for( rendered, inspected ) )
        printed = "".join( c.args[ 0 ] for c in out.write.call_args_list ).splitlines()
        args    = [ l[ len( probe_module.RECREATE_ARG_PREFIX ): ] for l in printed if l.startswith( probe_module.RECREATE_ARG_PREFIX ) ]
        self.assertEqual( args, probe_module.probe( SERVICE, runner=_runner_for( rendered, inspected ) )[ 2 ] )


class TestComposeInterpolatesFromTheEnvironmentItIsGiven( unittest.TestCase ):
    """
    The compose file takes some required values from the shell and its secrets from .env,
    so the probe answers "what would a recreate from THIS environment produce". It passes
    the environment it is given to compose unchanged, and `docker inspect` inherits.
    """

    def test_an_explicit_environ_reaches_compose_unchanged_and_inspect_inherits( self ):
        rendered, inspected = _pair()
        calls, envs = [ ], [ ]
        caller = { "PATH": "/usr/bin", "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD": "from-the-shell" }
        probe_module.probe( SERVICE, runner=_runner_for( rendered, inspected, calls, envs ), environ=caller )
        self.assertEqual( calls[ 1 ][ :2 ], [ "docker", "compose" ] )
        self.assertEqual( envs, [ None, caller ] )

    def test_no_environ_means_compose_inherits( self ):
        rendered, inspected = _pair()
        envs = [ ]
        probe_module.probe( SERVICE, runner=_runner_for( rendered, inspected, envs=envs ) )
        self.assertEqual( envs, [ None, None ] )

    def test_run_json_passes_the_env_to_the_child( self ):
        out = probe_module.run_json( [ sys.executable, "-c", "import json, os; print( json.dumps( sorted( os.environ ) ) )" ],
                                     env={ "ONLY_THIS": "1" } )
        self.assertIn( "ONLY_THIS", out )
        self.assertNotIn( "LUPIN_ROOT", out )


class TestEachKindOfDriftIsNamed( unittest.TestCase ):

    def test_a_changed_tmpfs_option_is_drift_the_mp3_upload_case( self ):
        rendered, inspected = _pair()
        inspected[ 0 ][ "HostConfig" ][ "Tmpfs" ][ "/tmp/lupin-stt" ] = "size=256m"
        self.assertEqual( _verdict( rendered, inspected ), ( probe_module.EXIT_DRIFT, [ "tmpfs /tmp/lupin-stt" ] ) )

    def test_a_tmpfs_the_container_lacks_is_drift( self ):
        rendered, inspected = _pair()
        inspected[ 0 ][ "HostConfig" ][ "Tmpfs" ] = None
        self.assertEqual( _verdict( rendered, inspected ), ( probe_module.EXIT_DRIFT, [ "tmpfs /tmp/lupin-stt" ] ) )

    def test_a_tmpfs_compose_no_longer_declares_is_drift( self ):
        rendered, inspected = _pair()
        del rendered[ "services" ][ SERVICE ][ "tmpfs" ]
        self.assertEqual( _verdict( rendered, inspected ), ( probe_module.EXIT_DRIFT, [ "tmpfs /tmp/lupin-stt" ] ) )

    def test_a_bind_mount_the_container_lacks_is_drift( self ):
        rendered, inspected = _pair()
        target = rendered[ "services" ][ SERVICE ][ "volumes" ][ 0 ][ "target" ]
        inspected[ 0 ][ "Mounts" ] = [ m for m in inspected[ 0 ][ "Mounts" ] if m[ "Destination" ] != target ]
        self.assertEqual( _verdict( rendered, inspected ), ( probe_module.EXIT_DRIFT, [ f"mount {target}" ] ) )

    def test_a_mount_compose_dropped_is_drift_because_a_recreate_would_remove_it( self ):
        rendered, inspected = _pair()
        dropped = rendered[ "services" ][ SERVICE ][ "volumes" ].pop( 0 )
        self.assertEqual( _verdict( rendered, inspected ), ( probe_module.EXIT_DRIFT, [ f"mount {dropped[ 'target' ]}" ] ) )

    def test_a_mount_turned_read_only_in_compose_is_drift( self ):
        rendered, inspected = _pair()
        volume = next( v for v in rendered[ "services" ][ SERVICE ][ "volumes" ] if not v.get( "read_only" ) )
        volume[ "read_only" ] = True
        self.assertEqual( _verdict( rendered, inspected ), ( probe_module.EXIT_DRIFT, [ f"mount {volume[ 'target' ]}" ] ) )

    def test_a_named_volume_is_compared_by_its_project_prefixed_name( self ):
        rendered, inspected = _pair()
        volume = next( v for v in rendered[ "services" ][ SERVICE ][ "volumes" ] if v[ "type" ] == "volume" )
        self.assertNotEqual( volume[ "source" ], rendered[ "volumes" ][ volume[ "source" ] ][ "name" ],
                             "the fixture no longer shows the short-name/prefixed-name split" )
        # CONTROL: without the rendered top-level names, the short name is compared and reads as drift.
        del rendered[ "volumes" ]
        self.assertEqual( _verdict( rendered, inspected ), ( probe_module.EXIT_DRIFT, [ f"mount {volume[ 'target' ]}" ] ) )

    def test_a_changed_environment_value_names_the_key_and_never_the_value( self ):
        rendered, inspected = _pair()
        rendered[ "services" ][ SERVICE ][ "environment" ][ "DB_PASSWORD" ] = "a-new-secret-value"
        code, fields = _verdict( rendered, inspected )
        self.assertEqual( ( code, fields ), ( probe_module.EXIT_DRIFT, [ "env DB_PASSWORD" ] ) )
        with patch( "sys.stdout" ) as out:
            probe_module.main( [ SERVICE ], runner=_runner_for( rendered, inspected ) )
        printed = "".join( call.args[ 0 ] for call in out.write.call_args_list )
        self.assertIn( "env DB_PASSWORD", printed )
        self.assertNotIn( "a-new-secret-value", printed )

    def test_an_environment_key_the_container_lacks_is_drift( self ):
        rendered, inspected = _pair()
        rendered[ "services" ][ SERVICE ][ "environment" ][ "LUPIN_BRAND_NEW" ] = "1"
        self.assertEqual( _verdict( rendered, inspected ), ( probe_module.EXIT_DRIFT, [ "env LUPIN_BRAND_NEW" ] ) )

    def test_a_null_compose_environment_value_means_empty( self ):
        rendered, inspected = _pair()
        rendered[ "services" ][ SERVICE ][ "environment" ][ "LUPIN_EMPTY" ] = None
        inspected[ 0 ][ "Config" ][ "Env" ].append( "LUPIN_EMPTY=" )
        self.assertEqual( _verdict( rendered, inspected ), ( probe_module.EXIT_NO_DRIFT, [ ] ) )

    def test_an_image_only_environment_key_is_not_drift( self ):
        rendered, inspected = _pair()
        inspected[ 0 ][ "Config" ][ "Env" ].append( "PATH_FROM_THE_IMAGE=/usr/bin" )
        self.assertEqual( _verdict( rendered, inspected ), ( probe_module.EXIT_NO_DRIFT, [ ] ) )

    def test_several_drifts_are_all_named_in_order( self ):
        rendered, inspected = _pair()
        rendered[ "services" ][ SERVICE ][ "environment" ][ "LUPIN_ENV" ] = "changed"
        inspected[ 0 ][ "HostConfig" ][ "Tmpfs" ] = { }
        self.assertEqual( _verdict( rendered, inspected ),
                          ( probe_module.EXIT_DRIFT, [ "tmpfs /tmp/lupin-stt", "env LUPIN_ENV" ] ) )


class TestNormalizers( unittest.TestCase ):

    def test_compose_tmpfs_accepts_the_string_form_and_a_bare_path( self ):
        self.assertEqual( probe_module.compose_tmpfs( { "tmpfs": "/run" } ), { "/run": "" } )
        self.assertEqual( probe_module.compose_tmpfs( { } ), { } )

    def test_a_service_and_container_with_nothing_declared_agree( self ):
        container = { "HostConfig": { }, "Mounts": None, "Config": { "Env": None } }
        self.assertEqual( probe_module.drifted_fields( { }, container, { } ), [ ] )

    def test_a_named_volume_absent_from_the_rendered_names_keeps_its_own_name( self ):
        service = { "volumes": [ { "type": "volume", "source": "external-vol", "target": "/data" } ] }
        self.assertEqual( probe_module.compose_mounts( service, { } ), { ( "volume", "external-vol", "/data", False ) } )


class TestTheProbeNeverRaises( unittest.TestCase ):

    def _unknown( self, runner ):
        code, fields, recreate = probe_module.probe( SERVICE, runner=runner )
        self.assertEqual( ( code, recreate ), ( probe_module.EXIT_UNKNOWN, [ ] ) )
        self.assertEqual( len( fields ), 1 )
        return fields[ 0 ]

    def test_docker_missing_is_unknown( self ):
        def runner( argv ): raise FileNotFoundError( "docker" )
        self.assertIn( "FileNotFoundError", self._unknown( runner ) )

    def test_a_container_without_compose_labels_is_unknown( self ):
        rendered, inspected = _pair()
        inspected[ 0 ][ "Config" ][ "Labels" ] = { }
        self.assertIn( "KeyError", self._unknown( _runner_for( rendered, inspected ) ) )

    def test_a_container_with_null_labels_is_unknown( self ):
        rendered, inspected = _pair()
        inspected[ 0 ][ "Config" ][ "Labels" ] = None
        self.assertIn( "KeyError", self._unknown( _runner_for( rendered, inspected ) ) )

    def test_an_empty_inspect_answer_is_unknown( self ):
        rendered, _ = _pair()
        self.assertIn( "IndexError", self._unknown( _runner_for( rendered, [ ] ) ) )

    def test_a_timeout_is_unknown( self ):
        def runner( argv ): raise subprocess.TimeoutExpired( argv, 30 )
        self.assertIn( "TimeoutExpired", self._unknown( runner ) )


class TestRunJson( unittest.TestCase ):

    def test_stdout_is_parsed( self ):
        self.assertEqual( probe_module.run_json( [ sys.executable, "-c", "print( '[1, 2]' )" ] ), [ 1, 2 ] )

    def test_a_non_zero_exit_raises_with_the_command_and_stderr( self ):
        with self.assertRaises( RuntimeError ) as caught:
            probe_module.run_json( [ sys.executable, "-c", "import sys; sys.stderr.write( 'no such container' ); sys.exit( 1 )" ] )
        self.assertIn( "exited 1", str( caught.exception ) )
        self.assertIn( "no such container", str( caught.exception ) )

    def test_non_json_stdout_raises_value_error( self ):
        with self.assertRaises( ValueError ):
            probe_module.run_json( [ sys.executable, "-c", "print( 'not json' )" ] )


class TestMain( unittest.TestCase ):

    def _main( self, argv, runner ):
        with patch( "sys.stdout" ) as out, patch( "sys.stderr" ) as err:
            code = probe_module.main( argv, runner=runner )
        text = lambda stream: "".join( c.args[ 0 ] for c in stream.write.call_args_list )
        return code, text( out ), text( err )

    def test_no_drift_prints_none( self ):
        code, out, _ = self._main( [ SERVICE ], _runner_for( *_pair() ) )
        self.assertEqual( code, probe_module.EXIT_NO_DRIFT )
        self.assertIn( "compose drift: none", out )

    def test_drift_prints_each_field( self ):
        rendered, inspected = _pair()
        inspected[ 0 ][ "HostConfig" ][ "Tmpfs" ] = { }
        code, out, _ = self._main( [ SERVICE ], _runner_for( rendered, inspected ) )
        self.assertEqual( code, probe_module.EXIT_DRIFT )
        self.assertIn( "lacks 1 compose value", out )
        self.assertIn( "  - tmpfs /tmp/lupin-stt", out )

    def test_unknown_prints_the_reason( self ):
        def runner( argv ): raise OSError( "permission denied on the docker socket" )
        code, out, _ = self._main( [ SERVICE ], runner )
        self.assertEqual( code, probe_module.EXIT_UNKNOWN )
        self.assertIn( "UNKNOWN", out )
        self.assertIn( "permission denied on the docker socket", out )

    def test_a_missing_container_argument_is_unknown_with_usage( self ):
        code, _, err = self._main( [ ], _runner_for( *_pair() ) )
        self.assertEqual( code, probe_module.EXIT_UNKNOWN )
        self.assertIn( "usage:", err )

    def test_argv_defaults_to_the_process_arguments( self ):
        with patch.object( sys, "argv", [ "compose_drift_probe.py", SERVICE ] ):
            code, _, _ = self._main( None, _runner_for( *_pair() ) )
        self.assertEqual( code, probe_module.EXIT_NO_DRIFT )


if __name__ == "__main__":
    unittest.main()
