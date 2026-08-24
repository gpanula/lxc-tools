"""Allow running the CLI via ``python -m lxc_tools``."""

import sys

from lxc_tools.cli import main

if __name__ == "__main__":
    sys.exit(main())
