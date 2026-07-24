"""A1Z arm control via DimOS MCP.

Runs a ModuleCoordinator with A1ZArmModule + McpServer so the arm is
controllable through MCP tools (localhost:9990/mcp).

Safety: skills only move at capped speed within joint limits; `estop`
disables motors immediately (arm goes limp). On exit the control loop stops
and motors DISABLE — support the arm first.

Usage (from dimos repo venv, with CAN deps installed):
    DIMOS_TRANSPORT=lcm python a1z_mcp_server.py
"""

import math
import sys
import threading
from pathlib import Path

import numpy as np

SKILL_SCRIPTS = Path.home() / "projects/hackerthon/.claude/skills/dimos-connection-setup-macos/scripts"
sys.path.insert(0, str(SKILL_SCRIPTS))

from a1z_mac import EchoFilterBus, open_bus  # noqa: E402
import a1z.robots.get_robot as gr  # noqa: E402

from dimos.agents.annotation import skill  # noqa: E402
from dimos.agents.mcp.mcp_server import McpServer  # noqa: E402
from dimos.core.coordination.blueprints import autoconnect  # noqa: E402
from dimos.core.coordination.module_coordinator import ModuleCoordinator  # noqa: E402
from dimos.core.core import rpc  # noqa: E402
from dimos.core.module import Module  # noqa: E402

# rad limits from a1z.robots.get_robot._JOINT_LIMITS
JOINT_LIMITS_DEG = [
    (-120.0, 120.0),
    (0.0, 180.0),
    (-180.0, 0.0),
    (-85.0, 85.0),
    (-85.0, 85.0),
    (-115.0, 115.0),
]
MAX_SPEED = 0.5  # rad/s, hard cap for MCP-triggered moves


class A1ZArmModule(Module):
    """Galaxea A1Z position-hold control exposed as MCP skills."""

    _robot = None
    _bus = None
    _lock = threading.Lock()

    @rpc
    def start(self) -> None:
        super().start()
        import os

        print(f"[a1z] start() in pid={os.getpid()}", flush=True)
        self._bus = EchoFilterBus(open_bus())
        gr.can.interface.Bus = lambda **kw: self._bus
        self._robot = gr.get_a1z_robot(
            gravity_comp_factor=1.0,
            zero_gravity_mode=False,
            control_freq_hz=250,
        )
        self._robot.start()  # locks current pose immediately

    @rpc
    def stop(self) -> None:
        with self._lock:
            if self._robot is not None:
                self._robot.stop()  # motors DISABLE — arm goes limp
                self._robot = None
            if self._bus is not None:
                self._bus.shutdown()
                self._bus = None
        super().stop()

    @skill
    def get_joint_state(self) -> str:
        """Return current joint positions (deg) and torques (Nm)."""
        import os

        with self._lock:
            if self._robot is None:
                return f"ERROR: arm not running (pid={os.getpid()}, robot={self._robot})"
            state = self._robot.get_joint_state()
        pos = [round(math.degrees(p), 2) for p in state["pos"]]
        eff = [round(float(e), 2) for e in state["eff"]]
        return f"pos(deg)={pos} eff(Nm)={eff}"

    @skill
    def move_to_pose(self, joints_deg: list[float], speed: float = 0.3) -> str:
        """Move all 6 joints to the given degrees and hold there.

        joints_deg: 6 joint angles in degrees, each within joint limits
        (j1 ±120, j2 0..180, j3 -180..0, j4/j5 ±85, j6 ±115).
        speed: max joint speed rad/s, capped at 0.5.
        """
        if len(joints_deg) != 6:
            return "ERROR: need exactly 6 joint angles"
        for i, (deg, (lo, hi)) in enumerate(zip(joints_deg, JOINT_LIMITS_DEG)):
            if not lo <= deg <= hi:
                return f"ERROR: joint{i + 1}={deg}° outside limits [{lo}, {hi}]"
        speed = min(max(speed, 0.05), MAX_SPEED)
        with self._lock:
            if self._robot is None:
                return "ERROR: arm not running (estopped or not started)"
            robot = self._robot
        target = np.deg2rad(np.array(joints_deg, dtype=float))
        robot.move_joints(target, speed=speed)
        return f"reached {joints_deg} deg"

    @skill
    def estop(self) -> str:
        """Emergency stop: disable all motors immediately. ARM GOES LIMP."""
        with self._lock:
            if self._robot is not None:
                self._robot.stop()
                self._robot = None
        return "estopped: motors disabled, arm is limp"


a1z_mcp = autoconnect(
    A1ZArmModule.blueprint(),
    McpServer.blueprint(),
)

if __name__ == "__main__":
    ModuleCoordinator.build(a1z_mcp).loop()
