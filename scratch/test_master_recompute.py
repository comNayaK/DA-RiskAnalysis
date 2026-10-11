import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scratch.regenerate_grid import generate_headline_and_gate7

if __name__ == "__main__":
    generate_headline_and_gate7()
