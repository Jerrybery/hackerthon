#!/usr/bin/env bash
# Deploy the slim A1Z DimOS MCP stack to an Orange Pi and run setup.
# Usage (from the hackerthon repo root on the workstation):
#   deploy/orange-pi/deploy.sh orangepi@10.80.11.57 [more-hosts...]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

for host in "$@"; do
  echo "=== $host: rsync ==="
  ssh -o BatchMode=yes "$host" 'mkdir -p ~/dimos-mcp'
  rsync -az --chmod=Fu+rw,Du+rwx "$ROOT/deploy/orange-pi/" "$host:~/dimos-mcp/"
  rsync -az --exclude='__pycache__' --exclude='*.pyc' \
    "$ROOT/dimos/pyproject.toml" "$ROOT/dimos/README.md" "$ROOT/dimos/MANIFEST.in" \
    "$host:~/dimos-mcp/dimos/"
  rsync -az --exclude='__pycache__' --exclude='*.pyc' --exclude='.git' \
    "$ROOT/dimos/dimos" "$host:~/dimos-mcp/dimos/"
  rsync -az \
    "$ROOT/a1z/a1z_mcp_server.py" "$ROOT/a1z/a1z_mac.py" "$ROOT/a1z/mcp_call.py" \
    "$ROOT/a1z/vision_grasp.py" "$ROOT/a1z/live_view.py" "$ROOT/a1z/grasp_servo.py" \
    "$ROOT/a1z/jog.py" "$ROOT/a1z/hold_neutral.py" "$ROOT/a1z/motions.py" \
    "$host:~/dimos-mcp/a1z/"
  rsync -az \
    "$ROOT/a1z/calibration/camera_intrinsics.yaml" "$ROOT/a1z/calibration/handeye_result.yaml" \
    "$host:~/dimos-mcp/a1z/calibration/"
  rsync -az --exclude='__pycache__' --exclude='*.pyc' --exclude='.git' \
    "$ROOT/a1z/GALAXEA-A1Z" "$host:~/dimos-mcp/a1z/"

  echo "=== $host: setup ==="
  ssh -o BatchMode=yes "$host" 'cd ~/dimos-mcp && bash setup.sh'
done
