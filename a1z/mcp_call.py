"""Minimal MCP streamable-HTTP client for calling A1Z arm skills.

Usage:
    a1z/.venv/bin/python a1z/mcp_call.py <tool> [json_args]
    a1z/.venv/bin/python a1z/mcp_call.py list
    a1z/.venv/bin/python a1z/mcp_call.py get_joint_state
    a1z/.venv/bin/python a1z/mcp_call.py move_to_tcp '{"x":0.3,"y":0.0,"z":0.2,"pitch_deg":-90}'
    a1z/.venv/bin/python a1z/mcp_call.py set_gripper '{"value":1.0}'
"""

import json
import sys

import httpx

URL = "http://localhost:9990/mcp"


class McpSession:
    def __init__(self, url: str = URL):
        self.url = url
        self.client = httpx.Client(timeout=60.0)
        self.session_id = None
        self._id = 0

    def _post(self, payload: dict) -> dict:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self.session_id:
            headers["mcp-session-id"] = self.session_id
        r = self.client.post(self.url, json=payload, headers=headers)
        if "mcp-session-id" in r.headers:
            self.session_id = r.headers["mcp-session-id"]
        r.raise_for_status()
        if r.status_code == 202 or not r.content:
            return {}
        ctype = r.headers.get("content-type", "")
        if "text/event-stream" in ctype:
            # parse SSE: take the JSON of the last data: line
            data = None
            for line in r.text.splitlines():
                if line.startswith("data:"):
                    data = line[5:].strip()
            return json.loads(data) if data else {}
        return r.json()

    def call(self, method: str, params: dict | None = None, notif: bool = False) -> dict:
        payload = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        if not notif:
            self._id += 1
            payload["id"] = self._id
        return self._post(payload)

    def initialize(self) -> None:
        self.call("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "a1z-cli", "version": "0.1"},
        })
        self.call("notifications/initialized", notif=True)

    def tool(self, name: str, args: dict) -> str:
        resp = self.call("tools/call", {"name": name, "arguments": args})
        if "error" in resp:
            return f"MCP-ERROR: {resp['error']}"
        result = resp.get("result", {})
        content = result.get("content", [])
        return "\n".join(c.get("text", "") for c in content if c.get("type") == "text")


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    tool = sys.argv[1]
    args = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
    s = McpSession()
    s.initialize()
    if tool == "list":
        resp = s.call("tools/list")
        for t in resp.get("result", {}).get("tools", []):
            print(f"- {t['name']}: {t.get('description', '').splitlines()[0]}")
        return
    print(s.tool(tool, args))


if __name__ == "__main__":
    main()
