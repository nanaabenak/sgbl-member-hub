#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
./stop_hub.sh
./start_hub.sh
