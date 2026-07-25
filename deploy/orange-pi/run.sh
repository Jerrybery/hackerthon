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
#
# A1Z_MIN_FREQ_HZ: the arm watchdog estops when the control loop drops
# below this for 6 s. On the Orange Pi 3B the CAN round-trip keeps the
# loop at ~52-75 Hz (varies with USB/NPU load) even on dedicated cores,
# so the 80 Hz default false-triggers and 60 proved marginal (measured
# 51.8-59.7 Hz steady on 2026-07-25 -> estop). 50 left only ~2 Hz of
# margin above the steady floor, and gamepad teleop at 25 Hz (FK+IK in
# the same worker process) repeatedly pushed the loop under it (measured
# 45.7 -> 29.1 Hz -> estop on 2026-07-25). 40 doubles the margin while
# still catching a genuinely stalled loop, which collapses to near zero.
set -euo pipefail
cd "$(dirname "$0")/a1z"
PYTEST_VERSION=1 DIMOS_TRANSPORT=lcm \
LISTEN_HOST="${LISTEN_HOST:-127.0.0.1}" \
MCP_PORT="${MCP_PORT:-9990}" \
A1Z_MIN_FREQ_HZ="${A1Z_MIN_FREQ_HZ:-40}" \
  ../.venv/bin/python a1z_mcp_server.py
