"""
The small wired helpers in `lupin_app/main.py` — the 16 statements row `e2099400` §3c calls
"the pure helpers to extract".

WHY THEY ARE TESTED IN PLACE RATHER THAN EXTRACTED. §3c's instruction was to move these
"into a measured module". main.py has BEEN in the coverage frame since the source list was
widened on 2026-08-13, so the move cannot buy measurement — the measurement is already
there. What it would buy is testability, and these four are testable where they stand once
the module globals they read are patched, which `test_managed_bounce_broadcast.py` already
does today. Moving code inside the file every server boot goes through, to reach a property
it already has, is churn with a risk attached.

WHAT THEY HAVE IN COMMON, and why they were uncovered. Every one of them reads a module
GLOBAL that is None until `lifespan` has run — `config_mgr`, `commons_store`,
`jobs_notification_queue` — or reaches for a heavyweight import (`torch`, the transformers
`pipeline`). Neither is available to a test that merely imports the module, which is why
they sat at zero while the file around them was 25% covered.

MEASURED SHARE, at sha ef63aed9 with an isolated coverage data file: 16 statements of
main.py's 367 missing — `_emit_managed_bounce` 5, `load_stt_model` 5, `_log_vram` 4,
`_managed_bounce_server_label` 2. Four per cent of the file's gap. Recorded so nobody reads
§3c and expects lupin_app to move on the strength of it; the mass is `lifespan` at 274.

Venue: :7999-eligible — in-process, no server, no network, no persistent-state mutation.
"""

import types
import unittest

from unittest import mock

from lupin_app import main


class LogVramTest( unittest.TestCase ):
    """`_log_vram` — the one-line VRAM snapshot printed after each model load."""

    def test_nothing_is_printed_when_there_is_no_cuda( self ):
        """
        A CPU box must not be asked for GPU numbers. `memory_allocated()` on a machine
        with no CUDA raises, so the guard is load-bearing rather than cosmetic — and this
        is the branch that actually runs in CI.
        """
        fake_torch = mock.MagicMock()
        fake_torch.cuda.is_available.return_value = False

        with mock.patch.object( main, "torch", fake_torch ), \
             mock.patch( "builtins.print" ) as printed:
            main._log_vram( "CodeRankEmbed" )

        printed.assert_not_called()
        fake_torch.cuda.memory_allocated.assert_not_called()

    def test_the_snapshot_reports_gibibytes_and_names_the_model( self ):
        """
        torch reports BYTES; the line reports GiB. A missing division shows up as a
        plausible-looking number with the wrong unit, which is the kind of thing nobody
        notices in a boot log — so assert the arithmetic, not just that something printed.
        """
        fake_torch = mock.MagicMock()
        fake_torch.cuda.is_available.return_value  = True
        fake_torch.cuda.memory_allocated.return_value = 3 * 1024 ** 3      # 3.00 GiB
        fake_torch.cuda.memory_reserved.return_value  = 7 * 1024 ** 3      # 7.00 GiB

        with mock.patch.object( main, "torch", fake_torch ), \
             mock.patch( "builtins.print" ) as printed:
            main._log_vram( "Whisper" )

        line = printed.call_args.args[ 0 ]
        self.assertIn( "Whisper", line )
        self.assertIn( "Allocated 3.00 GiB", line )
        self.assertIn( "Reserved 7.00 GiB",  line )


class ManagedBounceServerLabelTest( unittest.TestCase ):
    """
    `_managed_bounce_server_label` — which server this process says it is.

    This exists because of bug 652271f3: the dev and test containers run this same file and
    differ only by config block, so without the lookup the TEST server announced ":7999" and
    nine sessions were told the DEV server had bounced. The label is therefore not a cosmetic
    string, and "reads the config" is the property worth pinning.
    """

    def test_the_label_comes_from_config_not_from_a_constant( self ):
        fake_cfg = mock.MagicMock()
        fake_cfg.get.return_value = ":8000"

        with mock.patch.object( main, "config_mgr", fake_cfg, create=True ):
            self.assertEqual( main._managed_bounce_server_label(), ":8000" )

        key, = fake_cfg.get.call_args.args
        self.assertEqual( key, "managed bounce server label" )

    def test_an_unset_key_falls_back_to_the_shared_default_not_a_local_one( self ):
        """
        The fallback must be the constant the broadcast module owns, so the warning and
        the all-clear cannot disagree about who is speaking. A locally-typed ":7999" would
        satisfy a weaker test and re-open the bug.
        """
        from cosa.rest.managed_bounce_broadcast import DEFAULT_SERVER_LABEL

        fake_cfg = mock.MagicMock()
        fake_cfg.get.side_effect = lambda key, default=None: default

        with mock.patch.object( main, "config_mgr", fake_cfg, create=True ):
            self.assertEqual( main._managed_bounce_server_label(), DEFAULT_SERVER_LABEL )


class EmitManagedBounceTest( unittest.TestCase ):
    """
    `_emit_managed_bounce` — binds the measured broadcast logic to the live commons
    singletons. The logic itself (including the not-wired guard) lives in
    `cosa.rest.managed_bounce_broadcast` and is tested there; what is untested here is the
    WIRING, and wiring is exactly where bug 652271f3 lived.
    """

    def _run( self, *, threshold="28800" ):
        fake_cfg = mock.MagicMock()
        fake_cfg.get.return_value = threshold
        sentinel = { "recipients": 4 }

        with mock.patch.object( main, "config_mgr", fake_cfg, create=True ), \
             mock.patch.object( main, "commons_store", "STORE", create=True ), \
             mock.patch.object( main, "commons_rate_limiter", "LIMITER", create=True ), \
             mock.patch.object( main, "commons_ack_watcher", "WATCHER", create=True ), \
             mock.patch.object( main, "jobs_notification_queue", "QUEUE", create=True ), \
             mock.patch( "cosa.rest.managed_bounce_broadcast.emit_bounce_broadcast_in_process",
                         return_value=sentinel ) as emit:
            result = main._emit_managed_bounce( "warning", "the server is going down", broadcast_id="b-1" )

        return result, sentinel, emit.call_args.kwargs, fake_cfg

    def test_every_live_singleton_is_handed_to_the_measured_module( self ):
        """
        The failure this catches is a singleton silently passed as None — the broadcast
        then takes the not-wired path and NOBODY IS TOLD the server is bouncing, with no
        error anywhere. Assert each one arrives, by name.
        """
        _result, _sentinel, kwargs, _cfg = self._run()

        self.assertEqual( kwargs[ "store" ],              "STORE" )
        self.assertEqual( kwargs[ "rate_limiter" ],       "LIMITER" )
        self.assertEqual( kwargs[ "ack_watcher" ],        "WATCHER" )
        self.assertEqual( kwargs[ "notification_queue" ], "QUEUE" )
        self.assertEqual( kwargs[ "kind" ],               "warning" )
        self.assertEqual( kwargs[ "message" ],            "the server is going down" )
        self.assertEqual( kwargs[ "broadcast_id" ],       "b-1" )

    def test_the_liveness_threshold_is_read_from_config_and_passed_as_a_float( self ):
        """
        Config hands back a string here. Passed through unconverted it becomes a string
        compared against a timestamp — a TypeError deep inside the broadcast, at the
        moment the fleet most needs to hear from us.
        """
        _result, _sentinel, kwargs, cfg = self._run( threshold="900" )

        self.assertEqual( kwargs[ "active_session_threshold_seconds" ], 900.0 )
        self.assertIsInstance( kwargs[ "active_session_threshold_seconds" ], float )
        self.assertEqual( cfg.get.call_args.args[ 0 ], "commons broadcast liveness threshold seconds" )

    def test_the_broadcast_result_is_returned_untouched( self ):
        """The caller reads `recipients` off this to write the fire-time receipt."""
        result, sentinel, _kwargs, _cfg = self._run()
        self.assertIs( result, sentinel )


class LoadSttModelTest( unittest.IsolatedAsyncioTestCase ):
    """`load_stt_model` — builds the speech-to-text pipeline at boot."""

    async def _run( self, *, cuda ):
        fake_torch = mock.MagicMock()
        fake_torch.cuda.is_available.return_value = cuda
        fake_torch.float16 = "FP16"
        fake_torch.float32 = "FP32"

        fake_cfg = mock.MagicMock()
        fake_cfg.get.side_effect = lambda key, default=None: {
            "stt device id" : "cuda:3",
            "stt model id"  : "openai/whisper-large-v3",
        }.get( key, default )

        with mock.patch.object( main, "torch", fake_torch ), \
             mock.patch.object( main, "config_mgr", fake_cfg, create=True ), \
             mock.patch.object( main, "pipeline", return_value="PIPE" ) as built:
            returned = await main.load_stt_model()

        return returned, built.call_args

    async def test_a_gpu_box_builds_the_pipeline_in_half_precision( self ):
        returned, call = await self._run( cuda=True )

        self.assertEqual( returned, "PIPE" )
        self.assertEqual( call.args[ 0 ],           "automatic-speech-recognition" )
        self.assertEqual( call.kwargs[ "model" ],   "openai/whisper-large-v3" )
        self.assertEqual( call.kwargs[ "device" ],  "cuda:3" )
        self.assertEqual( call.kwargs[ "torch_dtype" ], "FP16" )

    async def test_a_cpu_box_builds_it_in_full_precision_instead( self ):
        """
        Half precision on CPU is not merely slower — torch refuses some ops outright. The
        dtype choice is the only branch in this function, so it is the only thing here that
        can be wrong.
        """
        _returned, call = await self._run( cuda=False )
        self.assertEqual( call.kwargs[ "torch_dtype" ], "FP32" )
