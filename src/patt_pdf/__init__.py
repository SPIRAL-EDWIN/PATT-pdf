"""PATT-PDF — Position-Aware Translation Toolkit for PDF.

Replaces English text in PDF pages with Chinese at the original position while
leaving numbers, figures, backgrounds and graphics untouched. This is a layout
workflow around existing machine-translation services; it is not a translation model.
"""
__version__ = "0.3.9.dev0"

# Bump when page analysis / rendering behaviour changes: cached page plans and QA
# results carry this tag and are recomputed when it differs.
ENGINE_VERSION = "patt-0.3-e4"
