#!/usr/bin/env bash
# Gas Saver launcher for Linux/macOS (works when called through a symlink)
cd "$(dirname "$(readlink -f "$0")")" || exit 1
exec python3 gas_monitor.py "$@"
