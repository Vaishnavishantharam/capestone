import sys
from pathlib import Path

# Make `core/` importable in tests without installing a package.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

