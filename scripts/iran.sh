#!/bin/bash
# Key-only SSH to Iran relay. No passwords.
exec ssh -o BatchMode=yes -o ConnectTimeout=20 -o StrictHostKeyChecking=yes root@${IRAN_IP} "$@"
