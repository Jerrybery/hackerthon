"""Motor scan test: enable each of the 6 A1Z motors, read one feedback frame, disable.

Safe: motors stay at zero torque; no motion commanded.

Usage:
    A1Z_WS=/path/to/workspace python scan_motors.py
    python scan_motors.py --workspace /path/to/workspace

The workspace must contain:
  - GALAXEA-A1Z/  (the SDK repo)
  - .venv/        (venv with a1z + pyusb + gs-usb installed)
"""

import argparse
import os
import sys
from pathlib import Path

SKILL_SCRIPTS = Path(__file__).resolve().parent


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--workspace",
        default=os.environ.get("A1Z_WS", ""),
        help="A1Z workspace dir (or set A1Z_WS)",
    )
    args = parser.parse_args()
    if not args.workspace:
        parser.error("workspace required: --workspace DIR or A1Z_WS env")

    ws = Path(args.workspace).expanduser().resolve()
    sdk = ws / "GALAXEA-A1Z"
    if not sdk.is_dir():
        parser.error(f"SDK repo not found at {sdk}")

    sys.path.insert(0, str(SKILL_SCRIPTS))
    sys.path.insert(0, str(sdk))
    sys.path.insert(0, str(sdk / "tools"))

    from a1z_mac import open_bus
    import motor_diag  # Galaxea SDK tool

    bus = open_bus()
    try:
        results = motor_diag.run_scan(bus, [0, 1, 2, 3, 4, 5])
    finally:
        bus.shutdown()

    ok = True
    for s in results:
        if s.online:
            print(
                f"joint{s.joint_idx + 1} id={hex(s.can_id)} ONLINE "
                f"pos={s.position:.3f}rad vel={s.velocity:.2f} "
                f"temp={s.temp_motor}C rtt={s.response_time_ms:.1f}ms"
            )
        else:
            print(f"joint{s.joint_idx + 1} id={hex(s.can_id)} OFFLINE ({s.error_msg})")
            ok = False
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
