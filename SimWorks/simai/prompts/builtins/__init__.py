"""
Dynamically imports all Python modules in this directory (excluding __init__.py).
Triggers decorator-based registration (e.g., for tools or prompt modifiers).
"""

import importlib
import pathlib

current_dir = pathlib.Path(__file__).parent

for path in current_dir.glob("*.py"):
    if path.name == "__init__.py":
        continue
    module_name = f"{__name__}.{path.stem}"
    importlib.import_module(module_name)