"""Pytest configuration — adds project root to sys.path for imports."""
import sys
from pathlib import Path

# Allow `from src.xxx import ...` in tests without sys.path hacks
sys.path.insert(0, str(Path(__file__).parent.parent))
