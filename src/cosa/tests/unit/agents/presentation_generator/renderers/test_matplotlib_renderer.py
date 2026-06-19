#!/usr/bin/env python3
"""
Unit tests for renderers/matplotlib_renderer.py

LLM-backed chart renderer with sandboxed subprocess execution. Boundaries
mocked: api_client (call_for_matplotlib), tempfile.NamedTemporaryFile,
subprocess.run, os.unlink/exists/getsize. No real Python exec / disk.
"""

import asyncio
import subprocess
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from cosa.agents.presentation_generator.renderers import matplotlib_renderer as mpmod
from cosa.agents.presentation_generator.renderers.matplotlib_renderer import MatplotlibRenderer


def _run( coro ):
    return asyncio.run( coro )


def _client( content="```python\nimport matplotlib.pyplot as plt\nplt.plot([1,2])\n```" ):
    client = MagicMock()
    resp = MagicMock()
    resp.content = content
    client.call_for_matplotlib = AsyncMock( return_value=resp )
    return client


class TestExtractPython:
    def test_fenced_labelled( self ):
        out = MatplotlibRenderer._extract_python_code( "```python\nimport x\nplt.plot()\n```" )
        assert "import x" in out and "```" not in out

    def test_fenced_bare( self ):
        out = MatplotlibRenderer._extract_python_code( "code:\n```\nimport y\nplt.bar()\n```" )
        assert "plt.bar" in out

    def test_bare_import_with_from( self ):
        out = MatplotlibRenderer._extract_python_code( "blah\nfrom matplotlib import pyplot\nx=1" )
        assert out.startswith( "from matplotlib" )

    def test_no_match( self ):
        assert MatplotlibRenderer._extract_python_code( "no code here" ) is None

    def test_import_substring_but_no_import_line( self ):
        # "import " appears as a substring but no line STARTS with import/from
        # → loop exhausts without break, code_start stays None → returns None
        assert MatplotlibRenderer._extract_python_code( "please import the data\nx = 1" ) is None

    def test_empty_and_none( self ):
        assert MatplotlibRenderer._extract_python_code( "" ) is None
        assert MatplotlibRenderer._extract_python_code( None ) is None


class TestInjectSavefig:
    def test_strips_show_and_appends( self ):
        code = "import matplotlib.pyplot as plt\nplt.plot([1])\nplt.show()"
        out = MatplotlibRenderer._inject_savefig( code, "/tmp/out.png" )
        assert "plt.savefig" in out
        assert "plt.close" in out
        assert "# disabled for headless" in out
        assert "/tmp/out.png" in out


class TestExecuteCode:
    def _tmp_cm( self, name="/tmp/mpl_x.py" ):
        fake_f = MagicMock()
        fake_f.name = name
        cm = MagicMock()
        cm.__enter__.return_value = fake_f
        cm.__exit__.return_value = False
        return cm

    def test_success_unlinks( self ):
        run_result = MagicMock( returncode=0, stdout=b"out", stderr=b"err" )
        with patch.object( mpmod.tempfile, "NamedTemporaryFile", return_value=self._tmp_cm() ), \
             patch.object( mpmod.subprocess, "run", return_value=run_result ), \
             patch( "os.unlink" ) as unlink:
            res = MatplotlibRenderer._execute_code( "code" )
        assert res[ "return_code" ] == 0
        assert res[ "stdout" ] == "out"
        assert res[ "stderr" ] == "err"
        unlink.assert_called_once_with( "/tmp/mpl_x.py" )

    def test_timeout( self ):
        with patch.object( mpmod.tempfile, "NamedTemporaryFile", return_value=self._tmp_cm() ), \
             patch.object( mpmod.subprocess, "run", side_effect=subprocess.TimeoutExpired( cmd="python3", timeout=30 ) ), \
             patch( "os.unlink" ):
            res = MatplotlibRenderer._execute_code( "code" )
        assert res[ "return_code" ] == -1
        assert "Timeout" in res[ "stderr" ]

    def test_generic_exception( self ):
        with patch.object( mpmod.tempfile, "NamedTemporaryFile", side_effect=OSError( "no temp" ) ):
            res = MatplotlibRenderer._execute_code( "code" )
        assert res[ "return_code" ] == -1
        assert "no temp" in res[ "stderr" ]


class TestRender:
    def test_no_api_client( self ):
        assert _run( MatplotlibRenderer().render( "chart", "x", output_dir="/o" ) ) is None

    def test_no_output_dir( self ):
        assert _run( MatplotlibRenderer().render( "chart", "x", api_client=_client() ) ) is None

    def test_extract_fails( self ):
        out = _run( MatplotlibRenderer().render( "chart", "x", api_client=_client( content="no code" ), output_dir="/o" ) )
        assert out is None

    def test_exec_failure_debug( self, capsys ):
        r = MatplotlibRenderer( debug=True )
        with patch.object( MatplotlibRenderer, "_execute_code",
                           return_value={ "return_code": 1, "stderr": "traceback here" } ):
            out = _run( r.render( "chart", "x", api_client=_client(), output_dir="/o", slide_title="T" ) )
        assert out is None
        assert "[MatplotlibRenderer] stderr" in capsys.readouterr().out

    def test_output_file_missing( self ):
        r = MatplotlibRenderer()
        with patch.object( MatplotlibRenderer, "_execute_code", return_value={ "return_code": 0 } ), \
             patch( "os.path.exists", return_value=False ):
            out = _run( r.render( "chart", "x", api_client=_client(), output_dir="/o" ) )
        assert out is None

    def test_success_with_title_debug( self, capsys ):
        r = MatplotlibRenderer( debug=True )
        with patch.object( MatplotlibRenderer, "_execute_code", return_value={ "return_code": 0 } ), \
             patch( "os.path.exists", return_value=True ), \
             patch( "os.path.getsize", return_value=12345 ):
            out = _run( r.render( "chart", "desc", api_client=_client(), output_dir="/o",
                                  slide_title="Sales", slide_index=4 ) )
        assert out == "![Sales](visuals/chart-004.png)"
        assert "[MatplotlibRenderer] Generated" in capsys.readouterr().out

    def test_success_alt_from_description( self ):
        r = MatplotlibRenderer()
        with patch.object( MatplotlibRenderer, "_execute_code", return_value={ "return_code": 0 } ), \
             patch( "os.path.exists", return_value=True ):
            out = _run( r.render( "chart", "a chart of growth metrics", api_client=_client(), output_dir="/o" ) )
        assert out.startswith( "![a chart of growth metrics]" )

    def test_exception_debug( self, capsys ):
        r = MatplotlibRenderer( debug=True )
        client = MagicMock()
        client.call_for_matplotlib = AsyncMock( side_effect=RuntimeError( "api boom" ) )
        out = _run( r.render( "chart", "x", api_client=client, output_dir="/o" ) )
        assert out is None
        assert "[MatplotlibRenderer] Exception" in capsys.readouterr().out

    def test_supported_types( self ):
        assert MatplotlibRenderer.SUPPORTED_TYPES == [ "chart", "plot", "graph", "data_viz" ]


if __name__ == "__main__":
    pytest.main( [ __file__, "-v" ] )
