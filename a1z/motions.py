"""Named poses and motion sequences for A1Z social behaviors (look-around
scan, nod greeting).

Pure data + thin helpers — no hardware imports, no DimOS/MCP dependency.
All angles are in DEGREES in joint order j1..j6; convert with np.deg2rad
at the move_joints call site. The MCP tools in a1z_mcp_server.py consume
these definitions; tune the constants here when poses need adjusting —
the tool logic should not have to change.

Joint semantics (URDF base frame):
    j1 = base rotation ("look around" sweeps this), limits ±120 deg
    j2 = shoulder pitch, 0..180 deg
    j3 = elbow, -180..0 deg
    j4 = wrist pitch ("nod" dips this), ±85 deg
    j5 = wrist, ±85 deg
    j6 = flange rotation, ±115 deg
"""

# Deg limits, kept in sync with a1z_mcp_server.JOINT_LIMITS_DEG
# (from a1z.robots.get_robot._JOINT_LIMITS).
JOINT_LIMITS_DEG = [
    (-120.0, 120.0),
    (0.0, 180.0),
    (-180.0, 0.0),
    (-85.0, 85.0),
    (-85.0, 85.0),
    (-115.0, 115.0),
]

# Stowed, safe pose — same as hold_neutral.py. Start/end reference.
NEUTRAL_DEG = [0.0, 34.0, -23.0, -29.0, 0.0, 0.0]

# Raised "alert" pose: elbow folded up, wrist camera high and facing
# forward — the robot "stands up" into this before looking around or
# greeting. Designed from the URDF (A1Z_Flange.urdf) with FK + static
# gravity torque analysis: the end effector is horizontal when
# j2+j3+j4=0; folding the elbow MORE (j3 more negative) raises the
# flange. [0,60,-90,30]: flange z=0.521m (vs 0.341 at [0,60,-45,-15]),
# x=0.168m, tau_j2=0.2 / tau_j3=-3.3 Nm (limits 25/20).
SCAN_POSE_DEG = [0.0, 60.0, -90.0, 30.0, 0.0, 0.0]

# j1 yaw stops (deg) visited while looking around. Each stop is a future
# face-detection checkpoint. ±60 keeps far inside the ±120 limit.
SCAN_YAW_STOPS_DEG = [-60.0, 0.0, 60.0]

# Pause (s) at each yaw stop — gives a camera/detector time to look.
SCAN_DWELL_S = 0.8

# Nod: j4 dips NOD_DIP_DEG from the scan-pose j4, NOD_TIMES times.
NOD_DIP_DEG = 30.0
NOD_TIMES = 2


def _check_within_limits(pose_deg, name: str) -> None:
    if len(pose_deg) != 6:
        raise ValueError(f"{name}: need 6 joint angles, got {len(pose_deg)}")
    for i, (deg, (lo, hi)) in enumerate(zip(pose_deg, JOINT_LIMITS_DEG)):
        if not lo <= deg <= hi:
            raise ValueError(f"{name}: joint{i + 1}={deg}° outside [{lo}, {hi}]")


def scan_stops(base_pose_deg=SCAN_POSE_DEG, yaws_deg=SCAN_YAW_STOPS_DEG):
    """Yield each look-around stop pose (base pose with j1 set to the yaw).

    Pattern for a future face-detection loop:
        for stop in scan_stops():
            move_joints(stop); check camera; break when a face is centered.
    """
    _check_within_limits(base_pose_deg, "base_pose")
    for yaw in yaws_deg:
        pose = list(base_pose_deg)
        pose[0] = yaw
        _check_within_limits(pose, f"scan stop j1={yaw}")
        yield pose


def nod_poses(base_pose_deg=SCAN_POSE_DEG, dip_deg=NOD_DIP_DEG, times=NOD_TIMES):
    """Yield the nod sequence: j4 dips by dip_deg and returns, `times` times.

    Starts from base_pose_deg (the caller moves there first); the last
    yielded pose equals base_pose_deg, so the arm ends where it started.
    """
    _check_within_limits(base_pose_deg, "base_pose")
    for _ in range(times):
        dip = list(base_pose_deg)
        dip[3] += dip_deg
        _check_within_limits(dip, "nod dip")
        yield dip
        yield list(base_pose_deg)


# Fail fast if someone tunes a constant outside the soft limits.
_check_within_limits(NEUTRAL_DEG, "NEUTRAL_DEG")
_check_within_limits(SCAN_POSE_DEG, "SCAN_POSE_DEG")
for _p in scan_stops():
    pass
for _p in nod_poses():
    pass
