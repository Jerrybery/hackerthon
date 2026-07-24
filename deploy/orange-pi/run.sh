#!/usr/bin/env bash
# Start the A1Z DimOS MCP server (default http://127.0.0.1:9990/mcp).
#
# Env overrides:
#   LISTEN_HOST   bind address (default 127.0.0.1; use 0.0.0.0 to expose
#                 the MCP on the LAN for remote nanobot/agent clients)
#   MCP_PORT      listen port (default 9990)
#
# PYTEST_VERSION=1 skips the LCM system configurator (it would demand sudo
# to add a multicast route / tune socket buffers). Single-process
# ModuleCoordinator works without the route; add it via sudo later if
# cross-process LCM is needed:
#   sudo ip route add 224.0.0.0/4 dev lo
set -euo pipefail
cd "$(dirname "$0")/a1z"
PYTEST_VERSION=1 DIMOS_TRANSPORT=lcm \
LISTEN_HOST="${LISTEN_HOST:-127.0.0.1}" \
MCP_PORT="${MCP_PORT:-9990}" \
  ../.venv/bin/python a1z_mcp_server.py
