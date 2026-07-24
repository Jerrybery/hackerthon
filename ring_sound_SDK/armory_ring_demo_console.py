# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import json
import queue
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any, Callable

import ring_sound as sdk


APP_TITLE = "Armory Ring Demo Console"
RING_NAME = "ring"
SCAN_SECONDS = 25.0
EVENT_LOG_PATH = Path("armory_demo_events.jsonl")

GESTURE_TO_INTENT = {
    "rotate_front": "deliver_water",
    "rotate_back": "deliver_snack",
    "wave": "sway_left_right",
}

INTENTS = {
    "deliver_water": {
        "title": "递水",
        "action": "deliver_water",
        "persona": "shinobi",
        "copy": "一个很小的手势，被放大成现实中的行动。",
        "hotkey": "1",
    },
    "deliver_snack": {
        "title": "送零食",
        "action": "deliver_snack",
        "persona": "winter_soldier",
        "copy": "第二只手理解需求，把物体带到用户身边。",
        "hotkey": "2",
    },
    "sway_left_right": {
        "title": "打招呼",
        "action": "sway_left_right",
        "persona": "devil_breaker",
        "copy": "机械臂用身体回应用户和观众的注视。",
        "hotkey": "3",
    },
    "stop": {
        "title": "软停止",
        "action": "stop",
        "persona": "guardian",
        "copy": "先停下来，安全永远比表演重要。",
        "hotkey": "S",
    },
    "return_home": {
        "title": "回到原点",
        "action": "return_home",
        "persona": "guardian",
        "copy": "回到初始姿态，准备下一次协作。",
        "hotkey": "H",
    },
}

PERSONAS = {
    "shinobi": {
        "name": "Shinobi / 忍义手",
        "tone": "精准、克制、快速执行",
        "color": "#2563eb",
    },
    "winter_soldier": {
        "name": "Winter Soldier / 稳定义肢",
        "tone": "可靠、强力、稳定抓取",
        "color": "#475569",
    },
    "devil_breaker": {
        "name": "Devil Breaker / 爆发机器臂",
        "tone": "外放、表演感、强反馈",
        "color": "#dc2626",
    },
    "guardian": {
        "name": "Guardian / 安全守护",
        "tone": "收束、停止、复位",
        "color": "#15803d",
    },
}


@dataclass(frozen=True)
class DemoEvent:
    ts: str
    source: str
    intent: str
    action: str
    persona_id: str
    persona_name: str
    text: str
    confidence: float
    gesture: str = ""
    robot_sent: bool = False
    robot_result: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "ts": self.ts,
            "source": self.source,
            "intent": self.intent,
            "action": self.action,
            "persona_id": self.persona_id,
            "persona_name": self.persona_name,
            "text": self.text,
            "confidence": self.confidence,
            "gesture": self.gesture,
            "robot_sent": self.robot_sent,
            "robot_result": self.robot_result,
        }


def is_ring_device(device: sdk.BleDeviceInfo) -> bool:
    return str(device.name or "").strip().lower() == RING_NAME


async def scan_ring_only(
    *,
    timeout_s: float = SCAN_SECONDS,
    log: Callable[[str], None] | None = None,
) -> tuple[list[sdk.BleDeviceInfo], int]:
    if log:
        log(f"开始扫描，只保留名称为 ring 的设备，最多 {timeout_s:g} 秒。")
    devices = await sdk.scan_rings(timeout_s=timeout_s)
    rings = [device for device in devices if is_ring_device(device)]
    ignored = len(devices) - len(rings)

    unique: dict[str, sdk.BleDeviceInfo] = {}
    for ring in rings:
        unique[ring.address] = ring
    return list(unique.values()), ignored


def parse_info_output(output: str) -> dict[str, str]:
    data: dict[str, str] = {}
    for line in output.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        data[key.strip()] = value.strip()
    return data


def run_official_info_command(address: str, *, timeout_s: float = 75.0) -> dict[str, str]:
    completed = subprocess.run(
        [sys.executable, "ring_sound.py", "info", "--address", address],
        cwd=Path(__file__).resolve().parent,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout_s,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise sdk.TransportError(f"official SDK info failed: {detail}")
    return parse_info_output(completed.stdout)


async def connect_ring(address: str, *, attempts: int, log: Callable[[str], None] | None = None) -> sdk.RingSoundClient:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        client = sdk.RingSoundClient(address=address)
        try:
            if log:
                log(f"连接 ring 尝试 {attempt}/{attempts}: {address}")
            await client.connect()
            sdk.enable_time_sync(client)
            return client
        except Exception as exc:
            last_error = exc
            await client.disconnect()
            if log:
                log(f"连接失败：{type(exc).__name__}: {exc}")
            if attempt < attempts:
                await asyncio.sleep(2.0)
    raise sdk.TransportError(f"ring 连接失败：{last_error}")


def post_robot_action(url: str, event: DemoEvent, *, timeout_s: float = 2.5) -> str:
    payload = {
        "action": event.action,
        "intent": event.intent,
        "source": event.source,
        "persona_id": event.persona_id,
        "text": event.text,
        "ts": event.ts,
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            body = response.read().decode("utf-8", errors="replace").strip()
            return f"HTTP {response.status}: {body[:120]}"
    except urllib.error.URLError as exc:
        return f"HTTP failed: {exc}"
    except TimeoutError:
        return "HTTP failed: timeout"


def write_event(event: DemoEvent) -> None:
    with EVENT_LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event.as_dict(), ensure_ascii=False) + "\n")


class DemoConsole:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("1180x760")
        self.root.minsize(1040, 680)

        self.ui_queue: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.worker_busy = False
        self.listen_thread: threading.Thread | None = None
        self.stop_ring_listener = threading.Event()

        self.address_var = tk.StringVar(value="")
        self.robot_url_var = tk.StringVar(value="http://10.80.11.57:8000/action")
        self.robot_enabled_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="待机：先扫描 ring，或直接用手动按钮演示")
        self.connection_var = tk.StringVar(value="Ring: 未连接")
        self.persona_var = tk.StringVar(value="当前人格：未触发")
        self.intent_var = tk.StringVar(value="当前意图：无")
        self.action_var = tk.StringVar(value="机械臂动作：未发送")
        self.story_var = tk.StringVar(value="一句话：把用户的微小意图，放大成现实中的行动能力。")

        self._build_ui()
        self._bind_hotkeys()
        self._set_status("待机：Demo Console 已准备", "#334155")
        self.root.after(100, self._pump_queue)

    def _build_ui(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(2, weight=1)

        header = ttk.Frame(self.root)
        header.grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 8))
        header.columnconfigure(0, weight=1)
        ttk.Label(
            header,
            text="Armory Ring Demo Console",
            font=("Microsoft YaHei UI", 22, "bold"),
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            header,
            text="理解意图的第二只手：戒指 / 手动 / 语音 / 直播事件，都汇聚为机械臂动作。",
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))

        self.status_label = tk.Label(
            self.root,
            textvariable=self.status_var,
            fg="white",
            anchor="w",
            padx=12,
            pady=9,
            font=("Microsoft YaHei UI", 11, "bold"),
        )
        self.status_label.grid(row=1, column=0, sticky="ew", padx=16)

        main = ttk.Frame(self.root)
        main.grid(row=2, column=0, sticky="nsew", padx=16, pady=12)
        main.columnconfigure(0, weight=5)
        main.columnconfigure(1, weight=4)
        main.rowconfigure(1, weight=1)

        self._build_controls(main)
        self._build_stage(main)
        self._build_ring_panel(main)
        self._build_log_panel(main)

        footer = ttk.Label(
            self.root,
            text="快捷键：1 递水 | 2 送零食 | 3 打招呼 | S 停止 | H 回到原点。比赛现场蓝牙不稳时，直接用快捷键兜底。",
        )
        footer.grid(row=3, column=0, sticky="ew", padx=16, pady=(0, 12))

    def _build_controls(self, parent: ttk.Frame) -> None:
        controls = ttk.LabelFrame(parent, text="输入与机械臂接口")
        controls.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        controls.columnconfigure(1, weight=1)

        ttk.Label(controls, text="ring 地址").grid(row=0, column=0, sticky="w", padx=10, pady=10)
        ttk.Entry(controls, textvariable=self.address_var).grid(row=0, column=1, sticky="ew", padx=(0, 10), pady=10)
        ttk.Button(controls, text="只扫描 ring", command=self.scan_ring).grid(row=0, column=2, padx=(0, 10), pady=10)
        ttk.Button(controls, text="测试连接/读电量", command=self.check_ring).grid(row=0, column=3, padx=(0, 10), pady=10)
        ttk.Button(controls, text="开始监听戒指", command=self.start_ring_listener).grid(row=0, column=4, padx=(0, 10), pady=10)
        ttk.Button(controls, text="停止监听", command=self.stop_listener).grid(row=0, column=5, padx=(0, 10), pady=10)

        ttk.Checkbutton(controls, text="向机械臂 HTTP 发送动作", variable=self.robot_enabled_var).grid(
            row=1, column=0, sticky="w", padx=10, pady=(0, 10)
        )
        ttk.Entry(controls, textvariable=self.robot_url_var).grid(row=1, column=1, columnspan=3, sticky="ew", padx=(0, 10), pady=(0, 10))
        ttk.Button(controls, text="清空事件日志", command=self.clear_log).grid(row=1, column=4, sticky="ew", padx=(0, 10), pady=(0, 10))
        ttk.Button(controls, text="连接修复提示", command=self.show_fix_tips).grid(row=1, column=5, sticky="ew", padx=(0, 10), pady=(0, 10))

    def _build_stage(self, parent: ttk.Frame) -> None:
        stage = ttk.LabelFrame(parent, text="演示舞台")
        stage.grid(row=1, column=0, sticky="nsew", padx=(0, 8))
        stage.columnconfigure(0, weight=1)
        stage.columnconfigure(1, weight=1)
        stage.rowconfigure(4, weight=1)

        ttk.Label(stage, textvariable=self.story_var, font=("Microsoft YaHei UI", 12, "bold"), wraplength=600).grid(
            row=0, column=0, columnspan=2, sticky="ew", padx=12, pady=(12, 8)
        )
        ttk.Label(stage, textvariable=self.connection_var).grid(row=1, column=0, sticky="w", padx=12, pady=4)
        ttk.Label(stage, textvariable=self.persona_var).grid(row=1, column=1, sticky="w", padx=12, pady=4)
        ttk.Label(stage, textvariable=self.intent_var, font=("Microsoft YaHei UI", 14, "bold")).grid(
            row=2, column=0, sticky="w", padx=12, pady=6
        )
        ttk.Label(stage, textvariable=self.action_var, font=("Microsoft YaHei UI", 14, "bold")).grid(
            row=2, column=1, sticky="w", padx=12, pady=6
        )

        cards = ttk.Frame(stage)
        cards.grid(row=3, column=0, columnspan=2, sticky="ew", padx=8, pady=8)
        for index, intent in enumerate(["deliver_water", "deliver_snack", "sway_left_right", "stop", "return_home"]):
            cards.columnconfigure(index, weight=1)
            meta = INTENTS[intent]
            text = f"{meta['hotkey']}  {meta['title']}"
            ttk.Button(cards, text=text, command=lambda value=intent: self.trigger_intent(value, source="manual")).grid(
                row=0,
                column=index,
                sticky="ew",
                padx=4,
                pady=4,
            )

        self.persona_text = tk.Text(stage, height=8, wrap="word", font=("Microsoft YaHei UI", 10))
        self.persona_text.grid(row=4, column=0, columnspan=2, sticky="nsew", padx=12, pady=(8, 12))
        self.persona_text.insert(
            "end",
            "演示话术：\n"
            "这不是一个替人做决定的机器人，而是一只理解意图的第二只手。\n"
            "当用户只做出很小的动作，Agent 会把它翻译成现实世界里的帮助：递水、送零食、打招呼、停止、复位。\n",
        )
        self.persona_text.configure(state="disabled")

    def _build_ring_panel(self, parent: ttk.Frame) -> None:
        panel = ttk.LabelFrame(parent, text="ring 扫描结果")
        panel.grid(row=1, column=1, sticky="nsew", padx=(8, 0), pady=(0, 8))
        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(0, weight=1)

        self.ring_tree = ttk.Treeview(panel, columns=("name", "address", "rssi"), show="headings", height=7)
        self.ring_tree.heading("name", text="名称")
        self.ring_tree.heading("address", text="地址")
        self.ring_tree.heading("rssi", text="信号")
        self.ring_tree.column("name", width=80)
        self.ring_tree.column("address", width=180)
        self.ring_tree.column("rssi", width=70)
        self.ring_tree.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        self.ring_tree.bind("<Double-1>", self.use_selected_ring)

    def _build_log_panel(self, parent: ttk.Frame) -> None:
        panel = ttk.LabelFrame(parent, text="事件流与调试日志")
        panel.grid(row=2, column=0, columnspan=2, sticky="nsew", pady=(8, 0))
        parent.rowconfigure(2, weight=1)
        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(0, weight=1)

        self.log_text = tk.Text(panel, height=12, wrap="word", font=("Consolas", 10))
        self.log_text.grid(row=0, column=0, sticky="nsew", padx=(10, 0), pady=10)
        scroll = ttk.Scrollbar(panel, command=self.log_text.yview)
        scroll.grid(row=0, column=1, sticky="ns", padx=(0, 10), pady=10)
        self.log_text.configure(yscrollcommand=scroll.set)

    def _bind_hotkeys(self) -> None:
        self.root.bind("1", lambda _event: self.trigger_intent("deliver_water", source="keyboard"))
        self.root.bind("2", lambda _event: self.trigger_intent("deliver_snack", source="keyboard"))
        self.root.bind("3", lambda _event: self.trigger_intent("sway_left_right", source="keyboard"))
        self.root.bind("s", lambda _event: self.trigger_intent("stop", source="keyboard"))
        self.root.bind("S", lambda _event: self.trigger_intent("stop", source="keyboard"))
        self.root.bind("h", lambda _event: self.trigger_intent("return_home", source="keyboard"))
        self.root.bind("H", lambda _event: self.trigger_intent("return_home", source="keyboard"))

    def _set_status(self, text: str, color: str) -> None:
        self.status_var.set(text)
        self.status_label.configure(bg=color)

    def _log(self, text: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_text.insert("end", f"[{ts}] {text}\n")
        self.log_text.see("end")

    def _post(self, kind: str, payload: Any = None) -> None:
        self.ui_queue.put((kind, payload))

    def _pump_queue(self) -> None:
        while True:
            try:
                kind, payload = self.ui_queue.get_nowait()
            except queue.Empty:
                break

            if kind == "status":
                text, color = payload
                self._set_status(text, color)
            elif kind == "log":
                self._log(str(payload))
            elif kind == "rings":
                self._render_rings(payload)
            elif kind == "connection":
                self.connection_var.set(str(payload))
            elif kind == "event":
                self._render_event(payload)
            elif kind == "done":
                self.worker_busy = False

        self.root.after(100, self._pump_queue)

    def _render_rings(self, rings: list[sdk.BleDeviceInfo]) -> None:
        self.ring_tree.delete(*self.ring_tree.get_children())
        for ring in rings:
            item = self.ring_tree.insert("", "end", values=(ring.name, ring.address, "" if ring.rssi is None else ring.rssi))
            self.ring_tree.selection_set(item)
            self.ring_tree.see(item)
            self.address_var.set(ring.address)
        if rings:
            self._set_status(f"扫描到 {len(rings)} 个 ring，已自动选中最近结果", "#2563eb")
        else:
            self._set_status("没有扫描到 ring，请靠近戒指或重启蓝牙", "#b45309")

    def _render_event(self, event: DemoEvent) -> None:
        persona = PERSONAS[event.persona_id]
        self.persona_var.set(f"当前人格：{persona['name']} | {persona['tone']}")
        self.intent_var.set(f"当前意图：{INTENTS[event.intent]['title']} ({event.intent})")
        robot_suffix = f" | {event.robot_result}" if event.robot_result else ""
        self.action_var.set(f"机械臂动作：{event.action}{robot_suffix}")
        self._set_status(f"{event.source} 触发：{event.intent} -> {event.action}", persona["color"])
        self._log(json.dumps(event.as_dict(), ensure_ascii=False))

    def run_worker(self, task_factory: Callable[[], Any]) -> None:
        if self.worker_busy:
            self._log("已有任务正在运行，请稍等。")
            return
        self.worker_busy = True

        def worker() -> None:
            try:
                asyncio.run(task_factory())
            except Exception as exc:
                self._post("status", (f"失败：{exc}", "#b91c1c"))
                self._post("log", f"错误：{type(exc).__name__}: {exc}")
            finally:
                self._post("done")

        threading.Thread(target=worker, daemon=True).start()

    def scan_ring(self) -> None:
        async def task() -> None:
            self._post("status", ("正在扫描 ring...", "#d97706"))
            rings, ignored = await scan_ring_only(log=lambda text: self._post("log", text))
            self._post("log", f"扫描完成：ring={len(rings)}，隐藏非 ring 设备={ignored}")
            self._post("rings", rings)

        self.run_worker(task)

    def check_ring(self) -> None:
        address = self.address_var.get().strip()
        if not address:
            messagebox.showwarning("缺少 ring 地址", "请先扫描 ring，或双击扫描结果选择地址。")
            return

        async def task() -> None:
            self._post("status", ("正在用官方 SDK 读取 ring 电量...", "#d97706"))
            info = await asyncio.to_thread(run_official_info_command, address)
            battery = info.get("battery_percent", "?")
            model = info.get("model", "?")
            firmware = info.get("firmware_version", "?")
            self._post("connection", f"Ring: 已识别 {address} | 电量 {battery}% | {model} | {firmware}")
            self._post("status", ("ring 连接测试成功", "#15803d"))
            self._post("log", f"ring info OK: address={address} battery={battery}% model={model}")

        self.run_worker(task)

    def use_selected_ring(self, _event: object = None) -> None:
        selected = self.ring_tree.selection()
        if not selected:
            return
        values = self.ring_tree.item(selected[0], "values")
        if len(values) >= 2:
            self.address_var.set(str(values[1]))
            self._log(f"已选择 ring 地址：{values[1]}")

    def start_ring_listener(self) -> None:
        if self.listen_thread and self.listen_thread.is_alive():
            self._log("戒指监听已经在运行。")
            return
        address = self.address_var.get().strip()
        if not address:
            messagebox.showwarning("缺少 ring 地址", "请先扫描 ring，或填写 ring 地址。")
            return

        self.stop_ring_listener.clear()

        def worker() -> None:
            asyncio.run(self._ring_listener_task(address))

        self.listen_thread = threading.Thread(target=worker, daemon=True)
        self.listen_thread.start()

    async def _ring_listener_task(self, address: str) -> None:
        client: sdk.RingSoundClient | None = None
        try:
            self._post("status", ("正在连接 ring 并监听手势...", "#d97706"))
            client = await connect_ring(address, attempts=5, log=lambda text: self._post("log", text))
            info = await sdk.get_system_info(client)
            self._post("connection", f"Ring: 监听中 {address} | 电量 {info.battery_percent}%")
            self._post("status", ("戒指监听中：长按、做动作、松手", "#15803d"))

            while not self.stop_ring_listener.is_set():
                try:
                    event = await sdk.wait_sensor_gesture_event(client, timeout_s=3.0)
                except sdk.TimeoutError:
                    continue
                gesture = sdk.sensor_gesture_name(event.gesture_id)
                intent = GESTURE_TO_INTENT.get(gesture)
                if not intent:
                    self._post("log", f"收到未映射手势：{gesture}")
                    continue
                self.trigger_intent(intent, source="ring", gesture=gesture, confidence=1.0)
        except Exception as exc:
            self._post("status", (f"戒指监听失败：{exc}", "#b91c1c"))
            self._post("log", f"戒指监听错误：{type(exc).__name__}: {exc}")
        finally:
            if client is not None:
                await client.disconnect()
            self._post("connection", "Ring: 监听已停止")

    def stop_listener(self) -> None:
        self.stop_ring_listener.set()
        self._log("正在停止戒指监听。")

    def trigger_intent(
        self,
        intent: str,
        *,
        source: str,
        gesture: str = "",
        confidence: float = 1.0,
    ) -> None:
        meta = INTENTS[intent]
        persona_id = meta["persona"]
        persona = PERSONAS[persona_id]
        text = meta["copy"]
        event = DemoEvent(
            ts=datetime.now().isoformat(timespec="seconds"),
            source=source,
            intent=intent,
            action=meta["action"],
            persona_id=persona_id,
            persona_name=persona["name"],
            text=text,
            confidence=confidence,
            gesture=gesture,
        )

        if self.robot_enabled_var.get():
            result = post_robot_action(self.robot_url_var.get().strip(), event)
            event = DemoEvent(**{**event.as_dict(), "robot_sent": True, "robot_result": result})

        write_event(event)
        self._post("event", event)

    def clear_log(self) -> None:
        self.log_text.delete("1.0", "end")
        if EVENT_LOG_PATH.exists():
            EVENT_LOG_PATH.unlink()
        self._log("已清空界面日志和 armory_demo_events.jsonl。")

    def show_fix_tips(self) -> None:
        messagebox.showinfo(
            "连接修复提示",
            "如果 ring 扫得到但连不上：\n\n"
            "1. 关闭旧版 ring 软件和所有 PowerShell/Python 调试窗口。\n"
            "2. 关闭手机 App 对戒指的连接。\n"
            "3. Windows 蓝牙关掉再打开。\n"
            "4. 戒指靠近电脑，长按确认有灯。\n"
            "5. 先用手动按钮保证演示链路，再恢复真实戒指监听。\n\n"
            "比赛现场优先保证 Demo 闭环，真实蓝牙不稳时用快捷键兜底。",
        )


def main() -> None:
    root = tk.Tk()
    app = DemoConsole(root)
    root.protocol("WM_DELETE_WINDOW", lambda: (app.stop_listener(), root.destroy()))
    root.mainloop()


if __name__ == "__main__":
    main()
