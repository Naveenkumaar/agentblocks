"""Ensure the repo root is importable so `app` and `evals` resolve in tests."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
