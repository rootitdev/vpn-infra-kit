#!/usr/bin/env python3
"""Extra Iran node N: publish the SAME desired state as the primary Iran node.

Usage (systemd): EXTRA_IRAN_IP=1.2.3.4 EXTRA_IRAN_NAME=iran2 extra_iran_sync_export.py
Shares the primary lock, so builds are serialized. Panel/core/users unchanged.
"""
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import iran_sync_export as m  # noqa: E402
m.IRAN = "root@" + os.environ["EXTRA_IRAN_IP"]
m.LOCAL_DIR = Path(f"/var/lib/pasarguard/{os.environ.get('EXTRA_IRAN_NAME', 'iran2')}-sync")
if __name__ == "__main__":
    m.main()
