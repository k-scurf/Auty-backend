"""Shim — run scripts/build_db.py"""
import runpy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
runpy.run_path(str(Path(__file__).parent / "scripts" / "build_db.py"), run_name="__main__")
