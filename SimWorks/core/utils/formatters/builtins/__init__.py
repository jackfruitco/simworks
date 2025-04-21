# core/utils/formatter/builtins/__init__.py
import importlib
import pathlib

# Dynamically import all .py files in this directory (except __init__.py)
for path in pathlib.Path(__file__).parent.glob("*.py"):
    if path.stem != "__init__":
        importlib.import_module(f"{__name__}.{path.stem}")