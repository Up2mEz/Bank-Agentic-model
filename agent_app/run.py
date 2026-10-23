"""Start the staff application from this checkout; pass --help for options."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from merchant_sandbox.server import main  # noqa: E402

if __name__ == "__main__":
    main()
