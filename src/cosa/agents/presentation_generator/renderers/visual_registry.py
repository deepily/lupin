#!/usr/bin/env python3
"""
Visual Renderer Protocol and Registry for Presentation Generator.

Defines the abstract renderer interface and a registry that dispatches
visual_type strings to the appropriate renderer implementation.

Design: Renderers return inline Marp-compatible markdown content
(e.g., Mermaid code blocks, tables), NOT file paths. Marp handles
final rendering at export time.
"""

from abc import ABC, abstractmethod
from typing import ClassVar, List, Optional


# =============================================================================
# Abstract Base Class
# =============================================================================

class VisualRenderer( ABC ):
    """
    Abstract base class for visual renderers.

    Each renderer handles one or more visual_type values and produces
    inline Marp-compatible markdown content.

    Requires:
        - visual_description is a non-empty string

    Ensures:
        - Returns inline markdown content (Mermaid block, table, etc.)
        - Returns None on rendering failure (graceful degradation)
    """
    SUPPORTED_TYPES: ClassVar[ List[ str ] ] = []

    @abstractmethod
    async def render( self, visual_type: str, visual_description: str, **kwargs ) -> Optional[ str ]:
        """
        Generate inline markdown content from a visual description.

        Requires:
            - visual_type is a non-empty string
            - visual_description is a non-empty string

        Ensures:
            - Returns Marp-compatible markdown string on success
            - Returns None on failure (caller should fall back to placeholder)

        Returns:
            str: Inline markdown content, or None on failure
        """
        ...


# =============================================================================
# Registry
# =============================================================================

class VisualRendererRegistry:
    """
    Registry mapping visual_type strings to VisualRenderer instances.

    Requires:
        - fallback is a VisualRenderer that handles any type

    Ensures:
        - get() always returns a renderer (never None)
        - Unknown types route to fallback renderer
    """

    def __init__( self, fallback: VisualRenderer, debug: bool = False ):
        """
        Initialize registry with a fallback renderer.

        Requires:
            - fallback is a VisualRenderer instance

        Ensures:
            - Registry is empty (no types registered)
            - Fallback is set for unregistered types
        """
        self._registry = {}
        self._fallback = fallback
        self.debug     = debug

    def register( self, renderer: VisualRenderer ) -> None:
        """
        Register a renderer for all its SUPPORTED_TYPES.

        Requires:
            - renderer is a VisualRenderer instance with SUPPORTED_TYPES

        Ensures:
            - Each type in SUPPORTED_TYPES maps to this renderer
        """
        for visual_type in renderer.SUPPORTED_TYPES:
            self._registry[ visual_type ] = renderer
            if self.debug: print( f"[Registry] Registered: {visual_type} -> {renderer.__class__.__name__}" )

    def get( self, visual_type: str ) -> VisualRenderer:
        """
        Get renderer for a visual type, falling back to placeholder.

        Requires:
            - visual_type is a string

        Ensures:
            - Returns a VisualRenderer (never None)
            - Unknown types return the fallback renderer

        Returns:
            VisualRenderer: The appropriate renderer
        """
        renderer = self._registry.get( visual_type, self._fallback )
        if self.debug and visual_type not in self._registry:
            print( f"[Registry] Fallback for: {visual_type}" )
        return renderer

    @property
    def registered_types( self ) -> list:
        """List all registered visual types."""
        return list( self._registry.keys() )


# =============================================================================
# Smoke Test
# =============================================================================

def quick_smoke_test():
    """Quick smoke test for VisualRenderer protocol and registry."""
    import asyncio

    print( "=" * 60 )
    print( "VisualRenderer + Registry Smoke Test" )
    print( "=" * 60 )

    try:
        # Test 1: ABC cannot be instantiated
        print( "\nTest 1: ABC cannot be instantiated..." )
        try:
            VisualRenderer()
            assert False, "Should have raised TypeError"
        except TypeError:
            pass
        print( "  PASS" )

        # Test 2: Concrete subclass
        print( "\nTest 2: Concrete subclass..." )

        class MockRenderer( VisualRenderer ):
            SUPPORTED_TYPES = [ "mock_type" ]
            async def render( self, visual_type, visual_description, **kwargs ):
                return f"MOCK: {visual_description}"

        mock = MockRenderer()
        result = asyncio.run( mock.render( "mock_type", "test description" ) )
        assert result == "MOCK: test description"
        print( "  PASS" )

        # Test 3: Registry dispatch
        print( "\nTest 3: Registry dispatch..." )

        class FallbackRenderer( VisualRenderer ):
            SUPPORTED_TYPES = []
            async def render( self, visual_type, visual_description, **kwargs ):
                return f"FALLBACK: {visual_type}"

        registry = VisualRendererRegistry( fallback=FallbackRenderer(), debug=True )
        registry.register( mock )

        assert registry.get( "mock_type" ) is mock
        assert isinstance( registry.get( "unknown_type" ), FallbackRenderer )
        assert registry.registered_types == [ "mock_type" ]
        print( "  PASS" )

        print( f"\n{'=' * 60}" )
        print( "All VisualRenderer smoke tests passed" )
        print( f"{'=' * 60}" )

    except Exception as e:
        print( f"\nSmoke test FAILED: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
