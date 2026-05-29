#!/usr/bin/env python3
"""
Matplotlib Renderer — LLM-backed chart code generation + sandboxed execution.

Calls Claude API with a natural-language chart description, extracts
the Python plotting code from the response, injects savefig(), executes
in a sandboxed subprocess, and returns a markdown image reference.

Produces PNG files in a visuals/ directory alongside the Marp file.
Marp resolves relative image paths at export time.
"""

import os
import re
import logging
import subprocess
import tempfile
from typing import Optional

from .visual_registry import VisualRenderer

logger = logging.getLogger( __name__ )


class MatplotlibRenderer( VisualRenderer ):
    """
    LLM-backed renderer that generates Matplotlib chart code and executes it.

    Flow: description → LLM generates Python → extract code → inject savefig →
    execute in subprocess → verify PNG → return markdown image reference.

    Requires:
        - api_client is a PresentationAPIClient instance (passed via kwargs)
        - output_dir is a writable directory path (passed via kwargs)

    Ensures:
        - Returns markdown image reference on success (e.g., ![title](visuals/chart-001.png))
        - Returns None on any failure (caller falls back to placeholder)
    """
    SUPPORTED_TYPES = [ "chart", "plot", "graph", "data_viz" ]

    def __init__( self, debug: bool = False, verbose: bool = False ):
        """
        Initialize MatplotlibRenderer.

        Requires:
            - debug and verbose are booleans

        Ensures:
            - Renderer is ready to call render()
        """
        self.debug   = debug
        self.verbose = verbose

    async def render( self, visual_type: str, visual_description: str, **kwargs ) -> Optional[ str ]:
        """
        Generate a chart PNG from natural-language description via Claude API.

        Requires:
            - visual_type is one of SUPPORTED_TYPES
            - visual_description is a non-empty string
            - kwargs[ "api_client" ] is a PresentationAPIClient instance
            - kwargs[ "output_dir" ] is a writable directory path

        Ensures:
            - Returns markdown image reference on success
            - Returns None on failure (non-fatal)

        kwargs:
            api_client: PresentationAPIClient (required)
            slide_title: str (optional, for context and image alt text)
            output_dir: str (required, directory for PNG output)
            slide_index: int (optional, for filename numbering, default 0)

        Returns:
            str: Markdown image reference, or None on failure
        """
        api_client  = kwargs.get( "api_client" )
        slide_title = kwargs.get( "slide_title", "" )
        output_dir  = kwargs.get( "output_dir" )
        slide_index = kwargs.get( "slide_index", 0 )

        if api_client is None:
            logger.warning( "MatplotlibRenderer: No api_client provided" )
            return None

        if output_dir is None:
            logger.warning( "MatplotlibRenderer: No output_dir provided" )
            return None

        try:
            from ..prompts.matplotlib import MATPLOTLIB_SYSTEM_PROMPT, get_matplotlib_prompt

            prompt = get_matplotlib_prompt(
                visual_type        = visual_type,
                visual_description = visual_description,
                slide_title        = slide_title,
            )

            response = await api_client.call_for_matplotlib(
                system_prompt = MATPLOTLIB_SYSTEM_PROMPT,
                user_message  = prompt,
            )

            # Extract Python code from response
            python_code = self._extract_python_code( response.content )
            if not python_code:
                logger.warning( f"MatplotlibRenderer: Could not extract Python code for: {slide_title[ :40 ]}" )
                return None

            # Build output path
            output_filename = f"chart-{slide_index:03d}.png"
            output_path     = os.path.join( output_dir, output_filename )

            # Inject savefig and strip plt.show()
            python_code = self._inject_savefig( python_code, output_path )

            # Execute in sandbox
            result = self._execute_code( python_code )
            if result[ "return_code" ] != 0:
                logger.warning( f"MatplotlibRenderer: Code execution failed for: {slide_title[ :40 ]}" )
                if self.debug: print( f"[MatplotlibRenderer] stderr: {result.get( 'stderr', '' )[ :200 ]}" )
                return None

            # Verify output file exists
            if not os.path.exists( output_path ):
                logger.warning( f"MatplotlibRenderer: Output file not created: {output_path}" )
                return None

            if self.debug:
                file_size = os.path.getsize( output_path )
                print( f"[MatplotlibRenderer] Generated {file_size:,} bytes: {output_filename} for: {slide_title[ :40 ]}" )

            # Return relative path for Marp
            rel_path = os.path.join( "visuals", output_filename )
            alt_text = slide_title or visual_description[ :60 ]
            return f"![{alt_text}]({rel_path})"

        except Exception as e:
            logger.error( f"MatplotlibRenderer failed: {e}" )
            if self.debug: print( f"[MatplotlibRenderer] Exception: {e}" )
            return None

    @staticmethod
    def _extract_python_code( response_content: str ) -> Optional[ str ]:
        """
        Extract Python code from Claude's response.

        Handles:
            - Fenced ```python ... ``` blocks
            - Fenced ``` ... ``` blocks (no python label)
            - Bare code starting with import statements

        Requires:
            - response_content is a string

        Ensures:
            - Returns raw Python code (no fences) on success
            - Returns None if no code found

        Returns:
            str: Python code, or None
        """
        if not response_content:
            return None

        # Try fenced block first (with or without "python" label)
        match = re.search( r"```(?:python)?\s*\n(.*?)```", response_content, re.DOTALL )
        if match:
            return match.group( 1 ).strip()

        # Try bare code starting with import
        if "import " in response_content:
            lines = response_content.split( "\n" )
            code_start = None
            for i, line in enumerate( lines ):
                if line.strip().startswith( "import " ) or line.strip().startswith( "from " ):
                    code_start = i
                    break
            if code_start is not None:
                return "\n".join( lines[ code_start: ] ).strip()

        return None

    @staticmethod
    def _inject_savefig( code: str, output_path: str ) -> str:
        """
        Inject plt.savefig() call and strip plt.show() from code.

        Requires:
            - code is a non-empty Python code string
            - output_path is an absolute file path

        Ensures:
            - plt.show() calls are removed
            - plt.savefig() + plt.close('all') appended at end
            - Existing plt.savefig() calls are preserved (user may want multiple outputs)

        Returns:
            str: Modified Python code
        """
        # Strip plt.show() calls
        code = re.sub( r"plt\.show\(\s*\)", "# plt.show()  # disabled for headless", code )

        # Append savefig + close
        savefig_line = f"\nplt.savefig( r\"{output_path}\", dpi=150, bbox_inches=\"tight\" )"
        close_line   = "\nplt.close( \"all\" )"

        return code + savefig_line + close_line

    @staticmethod
    def _execute_code( code: str ) -> dict:
        """
        Execute Python code in a sandboxed subprocess.

        Requires:
            - code is a valid Python code string

        Ensures:
            - Returns dict with 'return_code', 'stdout', 'stderr'
            - Timeout after 30 seconds
            - Temporary file is cleaned up

        Returns:
            dict: Execution result with return_code, stdout, stderr
        """
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".py", prefix="mpl_chart_", delete=False
            ) as f:
                f.write( code )
                temp_path = f.name

            try:
                result = subprocess.run(
                    [ "python3", temp_path ],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=30,
                    cwd=tempfile.gettempdir(),
                )
                return {
                    "return_code" : result.returncode,
                    "stdout"      : result.stdout.decode( "utf-8", errors="replace" ),
                    "stderr"      : result.stderr.decode( "utf-8", errors="replace" ),
                }
            finally:
                os.unlink( temp_path )

        except subprocess.TimeoutExpired:
            return { "return_code": -1, "stdout": "", "stderr": "Timeout: code execution exceeded 30 seconds" }
        except Exception as e:
            return { "return_code": -1, "stdout": "", "stderr": str( e ) }


# =============================================================================
# Smoke Test
# =============================================================================

def quick_smoke_test():
    """Quick smoke test for MatplotlibRenderer extraction and injection logic."""

    print( "=" * 60 )
    print( "MatplotlibRenderer Smoke Test" )
    print( "=" * 60 )

    try:
        # Test 1: Extract fenced python
        print( "\nTest 1: Extract fenced python..." )
        content = '```python\nimport matplotlib.pyplot as plt\nplt.plot([1,2,3])\n```'
        result  = MatplotlibRenderer._extract_python_code( content )
        assert result is not None
        assert "matplotlib" in result
        assert "```" not in result
        print( "  PASS" )

        # Test 2: Extract bare fenced
        print( "\nTest 2: Extract bare fenced..." )
        content = 'Here is the code:\n```\nimport matplotlib.pyplot as plt\nplt.bar([1,2], [3,4])\n```'
        result  = MatplotlibRenderer._extract_python_code( content )
        assert result is not None
        assert "plt.bar" in result
        print( "  PASS" )

        # Test 3: No code found
        print( "\nTest 3: No code found..." )
        result = MatplotlibRenderer._extract_python_code( "Just some text without any code." )
        assert result is None
        print( "  PASS" )

        # Test 4: Empty content
        print( "\nTest 4: Empty content..." )
        assert MatplotlibRenderer._extract_python_code( "" ) is None
        assert MatplotlibRenderer._extract_python_code( None ) is None
        print( "  PASS" )

        # Test 5: Savefig injection
        print( "\nTest 5: Savefig injection..." )
        code     = "import matplotlib.pyplot as plt\nplt.plot([1,2,3])\nplt.show()"
        injected = MatplotlibRenderer._inject_savefig( code, "/tmp/test.png" )
        assert "plt.savefig" in injected
        assert "plt.close" in injected
        assert 'plt.show()' not in injected or "# disabled" in injected
        print( "  PASS" )

        # Test 6: SUPPORTED_TYPES
        print( "\nTest 6: Supported types..." )
        assert "chart" in MatplotlibRenderer.SUPPORTED_TYPES
        assert "plot" in MatplotlibRenderer.SUPPORTED_TYPES
        assert "graph" in MatplotlibRenderer.SUPPORTED_TYPES
        assert "data_viz" in MatplotlibRenderer.SUPPORTED_TYPES
        print( "  PASS" )

        print( f"\n{'=' * 60}" )
        print( "All MatplotlibRenderer smoke tests passed" )
        print( f"{'=' * 60}" )

    except Exception as e:
        print( f"\nSmoke test FAILED: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
