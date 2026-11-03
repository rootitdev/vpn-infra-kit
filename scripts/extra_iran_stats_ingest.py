#!/usr/bin/env python3
"""Extra Iran node N: pull its Xray stats into the panel DB (user usage adds up across nodes).

Usage (systemd): EXTRA_IRAN_IP=1.2.3.4 EXTRA_IRAN_NAME=iran2 extra_iran_stats_ingest.py
Shares the primary lock (non-blocking: a skipped run is caught up by the next delta).
"""
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import iran_stats_ingest as m  # noqa: E402
m.IRAN = "root@" + os.environ["EXTRA_IRAN_IP"]
m.SNAP = Path(f"/var/lib/pasarguard/{os.environ.get('EXTRA_IRAN_NAME', 'iran2')}-stats-snapshot.json")
if __name__ == "__main__":
    m.main()
