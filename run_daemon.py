"""Entry point for the scheduled task: run the daemon in-process (no PYTHONPATH
needed) so the Task Scheduler can track and restart it directly."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from claude_deck.app import main

if __name__ == "__main__":
    main()
