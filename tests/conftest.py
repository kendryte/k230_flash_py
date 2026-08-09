"""Shared pytest setup.

Two things happen here:

1. `src/` goes on sys.path, so the tests import the working tree rather than
   whatever `k230-flash` happens to be pip-installed. Every test file used to do
   its own `sys.path.insert`, which meant a file could silently end up testing
   the installed package instead.
2. The `--hardware` gate. Hardware tests are deselected by default via
   `addopts` in pyproject.toml; passing `--hardware` re-enables them. Without the
   flag they are skipped rather than failing, so `pytest -m hardware` on a
   machine with no board reports "skipped", not a false failure.
"""

import sys
from pathlib import Path

import pytest

TESTS_ROOT = Path(__file__).resolve().parent
SRC = TESTS_ROOT.parent / "src"
for entry in (str(SRC), str(TESTS_ROOT)):
    if entry not in sys.path:
        sys.path.insert(0, entry)


@pytest.fixture(autouse=True)
def _quiet_library_logging():
    """The library logs at DEBUG through loguru. Left on, a failing assertion is
    buried under hundreds of protocol lines, so silence it by default; a test
    that cares about log output can re-add its own sink."""
    from loguru import logger

    logger.remove()
    yield
    logger.remove()


def pytest_addoption(parser):
    parser.addoption(
        "--hardware",
        action="store_true",
        default=False,
        help="run tests that need a real K230 board attached to a board-control rig",
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--hardware"):
        return
    skip = pytest.mark.skip(reason="needs a real K230 board; pass --hardware to run")
    for item in items:
        if "hardware" in item.keywords:
            item.add_marker(skip)
