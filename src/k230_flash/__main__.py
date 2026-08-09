"""Entry point for `python -m k230_flash`.

Without this the package can only be run as `python -m k230_flash.main`, which
is an easy thing to get wrong and gives an unhelpful "No module named
k230_flash.__main__" when you do.
"""

import sys

from .main import main

if __name__ == "__main__":
    sys.exit(main())
