# simcore/tools/builtins/__init__.py
"""
This module automatically imports all tools inside the simcore/tools/builtins/ subdirectory.
"""

import importlib
import os
import pathlib

# Automatically import all tool modules inside builtins/
_builtin_tools_dir = pathlib.Path(__file__).parent

for path in _builtin_tools_dir.glob("*.py"):
    if path.name == "__init__.py":
        continue  # skip __init__.py itself
    module_name = f"simcore.tools.builtins.{path.stem}"
    importlib.import_module(module_name)