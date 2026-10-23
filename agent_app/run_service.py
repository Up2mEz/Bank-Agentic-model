"""Start the evidence worker/API from a source checkout."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from merchant_sandbox.review_api import main  # noqa: E402

if __name__ == "__main__":
    main()
