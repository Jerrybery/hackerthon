"""A1Z arm control via DimOS MCP.

Runs a ModuleCoordinator with A1ZArmModule + McpServer so the arm is
controllable through MCP tools (localhost:9990/mcp).

Safety: skills only move at capped speed within joint limits; `shutdown`
ramps stiffness/gravity-comp to zero before disabling motors (graceful),
`estop` disables motors immediately (arm goes limp). On exit the control
loop stops and motors DISABLE — support the arm first.

Usage (from dimos repo venv, with CAN deps installed):
    DIMOS_TRANSPORT=lcm python a1z_mcp_server.py
"""

import math
import sys
import threading
from pathlib import Path

import numpy as np

A1Z_DIR = Path(__file__).parent
SKILL_SCRIPTS = Path.home() / "projects/hackerthon/.claude/skills/dimos-connection-setup-macos/scripts"
sys.path.insert(0, str(A1Z_DIR))
sys.path.insert(0, str(SKILL_SCRIPTS))

from a1z_mac import EchoFilterBus, open_bus  # noqa: E402
import a1z.robots.get_robot as gr  # noqa: E402
import motions  # noqa: E402  pose/sequence definitions for social behaviors

from dimos.agents.annotation import tool  # noqa: E402
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

URDF_PATH = A1Z_DIR / "GALAXEA-A1Z" / "a1z" / "robot_models" / "a1z" / "A1Z_Flange.urdf"
EE_FRAME = "arm_link6"
# TCP = midpoint between gripper fingertips, in arm_link6 frame (from A1Z_G1Z.urdf)
TCP_OFFSET_M = np.array([0.10, 0.0, 0.0])
# workspace guards for MCP Cartesian moves (base frame)
MAX_REACH_M = 0.60
MIN_Z_M = 0.02
MAX_Z_M = 0.60


class _IKSolver:
    """Damped-least-squares IK on the arm_link6 frame (Pinocchio direct).

    More robust than a1z.robots.kinematics.Kinematics.ik: uses the real
    joint limits (URDF j4 limit is tighter than hardware), multiple seeds
    and a rotation-weighted 6D task. Also provides FK.
    """

    def __init__(self, urdf_path: str, ee_frame: str = EE_FRAME):
        import pinocchio as pin

        self._pin = pin
        self._model = pin.buildModelFromUrdf(urdf_path)
        self._data = self._model.createData()
        self._fid = self._model.getFrameId(ee_frame)
        self._lo = np.deg2rad([l for l, _ in JOINT_LIMITS_DEG])
        self._hi = np.deg2rad([h for _, h in JOINT_LIMITS_DEG])

    def fk(self, q: np.ndarray) -> np.ndarray:
        self._pin.forwardKinematics(self._model, self._data, q)
        self._pin.updateFramePlacements(self._model, self._data)
        return self._data.oMf[self._fid].homogeneous.copy()

    def ik(self, T_target: np.ndarray, seeds, w_rot: float = 0.5,
           max_iters: int = 800, dt: float = 0.1, damping: float = 1e-4):
        """Return (pos_err_m, ang_err_deg, q) of the best solution found.

        NOTE: keep this cheap — it runs in the arm worker process, and a
        long solve starves the 250 Hz control loop (the SDK auto-estops
        after 6 s below 80 Hz). Good seeds matter more than iterations.
        """
        pin = self._pin
        tgt = pin.SE3(T_target[:3, :3], T_target[:3, 3])
        best = None
        for q0 in seeds:
            q = np.clip(np.asarray(q0, dtype=float).copy(), self._lo, self._hi)
            for _ in range(max_iters):
                pin.forwardKinematics(self._model, self._data, q)
                pin.updateFramePlacements(self._model, self._data)
                err6 = pin.log6(self._data.oMf[self._fid].actInv(tgt)).vector
                err = err6.copy()
                err[3:] *= w_rot
                if np.linalg.norm(err[:3]) < 1e-4 and np.linalg.norm(err6[3:]) < 1e-3:
                    break
                J = pin.computeFrameJacobian(self._model, self._data, q,
                                             self._fid, pin.LOCAL)
                J[3:] *= w_rot
                dq = J.T @ np.linalg.solve(J @ J.T + damping * np.eye(6), err)
                q = np.clip(pin.integrate(self._model, q, dq * dt), self._lo, self._hi)
            Tc = self._data.oMf[self._fid].homogeneous
            pos_err = float(np.linalg.norm(Tc[:3, 3] - T_target[:3, 3]))
            ang_err = float(np.degrees(np.arccos(np.clip(
                (np.trace(Tc[:3, :3].T @ T_target[:3, :3]) - 1) / 2, -1, 1))))
            score = pos_err + np.radians(ang_err) * 0.05
            if best is None or score < best[0]:
                best = (score, pos_err, ang_err, q.copy())
        _, pos_err, ang_err, q = best
        return pos_err, ang_err, q


class A1ZArmModule(Module):
    """Galaxea A1Z position-hold control exposed as MCP skills."""

    _robot = None
    _bus = None
    _kin = None
    _lock = threading.Lock()

    @rpc
    def start(self) -> None:
        super().start()
        import os

        print(f"[a1z] start() in pid={os.getpid()}", flush=True)
        self._bus = EchoFilterBus(open_bus())
        gr.can.interface.Bus = lambda **kw: self._bus
        # Slow hosts (e.g. Orange Pi) can't sustain 250 Hz: lower the target
        # and the estop floor via env. Defaults keep workstation behavior.
        control_freq = int(os.environ.get("A1Z_CONTROL_FREQ_HZ", "250"))
        min_freq = float(os.environ.get("A1Z_MIN_FREQ_HZ", "80.0"))
        self._robot = gr.get_a1z_robot(
            gravity_comp_factor=1.0,
            zero_gravity_mode=False,
            control_freq_hz=control_freq,
            min_freq_hz=min_freq,
            with_gripper=True,
        )
        self._robot.start()  # locks current pose immediately (gripper homes open)
        self._kin = _IKSolver(str(URDF_PATH), EE_FRAME)

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

    def _get_robot(self):
        with self._lock:
            robot = self._robot
        # If the control loop died (e.g. the low-frequency auto-estop),
        # report the arm as unavailable instead of letting move_joints
        # silently no-op on stale feedback.
        if robot is not None and not robot.is_running:
            return None
        return robot

    @staticmethod
    def _check_limits(joints_deg) -> str | None:
        for i, (deg, (lo, hi)) in enumerate(zip(joints_deg, JOINT_LIMITS_DEG)):
            if not lo <= deg <= hi:
                return f"ERROR: joint{i + 1}={deg:.1f}° outside limits [{lo}, {hi}]"
        return None

    @tool
    def get_joint_state(self) -> str:
        """Return current joint positions (deg) and torques (Nm)."""
        robot = self._get_robot()
        if robot is None:
            return "ERROR: arm not running"
        state = robot.get_joint_state()
        pos = [round(math.degrees(p), 2) for p in state["pos"]]
        eff = [round(float(e), 2) for e in state["eff"]]
        return f"pos(deg)={pos} eff(Nm)={eff}"

    @tool
    def move_to_pose(self, joints_deg: list[float], speed: float = 0.3) -> str:
        """Move all 6 joints to the given degrees and hold there.

        joints_deg: 6 joint angles in degrees, each within joint limits
        (j1 ±120, j2 0..180, j3 -180..0, j4/j5 ±85, j6 ±115).
        speed: max joint speed rad/s, capped at 0.5.
        """
        if len(joints_deg) != 6:
            return "ERROR: need exactly 6 joint angles"
        err = self._check_limits(joints_deg)
        if err:
            return err
        speed = min(max(speed, 0.05), MAX_SPEED)
        robot = self._get_robot()
        if robot is None:
            return "ERROR: arm not running (estopped or not started)"
        target = np.deg2rad(np.array(joints_deg, dtype=float))
        robot.move_joints(target, speed=speed)
        return f"reached {joints_deg} deg"

    def _move_deg(self, robot, pose_deg, speed: float) -> None:
        robot.move_joints(np.deg2rad(np.array(pose_deg, dtype=float)), speed=speed)

    @tool
    def nod_greet(self, speed: float = 0.3) -> str:
        """Greeting gesture: move to the raised alert pose and nod the
        wrist (j4) NOD_TIMES times, ending back at the alert pose.

        Poses come from motions.py (SCAN_POSE_DEG / NOD_DIP_DEG / NOD_TIMES).
        speed: max joint speed rad/s, capped at 0.5.
        """
        robot = self._get_robot()
        if robot is None:
            return "ERROR: arm not running (estopped or not started)"
        speed = min(max(speed, 0.05), MAX_SPEED)
        self._move_deg(robot, motions.SCAN_POSE_DEG, speed)
        for pose in motions.nod_poses():
            self._move_deg(robot, pose, speed)
        return f"greeting done (nodded {motions.NOD_TIMES} times)"

    @tool
    def scan_and_greet(self, speed: float = 0.3) -> str:
        """Find a person and greet them: raise into the alert pose, sweep
        the base (j1) through the yaw stops, and at each stop check the
        wrist-camera face-detection service. When a face is detected at
        the CENTER of the frame, stop sweeping and nod at that spot
        (facing the person). Returns a trigger string for the agent to
        start a conversation. If no centered face is found on the whole
        sweep, returns to facing forward and reports that.

        Requires the face-detection service (face_detect/server.py) to be
        running on this host (FACE_SERVICE_URL, default
        http://127.0.0.1:8095/faces).
        speed: max joint speed rad/s, capped at 0.5.
        """
        import time

        robot = self._get_robot()
        if robot is None:
            return "ERROR: arm not running (estopped or not started)"
        speed = min(max(speed, 0.05), MAX_SPEED)
        self._move_deg(robot, motions.SCAN_POSE_DEG, speed)
        for stop in motions.scan_stops():
            self._move_deg(robot, stop, speed)
            time.sleep(motions.SCAN_DWELL_S)  # let the view settle
            hit = self._centered_face()
            if hit == "DOWN":
                self._move_deg(robot, motions.SCAN_POSE_DEG, speed)
                return ("ERROR: face-detection service unreachable or stale "
                        "(start face_detect/server.py on this host first)")
            if hit is None:
                continue
            # nod facing the person (current yaw), not the forward pose
            for pose in motions.nod_poses(base_pose_deg=stop):
                self._move_deg(robot, pose, speed)
            return (f"human in sight at j1={stop[0]:.0f} deg "
                    f"(face conf {hit['conf']}), start a chat")
        self._move_deg(robot, motions.SCAN_POSE_DEG, speed)  # face forward again
        return "no person found after full sweep, facing forward again"

    @staticmethod
    def _centered_face():
        """Query the face-detection service; return the best centered face
        (dict) or None. Returns the string 'DOWN' if the service is
        unreachable or its data is stale."""
        import json
        import os
        import time
        import urllib.request

        url = os.environ.get("FACE_SERVICE_URL", "http://127.0.0.1:8095/faces")
        try:
            with urllib.request.urlopen(url, timeout=1.0) as resp:
                info = json.loads(resp.read())
        except Exception:
            return "DOWN"
        if time.time() - info.get("ts", 0) > 2.0:
            return "DOWN"  # stale detections (camera/detector stalled)
        centered = [f for f in info.get("faces", []) if f.get("centered")]
        if not centered:
            return None
        return max(centered, key=lambda f: f["conf"])

    def _goto_tcp(self, x: float, y: float, z: float,
                  roll_deg: float, pitch_deg: float, yaw_deg: float,
                  speed: float) -> str:
        """Shared implementation for move_to_tcp and the compound skills."""
        robot = self._get_robot()
        if robot is None:
            return "ERROR: arm not running (estopped or not started)"
        if math.hypot(x, y) > MAX_REACH_M:
            return f"ERROR: reach {math.hypot(x, y):.3f}m > {MAX_REACH_M}m"
        if not MIN_Z_M <= z <= MAX_Z_M:
            return f"ERROR: z={z} outside [{MIN_Z_M}, {MAX_Z_M}]"
        import pinocchio as pin

        R = pin.rpy.rpyToMatrix(np.deg2rad(np.array([roll_deg, pitch_deg, yaw_deg])))
        T_tcp = np.eye(4)
        T_tcp[:3, :3] = R
        T_tcp[:3, 3] = [x, y, z]
        T_link6_tcp = np.eye(4)
        T_link6_tcp[:3, 3] = TCP_OFFSET_M
        T_target = T_tcp @ np.linalg.inv(T_link6_tcp)

        q_cur = np.asarray(robot.get_joint_state()["pos"])
        seeds = [q_cur,
                 np.deg2rad([yaw_deg, 90, -90, 0, 0, 0.0]),
                 np.deg2rad([yaw_deg, 60, -60, 0, 0, 0.0]),
                 np.deg2rad([0, 120, -120, 45, 0, 0.0]),
                 np.deg2rad([20, 90, -60, 45, 0, 0.0]),
                 np.deg2rad([-20, 100, -100, 30, 0, 0.0])]
        pos_err, ang_err, q_sol = self._kin.ik(T_target, seeds)
        if pos_err > 0.005 or ang_err > 3.0:
            return (f"ERROR: pose unreachable (IK err {pos_err * 1000:.1f}mm / "
                    f"{ang_err:.1f}deg), refusing to move")
        speed = min(max(speed, 0.05), MAX_SPEED)
        robot.move_joints(q_sol, speed=speed)
        return f"reached tcp=({x:.3f}, {y:.3f}, {z:.3f}) rpy=({roll_deg}, {pitch_deg}, {yaw_deg})"

    @tool
    def move_to_tcp(self, x: float, y: float, z: float,
                    roll_deg: float = 0.0, pitch_deg: float = 0.0, yaw_deg: float = 0.0,
                    speed: float = 0.25) -> str:
        """Move the gripper TCP (10 cm in front of the flange, between the
        fingertips) to the given pose in the base frame.

        x,y,z: position in meters (base frame). |xy| <= 0.6, 0.02 <= z <= 0.6.
        roll/pitch/yaw: TCP orientation in degrees (extrinsic X-Y-Z about base
        axes). For top-down grasping use roll=0, pitch=90, yaw=0 (flange +X
        pointing straight down).
        speed: max joint speed rad/s, capped at 0.5.
        """
        return self._goto_tcp(x, y, z, roll_deg, pitch_deg, yaw_deg, speed)

    @tool
    def set_gripper(self, value: float) -> str:
        """Set gripper position: 0.0 = fully closed, 1.0 = fully open.
        Force-limited hybrid mode: closes until the object resists, then holds
        without crushing."""
        robot = self._get_robot()
        if robot is None:
            return "ERROR: arm not running"
        if robot.gripper is None:
            return "ERROR: no gripper attached"
        value = min(max(value, 0.0), 1.0)
        robot.command_gripper(value)
        return f"gripper -> {value}"

    @tool
    def capture_wrist_view(self, save_path: str = "/tmp/wrist_view.jpg") -> str:
        """Capture one frame from the wrist camera for annotation.

        Saves the frame with a CYAN cross at the TCP aim point and a 100px
        grid. To request a grasp, draw a RED mark (circle, dot or box) on
        the target object's base in this image, then call grasp_horizontal
        with the same path. Do NOT move the arm between capture and grasp.
        If live_view.py is running, its shared latest frame is used instead
        of opening the camera (which would conflict with the stream).

        save_path: where to write the JPEG image.
        """
        robot = self._get_robot()
        if robot is None:
            return "ERROR: arm not running"
        import cv2
        import vision_grasp as vg

        K, dist, X = vg.load_calib()
        frame = None
        import os
        import time

        live = "/tmp/wrist_live.jpg"
        if os.path.exists(live) and time.time() - os.path.getmtime(live) < 2.0:
            frame = cv2.imread(live)
        if frame is None:
            frame = vg.capture_frame()
        if frame is None:
            return "ERROR: camera read failed"
        ax, ay = vg.aim_pixel(K, dist, X)

        cv2.drawMarker(frame, (int(ax), int(ay)), (255, 255, 0), cv2.MARKER_CROSS, 40, 3)
        h, w = frame.shape[:2]
        for gx in range(0, w, 100):
            cv2.line(frame, (gx, 0), (gx, h), (0, 200, 0), 1)
        for gy in range(0, h, 100):
            cv2.line(frame, (0, gy), (w, gy), (0, 200, 0), 1)
        if not cv2.imwrite(save_path, frame):
            return f"ERROR: could not write {save_path}"
        q_deg = np.rad2deg(np.asarray(robot.get_joint_state()["pos"]))
        return (f"saved {save_path} ({w}x{h}), aim pixel = ({ax:.0f}, {ay:.0f}), "
                f"joints(deg) = {[round(float(v), 2) for v in q_deg]}")

    @tool
    def grasp_horizontal(self, image_path: str, table_z: float = 0.02,
                         u: float = -1.0, v: float = -1.0,
                         grasp_height: float = 0.13, backoff: float = 0.15,
                         lift: float = 0.15, speed: float = 0.2) -> str:
        """Side-clamp a bottle-like object horizontally and lift it.

        Reads the RED annotation mark in image_path (a frame from
        capture_wrist_view) — mark the object's BASE contact point on the
        table — back-projects it onto the tabletop plane, then runs:
        open gripper -> back off `backoff` meters from the target at
        grasp height, flange +X horizontal and yawed toward the target
        (pitch=0, fingers close sideways) -> advance horizontally until
        the TCP (fingertip midpoint) reaches the object center ->
        force-limited close -> lift. Aborts before advancing if any step
        fails.

        image_path: annotated image; the arm must NOT have moved since
        the frame was captured.
        table_z: height (m, base frame) of the surface the object sits on.
        u, v: optional pixel coordinates; if both >= 0 they are used
        directly instead of red-annotation detection.
        grasp_height: clamp height above table_z (m), aim for mid-body.
        NOTE: with the strictly horizontal (pitch=0) approach the wrist
        runs out of j4 travel below ~0.14m absolute z at typical bottle
        distances — keep table_z + grasp_height >= ~0.14.
        backoff: pre-grasp distance (m) behind the target along the
        approach direction.
        lift: how far (m) to raise the object after grasping.
        speed: max joint speed rad/s, capped at 0.5.
        """
        robot = self._get_robot()
        if robot is None:
            return "ERROR: arm not running"
        if robot.gripper is None:
            return "ERROR: no gripper attached"
        import cv2
        import vision_grasp as vg

        if u >= 0 and v >= 0:
            pu, pv = u, v
        else:
            img = cv2.imread(image_path)
            if img is None:
                return f"ERROR: could not read image {image_path}"
            found = vg.find_annotation_pixel(img)
            if found is None:
                return ("ERROR: no red annotation found in image; draw a red mark "
                        "on the target base, or pass u/v pixel coordinates explicitly")
            pu, pv = found

        K, dist, X = vg.load_calib()
        q = np.asarray(robot.get_joint_state()["pos"])
        T_base_cam = self._kin.fk(q) @ X
        target = vg.pixel_to_base(pu, pv, table_z, T_base_cam, K, dist)
        if target is None:
            return "ERROR: pixel ray does not hit the table plane in front of the camera"
        x, y = float(target[0]), float(target[1])
        if math.hypot(x, y) > MAX_REACH_M:
            return f"ERROR: target reach {math.hypot(x, y):.3f}m > {MAX_REACH_M}m"

        # horizontal approach, radially from the base toward the target
        r = math.hypot(x, y)
        dx, dy = x / r, y / r
        yaw_deg = math.degrees(math.atan2(y, x))
        z_grasp = table_z + grasp_height
        bx, by = x - dx * backoff, y - dy * backoff

        steps = []
        robot.command_gripper(1.0)
        st = self._goto_tcp(bx, by, z_grasp, 0.0, 0.0, yaw_deg, speed)
        steps.append(st)
        if st.startswith("ERROR"):
            return "ABORTED at backoff (gripper open): " + " | ".join(steps)
        st = self._goto_tcp(x, y, z_grasp, 0.0, 0.0, yaw_deg, min(speed, 0.1))
        steps.append(st)
        if st.startswith("ERROR"):
            return "ABORTED at advance (gripper open): " + " | ".join(steps)
        robot.command_gripper(0.0)
        steps.append("gripper closed (force-limited)")
        st = self._goto_tcp(x, y, min(z_grasp + lift, MAX_Z_M), 0.0, 0.0, yaw_deg, speed)
        steps.append(st)
        if st.startswith("ERROR"):
            return ("GRASPED but lift failed (object held at grasp height): "
                    + " | ".join(steps))
        return (f"GRASPED object at pixel ({pu:.0f}, {pv:.0f}) -> base "
                f"({x:.3f}, {y:.3f}, {table_z:.3f}), side-clamped at "
                f"z={z_grasp:.3f}, lifted +{lift:.2f}m. " + " | ".join(steps))

    @tool
    def estop(self) -> str:
        """Emergency stop: disable all motors immediately. ARM GOES LIMP."""
        with self._lock:
            if self._robot is not None:
                self._robot.stop()
                self._robot = None
        return "estopped: motors disabled, arm is limp"

    @tool
    def shutdown(self, release_seconds: float = 3.0) -> str:
        """Safe exit: move to the ZERO pose (all joints 0 deg) at low speed,
        then ramp stiffness and gravity comp to zero over release_seconds
        (0.5..10) and disable motors. The arm never powers down mid-pose —
        it always parks at zero first, then relaxes slowly instead of
        dropping instantly. Still SUPPORT THE ARM, it ends fully limp.
        The MCP server stays alive afterwards, but arm control needs a
        process restart.
        """
        import time

        release_seconds = min(max(release_seconds, 0.5), 10.0)
        with self._lock:
            robot = self._robot
        if robot is None:
            return "already shut down (arm not running)"
        # Park at the zero pose before releasing anything.
        robot.move_joints(np.zeros(6), speed=0.2)
        hold_pos = np.array(robot.get_joint_state()["pos"], dtype=float)
        # SDK defaults (arm_robot.py): position-hold gains
        kp0 = np.array([30.0, 30.0, 30.0, 20.0, 5.0, 5.0])
        kd0 = np.array([1.0, 1.0, 1.0, 0.5, 0.5, 0.5])
        g0 = float(getattr(robot, "gravity_comp_factor", 1.0))
        steps = max(int(release_seconds / 0.1), 1)
        for i in range(1, steps + 1):
            alpha = 1.0 - i / steps
            robot.gravity_comp_factor = g0 * alpha
            robot.command_joint_state(
                {
                    "pos": hold_pos,
                    "vel": np.zeros(6),
                    "kp": kp0 * alpha,
                    "kd": kd0,
                }
            )
            time.sleep(0.1)
        with self._lock:
            if self._robot is not None:
                self._robot.stop()  # motors DISABLE — arm goes limp
                self._robot = None
        return "shutdown complete: parked at zero pose, soft release done, motors disabled"


a1z_mcp = autoconnect(
    A1ZArmModule.blueprint(),
    McpServer.blueprint(),
)

if __name__ == "__main__":
    # Tee stdout+stderr (fd level, so native/library writes are captured too)
    # into logs/mcp_server.log — whoever launches this process, the motor logs
    # land in the file for the independent log monitor (log_tail50.py).
    import os

    _log_path = A1Z_DIR / "logs" / "mcp_server.log"
    _log_path.parent.mkdir(exist_ok=True)
    _log_f = open(_log_path, "a", buffering=1)  # append, line-buffered
    _orig_out = os.dup(1)
    _r, _w = os.pipe()
    os.dup2(_w, 1)
    os.dup2(_w, 2)

    def _pump() -> None:
        with os.fdopen(_r, "rb") as pr:
            while True:
                data = pr.read1(4096)
                if not data:
                    break
                try:
                    os.write(_orig_out, data)
                except OSError:
                    pass
                _log_f.write(data.decode("utf-8", errors="replace"))

    threading.Thread(target=_pump, daemon=True).start()

    ModuleCoordinator.build(a1z_mcp).loop()
