import sys
from pathlib import Path

# Determine the base directory for logs
# For packaged apps, this might be in user's app data directory
# For development, it's usually project root
if getattr(sys, "frozen", False):  # Check if running as a bundled executable
    BASE_LOG_DIR = Path(sys.executable).parent
else:
    BASE_LOG_DIR = Path(__file__).parent.parent.parent  # Project root

LOG_FILE_NAME = "k230_flash.log"
FULL_LOG_FILE_PATH = BASE_LOG_DIR / LOG_FILE_NAME
