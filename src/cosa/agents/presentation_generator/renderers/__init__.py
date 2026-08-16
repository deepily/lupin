#!/usr/bin/env python3
"""Visual and text renderers for Presentation Generator Agent."""

from .marp_text_renderer import MarpTextRenderer
from .pptx_deck_renderer import PptxDeckRenderer
from .visual_registry import VisualRenderer, VisualRendererRegistry
from .mermaid import MermaidRenderer
from .matplotlib_renderer import MatplotlibRenderer
from .d2_renderer import D2Renderer
from .nano_banana import NanoBananaRenderer
from .veo_renderer import VeoRenderer
from .placeholder import PlaceholderRenderer

__all__ = [
    "MarpTextRenderer",
    "PptxDeckRenderer",
    "VisualRenderer",
    "VisualRendererRegistry",
    "MermaidRenderer",
    "MatplotlibRenderer",
    "D2Renderer",
    "NanoBananaRenderer",
    "VeoRenderer",
    "PlaceholderRenderer",
]
