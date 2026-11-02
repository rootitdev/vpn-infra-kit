#!/bin/bash
# Shared env loader — never echo values
set -a
# shellcheck disable=SC1091
. /root/.vpn-secrets/.env
set +a
