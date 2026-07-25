"""Galaxea A1Z arm as one aggregated nanobot Tool.

Multiplexes a single `a1z` tool onto the DimOS MCP server (default
http://localhost:9990/mcp, override with A1Z_MCP_URL) that hosts the arm
skills. One compact schema instead of nine separate MCP tools keeps the
LLM context small; `args` is passed verbatim to the chosen sub-tool.

Self-contained async streamable-HTTP MCP client (JSON-RPC + SSE parsing),
no dependency on the a1z repo layout.
"""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

from nanobot.agent.tools.base import Tool, ToolResult

_URL = os.environ.get("A1Z_MCP_URL", "http://localhost:9990/mcp")
_TIMEOUT = httpx.Timeout(180.0, connect=10.0)

_SUBTOOLS: dict[str, str] = {
    "get_joint_state": "no args. Current joint positions (deg) and torques (Nm).",
    "get_flange_pose": "no args. Flange pose in base frame: xyz (m) + rpy (deg).",
    "move_to_pose": '{joints_deg: [6 floats], speed?: 0.3}. Joint-space move; limits j1 ±120, j2 0..180, j3 -180..0, j4/j5 ±85, j6 ±115. Neutral pose: [0,34,-23,-29,0,0]; zero: [0,0,0,0,0,0].',
    "move_to_tcp": '{x,y,z: float, roll_deg?,pitch_deg?,yaw_deg?: 0, speed?: 0.25}. Cartesian move of gripper TCP (10cm ahead of flange). |xy|<=0.6, 0.02<=z<=0.6. Horizontal bottle approach: roll=0, pitch=0, yaw=atan2(y,x).',
    "set_gripper": "{value: float} 0.0=closed, 1.0=open (force-limited close).",
    "capture_wrist_view": "{save_path?: /tmp/wrist_view.jpg}. One wrist-camera frame with aim crosshair + grid; arm must not move between this and a grasp.",
    "grasp_horizontal": '{image_path, u, v, table_z?: 0.02, grasp_height?: 0.13, backoff?: 0.15, lift?: 0.15, speed?: 0.2}. Side-clamp a bottle whose BASE pixel is (u,v) in image_path, then lift. Horizontal approach; needs table_z+grasp_height >= ~0.14.',
    "grasp_annotated": "{image_path, u?, v?, table_z?: 0.02, ...}. TOP-DOWN grasp variant (pitch=90).",
    "place_at": "{x,y,z, speed?: 0.2}. Place held object at base-frame (x,y,z), open gripper, retreat.",
    "estop": "no args. EMERGENCY: disable motors immediately, arm goes limp.",
    "shutdown": "{release_seconds?: 3.0}. Safe power-down: first move to the ZERO pose [0,0,0,0,0,0] at low speed, then ramp stiffness to zero and disable motors (arm limp afterwards, parked at zero).",
    "nod_greet": "{speed?: 0.3}. Raise into alert pose and nod the wrist (j4) twice as a greeting, ending at the alert pose.",
    "scan_and_greet": "{speed?: 0.3}. Find-a-person behavior: raise into alert pose, sweep the base (j1) through yaw stops, and at each stop check the wrist-camera face-detection service; when a face is at the CENTER of the frame, stop and nod facing the person. Returns 'human in sight, start a chat' so the agent can open a conversation, or 'no person found' after a full sweep. Needs face_detect/server.py running on the arm host.",
}


class _McpSession:
    """Minimal async streamable-HTTP MCP client."""

    def __init__(self, url: str) -> None:
        self.url = url
        self.session_id: str | None = None
        self._id = 0

    async def _post(self, client: httpx.AsyncClient, payload: dict) -> dict:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self.session_id:
            headers["mcp-session-id"] = self.session_id
        r = await client.post(self.url, json=payload, headers=headers)
        if "mcp-session-id" in r.headers:
            self.session_id = r.headers["mcp-session-id"]
        r.raise_for_status()
        if r.status_code == 202 or not r.content:
            return {}
        if "text/event-stream" in r.headers.get("content-type", ""):
            data = None
            for line in r.text.splitlines():
                if line.startswith("data:"):
                    data = line[5:].strip()
            return json.loads(data) if data else {}
        return r.json()

    async def call(self, client: httpx.AsyncClient, method: str,
                   params: dict | None = None, notif: bool = False) -> dict:
        payload: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        if not notif:
            self._id += 1
            payload["id"] = self._id
        return await self._post(client, payload)

    async def tool(self, name: str, args: dict) -> str:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            await self.call(client, "initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "nanobot-a1z", "version": "0.1"},
            })
            await self.call(client, "notifications/initialized", notif=True)
            resp = await self.call(client, "tools/call",
                                   {"name": name, "arguments": args})
        if "error" in resp:
            return f"MCP-ERROR: {resp['error']}"
        content = resp.get("result", {}).get("content", [])
        return "\n".join(c.get("text", "") for c in content if c.get("type") == "text")


class A1ZTool(Tool):
    """Single multiplexed tool for the Galaxea A1Z arm."""

    @property
    def name(self) -> str:
        return "a1z"

    @property
    def description(self) -> str:
        lines = [
            "Control the Galaxea A1Z robot arm via the local MCP server "
            f"({_URL}). Pick a sub-tool and pass its arguments as `args`. "
            "Moves are slow (tens of seconds); results are plain text, "
            "'ERROR...' means refused/failed. Sub-tools:",
        ]
        lines += [f"- {k}: {v}" for k, v in _SUBTOOLS.items()]
        return "\n".join(lines)

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "tool": {
                    "type": "string",
                    "enum": list(_SUBTOOLS),
                    "description": "Sub-tool to invoke (see description for its args).",
                },
                "args": {
                    "type": "object",
                    "description": "Arguments object passed verbatim to the sub-tool.",
                    "default": {},
                },
            },
            "required": ["tool"],
        }

    async def execute(self, tool: str = "", args: dict | None = None,
                      **kwargs: Any) -> Any:
        if tool not in _SUBTOOLS:
            return ToolResult.error(
                f"Error: unknown sub-tool {tool!r}; choose one of {sorted(_SUBTOOLS)}")
        if args is None:
            args = {}
        if not isinstance(args, dict):
            return ToolResult.error("Error: `args` must be an object")
        try:
            out = await _McpSession(_URL).tool(tool, args)
        except httpx.ConnectError:
            return ToolResult.error(
                f"Error: cannot reach A1Z MCP server at {_URL} "
                "(is a1z_mcp_server.py running?)")
        except Exception as e:  # timeouts, protocol errors, ...
            return ToolResult.error(f"Error: {type(e).__name__}: {e}")
        if out.startswith(("ERROR", "MCP-ERROR")):
            return ToolResult.error(f"Error: {out}")
        return out or "(no output)"
