#!/usr/bin/env bash
# One-shot setup for the A1Z DimOS MCP server on Orange Pi (aarch64, py3.10).
# Expects this layout (rsynced from the workstation):
#   ~/dimos-mcp/
#     dimos/            <- dimos repo subset (pyproject.toml + dimos/ package)
#     a1z/              <- arm server scripts + GALAXEA-A1Z SDK + calibration yamls
#     requirements-pi.txt
#     setup.sh  run.sh
set -euo pipefail
cd "$(dirname "$0")"

python3 -m venv .venv
./.venv/bin/pip install -U pip

# Editable installs without pulling the full (heavy) dependency lists.
./.venv/bin/pip install --no-deps -e dimos
./.venv/bin/pip install --no-deps -e a1z/GALAXEA-A1Z

./.venv/bin/pip install -r requirements-pi.txt

# Smoke test: module import must succeed without arm hardware attached
# (A1ZArmModule only opens the CAN bus when the coordinator starts).
cd a1z
../.venv/bin/python -c "import a1z_mcp_server; print('[setup] import OK')"
echo "[setup] done. Start with: ./run.sh"
