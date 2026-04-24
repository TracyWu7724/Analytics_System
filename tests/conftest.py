"""Root conftest — add backend/ to sys.path so tests can import services.*"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
