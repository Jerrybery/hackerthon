#!/usr/bin/env python3
"""macOS wrapper for the official tools/motor_diag.py (socketcan-only).

Opens the HHS USB-CANFD adapter via a1z_mac.open_bus() (gs_usb userspace),
wraps it in EchoFilterBus, monkey-patches can.interface.Bus so the stock
motor_diag script uses it, and stubs out the Linux `ip`-based interface
checks. All CLI args are forwarded unchanged, e.g.:

    python a1z/motor_diag_mac.py --scan
    python a1z/motor_diag_mac.py --listen --duration 5
    python a1z/motor_diag_mac.py --probe 3
"""

import importlib.util
import sys
from pathlib import Path

import can

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import a1z_mac  # noqa: E402

MOTOR_DIAG = HERE / "GALAXEA-A1Z" / "tools" / "motor_diag.py"


def main() -> None:
    bus = a1z_mac.EchoFilterBus(a1z_mac.open_bus(), channel="gs_usb0")

    spec = importlib.util.spec_from_file_location("motor_diag", MOTOR_DIAG)
    motor_diag = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(motor_diag)

    # Route the stock script's can.interface.Bus(...) to our gs_usb bus.
    can.interface.Bus = lambda **kw: bus
    # Skip Linux socketcan checks (gs_usb userspace adapter has no `ip link`).
    motor_diag.check_can_interface = lambda channel: (True, "gs_usb 用户态适配器 (HHS USB-CANFD)")
    motor_diag.check_can_errors = lambda channel: None

    motor_diag.main()


if __name__ == "__main__":
    main()
