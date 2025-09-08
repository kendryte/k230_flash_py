# progress.py
import sys


def progress_callback(current, total):
    percent = (current / total * 100) if total else 0
    sys.stdout.write(f"\rProgress: {percent:.2f}% ({current}/{total})")
    sys.stdout.flush()
    if current >= total:
        print()

