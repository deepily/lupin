#!/usr/bin/env python3
"""
D2 Renderer — LLM-backed diagram code generation with CLI rendering.

Calls Claude API with a natural-language visual description, extracts
the D2 syntax from the response, renders it to SVG via the d2 CLI,
and returns a markdown image reference.

Handles "flowchart_d2" and "architecture" visual types — producing
significantly prettier output than Mermaid for these use cases.

This is a file-producing renderer: it writes SVG files to an output
directory and returns markdown image references, unlike MermaidRenderer
which returns inline code blocks.
"""

import os
import re
import shutil
import asyncio
import logging
import subprocess
from typing import ClassVar, List, Optional

from .visual_registry import VisualRenderer

logger = logging.getLogger( __name__ )


class D2Renderer( VisualRenderer ):
    """
    LLM-backed renderer that generates D2 diagrams compiled to SVG.

    Calls Claude API with a visual description, extracts D2 syntax,
    renders via d2 CLI to SVG, and returns a markdown image reference.

    Requires:
        - api_client is a PresentationAPIClient instance (passed via kwargs)
        - output_dir is a writable directory path (passed via kwargs)
        - d2 CLI is installed and on PATH

    Ensures:
        - Returns a markdown image reference on success
        - Returns None on failure (caller falls back to placeholder)
    """
    SUPPORTED_TYPES: ClassVar[ List[ str ] ] = [ "flowchart_d2", "architecture" ]

    def __init__( self, debug: bool = False, verbose: bool = False, d2_theme: int = 0 ):
        """
        Initialize D2Renderer.

        Requires:
            - debug and verbose are booleans
            - d2_theme is a valid D2 theme ID (0=default, 100=sketch, etc.)

        Ensures:
            - Renderer is ready to call render()
            - CLI availability check is deferred to first render()
        """
        self.debug         = debug
        self.verbose        = verbose
        self.d2_theme      = d2_theme
        self._d2_available = None  # Lazy cache

    def _check_d2_available( self ) -> bool:
        """
        Check if d2 CLI is installed (cached after first call).

        Ensures:
            - Returns True if d2 is on PATH
            - Caches result for subsequent calls
        """
        if self._d2_available is None:
            self._d2_available = shutil.which( "d2" ) is not None
            if not self._d2_available:
                logger.warning( "D2Renderer: d2 CLI not found on PATH — install from https://d2lang.com" )
            elif self.debug:
                print( f"[D2Renderer] d2 CLI found: {shutil.which( 'd2' )}" )
        return self._d2_available

    async def render( self, visual_type: str, visual_description: str, **kwargs ) -> Optional[ str ]:
        """
        Generate D2 diagram from natural-language description via Claude API.

        Requires:
            - visual_type is "flowchart_d2" or "architecture"
            - visual_description is a non-empty string
            - kwargs[ "api_client" ] is a PresentationAPIClient instance
            - kwargs[ "output_dir" ] is a writable directory path

        Ensures:
            - Returns markdown image reference on success
            - Returns None on failure (non-fatal)

        kwargs:
            api_client: PresentationAPIClient (required)
            slide_title: str (optional, for context)
            output_dir: str (required, directory for SVG output)
            slide_index: int (optional, for unique filenames, default 0)

        Returns:
            str: Markdown image reference, or None on failure
        """
        if not self._check_d2_available():
            return None

        api_client  = kwargs.get( "api_client" )
        slide_title = kwargs.get( "slide_title", "" )
        output_dir  = kwargs.get( "output_dir" )
        slide_index = kwargs.get( "slide_index", 0 )

        if api_client is None:
            logger.warning( "D2Renderer: No api_client provided" )
            return None

        if output_dir is None:
            logger.warning( "D2Renderer: No output_dir provided" )
            return None

        try:
            from ..prompts.d2 import D2_SYSTEM_PROMPT, get_d2_prompt

            prompt = get_d2_prompt(
                visual_type        = visual_type,
                visual_description = visual_description,
                slide_title        = slide_title,
            )

            response = await api_client.call_for_d2(
                system_prompt = D2_SYSTEM_PROMPT,
                user_message  = prompt,
            )

            d2_code = self._extract_d2_code( response.content )
            if not d2_code:
                logger.warning( f"D2Renderer: Could not extract D2 code from response for: {slide_title[ :40 ]}" )
                return None

            # Ensure output directory exists
            os.makedirs( output_dir, exist_ok=True )

            # Render D2 → SVG
            output_filename = f"diagram-{slide_index:03d}.svg"
            output_path     = os.path.join( output_dir, output_filename )
            success         = await self._render_d2( d2_code, output_path, self.d2_theme )

            if not success:
                return None

            if self.debug: print( f"[D2Renderer] Generated SVG for: {slide_title[ :40 ]}" )

            # Return markdown image reference (relative path from Marp file)
            rel_path = os.path.join( "visuals", output_filename )
            return f"![{slide_title or visual_description[ :60 ]}]({rel_path})"

        except Exception as e:
            logger.error( f"D2Renderer failed: {e}" )
            return None

    async def _render_d2( self, d2_code: str, output_path: str, theme: int = 0 ) -> bool:
        """
        Execute d2 CLI to render D2 syntax to SVG.

        Requires:
            - d2_code is valid D2 syntax
            - output_path is a writable file path
            - theme is a valid D2 theme ID

        Ensures:
            - Returns True if SVG file was created
            - Returns False on any error (logged as warning)
        """
        try:
            # Strip remote icon references — terrastruct.com CDN returns 403,
            # causing D2 CLI to fail. Diagrams render fine without icons.
            filtered_lines = [
                line for line in d2_code.splitlines()
                if "icon:" not in line or "icons.terrastruct.com" not in line
            ]
            d2_code = "\n".join( filtered_lines )

            loop   = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: subprocess.run(
                    [ "d2", "--theme", str( theme ), "-", output_path ],
                    input=d2_code,
                    capture_output=True,
                    text=True,
                    timeout=30
                )
            )

            if result.returncode != 0:
                logger.warning( f"D2 CLI failed (rc={result.returncode}): {result.stderr[ :200 ]}" )
                return False

            return os.path.exists( output_path )

        except subprocess.TimeoutExpired:
            logger.warning( "D2 CLI timed out (30s limit)" )
            return False

        except Exception as e:
            logger.warning( f"D2 CLI execution error: {e}" )
            return False

    @staticmethod
    def _extract_d2_code( response_content: str ) -> Optional[ str ]:
        """
        Extract D2 code from Claude's response.

        Handles:
            - Fenced ```d2 ... ``` blocks
            - Fenced ``` ... ``` blocks (no d2 label)
            - Bare code with D2-like patterns (arrows, containers)

        Requires:
            - response_content is a string

        Ensures:
            - Returns raw D2 code (no fences) on success
            - Returns None if no D2 found

        Returns:
            str: Raw D2 code, or None
        """
        if not response_content:
            return None

        # Try fenced block first (with or without "d2" label)
        match = re.search( r"```(?:d2)?\s*\n(.*?)```", response_content, re.DOTALL )
        if match:
            return match.group( 1 ).strip()

        # Try bare D2 — look for arrow patterns or container syntax
        if "->" in response_content or "<->" in response_content:
            # Strip any leading text before the first node definition
            lines = response_content.strip().split( "\n" )
            d2_lines = []
            started  = False
            for line in lines:
                if not started and ( "->" in line or "{" in line or ":" in line ):
                    started = True
                if started:
                    d2_lines.append( line )
            if d2_lines:
                return "\n".join( d2_lines ).strip()

        return None


# =============================================================================
# Smoke Test
# =============================================================================

def quick_smoke_test():
    """Quick smoke test for D2Renderer extraction logic."""

    print( "=" * 60 )
    print( "D2Renderer Smoke Test" )
    print( "=" * 60 )

    try:
        # Test 1: Extract fenced d2
        print( "\nTest 1: Extract fenced d2..." )
        content = '```d2\na -> b -> c\nb -> d\n```'
        result  = D2Renderer._extract_d2_code( content )
        assert result is not None
        assert "a -> b -> c" in result
        assert "```" not in result
        print( "  PASS" )

        # Test 2: Extract bare fenced
        print( "\nTest 2: Extract bare fenced..." )
        content = 'Here is the diagram:\n```\nserver -> database: query\n```'
        result  = D2Renderer._extract_d2_code( content )
        assert result is not None
        assert "server -> database" in result
        print( "  PASS" )

        # Test 3: Extract bare D2 with arrows
        print( "\nTest 3: Extract bare D2..." )
        content = "api_gateway -> auth_service -> database"
        result  = D2Renderer._extract_d2_code( content )
        assert result is not None
        assert "api_gateway" in result
        print( "  PASS" )

        # Test 4: No D2 found
        print( "\nTest 4: No D2 found..." )
        result = D2Renderer._extract_d2_code( "Just some regular text without diagrams." )
        assert result is None
        print( "  PASS" )

        # Test 5: Empty content
        print( "\nTest 5: Empty content..." )
        assert D2Renderer._extract_d2_code( "" ) is None
        assert D2Renderer._extract_d2_code( None ) is None
        print( "  PASS" )

        # Test 6: SUPPORTED_TYPES
        print( "\nTest 6: Supported types..." )
        assert "flowchart_d2" in D2Renderer.SUPPORTED_TYPES
        assert "architecture" in D2Renderer.SUPPORTED_TYPES
        print( "  PASS" )

        print( f"\n{'=' * 60}" )
        print( "All D2Renderer smoke tests passed" )
        print( f"{'=' * 60}" )

    except Exception as e:
        print( f"\nSmoke test FAILED: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
