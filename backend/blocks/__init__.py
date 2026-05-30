"""Importing this package registers every block into engine.registry.REGISTRY.

The submodules are imported for their @register side effects. Import this
package (``import blocks``) once at startup before serving /api/blocks or
running a graph.
"""
from . import coc_blocks      # noqa: F401
from . import vision_blocks   # noqa: F401
from . import input_blocks    # noqa: F401
from . import ocr_blocks      # noqa: F401
from . import control_blocks  # noqa: F401
