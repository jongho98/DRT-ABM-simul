"""Run a configured single-zone simulation and generate reviewable results."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from drt_abm.runner import main

if __name__ == "__main__":
    main(ROOT)
