"""promodeler: code-first, deterministic 3D asset generation.

The ``core`` package is pure Python and never imports ``bpy``.
The ``kernel`` package runs inside a headless Blender process.
"""

__version__ = "0.0.1"

# Version of the kernel's compilation behavior. Bump whenever the mapping
# from recipe to geometry, materials, render or export changes, because it
# participates in the build cache key.
KERNEL_VERSION = 13
