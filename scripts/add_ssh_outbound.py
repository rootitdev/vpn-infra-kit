#!/usr/bin/env python3
"""Run ON EXIT: add TO-AMS-SSH (socks -> Iran-local haproxy 127.0.0.1:18300) to the panel core, then publish."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from vpn_path_lib import get_core, load_env, publish, put_core  # noqa: E402

env = load_env()
c = get_core(env)
obs = c["config"]["outbounds"]
if not any(o.get("tag") == "TO-AMS-SSH" for o in obs):
    tags = [o.get("tag") for o in obs]
    obs.insert(tags.index("DIRECT") if "DIRECT" in tags else len(obs),
               {"tag": "TO-AMS-SSH", "protocol": "socks",
                "settings": {"servers": [{"address": "127.0.0.1", "port": 18300}]}})
    put_core(env, c)
    print("added TO-AMS-SSH")
publish()
